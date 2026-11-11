#!/usr/bin/env python3
"""
TinyLift v2 -- demo elevator controller for access-control integrations
(Verkada AX11 relays in series with the floor buttons).

Based on https://github.com/ryanmalley101/tinyLift, rewritten to be easier to
follow and to keep running when the LCD is missing.

Run:
    python3 tinylift.py              normal operation
    python3 tinylift.py --test       wiring check: lights each LED, reports each button
    python3 tinylift.py --no-lcd     skip the display entirely
    python3 tinylift.py --sim        no hardware: type 1-6 / u / d + Enter to press buttons

All pins and timings: config.py.   Wiring: docs/WIRING.md.
"""
import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import config as cfg                      # noqa: E402
from display import Display               # noqa: E402
from elevator import Elevator, UP, DOWN   # noqa: E402

log = logging.getLogger("tinylift")


# =============================================================================
# Helpers
# =============================================================================
def pin_label(bcm):
    phys = cfg.BCM_TO_PHYSICAL.get(bcm)
    return f"GPIO{bcm} (pin {phys})" if phys else f"GPIO{bcm}"


def setup_logging(verbose):
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    log.addHandler(console)
    if cfg.LOG_FILE:
        path = os.path.join(HERE, cfg.LOG_FILE)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3)
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
            log.addHandler(fh)
        except OSError as e:
            log.warning("Can't write log file %s (%s) - console logging only", path, e)


def check_config():
    """Catch pin mistakes before touching any hardware."""
    buttons = cfg.FLOOR_BUTTON_PINS + [cfg.CALL_UP_BUTTON_PIN, cfg.CALL_DOWN_BUTTON_PIN]
    leds = cfg.FLOOR_LED_PINS + [cfg.CALL_UP_LED_PIN, cfg.CALL_DOWN_LED_PIN]
    problems = []
    if len(cfg.FLOOR_BUTTON_PINS) != cfg.TOTAL_FLOORS:
        problems.append(f"FLOOR_BUTTON_PINS has {len(cfg.FLOOR_BUTTON_PINS)} pins "
                        f"but TOTAL_FLOORS is {cfg.TOTAL_FLOORS}")
    if len(cfg.FLOOR_LED_PINS) != cfg.TOTAL_FLOORS:
        problems.append(f"FLOOR_LED_PINS has {len(cfg.FLOOR_LED_PINS)} pins "
                        f"but TOTAL_FLOORS is {cfg.TOTAL_FLOORS}")
    all_pins = buttons + leds
    dupes = sorted({p for p in all_pins if all_pins.count(p) > 1})
    if dupes:
        problems.append("pins used twice: " + ", ".join(pin_label(p) for p in dupes))
    for p in all_pins:
        if p not in cfg.BCM_TO_PHYSICAL:
            problems.append(f"GPIO{p} is not a usable header pin")
    if cfg.LCD_ENABLED and ({2, 3} & set(all_pins)):
        problems.append("GPIO2/GPIO3 (pins 3/5) are the LCD's I2C lines - don't use them for buttons/LEDs")
    if problems:
        for p in problems:
            log.error("config.py: %s", p)
        sys.exit(2)
    if {14, 15} & set(all_pins):
        log.warning("GPIO14/15 are the serial-console pins; they toggle during boot. "
                    "Disable the serial console (raspi-config) if you use them.")


# =============================================================================
# GPIO layer (real or simulated)
# =============================================================================
class FakeGPIO:
    """Stand-in for RPi.GPIO so the program can run on any computer (--sim)."""
    BCM = OUT = IN = PUD_UP = HIGH = 1
    LOW = 0

    def __init__(self):
        self.levels = {}

    def setwarnings(self, _): pass
    def setmode(self, _): pass

    def setup(self, pin, mode, pull_up_down=None, initial=None):
        self.levels[pin] = 1 if mode == self.IN else (initial or 0)

    def output(self, pin, value): self.levels[pin] = value
    def input(self, pin): return self.levels.get(pin, 1)
    def cleanup(self): pass


def load_gpio(sim):
    if sim:
        log.info("SIMULATION MODE - no GPIO used")
        return FakeGPIO()
    try:
        import RPi.GPIO as GPIO
        return GPIO
    except (ImportError, RuntimeError) as e:
        log.error("Can't load RPi.GPIO (%s). On the Pi run: sudo apt install python3-rpi.gpio  "
                  "-- or use --sim to try the program without hardware.", e)
        sys.exit(1)


class Leds:
    """Named LED outputs; only writes a pin when its state changes."""

    def __init__(self, gpio):
        self.gpio = gpio
        self.pins = {f"Floor {i + 1}": p for i, p in enumerate(cfg.FLOOR_LED_PINS)}
        self.pins["Call UP"] = cfg.CALL_UP_LED_PIN
        self.pins["Call DOWN"] = cfg.CALL_DOWN_LED_PIN
        self.state = {}
        for name, pin in self.pins.items():
            gpio.setup(pin, gpio.OUT, initial=self._level(False))
            self.state[name] = False

    def _level(self, on):
        return (1 if on else 0) if cfg.LED_ACTIVE_HIGH else (0 if on else 1)

    def set(self, name, on):
        if self.state.get(name) != on:
            self.gpio.output(self.pins[name], self._level(on))
            self.state[name] = on

    def all(self, on):
        for name in self.pins:
            self.set(name, on)


class ButtonPoller(threading.Thread):
    """
    Polls the button inputs every 5 ms with a debounce, instead of using
    GPIO edge interrupts. This is more forgiving of noise on the long runs
    through the AX11, and it also works on newer Pi OS releases where
    RPi.GPIO's add_event_detect() is broken.
    """

    def __init__(self, gpio, buttons, stop_event):
        super().__init__(daemon=True, name="buttons")
        self.gpio = gpio
        self.buttons = buttons            # list of (name, pin, callback)
        self.stop_event = stop_event
        self.debounce = cfg.DEBOUNCE_MS / 1000.0
        for _, pin, _ in buttons:
            gpio.setup(pin, gpio.IN, pull_up_down=gpio.PUD_UP)

    def run(self):
        now = time.monotonic()
        state = {}
        for name, pin, _ in self.buttons:
            v = self.gpio.input(pin)
            state[pin] = {"stable": v, "raw": v, "since": now, "warned": False}
            if v == 0:
                log.warning("Button '%s' on %s reads PRESSED at startup. If nobody is pressing it, "
                            "it's probably wired to the button's NC terminal (green) instead of NO "
                            "(white).", name, pin_label(pin))
                state[pin]["warned"] = True
        while not self.stop_event.is_set():
            now = time.monotonic()
            for name, pin, callback in self.buttons:
                s = state[pin]
                v = self.gpio.input(pin)
                if v != s["raw"]:
                    s["raw"], s["since"] = v, now
                elif v != s["stable"] and now - s["since"] >= self.debounce:
                    s["stable"] = v
                    if v == 0:
                        try:
                            callback()
                        except Exception:   # noqa: BLE001 - never let a press kill the poller
                            log.exception("Error handling button '%s'", name)
                    else:
                        s["warned"] = False
                elif v == 0 and s["stable"] == 0 and not s["warned"] and now - s["since"] > 10:
                    log.warning("Button '%s' on %s has read PRESSED for 10+ s - stuck button "
                                "or NO/NC swapped?", name, pin_label(pin))
                    s["warned"] = True
            time.sleep(0.005)


def start_keyboard_sim(floor_cb, call_cb, stop_event):
    """--sim: type 1-6, u, d (then Enter). q quits."""
    def reader():
        log.info("Type a floor number 1-%d, 'u' (call up), 'd' (call down) or 'q', then Enter",
                 cfg.TOTAL_FLOORS)
        for line in sys.stdin:
            for ch in line.strip().lower().split():
                if ch == "q":
                    stop_event.set()
                    return
                if ch == "u":
                    call_cb(UP)
                elif ch == "d":
                    call_cb(DOWN)
                elif ch.isdigit():
                    floor_cb(int(ch))
        # stdin closed (e.g. piped input) -- just let the lift keep running
    threading.Thread(target=reader, daemon=True, name="keyboard").start()


# =============================================================================
# Modes
# =============================================================================
def screen_lines(snap):
    d = snap["direction"]
    arrow = {"UP": "^", "DOWN": "v"}.get(d, "-")
    calls = " ".join(x for x, on in (("UP", snap["hall_up"]), ("DN", snap["hall_down"])) if on)
    stops = ", ".join(str(f) for f in snap["car_calls"])
    return [
        f"Floor {snap['floor']}  {arrow}",
        "Doors OPEN" if snap["doors_open"] else f"Direction: {d}",
        f"Stops: {stops or '-'}",
        f"Lobby call: {calls or '-'}",
    ]


def run_wiring_test(gpio, leds, display, stop):
    log.info("=== WIRING TEST ===  (Ctrl+C to quit)")
    display.show(["TinyLift", "Wiring test", "Watch the LEDs,", "then press buttons"])
    log.info("Step 1: lighting each LED for 1.5 s. Check that the RIGHT button lights.")
    for name, pin in leds.pins.items():
        if stop.is_set():
            return
        log.info("  LED %-10s %-16s ON", name, pin_label(pin))
        leds.set(name, True)
        stop.wait(1.5)
        leds.set(name, False)
    log.info("Step 2: press each button. Its LED toggles and the pin is printed. "
             "If a button never shows up, check its wire and its AX11 relay.")

    def make_cb(name, pin):
        def cb():
            leds.set(name, not leds.state[name])
            log.info("  Button %-10s %-16s PRESSED", name, pin_label(pin))
            display.show(["Button pressed:", name, pin_label(pin), ""])
        return cb

    buttons = [(f"Floor {i + 1}", p, make_cb(f"Floor {i + 1}", p))
               for i, p in enumerate(cfg.FLOOR_BUTTON_PINS)]
    buttons += [("Call UP", cfg.CALL_UP_BUTTON_PIN, make_cb("Call UP", cfg.CALL_UP_BUTTON_PIN)),
                ("Call DOWN", cfg.CALL_DOWN_BUTTON_PIN, make_cb("Call DOWN", cfg.CALL_DOWN_BUTTON_PIN))]
    ButtonPoller(gpio, buttons, stop).start()
    while not stop.wait(1.0):
        display.poll()   # lets the LCD reconnect if it's plugged in late


def run_elevator(gpio, leds, display, stop, sim):
    car = Elevator(cfg.TOTAL_FLOORS, cfg.LOBBY_FLOOR, cfg.START_FLOOR)
    wake = threading.Event()

    def refresh():
        snap = car.snapshot()
        for f in range(1, cfg.TOTAL_FLOORS + 1):
            leds.set(f"Floor {f}", f in snap["car_calls"])
        leds.set("Call UP", snap["hall_up"])
        leds.set("Call DOWN", snap["hall_down"])
        display.show(screen_lines(snap))
        return snap

    def on_floor(n):
        log.info("Button: %s", car.press_floor(n))
        refresh()
        wake.set()

    def on_call(direction):
        log.info("Button: %s", car.press_call(direction))
        refresh()
        wake.set()

    buttons = [(f"Floor {i + 1}", p, (lambda n=i + 1: on_floor(n)))
               for i, p in enumerate(cfg.FLOOR_BUTTON_PINS)]
    buttons += [("Call UP", cfg.CALL_UP_BUTTON_PIN, lambda: on_call(UP)),
                ("Call DOWN", cfg.CALL_DOWN_BUTTON_PIN, lambda: on_call(DOWN))]
    if sim:
        start_keyboard_sim(on_floor, on_call, stop)
    else:
        ButtonPoller(gpio, buttons, stop).start()

    log.info("Elevator ready: %d floors, lobby = floor %d, cab at floor %d",
             cfg.TOTAL_FLOORS, cfg.LOBBY_FLOOR, cfg.START_FLOOR)
    while not stop.is_set():
        wake.clear()
        snap = refresh()
        if snap["doors_open"]:
            stop.wait(cfg.DOOR_DWELL_SECONDS)      # doors open at a floor
        elif car.stops():
            stop.wait(cfg.FLOOR_TRAVEL_SECONDS)    # travelling to the next floor
        else:
            # Idle: sleep until a button is pressed (re-check every 1 s so the
            # LCD can reconnect and Ctrl+C is noticed promptly).
            wake.wait(1.0)
            continue
        if stop.is_set():
            break
        event = car.step()
        if event:
            log.info("Cab: %s   (stops: %s)", event, car.snapshot()["car_calls"] or "none")


# =============================================================================
def main():
    ap = argparse.ArgumentParser(description="TinyLift v2 demo elevator")
    ap.add_argument("--test", action="store_true", help="wiring check mode")
    ap.add_argument("--no-lcd", action="store_true", help="don't use the display at all")
    ap.add_argument("--sim", action="store_true", help="run without Pi hardware (keyboard input)")
    ap.add_argument("--floor-seconds", type=float, help="override FLOOR_TRAVEL_SECONDS")
    ap.add_argument("--dwell-seconds", type=float, help="override DOOR_DWELL_SECONDS")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    if args.floor_seconds is not None:
        cfg.FLOOR_TRAVEL_SECONDS = args.floor_seconds
    if args.dwell_seconds is not None:
        cfg.DOOR_DWELL_SECONDS = args.dwell_seconds

    setup_logging(args.verbose)
    log.info("TinyLift v2 starting")
    check_config()

    stop = threading.Event()

    def handle_signal(signum, _frame):
        log.info("Signal %s received - shutting down", signum)
        stop.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    gpio = load_gpio(args.sim)
    gpio.setwarnings(False)
    gpio.setmode(gpio.BCM)
    leds = Leds(gpio)
    display = Display(cfg, log, enabled=not args.no_lcd)

    try:
        if cfg.STARTUP_LAMP_TEST and not args.test:
            leds.all(True)
            display.show(["TinyLift v2", "Starting...", "", ""])
            stop.wait(1.0)
            leds.all(False)
        if args.test:
            run_wiring_test(gpio, leds, display, stop)
        else:
            run_elevator(gpio, leds, display, stop, args.sim)
    finally:
        log.info("Stopping: LEDs off, display cleared, GPIO released")
        try:
            leds.all(False)
        except Exception:   # noqa: BLE001
            pass
        display.close()
        gpio.cleanup()


if __name__ == "__main__":
    main()
