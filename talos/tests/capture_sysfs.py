#!/usr/bin/env python3
"""Capture tests/fixtures/talos-sysfs.json from a live node, for test_temps.py.

    cd talos && tests/capture_sysfs.py 192.168.1.181

Records talosctl's raw output for every directory temps.sh lists and every file it reads: the
hostname, each hwmon device and each thermal zone. Run it from talos/, where mise puts the pinned
talosctl on PATH.
"""

import json
import subprocess
import sys
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "talos-sysfs.json"


def main(node):
    captured = {"list": {}, "read": {}}

    def talosctl(*args):
        result = subprocess.run(
            ["talosctl", "--talosconfig", "generated/talosconfig", "-e", node, "-n", node, *args],
            capture_output=True, text=True,
        )
        return result.stdout if result.returncode == 0 else None

    def entries(directory):
        listing = talosctl("list", directory)
        if listing is None:
            sys.exit(f"Error: talosctl could not list {directory} on {node}")
        captured["list"][directory] = listing
        return [name for name in listing.splitlines() if name and name != "."]

    def read(path):
        content = talosctl("read", path)
        if content is not None:
            captured["read"][path] = content

    read("/proc/sys/kernel/hostname")
    for root, prefix, wanted in (
        ("/sys/class/hwmon", "hwmon",
         lambda f: f == "name" or f.startswith("temp") or f.endswith("_alarm")),
        ("/sys/class/thermal", "thermal_zone", lambda f: f.startswith("trip_point_")),
    ):
        for device in entries(root):
            if device.startswith(prefix):
                for name in entries(f"{root}/{device}"):
                    if wanted(name):
                        read(f"{root}/{device}/{name}")

    FIXTURE.write_text(json.dumps(captured, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {FIXTURE.name}: {len(captured['list'])} listings, {len(captured['read'])} files")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: tests/capture_sysfs.py <node>")
    main(sys.argv[1])
