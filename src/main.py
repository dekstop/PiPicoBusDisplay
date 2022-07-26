"""
MIT License

Copyright (c) 2022 Martin Dittus

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""Displays TfL bus arrival times on a Raspberry Pi Pico W with HD44780 LCD"""

# Pin configuration for the HD44780 LCD module:
#
# Pin Code    Description         Connect to
# --------------------------------------------------------
# 1   VSS     GND                 Ground
# 2   VDD     +5V                 5V
# 3   V0      Contrast (0-5V)*    Ground, or trimmer
# 4   RS      Register select     Pico Pin 16
# 5   R/W     Read/write          Ground
# 6   E       Enable              Pico Pin 17
# 7   DB0     Data Bit 0          Unused
# 8   DB1     Data Bit 1          Unused
# 9   DB2     Data Bit 2          Unused
# 10  DB3     Data Bit 3          Unused
# 11  DB4     Data Bit 4          Pico Pin 18
# 12  DB5     Data Bit 5          Pico Pin 19
# 13  DB6     Data Bit 6          Pico Pin 20
# 14  DB7     Data Bit 7          Pico Pin 21
# 15  A       Backlight +V        3.5V for LED backlight
# 16  K       Backlight GND       Ground

import machine
import network
import time
import urequests as requests

from gpio_lcd import GpioLcd

# ============
# = Settings =
# ============

import config

# =====================
# = Custom characters =
# =====================

# https://maxpromer.github.io/LCD-Character-Creator/

# Bus/TFL icon
TFL_ICON_CHAR_IDX = 0
TFL_ICON_CHAR = '\x00'
TFL_ICON_CHAR_BYTES = bytearray([0x00,0x0E,0x11,0x1F,0x11,0x0E,0x00,0x00])

# "..." character
ELLIPSIS_CHAR_IDX = 1
ELLIPSIS_CHAR = '\x01'
ELLIPSIS_CHAR_BYTES = bytearray([0x00,0x00,0x00,0x00,0x00,0x00,0x15,0x00])


# =========
# = Tools =
# =========

def substr(txt, max_len):
    if len(txt)<=max_len:
        return f"{txt:max_len}"
    return f"{txt[:max_len-1]}{ELLIPSIS_CHAR}"

def format_minutes_seconds(seconds):
    minutes = seconds // 60
    seconds = seconds % 60
    if minutes > 0:
        return f"{minutes}m{seconds}s"
    else:
        return f"{seconds}s"

def format_minutes(seconds):
    # minutes = round(seconds / 60) # too generous, might underestimate actual time left
    minutes = seconds // 60 # more pessimistic estimate of available time
    return f"{minutes}m"

def format_arrival(arrival, max_width):
    #f"{arrival['lineName']} to {arrival['destinationName']} in {format_seconds(arrival['timeToStation'])}"
    line = str(arrival['lineName'])
    destination = str(arrival['destinationName'])
    #eta = format_minutes_seconds(arrival['timeToStation'])
    eta = format_minutes(arrival['timeToStation'])
    max_width = max_width - 2 - len(line) - 1 - len(eta) - 1
    return f"{TFL_ICON_CHAR}{line} {substr(destination, max_width)} {eta}"

def display_arrivals_grid(arrivals, lcd, 
                          num_arrivals=2, 
                          num_columns=1,
                          column_width=16):
    lcd.clear()
    for idx, arrival in enumerate(arrivals[:num_arrivals]):
        lcd.move_to((idx % num_columns) * (column_width + 1), idx // num_columns)
        lcd.putstr(format_arrival(arrival, column_width))

def format_arrival_group(line, arrivals, max_width):
    etas = []
    for arrival in arrivals:
        #eta = format_minutes_seconds(arrival['timeToStation'])
        etas += [format_minutes(arrival['timeToStation'])]
    txt = f"{TFL_ICON_CHAR}{line}"
    
    for eta in etas:
        txt_tmp = f"{txt} {eta}"
        if len(txt_tmp)>max_width:
          break
        txt = txt_tmp
    return txt

def display_grouped_arrivals_grid(arrivals, lcd,
                                  lines=None,
                                  num_columns=1,
                                  column_width=16):
    lcd.clear()
    if lines is None:
        lines = sorted(set([arrival['lineName'] for arrival in arrivals]))
    for idx, line in enumerate(lines):
        line_arrivals = [arrival for arrival in arrivals 
          if arrival['lineName']==line]
        lcd.move_to((idx % num_columns) * (column_width + 1), idx // num_columns)
        lcd.putstr(format_arrival_group(line, line_arrivals, column_width))

# =========
# = Setup =
# =========

led = machine.Pin("LED", machine.Pin.OUT)
led.off()

lcd = GpioLcd(rs_pin=machine.Pin(16),
              enable_pin=machine.Pin(17),
              d4_pin=machine.Pin(18),
              d5_pin=machine.Pin(19),
              d6_pin=machine.Pin(20),
              d7_pin=machine.Pin(21),
              num_lines=config.LCD_ROWS, 
              num_columns=config.LCD_COLUMNS)

# Custom characters
lcd.custom_char(TFL_ICON_CHAR_IDX, TFL_ICON_CHAR_BYTES)
lcd.custom_char(ELLIPSIS_CHAR_IDX, ELLIPSIS_CHAR_BYTES)

lcd.display_on()
lcd.clear()

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm = 0xa11140) # Disable power-saving mode
wlan.connect(config.WIFI_SSID, config.WIFI_PWD)

# ===================
# = Connect to Wifi =
# ===================

print("Connecting to wifi...")

lcd.putstr('Connecting to wifi...')
lcd.show_cursor()
lcd.blink_cursor_on()

while not wlan.isconnected() and wlan.status() >= 0:
    led.toggle()
    time.sleep(0.5)

print('Connected.')
#print(wlan.ifconfig())

lcd.clear()
lcd.blink_cursor_off()
lcd.hide_cursor()

led.off()

# =============
# = Main loop =
# =============

while True:
    
    #
    # API request
    #
    led.on()
    lcd.show_cursor()
    lcd.blink_cursor_on()
    
    error = None
    error_info = None
    arrivals = []
    for naptanId in config.NAPTAN_IDS:
        text = None
        print(f"Requesting stop {naptanId}...")
        try:
            r = requests.get(f"https://api.tfl.gov.uk/StopPoint/{naptanId}/Arrivals?app_key={config.TFL_APP_KEY}",
                             headers={
                                 'User-Agent': config.USER_AGENT,
                             })
            text = r.text
            arrivals += r.json()
            r.close()
        except Exception as e:
            error = f"Error: {str(e)}"
            print(error)
            if text:
                error_info = text
                print(text)
            break

    led.off()
    lcd.blink_cursor_off()
    lcd.hide_cursor()

    #
    # Display
    #
    if error:
        lcd.clear()
        lcd.putstr(error)
        if error_info:
            lcd.move_to(0,1)
            lcd.putstr(error_info)
        for i in range(config.UPDATE_WAIT_SECONDS * 5):
            led.toggle()
            time.sleep(0.2)
        lcd.clear()
    else: #if len(arrivals)>0:

        # Sort all entries by arrival time
        arrivals = sorted(arrivals, 
          key=lambda arrival: arrival['timeToStation'])
      
        # Log the full list
        for arrival in arrivals:
            print(f"{arrival['lineName']} to {arrival['destinationName']} in {format_minutes_seconds(arrival['timeToStation'])}")

        # Display the nearest 4 arrivals as a 2x2 grid
        # display_arrivals_grid(arrivals, lcd,
        #                       num_arrivals=4,
        #                       num_columns=2,
        #                       column_width=config.LCD_COLUMNS // 2)
        
        # Display all/most arrivals, grouped by line, as a 2x2 grid
        display_grouped_arrivals_grid(arrivals, lcd,
                                      lines=config.LINE_DISPLAY_ORDER,
                                      num_columns=2,
                                      column_width=config.LCD_COLUMNS // 2)

        time.sleep(config.UPDATE_WAIT_SECONDS)
