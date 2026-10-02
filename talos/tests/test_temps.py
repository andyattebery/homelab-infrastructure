"""temps.sh: every sensor on each node, in the order the nodes were given; a silent node is reported.

The node is fixtures/talos-sysfs.json: talosctl's output for each directory temps.sh lists and each
file it reads, captured from pi-cluster-01 by tests/capture_sysfs.py (README.md, "Tests").
talosctl's stub serves it for any node, fails every call to a node in $STUB_TALOS_DOWN, and slows
the hostname read of a node in $STUB_TALOS_SLOW.
"""

import json
import re

import pytest

from support import FIXTURES, calls, make_env, run

SYSFS = FIXTURES / "talos-sysfs.json"
needs_sysfs = pytest.mark.skipif(
    not SYSFS.exists(), reason="fixtures/talos-sysfs.json is captured from pi-cluster-01 (README.md, Tests)"
)
HEADER = ["NODE", "DEVICE", "SENSOR", "TEMP", "MAX", "CRIT", "ALARM"]


def read(path):
    return json.loads(SYSFS.read_text())["read"][path].strip()


def celsius(millidegrees):
    tenths = (int(millidegrees) + 50) // 100
    return f"{tenths // 10}.{tenths % 10}C"


def table(stdout):
    """The printed table as lists of cells. Columns are at least two spaces apart; a cell can
    hold one space ("Sensor 1", "no answer")."""
    return [re.split(r"\s{2,}", line.strip()) for line in stdout.splitlines()]


def temps(tmp_path, talos, *args, **stubs):
    env = make_env(tmp_path, STUB_TALOS_SYSFS=SYSFS, **stubs)
    env.pop("TALOS_NODES", None)
    return env, run(talos, "temps.sh", *args, env=env)


# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("args", [[], ["192.168.1.181", "192.168.1.182"], ["-h"], ["--help"]])
def test_refuses_bad_arguments_before_asking_a_node(tmp_path, talos, args):
    env, result = temps(tmp_path, talos, *args)
    assert result.returncode == 1
    assert result.stdout.startswith("Usage:")
    assert calls(env) == []


@needs_sysfs
def test_shows_every_sensor_with_its_limits(tmp_path, talos):
    env, result = temps(tmp_path, talos, "192.168.1.181")
    assert result.returncode == 0, result.stdout + result.stderr
    host = read("/proc/sys/kernel/hostname")
    hwmon = "/sys/class/hwmon"
    assert table(result.stdout) == [
        HEADER,
        # No limit of its own; crit is thermal_zone0's critical trip, the zone that links hwmon0.
        [host, "cpu_thermal", "temp1", celsius(read(f"{hwmon}/hwmon0/temp1_input")), "-",
         celsius(read("/sys/class/thermal/thermal_zone0/trip_point_0_temp")), "-"],
        [host, "rpi_volt", "in0_lcrit", "-", "-", "-", read(f"{hwmon}/hwmon1/in0_lcrit_alarm")],
        [host, "nvme", read(f"{hwmon}/hwmon2/temp1_label"), celsius(read(f"{hwmon}/hwmon2/temp1_input")),
         celsius(read(f"{hwmon}/hwmon2/temp1_max")), celsius(read(f"{hwmon}/hwmon2/temp1_crit")),
         read(f"{hwmon}/hwmon2/temp1_alarm")],
        # Its max is 65535 K, the drive's "no limit".
        [host, "nvme", read(f"{hwmon}/hwmon2/temp2_label"), celsius(read(f"{hwmon}/hwmon2/temp2_input")),
         "-", "-", "-"],
    ]
    # Every call went to that node alone, endpoint and node both.
    assert {tuple(c[1:7]) for c in calls(env, "talosctl")} == {
        ("--talosconfig", "generated/talosconfig", "-e", "192.168.1.181", "-n", "192.168.1.181"),
    }


@needs_sysfs
def test_a_silent_node_is_reported_in_its_place_and_fails_the_run(tmp_path, talos):
    # .181 answers last (its first call is slowed), .182 fails at once: the rows still follow the
    # order given, not the order the nodes answered in.
    env, result = temps(
        tmp_path, talos, "192.168.1.181,192.168.1.182,192.168.1.183",
        STUB_TALOS_DOWN="192.168.1.182", STUB_TALOS_SLOW="192.168.1.181",
    )
    assert result.returncode == 1
    rows = table(result.stdout)[1:]
    assert len(rows) == 9
    assert rows[4] == ["192.168.1.182", "no answer"]
    assert [row[1] for row in rows[:4]] == [row[1] for row in rows[5:]]
    # The silent node got one call: the hostname read.
    assert len([c for c in calls(env, "talosctl") if "192.168.1.182" in c]) == 1
