#!/bin/bash
# TinyLift boot launcher -- run by cron at every boot, shows TinyLift's output
# on the Pi's monitor.
#
# Install it with:   bash install.sh --cron
# (that adds this line to your crontab:  @reboot /bin/bash <this folder>/start_on_boot.sh)
#
# What it does:
#   1. waits for the Pi to finish booting
#   2. if the desktop is up, opens a terminal window titled "TinyLift" running
#      the program, so you see every button press and floor change
#   3. with no desktop (console-only Pi), prints the output on the console
#      screen (tty1) instead
# The program's own log is still written to logs/tinylift.log, and this
# launcher's notes go to logs/boot.log (check that file if nothing appears).

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="/tmp/tinylift.lock"
BOOT_DELAY="${TINYLIFT_BOOT_DELAY:-15}"   # seconds to wait after boot
DESKTOP_WAIT="${TINYLIFT_DESKTOP_WAIT:-90}"  # seconds to wait for the desktop

# ---------------------------------------------------------------------------
# Inner mode: this is what actually runs inside the terminal window / console.
# ---------------------------------------------------------------------------
if [ "$1" == "--inner" ]; then
    cd "$DIR" || exit 1
    exec 9>"$LOCK"
    if ! flock -n 9; then
        echo "TinyLift is already running - not starting a second copy."
        sleep 10
        exit 0
    fi
    echo "Starting TinyLift ($(date))   -   close this window or press Ctrl+C to stop."
    echo
    python3 -u tinylift.py
    code=$?
    echo
    echo "TinyLift stopped (exit code $code). Full log: $DIR/logs/tinylift.log"
    if [ "$2" != "--console" ]; then
        read -r -p "Press Enter to close this window."
    fi
    exit $code
fi

# ---------------------------------------------------------------------------
# Outer mode: started by cron.
# ---------------------------------------------------------------------------
mkdir -p "$DIR/logs"
exec >>"$DIR/logs/boot.log" 2>&1
echo "== $(date '+%Y-%m-%d %H:%M:%S')  boot launcher started (user $(id -un))"

if systemctl is-active --quiet tinylift.service 2>/dev/null; then
    echo "   The tinylift systemd service is already running it - nothing to do."
    echo "   (Use either cron OR the service, not both: bash install.sh --cron turns the service off.)"
    exit 0
fi

sleep "$BOOT_DELAY"

# Settings a cron job doesn't have but a desktop window needs.
export DISPLAY="${DISPLAY:-:0}"
export XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[ -S "$XDG_RUNTIME_DIR/wayland-1" ] && export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}"

# Wait for the desktop (panel running) if this Pi boots to one.
desktop_up() {
    [ -S /tmp/.X11-unix/X0 ] && pgrep -u "$(id -u)" -f "lxpanel|wf-panel-pi" >/dev/null
}
waited=0
while ! desktop_up && [ $waited -lt $DESKTOP_WAIT ]; do
    sleep 2; waited=$((waited + 2))
done

if desktop_up; then
    sleep 3   # let the desktop settle so the window lands on top
    if command -v lxterminal >/dev/null; then
        echo "   Desktop found - opening a TinyLift terminal window (lxterminal)."
        setsid lxterminal --title=TinyLift --geometry=100x30 \
            -e /bin/bash "$DIR/start_on_boot.sh" --inner &
    elif command -v x-terminal-emulator >/dev/null; then
        echo "   Desktop found - opening a TinyLift terminal window (x-terminal-emulator)."
        setsid x-terminal-emulator -T TinyLift \
            -e /bin/bash "$DIR/start_on_boot.sh" --inner &
    else
        echo "   Desktop found but no terminal program - running in the background."
        echo "   Watch it with:  tail -f $DIR/logs/tinylift.log"
        setsid /bin/bash "$DIR/start_on_boot.sh" --inner --console </dev/null >/dev/null 2>&1 &
    fi
elif [ -w /dev/tty1 ]; then
    echo "   No desktop - showing the output on the console screen (tty1)."
    setsid /bin/bash "$DIR/start_on_boot.sh" --inner --console </dev/null >/dev/tty1 2>&1 &
else
    echo "   No desktop, and this user can't write to the console screen (tty1)."
    echo "   Running in the background. Watch it with:  tail -f $DIR/logs/tinylift.log"
    echo "   (Turn on console autologin in raspi-config -> System Options -> Boot / Auto Login"
    echo "    to see it on the screen.)"
    setsid /bin/bash "$DIR/start_on_boot.sh" --inner --console </dev/null >/dev/null 2>&1 &
fi
echo "   launched."
