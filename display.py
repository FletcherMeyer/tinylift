"""
Optional I2C display. Two kinds are supported:

  * OLED  - SSD1306 / SH1106 graphic screens (e.g. ELEGOO 0.96" 128x64),
            usually at I2C address 0x3C or 0x3D. Uses the luma.oled library.
  * char  - HD44780 character LCD (16x2 / 20x4) with a PCF8574 I2C backpack,
            usually at 0x27 or 0x3F. Uses the RPLCD library.

With LCD_TYPE = "auto" (config.py) the address decides: 0x3C/0x3D = OLED,
anything else = character LCD.

The elevator NEVER depends on this. If the screen is missing, unplugged, or
the libraries aren't installed, a warning goes to the log and the program
keeps running. It quietly retries every LCD_RETRY_SECONDS so you can plug
the screen in while it runs.
"""
import sys
import time
import types

OLED_ADDRESSES = (0x3C, 0x3D)


def _smbus2_location():
    """Where Python finds 'smbus2' (to explain a broken or shadowed install)."""
    import importlib.util
    try:
        spec = importlib.util.find_spec("smbus2")
    except (ImportError, ValueError):
        spec = None
    if spec is None:
        return "not installed"
    if spec.origin and spec.origin != "namespace":
        return "found at " + spec.origin
    paths = list(spec.submodule_search_locations or [])
    return "found at " + (", ".join(paths) or "unknown") + " (a folder with no __init__.py)"


_SMBUS = None   # (SMBus class, from_smbus2, why smbus2 failed) - worked out once


def _smbus_class():
    """Return (SMBus class, from_smbus2). Prefers smbus2; falls back to the
    'smbus' module that ships with Raspberry Pi OS (python3-smbus), so a
    missing or broken smbus2 install doesn't take the screen down."""
    global _SMBUS
    if _SMBUS is None:
        try:
            from smbus2 import SMBus
            _SMBUS = (SMBus, True, None)
        except ImportError as e2:
            where = _smbus2_location()
            try:
                from smbus import SMBus
            except ImportError:
                raise ImportError(f"no working I2C library: smbus2 failed ({e2}; smbus2 "
                                  f"{where}) and python3-smbus is not installed")
            # luma.core does 'import smbus2' even when it's handed a bus, so
            # make sure that import succeeds.
            try:
                import smbus2  # noqa: F401  (a shadowing folder still imports)
            except ImportError:
                shim = types.ModuleType("smbus2")
                shim.SMBus = SMBus
                sys.modules["smbus2"] = shim
            _SMBUS = (SMBus, False, f"{e2}; smbus2 {where}")
    return _SMBUS[0], _SMBUS[1]

# Defaults for settings that older copies of config.py don't have, so this file
# can be dropped into an existing install without touching config.py.
DEFAULTS = {"LCD_TYPE": "auto", "OLED_DRIVER": "ssd1306", "OLED_WIDTH": 128,
            "OLED_HEIGHT": 64, "OLED_ROTATE": 0}


def opt(cfg, name):
    return getattr(cfg, name, DEFAULTS[name])

# Fonts for the OLED, first one found wins. DejaVu ships with Raspberry Pi OS
# (install.sh also installs it); otherwise Pillow's built-in font is used.
FONT_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
FONT_REGULAR = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _load_font(paths, size):
    from PIL import ImageFont
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()


class _CharLcd:
    """HD44780 character LCD behind a PCF8574 backpack."""
    kind = "character LCD"

    def __init__(self, cfg, addr):
        from RPLCD.i2c import CharLCD
        self.cfg = cfg
        self.lcd = CharLCD(cfg.LCD_EXPANDER, addr, port=cfg.LCD_I2C_PORT,
                           cols=cfg.LCD_COLS, rows=cfg.LCD_ROWS,
                           charmap=cfg.LCD_CHARMAP, auto_linebreaks=False)
        self.lcd.clear()
        self.size = f"{cfg.LCD_COLS}x{cfg.LCD_ROWS} characters"

    def write(self, lines):
        cols = self.cfg.LCD_COLS
        for r, text in enumerate(lines[:self.cfg.LCD_ROWS]):
            self.lcd.cursor_pos = (r, 0)
            self.lcd.write_string(text[:cols].ljust(cols))

    def close(self):
        self.lcd.close(clear=True)


class BuiltinOled:
    """Minimal SSD1306 / SH1106 driver: just Pillow + smbus, no luma.

    Used when the luma.oled library is missing or broken, so the screen still
    works. Same interface as the parts of a luma device TinyLift uses:
    width, height, size, mode, display(image), clear(), hide()."""
    mode = "1"

    def __init__(self, bus, address, width=128, height=64, rotate=0, driver="ssd1306"):
        self._bus, self._addr = bus, address
        self._rotate = rotate % 4
        self._pages = height // 8
        self._native = (width, height)
        # SH1106 has 132 columns of RAM with the visible 128 starting at column 2.
        self._col_offset = 2 if driver.lower() == "sh1106" else 0
        self.width, self.height = (height, width) if self._rotate % 2 else (width, height)
        self.size = (self.width, self.height)
        if self._col_offset:   # SH1106: own charge-pump command; page mode is its only mode
            chip = (0xAD, 0x8B)                 # DC-DC (charge pump) on
        else:                  # SSD1306
            chip = (0x8D, 0x14,                 # charge pump on
                    0x20, 0x02)                 # page addressing mode
        self._cmd(0xAE,                         # display off
                  0xD5, 0x80,                   # clock divide / oscillator
                  0xA8, height - 1,             # multiplex = rows - 1
                  0xD3, 0x00,                   # display offset 0
                  0x40,                         # start line 0
                  *chip,
                  0xA1,                         # flip columns (standard module wiring)
                  0xC8,                         # scan rows bottom-up (standard wiring)
                  0xDA, 0x12 if height == 64 else 0x02,   # COM pin layout
                  0x81, 0xCF,                   # contrast
                  0xD9, 0xF1,                   # pre-charge
                  0xDB, 0x40,                   # VCOMH level
                  0xA4,                         # show RAM contents
                  0xA6)                         # normal (not inverted)
        self.clear()
        self._cmd(0xAF)                         # display on

    def _cmd(self, *cmds):
        for i in range(0, len(cmds), 16):
            self._bus.write_i2c_block_data(self._addr, 0x00, list(cmds[i:i + 16]))

    def display(self, image):
        if self._rotate:
            image = image.rotate(-90 * self._rotate, expand=True)
        image = image.convert("1")
        w, h = self._native
        px = image.load()
        col_lo = self._col_offset & 0x0F
        col_hi = 0x10 | (self._col_offset >> 4)
        for page in range(self._pages):
            y0 = page * 8
            row = bytearray(w)
            for x in range(w):
                b = 0
                for bit in range(8):
                    if px[x, y0 + bit]:
                        b |= 1 << bit
                row[x] = b
            self._cmd(0xB0 | page, col_lo, col_hi)
            for i in range(0, w, 32):
                self._bus.write_i2c_block_data(self._addr, 0x40, list(row[i:i + 32]))

    def clear(self):
        from PIL import Image
        self.display(Image.new("1", self.size))

    def hide(self):
        self._cmd(0xAE)


class _Oled:
    """SSD1306 / SH1106 graphic OLED. First line is drawn large."""
    kind = "OLED"

    def __init__(self, cfg, addr, device=None, log=None):
        self.cfg = cfg
        self.driver_name = "luma.oled"
        if device is None:
            try:
                device = self._luma_device(cfg, addr)
            except Exception as e:     # noqa: BLE001 - broken luma install, etc.
                if log:
                    log.warning("luma.oled library not usable (%s: %s) - using TinyLift's "
                                "built-in OLED driver instead.", type(e).__name__, e)
                SMBus, _ = _smbus_class()
                device = BuiltinOled(SMBus(cfg.LCD_I2C_PORT), addr,
                                     width=opt(cfg, "OLED_WIDTH"), height=opt(cfg, "OLED_HEIGHT"),
                                     rotate=opt(cfg, "OLED_ROTATE"),
                                     driver=opt(cfg, "OLED_DRIVER"))
                self.driver_name = "built-in driver"
        self.device = device
        self.size = f"{device.width}x{device.height} {opt(cfg, 'OLED_DRIVER').upper()}"
        if device.height >= 64:
            # 128x64: one big line + three small lines
            self.layout = [(0, _load_font(FONT_BOLD, 16)),
                           (20, _load_font(FONT_REGULAR, 11)),
                           (34, _load_font(FONT_REGULAR, 11)),
                           (48, _load_font(FONT_REGULAR, 11))]
        else:
            # 128x32: three small lines
            small = _load_font(FONT_REGULAR, 10)
            self.layout = [(0, small), (11, small), (22, small)]

    @staticmethod
    def _luma_device(cfg, addr):
        from luma.core.interface.serial import i2c
        from luma.oled import device as luma_devices
        driver = getattr(luma_devices, opt(cfg, "OLED_DRIVER").lower())
        SMBus, from_smbus2 = _smbus_class()
        if from_smbus2:
            serial = i2c(port=cfg.LCD_I2C_PORT, address=addr)
        else:   # hand luma an already-open python3-smbus bus
            serial = i2c(bus=SMBus(cfg.LCD_I2C_PORT), address=addr)
        return driver(serial, width=opt(cfg, "OLED_WIDTH"), height=opt(cfg, "OLED_HEIGHT"),
                      rotate=opt(cfg, "OLED_ROTATE"))

    @staticmethod
    def _width(draw, text, font):
        try:
            return draw.textlength(text, font=font)      # Pillow >= 8
        except AttributeError:
            return draw.textsize(text, font=font)[0]

    def write(self, lines):
        from PIL import Image, ImageDraw
        small = self.layout[-1][1]
        image = Image.new(self.device.mode, self.device.size)
        draw = ImageDraw.Draw(image)
        for i, ((y, font), text) in enumerate(zip(self.layout, lines)):
            text = text.rstrip()
            arrow = None
            if i == 0:
                # Draw a real triangle instead of the LCD's ^ / v / - marker
                # (shapes, not font glyphs, so any font works).
                if text.endswith((" ^", " v", " -")):
                    arrow = {"^": "up", "v": "down", "-": None}[text[-1]]
                    text = text[:-1].rstrip()
                if self._width(draw, text, font) > self.device.width:
                    font = small                      # too wide for the big font
            draw.text((0, y), text, font=font, fill="white")
            if arrow:
                x = int(self._width(draw, text, font)) + 8
                top, bot = y + 3, y + 15
                if arrow == "up":
                    pts = [(x, bot), (x + 12, bot), (x + 6, top)]
                else:
                    pts = [(x, top), (x + 12, top), (x + 6, bot)]
                draw.polygon(pts, fill="white")
        self.device.display(image)

    def close(self):
        self.device.clear()
        self.device.hide()


class Display:
    def __init__(self, cfg, log, enabled=True):
        self.cfg = cfg
        self.log = log
        self.enabled = enabled and cfg.LCD_ENABLED
        self.screen = None
        self.address = None
        self._last_attempt = 0.0
        self._last_lines = None
        self._wanted = []
        self._warned = False
        self._fallback_noted = False
        self._luma_noted = False
        if not self.enabled:
            self.log.info("Display disabled - running without a screen")
            return
        self._connect()

    # ------------------------------------------------------------ connection
    def _find_address(self):
        SMBus, from_smbus2 = _smbus_class()
        if not from_smbus2 and not self._fallback_noted:
            self._fallback_noted = True
            self.log.warning("smbus2 isn't usable (%s), so the screen is using the "
                             "built-in 'smbus' library instead. That works fine; to fix "
                             "smbus2 see the troubleshooting table in docs/WIRING.md.",
                             _SMBUS[2])
        bus = SMBus(self.cfg.LCD_I2C_PORT)
        try:
            for addr in self.cfg.LCD_ADDRESSES:
                try:
                    bus.read_byte(addr)
                    return addr
                except OSError:
                    continue
        finally:
            bus.close()
        return None

    def _connect(self):
        self._last_attempt = time.monotonic()
        try:
            addr = self._find_address()
            if addr is None:
                raise OSError("no device answered at "
                              + ", ".join(hex(a) for a in self.cfg.LCD_ADDRESSES))
            kind = opt(self.cfg, "LCD_TYPE").lower()
            if kind == "auto":
                kind = "oled" if addr in OLED_ADDRESSES else "char"
            if kind == "oled":
                self.screen = _Oled(self.cfg, addr, log=None if self._luma_noted else self.log)
                self._luma_noted = self._luma_noted or self.screen.driver_name != "luma.oled"
            else:
                self.screen = _CharLcd(self.cfg, addr)
            self.address = addr
            self._last_lines = None
            self._warned = False
            self.log.info("Display connected: %s (%s, %s) at I2C address %s",
                          self.screen.kind, self.screen.size,
                          getattr(self.screen, "driver_name", "RPLCD"), hex(addr))
        except ImportError as e:
            self.screen = None
            self.enabled = False   # retrying won't help until libs are installed
            self.log.warning("Display library missing (%s). Run install.sh, or: "
                             "sudo apt-get install -y python3-pil, then pip3 install --user --no-deps "
                             "--only-binary=:all: luma.oled==3.8.1 luma.core==2.3.1 cbor2==5.6.5 "
                             "smbus2==0.5.0 RPLCD==1.3.1. Continuing WITHOUT display.", e)
        except Exception as e:     # noqa: BLE001 - any display failure must not stop the lift
            self.screen = None
            if not self._warned:
                self.log.warning("Display not detected on I2C bus %d (%s). Continuing WITHOUT "
                                 "display; will retry every %ds.",
                                 self.cfg.LCD_I2C_PORT, e, self.cfg.LCD_RETRY_SECONDS)
                self._warned = True

    # ---------------------------------------------------------------- output
    def show(self, lines):
        """Show up to 4 lines. Only redraws when the text changes."""
        self._wanted = list(lines)
        if not self.enabled:
            return
        if self.screen is None:
            if time.monotonic() - self._last_attempt >= self.cfg.LCD_RETRY_SECONDS:
                self._connect()
            if self.screen is None:
                return
        lines = [(l or "") for l in list(lines)[:4]]
        lines += [""] * (4 - len(lines))
        if lines == self._last_lines:
            return
        try:
            self.screen.write(lines)
            self._last_lines = lines
        except Exception as e:     # noqa: BLE001
            self.log.warning("Display write failed (%s) - screen offline, elevator keeps "
                             "running; will retry every %ds.", e, self.cfg.LCD_RETRY_SECONDS)
            self.screen = None
            self._warned = True
            self._last_attempt = time.monotonic()

    def poll(self):
        """Call periodically: reconnects a late/unplugged screen and redraws."""
        self.show(self._wanted)

    def close(self):
        if self.screen is not None:
            try:
                self.screen.close()
            except Exception:      # noqa: BLE001
                pass
            self.screen = None
