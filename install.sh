#!/bin/bash
# TinyLift v2 installer.
# Installs the Python libraries, checks I2C, and (optionally) sets TinyLift to
# start at boot. Run it from wherever you cloned the repo:
#
#   git clone https://github.com/FletcherMeyer/tinylift.git ~/tinylift
#   cd ~/tinylift && bash install.sh
#
# TinyLift runs from that folder. (If you instead copied the folder onto the SD
# card's boot partition, running it from there copies it to
# ~/Downloads/tinylift_v2 first, because the boot partition can't run scripts.)
#
# Optional, start TinyLift at every boot (pick one):
#   --cron          cron @reboot job, output shown in a window on the Pi's screen
#   --autostart     hidden systemd service (no window, logs only)
#   --no-autostart  undo either one
set -e

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$SRC" in
    /boot/*) DEST="$HOME/Downloads/tinylift_v2" ;;   # copied onto the SD card's boot partition
    *)       DEST="$SRC" ;;                         # a normal git clone: install in place
esac

if [ "$SRC" != "$DEST" ]; then
    echo "== Copying $SRC -> $DEST"
    if [ -e "$DEST" ]; then
        BACKUP="${DEST}_backup_$(date +%Y%m%d_%H%M%S)"
        echo "   $DEST already exists - moving it to $BACKUP first"
        mv "$DEST" "$BACKUP"
    fi
    mkdir -p "$(dirname "$DEST")"
    cp -r "$SRC" "$DEST"
else
    echo "== Installing in place: $DEST"
fi
# Keep your own pin/timing edits: reuse the previous config.py if there was one.
# (Settings added in newer versions have built-in defaults, so an older
# config.py keeps working.)
if [ -n "$BACKUP" ] && [ -f "$BACKUP/config.py" ]; then
    cp "$BACKUP/config.py" "$DEST/config.py"
    echo "   Kept your existing config.py (the new default is in $SRC/config.py)"
fi
# Files copied off the FAT boot partition may have Windows line endings / no exec bit.
sed -i 's/\r$//' "$DEST"/*.py "$DEST"/*.sh "$DEST"/*.service 2>/dev/null || true
chmod +x "$DEST/tinylift.py" "$DEST/install.sh" "$DEST/start_on_boot.sh"

echo "== Installing Python libraries (RPi.GPIO, smbus2, RPLCD, luma.oled)"
sudo apt-get update >/dev/null || true
sudo apt-get install -y python3-rpi.gpio python3-smbus python3-pip python3-pil \
    fonts-dejavu-core i2c-tools >/dev/null || \
    echo "   (apt step failed - continuing; RPi.GPIO is normally preinstalled)"
# Pillow comes ONLY from apt (python3-pil, pre-built). pip must never try to
# build it - that fails on a Pi 3. So the pip packages are exact, pure-Python
# versions installed with --no-deps --only-binary=:all: (pip can't compile
# anything). luma.core 2.3.1 / luma.oled 3.8.1 are the newest versions that
# accept Bullseye's Pillow 8.1; newer luma needs Pillow >= 9.2.
PKGS="luma.oled==3.8.1 luma.core==2.3.1 cbor2==5.6.5 smbus2==0.5.0 RPLCD==1.3.1"
PIPOPTS="--user --no-deps --only-binary=:all:"
# The check imports the actual names, not just the package: a package whose
# files are empty or cut short (an install followed by a power cut before the
# SD card finished writing) still "imports" but has nothing in it.
LIBCHECK="from smbus2 import SMBus; from luma.core.interface.serial import i2c; from luma.oled.device import ssd1306; from RPLCD.i2c import CharLCD"
if ! python3 -c "$LIBCHECK" 2>/dev/null; then
    echo "   Libraries missing or damaged - doing a clean reinstall."
    pip3 uninstall -y luma.oled luma.core cbor2 smbus2 RPLCD >/dev/null 2>&1 || \
    pip3 uninstall -y --break-system-packages luma.oled luma.core cbor2 smbus2 RPLCD >/dev/null 2>&1 || true
    pip3 install $PIPOPTS --no-cache-dir --force-reinstall $PKGS 2>/dev/null || \
    pip3 install $PIPOPTS --no-cache-dir --force-reinstall --break-system-packages $PKGS
fi
sync   # flush everything to the SD card now, so a power cut can't empty the files
if python3 -c "$LIBCHECK" 2>/dev/null; then
    echo "   Display libraries OK."
else
    echo "   WARNING: the display libraries still won't import:"
    python3 -c "$LIBCHECK" 2>&1 | tail -1 | sed 's/^/     /'
    echo "   The screen still works: TinyLift falls back to its built-in OLED driver."
    echo "   Empty library files point to SD-card damage - see the troubleshooting"
    echo "   table in docs/WIRING.md."
fi
if ! python3 -c "import PIL" 2>/dev/null; then
    echo "   WARNING: Pillow (python3-pil) is missing - the OLED won't work until"
    echo "   'sudo apt-get install -y python3-pil' succeeds. The elevator still runs."
fi

echo "== Checking I2C (for the screen)"
if [ -e /dev/i2c-1 ]; then
    echo "   I2C is on. Devices found on bus 1 (OLED is usually 3c, character LCD 27 or 3f):"
    i2cdetect -y 1 || true
else
    echo "   I2C is OFF. Turning it on (takes effect after a reboot)..."
    sudo raspi-config nonint do_i2c 0 || echo "   Enable it manually: sudo raspi-config -> Interface Options -> I2C"
fi

CRON_LINE="@reboot /bin/bash $DEST/start_on_boot.sh"
remove_cron() {
    if crontab -l 2>/dev/null | grep -q "start_on_boot.sh"; then
        crontab -l 2>/dev/null | grep -v "start_on_boot.sh" | crontab -
        echo "   Removed the TinyLift line from your crontab."
    fi
}
remove_service() {
    if [ -f /etc/systemd/system/tinylift.service ]; then
        sudo systemctl disable --now tinylift.service 2>/dev/null || true
        sudo rm -f /etc/systemd/system/tinylift.service
        sudo systemctl daemon-reload
        echo "   Removed the tinylift systemd service."
    fi
}

case "$1" in
--cron)
    # Start at every boot from cron, with the output shown on the Pi's screen.
    echo "== Adding TinyLift to cron (@reboot, output on screen)"
    remove_service   # never run two copies at once - they'd fight over the GPIO pins
    ( crontab -l 2>/dev/null | grep -v "start_on_boot.sh"; echo "$CRON_LINE" ) | crontab -
    echo "   crontab now has:  $CRON_LINE"
    echo "   Reboot to try it: sudo reboot"
    echo "   If nothing shows up, read $DEST/logs/boot.log"
    ;;
--autostart)
    # Start at every boot as a hidden systemd service (no window; logs only).
    echo "== Installing autostart service"
    remove_cron
    sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$DEST|g" "$DEST/tinylift.service" | \
        sudo tee /etc/systemd/system/tinylift.service >/dev/null
    sudo systemctl daemon-reload
    sudo systemctl enable --now tinylift.service
    echo "   Running. Logs: journalctl -u tinylift -f    Stop: sudo systemctl stop tinylift"
    ;;
--no-autostart)
    echo "== Turning off start-at-boot"
    remove_cron
    remove_service
    ;;
esac

# Warn about anything else in cron that starts a Python program at boot
# (for example the original tinyLift) - two programs on the same pins
# cause phantom presses and LEDs that flicker.
OTHER=$(crontab -l 2>/dev/null | grep -i "@reboot" | grep -v "start_on_boot.sh" || true)
if [ -n "$OTHER" ]; then
    echo
    echo "   NOTE: your crontab also starts this at boot:"
    echo "$OTHER" | sed 's/^/     /'
    echo "   If that's the old tinyLift program, remove it with: crontab -e"
fi

echo
echo "Done. Next steps:"
echo "  cd $DEST"
echo "  python3 tinylift.py --test     # check every LED and button"
echo "  python3 tinylift.py            # run the elevator"
