"""Guards for the KVM switch hotkey sender that kvmd's menu buttons run.

    cd ansible && .venv/bin/pytest roles/pikvm_ch9329_kvm_switch_input/tests/ -q

Hermetic: no serial port, no kvmd, no sleeping. The script's two I/O boundaries are injected:
pyserial's Serial (the port) and kvmd's ChipConnection (CH9329 framing and reply checking, which
kvmd owns and PiKVM's own CH9329 HID mode runs on). kvmd is not installed here, so a fixture puts a
stub `kvmd.plugins.hid.ch9329.chip` into sys.modules before the script is loaded.

WHAT IT CANNOT PROVE. kvmd's framing against the real chip, that the kvmd import resolves on the
PiKVM, and that the KVM switch accepts the key spacing. The first press of a menu button proves all
three.

The expected payloads are written out by hand from WCH's "CH9329芯片串口通信协议" V1.0: section
2.2.2 (command 0x02, length 8, data [modifiers, 0x00, key1..key6]) and appendix 1 (ScrollLock 0x47,
Digit1-4 0x1E-0x21). Nothing below computes them with the script's own code.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest
import serial

SCRIPT = Path(__file__).resolve().parents[1] / "files" / "pikvm_ch9329_kvm_switch_input.py"
DEVICE = "/dev/serial/by-id/usb-example-if00-port0"

# What ChipConnection.xfer receives: address 0x00, command 0x02, length 0x08, then the 8-byte report.
SCROLL_LOCK_DOWN = bytes.fromhex("00 02 08 00 00 47 00 00 00 00 00")
ALL_KEYS_UP = bytes.fromhex("00 02 08 00 00 00 00 00 00 00 00")
DIGIT_DOWN = {
    1: bytes.fromhex("00 02 08 00 00 1e 00 00 00 00 00"),
    2: bytes.fromhex("00 02 08 00 00 1f 00 00 00 00 00"),
    3: bytes.fromhex("00 02 08 00 00 20 00 00 00 00 00"),
    4: bytes.fromhex("00 02 08 00 00 21 00 00 00 00 00"),
}


class ChipResponseError(Exception):
    """Stands in for kvmd's ChipResponseError, which ChipConnection.xfer raises."""


def _load():
    assert SCRIPT.exists(), "script missing at %s" % SCRIPT
    spec = importlib.util.spec_from_file_location("_pikvm_ch9329_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # The script lives in an Ansible files/ directory; bytecode there would be untracked cruft
    # next to a file the role copies to the PiKVM.
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def chip(monkeypatch):
    """A stub of kvmd's chip module. Every xfer and sleep lands in one ordered event list."""
    state = types.SimpleNamespace(events=[], ttys=[], fail_on_xfer=None)

    class ChipConnection:
        # kvmd: ChipConnection(tty: serial.Serial); xfer(cmd: bytes) -> int, the LED byte for a
        # GET_INFO reply and -1 for anything else.
        def __init__(self, tty):
            state.ttys.append(tty)

        def xfer(self, cmd):
            state.events.append(("xfer", bytes(cmd)))
            xfers = sum(1 for kind, _ in state.events if kind == "xfer")
            if xfers == state.fail_on_xfer:
                raise ChipResponseError("Response error code = 228")
            return -1

    chip_module = types.ModuleType("kvmd.plugins.hid.ch9329.chip")
    chip_module.ChipConnection = ChipConnection
    chip_module.ChipResponseError = ChipResponseError
    for name in ("kvmd", "kvmd.plugins", "kvmd.plugins.hid", "kvmd.plugins.hid.ch9329"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "kvmd.plugins.hid.ch9329.chip", chip_module)
    return state


@pytest.fixture
def port(monkeypatch):
    """Replaces serial.Serial. Records how the port was opened, or raises `error` instead."""

    class Tty:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    state = types.SimpleNamespace(opens=[], tty=Tty(), error=None)

    def fake_serial(port, baudrate, **kwargs):
        state.opens.append((port, baudrate, kwargs))
        if state.error is not None:
            raise state.error
        return state.tty

    monkeypatch.setattr(serial, "Serial", fake_serial)
    return state


@pytest.fixture
def script(chip, port, monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "time", types.SimpleNamespace(sleep=lambda s: chip.events.append(("sleep", s))))
    return module


@pytest.mark.parametrize("input_number", [1, 2, 3, 4])
def test_types_scroll_lock_twice_then_the_input_digit(script, chip, input_number):
    assert script.main([DEVICE, str(input_number)]) == 0

    # Three presses, each down then up, with a pause between presses and none after the last.
    assert [kind for kind, _ in chip.events] == ["xfer", "xfer", "sleep", "xfer", "xfer", "sleep", "xfer", "xfer"]
    assert [value for kind, value in chip.events if kind == "xfer"] == [
        SCROLL_LOCK_DOWN,
        ALL_KEYS_UP,
        SCROLL_LOCK_DOWN,
        ALL_KEYS_UP,
        DIGIT_DOWN[input_number],
        ALL_KEYS_UP,
    ]
    assert all(value > 0 for kind, value in chip.events if kind == "sleep")


def test_chip_error_stops_the_sequence_and_exits_1(script, chip, capsys):
    chip.fail_on_xfer = 1

    assert script.main([DEVICE, "1"]) == 1

    # Nothing is sent after the chip rejects a command, and kvmd's log gets the reason.
    assert chip.events == [("xfer", SCROLL_LOCK_DOWN)]
    assert "Response error code = 228" in capsys.readouterr().err


def test_opens_the_port_exclusively_with_bounded_io(script, chip, port):
    assert script.main([DEVICE, "2"]) == 0

    ((device, baudrate, kwargs),) = port.opens
    assert device == DEVICE
    # The cable's CH9329 answered GET_INFO at 9600 baud on 2026-10-07; at any other rate it is silent.
    assert baudrate == 9600
    # kvmd's cmd driver waits on the script with no timeout, so neither reads nor writes may block forever.
    assert kwargs.get("timeout") is not None and kwargs["timeout"] > 0
    assert kwargs.get("write_timeout") is not None and kwargs["write_timeout"] > 0
    # Two buttons pressed together must not interleave their keys on one chip.
    assert kwargs.get("exclusive") is True
    # kvmd's ChipConnection talks over that same port, not one it opened itself.
    assert chip.ttys == [port.tty]


def test_unopenable_port_exits_1_without_touching_the_chip(script, chip, port, capsys):
    port.error = serial.SerialException(2, "could not open port %s: [Errno 2] No such file or directory" % DEVICE)

    assert script.main([DEVICE, "1"]) == 1

    assert chip.ttys == []
    assert chip.events == []
    assert "No such file or directory" in capsys.readouterr().err


@pytest.mark.parametrize("input_number", ["0", "10"])
def test_rejects_an_input_with_no_digit_key_before_opening_the_port(script, port, input_number):
    # 0 would type the key before Digit1 (Z); only 1-9 map to digit keys.
    with pytest.raises(SystemExit) as exit_info:
        script.main([DEVICE, input_number])

    assert exit_info.value.code == 2
    assert port.opens == []
