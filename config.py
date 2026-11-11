"""
TinyLift v2 -- every setting you might want to change lives in this file.

Pin numbers below are BCM GPIO numbers (what the code uses). The comment on
each line gives the PHYSICAL header pin (1-40) you actually solder to.
See docs/WIRING.md for the pictures.

Layout:
  * Buttons are all on the header's odd-pin row (pins 11-37).
  * LEDs are on the even-pin row, except the Floor 3 LED (pin 23).
  * GPIO8, GPIO9 and GPIO11 are the Pi's SPI pins. That's fine as long as SPI
    stays off (the Raspberry Pi OS default) - don't turn SPI on in raspi-config.
"""

# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------
TOTAL_FLOORS = 6
LOBBY_FLOOR = 3          # floor the exterior UP/DOWN call buttons are on
START_FLOOR = 3          # where the cab "is" when the program starts

FLOOR_TRAVEL_SECONDS = 2.0   # time to move one floor
DOOR_DWELL_SECONDS = 2.0     # time the cab waits at a floor it stopped at

# --------------------------------------------------------------------------
# Buttons (inputs). Wired: Pi pin -> [AX11 relay COM->NO] -> button NO,
# button C -> GND. The Pi's internal pull-up is used, pressed = LOW.
# --------------------------------------------------------------------------
FLOOR_BUTTON_PINS = [
    17,  # Floor 1  -> physical pin 11
    27,  # Floor 2  -> physical pin 13
    9,   # Floor 3  -> physical pin 21
    5,   # Floor 4  -> physical pin 29
    6,   # Floor 5  -> physical pin 31
    13,  # Floor 6  -> physical pin 33
]
CALL_UP_BUTTON_PIN = 19    # physical pin 35
CALL_DOWN_BUTTON_PIN = 26  # physical pin 37

# A press must read LOW this long before it counts (filters switch bounce
# and noise picked up on long wires to the AX11).
DEBOUNCE_MS = 40

# --------------------------------------------------------------------------
# LEDs (outputs). Each pin drives one transistor base on the soldered
# breadboard. HIGH = transistor on = button's LED ring lit.
# --------------------------------------------------------------------------
FLOOR_LED_PINS = [
    18,  # Floor 1 LED -> physical pin 12
    8,   # Floor 2 LED -> physical pin 24
    11,  # Floor 3 LED -> physical pin 23
    25,  # Floor 4 LED -> physical pin 22
    12,  # Floor 5 LED -> physical pin 32
    16,  # Floor 6 LED -> physical pin 36
]
CALL_UP_LED_PIN = 20    # physical pin 38
CALL_DOWN_LED_PIN = 21  # physical pin 40

LED_ACTIVE_HIGH = True       # NPN transistors: HIGH turns the LED on
STARTUP_LAMP_TEST = True     # light every LED for 1 s at startup

# --------------------------------------------------------------------------
# Display (optional -- the program runs fine without it)
# --------------------------------------------------------------------------
LCD_ENABLED = True
LCD_I2C_PORT = 1             # /dev/i2c-1 (header pins 3 = SDA, 5 = SCL)

# Which kind of screen:
#   "auto" - decide by address: 0x3C/0x3D = OLED, anything else = character LCD
#   "oled" - SSD1306/SH1106 graphic OLED (e.g. ELEGOO 0.96" 128x64)
#   "char" - HD44780 character LCD with a PCF8574 I2C backpack
LCD_TYPE = "auto"

# Addresses to look for, in order. OLEDs are 0x3C/0x3D; character-LCD
# backpacks are 0x20-0x27 (PCF8574) or 0x38-0x3F (PCF8574A).
LCD_ADDRESSES = [0x3C, 0x3D, 0x27, 0x3F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25,
                 0x26, 0x38, 0x39, 0x3A, 0x3B, 0x3E]
LCD_RETRY_SECONDS = 30       # if the screen is missing/unplugged, try again this often

# OLED settings (ELEGOO 0.96" = ssd1306, 128 x 64)
OLED_DRIVER = "ssd1306"      # "sh1106" for most 1.3" OLEDs
OLED_WIDTH = 128
OLED_HEIGHT = 64             # 32 for the thin 128x32 modules
OLED_ROTATE = 0              # 2 = upside down (if the screen is mounted flipped)

# Character-LCD settings (only used for a 16x2 / 20x4 LCD)
LCD_EXPANDER = "PCF8574"     # use "MCP23008" or "MCP23017" if your backpack is one
LCD_COLS = 20                # 16 for a 1602 display
LCD_ROWS = 4                 # 2 for a 1602 display
LCD_CHARMAP = "A00"

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_FILE = "logs/tinylift.log"   # relative to this folder; set to None to disable

# --------------------------------------------------------------------------
# Reference only: BCM GPIO -> physical header pin (Pi 3B+ / 4 / Zero 40-pin).
# Used to print friendly messages. Don't edit.
# --------------------------------------------------------------------------
BCM_TO_PHYSICAL = {
    2: 3, 3: 5, 4: 7, 14: 8, 15: 10, 17: 11, 18: 12, 27: 13, 22: 15, 23: 16,
    24: 18, 10: 19, 9: 21, 25: 22, 11: 23, 8: 24, 7: 26, 5: 29, 6: 31, 12: 32,
    13: 33, 19: 35, 16: 36, 26: 37, 20: 38, 21: 40,
}
