#!/usr/bin/env python3
"""Answer one question: does UI_DEV_CREATE succeed inside an unprivileged PVE container?

This is "The one unknown" in plans/vdesktop-01-wayland-native.md. uinput's own source has no
capability check at all -- `drivers/input/misc/uinput.c` at v7.0 has zero `capable`/`CAP_*`/uid
checks in 1171 lines, so access is governed only by file permissions. But AppArmor and seccomp
are not in that source, PVE ships its own container profile, and every published containerised
guide does this PRIVILEGED, so no source reading settles it. Only a box does.

If UI_DEV_CREATE fails here, the whole Wayland route dies: Wayland has no XTest, so uinput is the
only way to inject input into a wlroots compositor.

It creates a device with Sunshine's REAL identifiers -- vendor 0x1209, product 0x0002, the
keyboard profile from libvirtualhid `src/core/profiles.cpp` -- rather than arbitrary ones, so the
resulting sysfs attributes are what a host udev rule written for Sunshine would actually match.
(Not 0xBEEF/0xDEAD: those are inputtino's, which Sunshine 2026.906.222525 no longer uses, and
every guide has it wrong.)

Usage:
    uinput_probe.py              # create, report, destroy
    uinput_probe.py --hold 30    # keep the device alive 30s so something else can look at it

It destroys the device it created and leaves nothing behind unless --hold is interrupted.
"""

import argparse
import ctypes
import errno
import fcntl
import os
import struct
import sys
import time

# --- ioctl plumbing -------------------------------------------------------------------------
#
# Linux's _IOC encoding, from include/uapi/asm-generic/ioctl.h. Computed rather than hardcoded:
# a wrong magic number fails with EINVAL, which reads exactly like a permission problem and would
# send the whole investigation in the wrong direction.
_IOC_NRBITS, _IOC_TYPEBITS, _IOC_SIZEBITS = 8, 8, 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _ioc(direction, typ, nr, size):
    return (
        (direction << _IOC_DIRSHIFT)
        | (ord(typ) << _IOC_TYPESHIFT)
        | (nr << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


UINPUT_IOCTL_BASE = "U"

# struct uinput_setup { struct input_id id; char name[80]; __u32 ff_effects_max; }
# input_id is four __u16 = 8 bytes; 8 + 80 + 4 = 92.
UINPUT_MAX_NAME_SIZE = 80
UINPUT_SETUP_SIZE = 8 + UINPUT_MAX_NAME_SIZE + 4

UI_DEV_CREATE = _ioc(_IOC_NONE, UINPUT_IOCTL_BASE, 1, 0)
UI_DEV_DESTROY = _ioc(_IOC_NONE, UINPUT_IOCTL_BASE, 2, 0)
UI_DEV_SETUP = _ioc(_IOC_WRITE, UINPUT_IOCTL_BASE, 3, UINPUT_SETUP_SIZE)
UI_SET_EVBIT = _ioc(_IOC_WRITE, UINPUT_IOCTL_BASE, 100, 4)
UI_SET_KEYBIT = _ioc(_IOC_WRITE, UINPUT_IOCTL_BASE, 101, 4)


def UI_GET_SYSNAME(length):
    """_IOR(UINPUT_IOCTL_BASE, 44, char[len]) -- asks the kernel which eventN it allocated.

    Worth using rather than diffing /dev/input before and after: the minor is allocated at
    UI_DEV_CREATE time and a diff races anything else on the box that creates a device.
    """
    return _ioc(_IOC_READ, UINPUT_IOCTL_BASE, 44, length)


EV_SYN, EV_KEY = 0x00, 0x01
KEY_A = 30

# Sunshine's virtual keyboard, from libvirtualhid src/core/profiles.cpp make_simple_profile().
# sysfs prints these as %04x, which is the form a udev rule's ATTRS{id/vendor} matches.
SUNSHINE_VENDOR = 0x1209
SUNSHINE_KEYBOARD_PRODUCT = 0x0002
DEVICE_NAME = b"uinput-probe (vdesktop plan)"


def probe(hold_seconds: int = 0) -> int:
    print(f"running as uid={os.getuid()} gid={os.getgid()} groups={sorted(os.getgroups())}")

    try:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    except FileNotFoundError:
        print("FAIL: /dev/uinput does not exist.")
        print("      The container has no uinput passthrough. In PVE that is a `devN` entry in")
        print("      the container config, applied at container START -- see the plan.")
        return 2
    except PermissionError:
        print("FAIL: cannot open /dev/uinput (EACCES).")
        print("      This is a FILE PERMISSION failure, not a capability one -- check the node's")
        print("      gid= on the devN entry and this user's group membership. It does NOT")
        print("      answer whether UI_DEV_CREATE would work.")
        return 2

    print("opened /dev/uinput")

    try:
        # Declare what the device can emit. Without at least one EV_KEY bit the kernel creates a
        # device libinput then classifies as unhandled, which would look like a udev problem.
        #
        # The bit is passed BY VALUE, not as a pointer to an int. `_IOW(…, 100, int)` describes
        # the argument's size, but uinput_ioctl_handler() uses `arg` itself as the bit number
        # (drivers/input/misc/uinput.c). Handing it a 4-byte buffer passes a POINTER, the kernel
        # reads that address as the bit, and it fails with EINVAL -- which looks like a malformed
        # ioctl rather than a wrong argument. Cost 20 minutes on 2026-09-14.
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_KEYBIT, KEY_A)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)

        setup = struct.pack(
            "HHHH80sI",
            0x03,  # BUS_USB, what Sunshine's profile reports
            SUNSHINE_VENDOR,
            SUNSHINE_KEYBOARD_PRODUCT,
            0x0111,  # version
            DEVICE_NAME,
            0,  # ff_effects_max
        )
        fcntl.ioctl(fd, UI_DEV_SETUP, setup)
        print("UI_DEV_SETUP ok")

        # THE question.
        fcntl.ioctl(fd, UI_DEV_CREATE)
    except OSError as exc:
        print(f"FAIL: {exc.__class__.__name__}: {os.strerror(exc.errno)} (errno {exc.errno})")
        if exc.errno in (errno.EPERM, errno.EACCES):
            print()
            print("      UI_DEV_CREATE was REFUSED. uinput.c itself has no capability check, so")
            print("      this is AppArmor or seccomp in PVE's unprivileged container profile.")
            print("      That is the answer the plan could not get from source, and it is the")
            print("      one that kills the Wayland route: Wayland has no XTest fallback.")
        os.close(fd)
        return 1

    sysname = bytearray(64)
    try:
        fcntl.ioctl(fd, UI_GET_SYSNAME(len(sysname)), sysname, True)
        name = sysname.split(b"\0", 1)[0].decode()
    except OSError:
        name = ""

    print()
    print(f"PASS: UI_DEV_CREATE succeeded. kernel allocated: {name or '<unknown>'}")

    # UI_GET_SYSNAME returns the INPUT DEVICE name (`input19`), not the evdev node (`event19`),
    # and the two numbers are allocated from different counters -- they are NOT interchangeable.
    # The evdev node is a child in sysfs, so resolve it rather than assuming. Getting this wrong
    # is how a probe reports a device node that belongs to something else entirely.
    evdev = None
    if name:
        try:
            children = os.listdir(f"/sys/class/input/{name}")
            evdev = next((c for c in children if c.startswith("event")), None)
        except OSError:
            pass

    if not evdev:
        print("      could not resolve the evdev node from sysfs; /sys may not expose it here")
    else:
        node = f"/dev/input/{evdev}"
        print(f"      evdev node: {evdev}")
        try:
            info = os.stat(node)
            print(f"      {node}  major={os.major(info.st_rdev)} minor={os.minor(info.st_rdev)} "
                  f"uid={info.st_uid} gid={info.st_gid} mode={oct(info.st_mode & 0o777)}")
            if info.st_uid == 65534 or info.st_gid == 65534:
                print("      gid 65534 is `nobody`: owned by a HOST group outside this")
                print("      container's id map. EXPECTED until the host udev rule puts these")
                print("      devices in a group whose gid maps inside -- the lxc-input group at")
                print("      100996 in the plan, which is NOT installed yet. A compositor could")
                print("      see this device and would fail to open it.")
            else:
                print("      readable ownership: a compositor in this container could open it.")
        except FileNotFoundError:
            print(f"      {node} is not visible in this container -- /dev/input is not bound in.")

    if hold_seconds:
        print(f"\nholding the device open for {hold_seconds}s ...")
        time.sleep(hold_seconds)

    fcntl.ioctl(fd, UI_DEV_DESTROY)
    os.close(fd)
    print("\ndestroyed the device; nothing left behind")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hold", type=int, default=0, metavar="SECONDS")
    args = parser.parse_args()
    sys.exit(probe(args.hold))
