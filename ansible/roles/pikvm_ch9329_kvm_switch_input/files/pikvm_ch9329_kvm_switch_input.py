#!/usr/bin/env python3
"""Switch a KVM switch's input by typing its hotkey on a CH9329 UART-to-USB-HID keyboard.

Types ScrollLock, ScrollLock, <input_number>. kvmd's own CH9329 code frames each command and checks
the chip's reply; this script owns the port settings, the keys and the timing.
"""

import argparse
import sys
import time

import serial

from kvmd.plugins.hid.ch9329.chip import ChipConnection
from kvmd.plugins.hid.ch9329.chip import ChipResponseError

SPEED = 9600  # the CH9329's factory default
REPLY_TIMEOUT = 0.5  # WCH protocol V1.0: no reply within 500 ms means the command failed
KEY_GAP = 0.25  # seconds between presses

SCROLL_LOCK = 0x47
DIGIT_1 = 0x1E  # Digit1..Digit9 are 0x1E..0x26


def keyboard_report(code: int) -> bytes:
    # Address 0x00, CMD_SEND_KB_GENERAL_DATA 0x02, 8 data bytes: modifiers, reserved, six keys.
    return bytes([0x00, 0x02, 0x08, 0x00, 0x00, code, 0x00, 0x00, 0x00, 0x00, 0x00])


def press(conn: ChipConnection, code: int) -> None:
    conn.xfer(keyboard_report(code))
    conn.xfer(keyboard_report(0x00))


def switch_input(conn: ChipConnection, input_number: int) -> None:
    for index, code in enumerate((SCROLL_LOCK, SCROLL_LOCK, DIGIT_1 + input_number - 1)):
        if index:
            time.sleep(KEY_GAP)
        press(conn, code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Switch a KVM switch's input through a CH9329.")
    parser.add_argument("device", help="the CH9329's serial port, preferably its /dev/serial/by-id/ path")
    parser.add_argument("input_number", type=int, choices=range(1, 10))
    args = parser.parse_args(argv)

    print(f"Sending ScrollLock + ScrollLock + {args.input_number} to {args.device}", flush=True)
    try:
        with serial.Serial(args.device, SPEED, timeout=REPLY_TIMEOUT, write_timeout=REPLY_TIMEOUT, exclusive=True) as tty:
            switch_input(ChipConnection(tty), args.input_number)
    except (serial.SerialException, ChipResponseError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
