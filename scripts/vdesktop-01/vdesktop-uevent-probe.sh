#!/usr/bin/env bash
#
# Prove -- or disprove -- that a synthetic udev event reaches a libudev subscriber inside an
# unprivileged PVE container.
#
# Usage:
#   scripts/vdesktop-01/vdesktop-uevent-probe.sh <host> [--install-udev] [--keep]
#
#   scripts/vdesktop-01/vdesktop-uevent-probe.sh vdesktop-01
#   scripts/vdesktop-01/vdesktop-uevent-probe.sh vdesktop-01 --install-udev
#
# WHY THIS EXISTS. plans/vdesktop-01-wayland-native.md rests on one claim that source can only
# argue and a box has to settle: that the container's own root may send to the udev multicast
# group, and that a real libudev accepts the message scripts/fake_udev_send.py builds. If that
# is false the plan's whole design collapses back to a startup ordering that was proven
# self-defeating, so this runs before any role is written.
#
# WHAT IT PROVES, and in what order:
#
#   CONTROL 1  an ORDINARY USER sending to the group is refused with EPERM.
#              Proves the privilege boundary is real and that a later pass is not an artefact of
#              the group being open to anyone.
#   CONTROL 2  ROOT sending a message whose subsystem hash does NOT match what the monitor
#              subscribed to is accepted by the kernel and NEVER ARRIVES.
#              This is the silent-drop failure the pytest exists to prevent, reproduced
#              deliberately. Without it a green MAIN proves only "something arrived", not "the
#              filter was satisfied".
#   MAIN       ROOT sending a correctly-hashed message DOES arrive at `udevadm monitor`.
#
# A pass on MAIN with either control also passing is NOT a pass -- it means the probe cannot
# distinguish, and it is reported as such.
#
# WHAT IT DOES NOT PROVE. That libinput specifically adds the device: that needs a compositor,
# and belongs to the build. `udevadm monitor --subsystem-match=input` installs the SAME BPF
# filter libinput installs (sd_device_monitor_filter_add_match_subsystem_devtype), so the
# transport and the filter are covered; the evdev classification layer above them is not.
#
# STATE IT CHANGES on the target: writes two files under /tmp, and -- only with --install-udev --
# installs the `udev` package. Nothing else. It starts a `udevadm monitor` and stops the one it
# started. It is safe to re-run and cleans up after itself unless --keep is given.
#
# The target is expected to be a throwaway. CT 120 is unmanaged and is destroyed at the start of
# the build, which is why the package install is offered at all; do not point this at a host you
# care about without reading the paragraph above.

set -euo pipefail

HOST=""
INSTALL_UDEV=0
KEEP=0

while [ $# -gt 0 ]; do
    case "$1" in
        --install-udev) INSTALL_UDEV=1 ;;
        --keep)         KEEP=1 ;;
        -h|--help)      sed -n '2,45p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*)             echo "unknown option: $1" >&2; exit 2 ;;
        *)              [ -n "$HOST" ] && { echo "unexpected argument: $1" >&2; exit 2; }
                        HOST="$1" ;;
    esac
    shift
done

[ -n "$HOST" ] || { echo "error: no host given" >&2; exit 2; }

# THE SENDER IS THE ROLE'S COPY, not a duplicate kept next to this probe. It used to sit beside
# this script; once roles/udev_shim was created it moved there and this line was not updated, so
# the probe exited 2 with "not found" until 2026-09-14. Pointing at the role's file also means
# the probe exercises exactly what the role deploys, which is the only version worth probing.
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
SENDER="$ROOT/ansible/roles/udev_shim/files/fake_udev_send.py"
[ -r "$SENDER" ] || { echo "error: $SENDER not found" >&2; exit 2; }

REMOTE_SENDER=/tmp/fake_udev_send.py
REMOTE_CAPTURE=/tmp/vdesktop-uevent-probe.capture

remote() { ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" 'bash -s'; }

echo "== copying the sender to $HOST"
# bash -c on the far side: these hosts log in to fish, and a fish parse error on a redirect
# reads like a bug in this script rather than a shell mismatch.
ssh -o BatchMode=yes -o ConnectTimeout=15 "$HOST" \
    "bash -c 'cat > $REMOTE_SENDER && chmod 0755 $REMOTE_SENDER'" < "$SENDER"

remote <<REMOTE
set -uo pipefail

INSTALL_UDEV=$INSTALL_UDEV
KEEP=$KEEP
SENDER=$REMOTE_SENDER
CAPTURE=$REMOTE_CAPTURE

echo
echo "== what this container actually is"
# The probe is meaningless on anything that is not an unprivileged user-namespaced container:
# on a normal host root has CAP_NET_ADMIN in init_user_ns and the interesting question is not
# being asked at all.
echo "-- /proc/self/uid_map:"
sed 's/^/     /' /proc/self/uid_map
if awk 'NR==1 && \$2 == 0 && \$3 > 65535 { exit 1 }' /proc/self/uid_map; then
    echo "   -> UID-MAPPED (unprivileged container). This is the condition under test."
else
    echo "   -> NOT user-namespaced. A pass here would NOT answer the question this probe asks."
fi
echo "-- udevd running: \$(pgrep -x systemd-udevd >/dev/null && echo yes || echo no)"
echo "-- /run/udev exists: \$([ -d /run/udev ] && echo yes || echo no)"
echo "-- kernel: \$(uname -r)"

echo
echo "== subscriber availability"
if ! command -v udevadm >/dev/null 2>&1; then
    if [ "\$INSTALL_UDEV" = "1" ]; then
        echo "-- udevadm missing; installing the udev package (--install-udev was given)"
        sudo apt-get update -qq && sudo apt-get install -y -qq udev || {
            echo "RESULT: INCONCLUSIVE -- could not install udev, so there is no libudev"
            echo "        subscriber to receive with. Nothing was proven."
            exit 3
        }
    else
        echo "RESULT: INCONCLUSIVE -- no udevadm on this host, so there is no libudev subscriber"
        echo "        to receive with. Nothing was proven either way."
        echo "        Re-run with --install-udev to install the udev package first."
        exit 3
    fi
fi
echo "-- udevadm: \$(command -v udevadm) (\$(udevadm --version 2>/dev/null || echo '?'))"

echo
echo "== /run/udev/control -- WITHOUT THIS THE RECEIVER NEVER JOINS THE GROUP"
# systemd v257 src/libsystemd/sd-device/device-monitor.c:158-175:
#
#     if (group == MONITOR_GROUP_UDEV &&
#         access("/run/udev/control", F_OK) < 0 &&
#         dev_is_devtmpfs() <= 0) {
#             ... "We do not set a netlink multicast group here, so the socket
#                  will not receive any messages."
#
# So a subscriber in a container with no udevd silently binds to NO group and hears nothing --
# the send is irrelevant. This is Wolf's first of three requirements, and it is a property of
# the RECEIVER, which is why creating it here is part of the design rather than a test fixture.
# The real role must create it before the compositor starts, for the same reason.
#
# /run is a tmpfs; this file is empty, is never read, and is gone at the next boot.
if [ -e /run/udev/control ]; then
    echo "-- already present"
else
    sudo mkdir -p /run/udev && sudo touch /run/udev/control
    echo "-- created (was absent, which is why an earlier run of this probe saw"
    echo "   'The udev service seems not to be active, disabling the monitor')"
fi

cleanup() {
    sudo pkill -TERM -f "udevadm monitor" 2>/dev/null || true
    if [ "\$KEEP" != "1" ]; then
        rm -f "\$CAPTURE" "\$SENDER"
    fi
}
trap cleanup EXIT

start_monitor() {
    sudo pkill -TERM -f "udevadm monitor" 2>/dev/null || true
    rm -f "\$CAPTURE"
    # --subsystem-match=input installs the same BPF subsystem filter libinput installs. That
    # filter is the thing under test; without it this would prove only that bytes moved.
    sudo setsid udevadm monitor --udev --subsystem-match=input >"\$CAPTURE" 2>&1 &
    # The monitor must be bound BEFORE the send: this is multicast, not a queue, and a message
    # sent before the subscriber binds is simply gone. A missed bind would otherwise read as a
    # dropped message, which is the exact wrong conclusion.
    for _ in \$(seq 1 40); do
        [ -s "\$CAPTURE" ] && break
        sleep 0.1
    done
    sleep 0.3
}

stop_monitor() {
    sudo pkill -TERM -f "udevadm monitor" 2>/dev/null || true
    sleep 0.3
}

echo
echo "== sender sanity -- before any result is interpreted"
# Added 2026-09-14 after the first run of this probe: the sender crashed on a missing socket
# constant, and CONTROL 2 read that crash as "the message was silently dropped" -- a control
# passing for entirely the wrong reason, which is worse than one that fails. Nothing below is
# believable unless the sender can at least build a message, so that is checked first and
# separately. --self-test opens no socket and needs no privilege.
if ! SELF=\$(python3 "\$SENDER" --devpath /devices/probe/selftest --self-test 2>&1); then
    echo "\$SELF" | sed 's/^/     /'
    echo "RESULT: INCONCLUSIVE -- the sender cannot even build a message on this host, so no"
    echo "        control below would mean anything. Fix the sender; nothing was proven."
    exit 3
fi
echo "\$SELF" | sed 's/^/     /'

echo
echo "== CONTROL 1 -- an ordinary user must be refused"
C1_OUT=\$(python3 "\$SENDER" --devpath /devices/probe/control1 --devname input/control1 2>&1) && C1_RC=0 || C1_RC=\$?
echo "\$C1_OUT" | sed 's/^/     /'
if [ "\$C1_RC" != "0" ] && echo "\$C1_OUT" | grep -q EPERM; then
    echo "   -> CONTROL 1 fired: unprivileged send refused with EPERM, as the kernel source says"
    echo "      it must (af_netlink.c:1843-1846 -> ns_capable(CAP_NET_ADMIN))."
    C1_OK=1
elif [ "\$C1_RC" = "0" ]; then
    echo "   -> CONTROL 1 DID NOT FIRE: the group accepted an UNPRIVILEGED send. MAIN below would"
    echo "      then prove nothing about privilege."
    C1_OK=0
else
    echo "   -> CONTROL 1 INCONCLUSIVE: the sender failed (rc=\$C1_RC) for a reason that is not"
    echo "      EPERM, so this says nothing about the permission boundary."
    C1_OK=0
fi

echo
echo "== CONTROL 2 -- root, but the WRONG subsystem hash: must be silently dropped"
start_monitor
# Same code path, same privilege, only the hashed subsystem differs -- so the monitor's BPF
# filter is the only thing that can reject it. This reproduces the silent drop deliberately.
#
# The send MUST SUCCEED for this control to mean anything: "never arrived" is only evidence of
# filtering if the message actually left. A failed send that never arrives is a tautology.
C2_OUT=\$(sudo python3 "\$SENDER" --devpath /devices/probe/control2 --devname input/control2 \
    --subsystem definitely-not-input 2>&1) && C2_SENT=1 || C2_SENT=0
echo "\$C2_OUT" | sed 's/^/     /'
stop_monitor
if [ "\$C2_SENT" != "1" ]; then
    echo "   -> CONTROL 2 INCONCLUSIVE: the send itself failed, so its non-arrival proves"
    echo "      nothing about the subsystem filter."
    C2_OK=0
elif grep -q 'control2' "\$CAPTURE" 2>/dev/null; then
    echo "   -> CONTROL 2 DID NOT FIRE: a wrongly-hashed message ARRIVED anyway. The monitor is"
    echo "      not filtering, so MAIN cannot prove the hash is right."
    C2_OK=0
else
    echo "   -> CONTROL 2 fired: sent SUCCESSFULLY and never arrived. That is the silent drop the"
    echo "      pytest guards against, reproduced on purpose."
    C2_OK=1
fi

echo
echo "== MAIN -- root, correct hash: must arrive"
start_monitor
MAIN_OUT=\$(sudo python3 "\$SENDER" --devpath /devices/probe/main --devname input/main \
    --subsystem input 2>&1) && MAIN_SENT=1 || MAIN_SENT=0
echo "\$MAIN_OUT" | sed 's/^/     /'
stop_monitor
echo "-- captured:"
sed 's/^/     /' "\$CAPTURE" 2>/dev/null | head -20
if [ "\$MAIN_SENT" != "1" ]; then
    echo "   -> the send FAILED. That is a different finding from a message that was dropped;"
    echo "      read the error above before concluding anything about the design."
    MAIN_OK=0
elif grep -q '/devices/probe/main' "\$CAPTURE" 2>/dev/null; then
    MAIN_OK=1
else
    MAIN_OK=0
fi

if [ "\$MAIN_OK" != "1" ]; then
    echo
    echo "== DIAGNOSTIC -- MAIN failed, so narrow down WHERE the message is lost"
    #
    # There are three distinguishable places a correctly-sent message can vanish, and they have
    # completely different fixes. Running this automatically rather than leaving it to a second
    # hand-run command, because the interesting state is gone once the monitor stops.
    #
    #   (a) it arrives with NO subsystem filter  -> the BPF filter rejected it: the subsystem
    #       hash or its byte order is wrong, and the pytest's assumptions are wrong with it.
    #   (b) it does not arrive, and debug logs "Failed to create device from received message"
    #       -> the bytes reached the socket and sd-device refused to parse them. That is
    #       device_verify() at device-private.c:428 -- devpath, subsystem, action, seqnum != 0.
    #   (c) it does not arrive and debug says nothing at all -> it never reached the socket.
    #       The send returned success, so that points at the multicast delivery itself.
    sudo pkill -TERM -f "udevadm monitor" 2>/dev/null || true
    rm -f "\$CAPTURE"
    # No --subsystem-match: removes the BPF filter entirely. SYSTEMD_LOG_LEVEL=debug makes
    # sd-device say why it dropped something instead of dropping it quietly.
    sudo setsid env SYSTEMD_LOG_LEVEL=debug udevadm monitor --udev >"\$CAPTURE" 2>&1 &
    for _ in \$(seq 1 40); do [ -s "\$CAPTURE" ] && break; sleep 0.1; done
    sleep 0.3
    sudo python3 "\$SENDER" --devpath /devices/probe/diag --devname input/diag \
        --subsystem input 2>&1 | sed 's/^/     /'
    sleep 0.5
    sudo pkill -TERM -f "udevadm monitor" 2>/dev/null || true
    sleep 0.3
    echo "-- unfiltered + debug capture:"
    sed 's/^/     /' "\$CAPTURE" 2>/dev/null | head -40
    if grep -q '/devices/probe/diag' "\$CAPTURE" 2>/dev/null; then
        echo "   -> (a) ARRIVES WITHOUT THE SUBSYSTEM FILTER. The transport and sd-device are"
        echo "      fine; the BPF subsystem filter is what rejected MAIN. The hash or its byte"
        echo "      order is wrong -- and scripts/tests/test_fake_udev_send.py is asserting the"
        echo "      wrong thing, so fix the test first."
    elif grep -qi 'failed to create device\|does not pass filter\|Invalid\|sd-device' "\$CAPTURE" 2>/dev/null; then
        echo "   -> (b) REACHED THE SOCKET AND WAS REFUSED. Read the sd-device line above:"
        echo "      device_verify() needs DEVPATH, SUBSYSTEM, ACTION and SEQNUM != 0."
    else
        echo "   -> (c) NOTHING REACHED THE SOCKET, despite the send returning success. The"
        echo "      message is being dropped in multicast delivery, not by any parser."
    fi
fi

echo
echo "== RESULT"
if [ "\$MAIN_OK" != "1" ] && [ "\$C2_OK" = "1" ]; then
    echo "NOTE: CONTROL 2 'passing' is vacuous while MAIN fails -- if nothing arrives at all,"
    echo "      a wrongly-hashed message not arriving proves nothing about filtering."
fi
if [ "\$MAIN_OK" = "1" ] && [ "\$C1_OK" = "1" ] && [ "\$C2_OK" = "1" ]; then
    echo "PASS -- a synthetic uevent from the container's own root reaches a libudev subscriber"
    echo "        through the subsystem filter, an unprivileged sender is refused, and a"
    echo "        wrongly-hashed one is dropped. The design in"
    echo "        plans/vdesktop-01-wayland-native.md is sound on this box."
    exit 0
elif [ "\$MAIN_OK" = "1" ]; then
    echo "INCONCLUSIVE -- the message arrived, but a control did not fire"
    echo "        (control1=\$C1_OK control2=\$C2_OK), so this probe cannot distinguish a real"
    echo "        pass from an open socket. Fix the control before believing the result."
    exit 3
else
    echo "FAIL -- a correctly-hashed message from root did NOT reach the subscriber."
    echo "        Do not proceed. The fake-udev route in plans/vdesktop-01-wayland-native.md"
    echo "        does not work here and the design needs rethinking from the top."
    exit 1
fi
REMOTE
