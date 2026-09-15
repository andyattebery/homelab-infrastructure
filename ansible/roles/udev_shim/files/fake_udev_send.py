#!/usr/bin/env python3
"""Send a synthetic udev event onto the NETLINK_KOBJECT_UEVENT *udev* multicast group.

Why this exists: an unprivileged PVE container runs no udevd and receives no kernel uevents in
its network namespace, so a wlroots compositor's libinput never learns about input devices that
appear after it starts. Sunshine's virtual keyboard and mouse are exactly such devices. libinput
does not listen to the kernel, though -- it listens to the *udevd-processed* group, which is a
userspace group that anything with CAP_NET_ADMIN in the owning netns may write to. This writes
to it.

Ported from games-on-whales/wolf `src/fake-udev/`, whose header struct is itself copied from
systemd `src/libsystemd/sd-device/device-monitor.c`. Verified against systemd v257 and against
Linux v7.0's netlink permission check. The calling playbook's plan carries the full derivation.

THE SILENT FAILURE THIS FILE EXISTS TO AVOID: a subscriber attaches a BPF filter that compares
`filter_subsystem_hash` against MurmurHash2 of the subsystem it asked for. Get that hash wrong,
or get the field endianness wrong, and the kernel drops the message inside the receiver's socket
filter. `sendmsg` still returns success, nothing is logged anywhere, and the only symptom is a
device that never appears. tests/test_fake_udev_send.py pins every one of those bytes.

Usage:
    fake-udev-send.py --devnode /dev/input/event12 [--action add] [--seqnum N]
    fake-udev-send.py --devpath /devices/virtual/input/input9/event12 \\
                      --devname input/event12 --major 13 --minor 76
    fake-udev-send.py --self-test          # no socket, prints the bytes it would send

`--write-db` additionally writes /run/udev/data/c<major>:<minor> and creates /run/udev/control.
Neither is required for a subscriber's *monitor* to accept the event -- see the module notes --
but the db file is what makes a later re-enumeration (a compositor restart) find the device.
"""

import argparse
import glob
import os
import subprocess
import socket
import stat
import struct
import sys

# --- the wire format ------------------------------------------------------------------------
#
# systemd v257 src/libsystemd/sd-device/device-monitor.c:72-89, field for field:
#
#     char     prefix[8];               offset  0   "libudev\0"
#     unsigned magic;                   offset  8   BIG-endian 0xfeedcafe
#     unsigned header_size;             offset 12   host order
#     unsigned properties_off;          offset 16   host order
#     unsigned properties_len;          offset 20   host order
#     unsigned filter_subsystem_hash;   offset 24   BIG-endian
#     unsigned filter_devtype_hash;     offset 28   BIG-endian
#     unsigned filter_tag_bloom_hi;     offset 32   BIG-endian
#     unsigned filter_tag_bloom_lo;     offset 36   BIG-endian
#
# The split endianness is not a quirk to tidy up. The receiver compares magic raw against
# `htobe32(UDEV_MONITOR_MAGIC)` (`:643`) but reads `properties_off` as a plain integer (`:648`),
# and the BPF filter loads the hash with BPF_LD|BPF_W|BPF_ABS (`:866`), which is defined to load
# big-endian. Writing all nine fields one way breaks it in both directions at once.
HEADER_SIZE = 40
UDEV_MONITOR_MAGIC = 0xFEEDCAFE
MONITOR_GROUP_UDEV = 2  # group 1 is the KERNEL group; libinput subscribes to 2.
UDEV_DATA_DIR = "/run/udev/data"
UDEV_CONTROL = "/run/udev/control"
# Used only for `test-builtin input_id`, which reads sysfs and writes properties to
# stdout -- it changes nothing.
UDEVADM = "/usr/bin/udevadm"

# `include/uapi/linux/netlink.h:24` at Linux v7.0: `#define NETLINK_KOBJECT_UEVENT 15`.
#
# Hardcoded with a getattr fallback rather than taken from the socket module, because Python does
# NOT reliably export it: Debian 13's python3.13 raises AttributeError on
# `socket.NETLINK_KOBJECT_UEVENT` while other builds have it. Measured on a Debian 13 container
# 2026-09-14, where its absence crashed every send. The constant is a kernel ABI number and
# cannot change.
NETLINK_KOBJECT_UEVENT = getattr(socket, "NETLINK_KOBJECT_UEVENT", 15)


def murmurhash2(key: bytes, seed: int = 0) -> int:
    """MurmurHash2, 32-bit, Austin Appleby's public-domain original.

    Byte-for-byte the algorithm in systemd v257 `src/basic/MurmurHash2.c` and in Wolf's vendored
    copy, which are identical to each other.

    NOT endian-neutral, deliberately: the C reads each 4-byte block with `*(uint32_t*)data`, so
    the result depends on the host's byte order, and the original's own header says so. Both the
    controller running the tests (arm64) and the container (amd64) are little-endian, so `<I`
    below matches what the container's libudev computes. On a big-endian host this whole file
    would need revisiting, and nothing in this homelab is one.
    """
    m = 0x5BD1E995
    r = 24
    length = len(key)
    h = (seed ^ length) & 0xFFFFFFFF

    offset = 0
    while length >= 4:
        (k,) = struct.unpack_from("<I", key, offset)
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> r
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        offset += 4
        length -= 4

    # The C switch falls through deliberately; these are the same three cases in order.
    if length == 3:
        h ^= key[offset + 2] << 16
    if length >= 2:
        h ^= key[offset + 1] << 8
    if length >= 1:
        h ^= key[offset]
        h = (h * m) & 0xFFFFFFFF

    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF


def string_hash32(value: str) -> int:
    """systemd's `string_hash32` -- device-monitor.c:688-690, MurmurHash2(str, strlen(str), 0)."""
    return murmurhash2(value.encode(), 0)


def build_payload(properties: "dict[str, str]") -> bytes:
    """The properties buffer: NUL-terminated `key=value` entries, one after another.

    Order is preserved as given rather than sorted. udev does not sort, and ACTION/DEVPATH lead
    in every real message; keeping that shape means a capture of ours looks like a capture of
    udev's when someone compares the two.
    """
    return b"".join(f"{k}={v}".encode() + b"\0" for k, v in properties.items())


def build_header(properties_len: int, subsystem: str, devtype: "str | None" = None) -> bytes:
    """The 40-byte monitor header. See the field table above for why the endianness is mixed."""
    return struct.pack(
        "<8sIIIIIIII",
        b"libudev\0",
        struct.unpack("<I", struct.pack(">I", UDEV_MONITOR_MAGIC))[0],
        HEADER_SIZE,
        HEADER_SIZE,
        properties_len,
        struct.unpack("<I", struct.pack(">I", string_hash32(subsystem)))[0],
        struct.unpack("<I", struct.pack(">I", string_hash32(devtype)))[0] if devtype else 0,
        0,  # filter_tag_bloom_hi -- no tags, and a zero bloom matches a subscriber with no tag
        0,  # filter_tag_bloom_lo    filter, which is what libinput is.
    )


def build_message(properties: "dict[str, str]", devtype: "str | None" = None) -> bytes:
    """Header followed by payload. Wolf sends these as two iovecs in one sendmsg; one
    concatenated buffer is the same bytes on the wire and needs no sendmsg(2) plumbing."""
    subsystem = properties.get("SUBSYSTEM")
    if not subsystem:
        raise ValueError("SUBSYSTEM is required: it is what the receiver's BPF filter matches on")
    payload = build_payload(properties)
    return build_header(len(payload), subsystem, devtype) + payload


def send_message(message: bytes, group: int = MONITOR_GROUP_UDEV) -> None:
    """Put the message on the multicast group.

    Binding needs no privilege -- lib/kobject_uevent.c:776-780 sets NL_CFG_F_NONROOT_RECV on
    NETLINK_KOBJECT_UEVENT. SENDING to a group does: af_netlink.c:1843-1846 gates it on
    `netlink_allowed(sock, NL_CFG_F_NONROOT_SEND)`, that flag is not set, so it falls to
    `ns_capable(sock_net(sk)->user_ns, CAP_NET_ADMIN)` (af_netlink.c:904-908) -- the user
    namespace owning the socket's NETWORK namespace, not init_user_ns. An unprivileged LXC's
    netns is owned by the container's own userns, so the container's root passes. An ordinary
    user does not, and gets EPERM here rather than a silent drop.
    """
    sock = socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, NETLINK_KOBJECT_UEVENT)
    try:
        sock.bind((0, group))
        sock.sendto(message, (0, group))
    finally:
        sock.close()


def write_db_entry(major: int, minor: int, properties: "dict[str, str]") -> str:
    """Write /run/udev/data/c<major>:<minor>.

    Only the `E:` lines are read on the path that matters here. systemd v257 sd-device.c:1770-1771
    sets is_initialized as soon as the file is read at all, under the comment "devices with a
    database entry are initialized" -- so existence is the requirement and no particular line
    inside it is. Format from device_update_db() in device-private.c.
    """
    os.makedirs(UDEV_DATA_DIR, exist_ok=True)
    path = os.path.join(UDEV_DATA_DIR, f"c{major}:{minor}")
    body = "".join(f"E:{k}={v}\n" for k, v in properties.items())
    with open(path, "w") as handle:
        handle.write(body)
    return path


def ensure_control() -> None:
    """/run/udev/control must exist. Presence only -- the Wolf manual: "this is not used for
    anything else apart from detection that udev is present". Contents are never read."""
    os.makedirs(os.path.dirname(UDEV_CONTROL), exist_ok=True)
    if not os.path.exists(UDEV_CONTROL):
        with open(UDEV_CONTROL, "w"):
            pass


def properties_for_devnode(devnode: str, action: str, seqnum: int) -> "tuple[dict, int, int]":
    """Derive a real device's properties by stat()ing it. Minors are never assumed."""
    info = os.stat(devnode)
    if not stat.S_ISCHR(info.st_mode):
        raise ValueError(f"{devnode} is not a character device")
    major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
    sysname = os.path.basename(devnode)
    properties = {
        "ACTION": action,
        # The REAL sysfs path, resolved, not synthesised. A made-up DEVPATH points sd-device's
        # syspath at a node that does not exist, and anything that later reads a sysfs attribute
        # for the device gets nothing.
        "DEVPATH": devpath_for(sysname),
        "SUBSYSTEM": "input",
        "DEVNAME": f"input/{sysname}",
        "SEQNUM": str(seqnum),
        "MAJOR": str(major),
        "MINOR": str(minor),
    }
    properties.update(classify(sysname))
    return properties, major, minor


def devpath_for(sysname: str) -> str:
    """The real sysfs DEVPATH for an input device, e.g. /devices/virtual/input/input20/event8.

    Resolved from sysfs rather than synthesised. libinput's device_added() reads properties off
    the received message, but sd-device keeps the syspath and anything that later asks the device
    for a sysfs attribute needs it to be real. Input devices are not namespaced, so /sys/class
    /input works inside the container -- verified on CT 120.
    """
    real = os.path.realpath(f"/sys/class/input/{sysname}")
    return real[len("/sys"):] if real.startswith("/sys/") else f"/devices/virtual/input/{sysname}"


def classify(sysname: str) -> "dict[str, str]":
    """The ID_INPUT* properties for a device, from udev's OWN classifier.

    THIS IS NOT OPTIONAL, and the first build of this role learned that the hard way. libinput
    enumerates a device, opens it, and then CLASSIFIES it in evdev_device_create(); a device with
    no ID_INPUT_KEYBOARD / ID_INPUT_MOUSE / ID_INPUT_TOUCHPAD comes back EVDEV_UNHANDLED_DEVICE
    and is dropped. That drop is logged at info level and nothing surfaces it, so the symptom is
    a compositor reporting ZERO input devices while the events arrive correctly -- measured
    2026-09-14, with `swaymsg -t get_inputs` empty and no error anywhere.

    Shelling out to `udevadm test-builtin input_id` rather than reimplementing the capability
    bitmask parse: that builtin IS what real udev runs to produce these properties, so this
    cannot drift from what a machine with a working udevd would have computed. On the devices
    this exists for it returns ID_INPUT_KEYBOARD for the keyboard and ID_INPUT_MOUSE for the
    mouse, which is exactly what makes libinput keep them.

    A failure here is deliberately not fatal: announcing with fewer properties is strictly better
    than not announcing at all, and the caller logs it.
    """
    try:
        result = subprocess.run(
            [UDEVADM, "test-builtin", "input_id", f"/sys/class/input/{sysname}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{sysname}: could not run udevadm test-builtin input_id ({exc})", file=sys.stderr)
        return {}

    properties = {}
    for line in result.stdout.splitlines():
        # The builtin also prints progress and a trailing summary; only KEY=VALUE lines starting
        # ID_INPUT are ours.
        if line.startswith("ID_INPUT") and "=" in line:
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()
    return properties


def reconcile(seqnum_start: int = 1000) -> int:
    """Announce every /dev/input/event* device, writing its db entry first.

    ANNOUNCING REPEATEDLY IS SAFE, and the design depends on that rather than on tracking state.
    libinput's device_added() calls filter_duplicates() (udev-seat.c:55-73), which walks the
    seat's device list and ignores a device whose syspath it already has. So this can run on
    every trigger with no bookkeeping, no state file, and no risk of double-adding.

    That matters because a device node is created BEFORE the host's udev has finished setting its
    ownership. Measured on CT 120 2026-09-14: one IN_CREATE followed by three IN_ATTRIB. A
    systemd.path unit using PathChanged= watches IN_ATTRIB too (systemd v257 src/core/path.c:42),
    so this is re-run after the host rule lands and the second announcement carries the device in
    its final, openable state. Without the re-run, a compositor would see the pre-rule ownership
    and fail to open it.
    """
    ensure_control()
    nodes = sorted(glob.glob("/dev/input/event*"))
    if not nodes:
        # A glob that matches nothing must not report itself as a perfect result.
        print("no /dev/input/event* devices found -- nothing announced", file=sys.stderr)
        return 0

    announced = 0
    for seq, node in enumerate(nodes, start=seqnum_start):
        try:
            info = os.stat(node)
        except OSError as exc:
            print(f"{node}: cannot stat ({exc.strerror}), skipping", file=sys.stderr)
            continue
        if not stat.S_ISCHR(info.st_mode):
            continue
        major, minor = os.major(info.st_rdev), os.minor(info.st_rdev)
        sysname = os.path.basename(node)
        properties = {
            "ACTION": "add",
            "DEVPATH": devpath_for(sysname),
            "SUBSYSTEM": "input",
            "DEVNAME": f"input/{sysname}",
            # SEQNUM must be non-zero or sd-device rejects the whole message in device_verify()
            # (systemd v257 device-private.c:428). Zero is the one value that fails silently.
            "SEQNUM": str(seq),
            "MAJOR": str(major),
            "MINOR": str(minor),
        }
        # Merged AFTER the fixed keys so a classifier that somehow returns ACTION or DEVPATH
        # cannot overwrite them. Without these libinput drops the device silently -- see
        # classify().
        properties.update(classify(sysname))
        write_db_entry(major, minor, properties)
        try:
            send_message(build_message(properties))
        except PermissionError:
            print("EPERM: must run as the container's root -- see send_message()", file=sys.stderr)
            return 1
        announced += 1
        print(f"announced {sysname} (c{major}:{minor}) {properties['DEVPATH']}")

    print(f"announced {announced} of {len(nodes)} device node(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="announce every /dev/input/event* device; safe to re-run, libinput de-duplicates",
    )
    parser.add_argument("--devnode", help="a real character device, e.g. /dev/input/event12")
    parser.add_argument("--devpath", help="synthetic DEVPATH, when there is no real device")
    parser.add_argument("--devname", help="synthetic DEVNAME, relative: input/event12")
    parser.add_argument("--subsystem", default="input")
    parser.add_argument("--action", default="add", choices=["add", "remove", "change"])
    parser.add_argument("--seqnum", type=int, default=1234)
    parser.add_argument("--major", type=int)
    parser.add_argument("--minor", type=int)
    parser.add_argument("--write-db", action="store_true")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="build and print the message without opening a socket. Needs no privilege.",
    )
    args = parser.parse_args()

    if args.reconcile:
        return reconcile()

    if args.devnode:
        properties, major, minor = properties_for_devnode(args.devnode, args.action, args.seqnum)
    elif args.devpath:
        properties = {
            "ACTION": args.action,
            "DEVPATH": args.devpath,
            "SUBSYSTEM": args.subsystem,
            "SEQNUM": str(args.seqnum),
        }
        if args.devname:
            properties["DEVNAME"] = args.devname
        major, minor = args.major, args.minor
    else:
        parser.error("one of --devnode or --devpath is required")

    message = build_message(properties)

    if args.self_test:
        print(f"header  {HEADER_SIZE} bytes, subsystem hash 0x{string_hash32(args.subsystem):08x}")
        print(f"payload {len(message) - HEADER_SIZE} bytes")
        for key, value in properties.items():
            print(f"  {key}={value}")
        print(f"total   {len(message)} bytes")
        return 0

    if args.write_db:
        ensure_control()
        if major is None or minor is None:
            print("--write-db needs --major/--minor when used with --devpath", file=sys.stderr)
            return 2
        print(f"wrote {write_db_entry(major, minor, properties)}")

    try:
        send_message(message)
    except PermissionError:
        # The one failure worth naming, because it is the whole question this probe asks.
        print(
            "EPERM sending to the udev multicast group. Sending needs CAP_NET_ADMIN in the user "
            "namespace owning this netns -- run as the container's root, not as an ordinary "
            "user. If this fails AS ROOT inside an unprivileged LXC, then this host cannot "
            "synthesise udev events at all and the caller's design has to change.",
            file=sys.stderr,
        )
        return 1

    print(f"sent {len(message)} bytes: {args.action} {properties.get('DEVPATH')} "
          f"({properties['SUBSYSTEM']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
