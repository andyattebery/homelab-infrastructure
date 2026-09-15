"""Pin every byte of the udev monitor message that can fail silently.

Run:
    cd ansible && .venv/bin/pytest ../scripts/tests/ -q

WHAT THIS IS FOR. A subscriber (libinput, `udevadm monitor`, anything on libudev) attaches a BPF
socket filter that compares `filter_subsystem_hash` in our header against its own MurmurHash2 of
the subsystem it subscribed to. If our hash is wrong, or any field's endianness is wrong, the
kernel drops the message inside the *receiver's* filter: `sendmsg` returns success, nothing is
logged at either end, and the only symptom is an input device that never appears. There is no
error to go looking for. That is why these assertions are this pedantic.

WHAT IT CANNOT PROVE. That a real libudev accepts the message, and that sending to the multicast
group is permitted in an unprivileged container. Neither is answerable on a laptop: the first
needs libudev, the second needs an LXC. `scripts/vdesktop-uevent-probe.sh` covers both, on a
real container. See ansible/tests/README.md, "Where a new test goes" -- this is the pytest row, and the
probe is the thing a pytest cannot replace.

THE REFERENCE VECTORS ARE NOT SELF-GENERATED. Asserting our port against our port's own output
would prove only that it is deterministic. The constants below came from compiling Austin
Appleby's original -- systemd v257 `src/basic/MurmurHash2.c`, unmodified except for its include
line -- with `cc -O2` on 2026-09-14 and reading its output. Regenerating them means doing that
again, not calling the Python.
"""

import struct

import pytest

import fake_udev_send as fus

# From the compiled upstream C, seed 0, on a little-endian host. See the module docstring.
UPSTREAM_VECTORS = {
    "": 0x00000000,
    "a": 0x92685F5E,
    "ab": 0x1AA14063,
    "abc": 0x13577C9B,
    "abcd": 0x26873021,
    "input": 0xC1A28470,
    "hidraw": 0xC2CAF397,
    "sound": 0xD196AB6E,
    "block": 0xF0031DB7,
}


@pytest.mark.parametrize("value,expected", sorted(UPSTREAM_VECTORS.items()))
def test_murmurhash2_matches_upstream_c(value, expected):
    """The port agrees with the C for every length class mod 4.

    The vectors are chosen to cover the fall-through tail: "abcd" takes the loop only, "abc"/"ab"
    /"a" take one, two and three tail cases. A port that mishandles the tail passes on "abcd"
    alone, which is the trap a single-vector test walks into.
    """
    assert fus.string_hash32(value) == expected


def test_empty_string_hash_is_zero_by_construction():
    """An independent check that does not depend on the recorded vectors at all.

    h starts as `seed ^ len` = 0, no block runs, no tail runs, and the final avalanche of zero is
    zero. So this one is derivable from the algorithm by hand -- it catches a port that silently
    seeds with something other than 0.
    """
    assert fus.murmurhash2(b"", 0) == 0


def test_header_is_exactly_forty_bytes():
    """systemd's struct is 8 + 8*4. A header of any other size makes `properties_off` a lie and
    the receiver reads the payload from the wrong place."""
    assert len(fus.build_header(0, "input")) == 40
    assert fus.HEADER_SIZE == 40


def test_header_prefix_is_nul_terminated_libudev():
    """The receiver dispatches on `streq(message.nulstr, "libudev")` (device-monitor.c:641). A
    prefix without its NUL falls through to the *kernel* message branch, which then rejects it
    for having no "@/" -- an error that reads as a malformed kernel event, nowhere near the
    cause."""
    assert fus.build_header(0, "input")[:8] == b"libudev\0"


def test_magic_is_big_endian():
    """Compared raw against `htobe32(UDEV_MONITOR_MAGIC)` at device-monitor.c:643. Stored
    little-endian it becomes 0xfecaedfe on the wire and the receiver logs "Invalid message
    signature"."""
    (magic_be,) = struct.unpack_from(">I", fus.build_header(0, "input"), 8)
    assert magic_be == fus.UDEV_MONITOR_MAGIC


def test_subsystem_hash_is_big_endian_and_correct():
    """The single most important assertion in this file.

    Two ways to get it wrong, both silent: the wrong hash, or the right hash in the wrong byte
    order. The BPF filter loads this field with BPF_LD|BPF_W|BPF_ABS (device-monitor.c:866),
    which is defined to load big-endian, and compares against the host-order hash -- so the
    field must be stored big-endian for the comparison to land.
    """
    header = fus.build_header(0, "input")
    (hash_be,) = struct.unpack_from(">I", header, 24)
    assert hash_be == UPSTREAM_VECTORS["input"]

    # And it is genuinely byte-swapped, not accidentally palindromic.
    (hash_le,) = struct.unpack_from("<I", header, 24)
    assert hash_le != hash_be


def test_length_fields_are_host_order_not_big_endian():
    """`properties_off` is read as a plain integer at device-monitor.c:648 -- no be32toh. Storing
    it big-endian yields 0x28000000, which trips the receiver's "Invalid offset for properties"
    guard. This is the field where copying the magic's treatment breaks it."""
    header = fus.build_header(17, "input")
    header_size, properties_off, properties_len = struct.unpack_from("<III", header, 12)
    assert (header_size, properties_off, properties_len) == (40, 40, 17)


def test_devtype_and_tag_bloom_are_zero_when_unset():
    """libinput subscribes with no devtype and no tag filter, and a zero field matches. A junk
    value here would be compared against and would drop the message."""
    header = fus.build_header(0, "input")
    devtype, bloom_hi, bloom_lo = struct.unpack_from("<III", header, 28)
    assert (devtype, bloom_hi, bloom_lo) == (0, 0, 0)


def test_payload_is_nul_terminated_key_values_in_order():
    """udev does not sort properties and neither do we -- a capture of ours should look like a
    capture of udev's. The trailing NUL on the last entry is required: the receiver walks the
    buffer by NUL and a missing one runs the last property into whatever follows."""
    payload = fus.build_payload({"ACTION": "add", "DEVPATH": "/devices/x", "SUBSYSTEM": "input"})
    assert payload == b"ACTION=add\0DEVPATH=/devices/x\0SUBSYSTEM=input\0"
    assert payload.endswith(b"\0")


def test_properties_len_matches_the_payload_actually_appended():
    """Header and payload are built in separate functions; this is the seam where they can drift
    apart. A short `properties_len` truncates the last property silently."""
    properties = {"ACTION": "add", "DEVPATH": "/devices/virtual/input/event9", "SUBSYSTEM": "input"}
    message = fus.build_message(properties)
    (properties_len,) = struct.unpack_from("<I", message, 20)
    assert properties_len == len(message) - fus.HEADER_SIZE
    assert message[fus.HEADER_SIZE:] == fus.build_payload(properties)


def test_missing_subsystem_is_refused_rather_than_hashed_as_empty():
    """Without SUBSYSTEM the hash would be MurmurHash2("") == 0, which matches no subscriber's
    filter -- a message that sends cleanly and is dropped by every receiver. Refuse it instead."""
    with pytest.raises(ValueError, match="SUBSYSTEM"):
        fus.build_message({"ACTION": "add", "DEVPATH": "/devices/x"})


def test_a_different_subsystem_produces_a_different_hash():
    """Guards against a build_header that ignores its subsystem argument and hardcodes `input` --
    which would pass every other assertion in this file."""
    input_header = fus.build_header(0, "input")
    sound_header = fus.build_header(0, "sound")
    assert input_header[24:28] != sound_header[24:28]
    (sound_be,) = struct.unpack_from(">I", sound_header, 24)
    assert sound_be == UPSTREAM_VECTORS["sound"]


def test_netlink_protocol_constant_is_the_kernel_abi_number():
    """`NETLINK_KOBJECT_UEVENT` is 15 -- include/uapi/linux/netlink.h:24 at Linux v7.0.

    Pinned because Python does NOT reliably export it: Debian 13's python3.13 has no
    `socket.NETLINK_KOBJECT_UEVENT` and raises AttributeError, while other builds do have it.
    Discovered on a Debian 13 container on 2026-09-14, where its absence crashed every send.
    It is a kernel ABI number and cannot change.
    """
    assert fus.NETLINK_KOBJECT_UEVENT == 15


def test_udev_group_is_two_not_the_kernel_group():
    """Group 1 is the KERNEL group, group 2 the udevd-processed one. libinput subscribes to 2
    (`udev_monitor_new_from_netlink(udev, "udev")`, udev-seat.c:284). Sending to group 1 would
    reach a `udevadm monitor --kernel` and never reach libinput."""
    assert fus.MONITOR_GROUP_UDEV == 2


class _FakeRun:
    """Stands in for subprocess.run so classify() can be tested with no udevadm and no devices."""

    def __init__(self, stdout):
        self.stdout = stdout


def test_classify_extracts_the_id_input_properties(monkeypatch):
    """THE regression test for the bug that shipped: a device announced without
    ID_INPUT_KEYBOARD / ID_INPUT_MOUSE is opened by libinput, classified as
    EVDEV_UNHANDLED_DEVICE, and dropped -- logged at info level and surfaced nowhere. The
    observed symptom on a real host was `swaymsg -t get_inputs` returning ZERO devices while
    every event arrived correctly and the udev rule had done its job.

    Real `udevadm test-builtin input_id` output for the keyboard this exists for, interleaved
    with the progress lines the builtin also prints.
    """
    output = (
        "Loading builtin: input_id\n"
        "ID_INPUT=1\n"
        "ID_INPUT_MOUSE=1\n"
        "ID_INPUT_KEY=1\n"
        "ID_INPUT_KEYBOARD=1\n"
        "Unload module index\n"
    )
    monkeypatch.setattr(fus.subprocess, "run", lambda *a, **k: _FakeRun(output))
    assert fus.classify("event8") == {
        "ID_INPUT": "1",
        "ID_INPUT_MOUSE": "1",
        "ID_INPUT_KEY": "1",
        "ID_INPUT_KEYBOARD": "1",
    }


def test_classify_ignores_non_id_input_lines():
    """The builtin prints progress and a summary around the properties. Anything that is not an
    ID_INPUT key would become a bogus udev property on the wire."""
    output = "Loading builtin: input_id\nDEVPATH=/devices/x\nID_INPUT=1\nUnload module index\n"
    import types
    fake = types.SimpleNamespace(run=lambda *a, **k: _FakeRun(output))
    real = fus.subprocess
    fus.subprocess = fake
    try:
        assert fus.classify("event8") == {"ID_INPUT": "1"}
    finally:
        fus.subprocess = real


def test_classify_survives_a_missing_udevadm(monkeypatch):
    """Announcing with fewer properties beats not announcing at all, so a failure here must not
    be fatal -- the caller logs it and carries on."""
    def boom(*a, **k):
        raise FileNotFoundError("no udevadm")
    monkeypatch.setattr(fus.subprocess, "run", boom)
    assert fus.classify("event8") == {}
