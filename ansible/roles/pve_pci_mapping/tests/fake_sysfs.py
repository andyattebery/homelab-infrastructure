"""Recorded PCIe enumerations of a real EPYC node as fake sysfs trees.

Used by test_resolve_pci_topology.py (imported) and by test.yml (run as a script):

    python3 fake_sysfs.py build <root> lan_off|lan_on

Both layouts are recordings of the host's kernel log, not inventions: lan_off is the
2026-08-31 boot (Onboard LAN hidden), lan_on the 2026-08-28 boot (root port 40:01.3 present
with the X550 at bus 42, everything below bus 40 shifted by two, IOMMU groups by three).
"""

import os
import sys
from pathlib import Path

# (chain of addresses from the root bus, vendor:device, subsystem or None, iommu group, driver)
# Only leaves carry attributes; bridges are bare directories, as in a real sysfs the resolver
# never reads a bridge's attributes.
LAN_OFF = [
    ("0000:00/0000:00:01.1/0000:01:00.0", "10de:24b0", "1028:14ad", 97, "vfio-pci"),
    ("0000:00/0000:00:01.1/0000:01:00.1", "10de:228b", "1028:14ad", 97, "vfio-pci"),
    ("0000:00/0000:00:03.5/0000:02:00.0", "8086:2525", "8086:380a", 98, "nvme"),
    ("0000:40/0000:40:01.1/0000:41:00.0", "8086:2525", "8086:380a", 69, "nvme"),
    ("0000:40/0000:40:01.4/0000:42:00.0", "1b21:2142", "1b21:2142", 70, "xhci_hcd"),
    ("0000:40/0000:40:01.5/0000:43:00.0/0000:44:00.0", "1a03:2000", "1a03:2000", 71, None),
    ("0000:40/0000:40:03.1/0000:45:00.0", "15b3:1015", "15b3:0004", 72, "mlx5_core"),
    ("0000:40/0000:40:03.1/0000:45:00.1", "15b3:1015", "15b3:0004", 73, "mlx5_core"),
    ("0000:40/0000:40:03.3/0000:46:00.0", "8086:2525", "8086:380a", 74, "vfio-pci"),
    ("0000:40/0000:40:03.4/0000:47:00.0", "8086:2525", "8086:380a", 75, "vfio-pci"),
    ("0000:80/0000:80:01.4/0000:83:00.0", "1c5c:2429", "1590:02d0", 44, "vfio-pci"),
    ("0000:80/0000:80:03.1/0000:84:00.0", "1000:00c4", "1000:31a0", 45, "vfio-pci"),
    ("0000:c0/0000:c0:01.1/0000:c1:00.0/0000:c2:01.0/0000:c3:00.0", "8086:e20b", "1849:6021", 17, "vfio-pci"),
    ("0000:c0/0000:c0:01.1/0000:c1:00.0/0000:c2:02.0/0000:c4:00.0", "8086:e2f7", "1849:6021", 18, "vfio-pci"),
    ("0000:c0/0000:c0:03.1/0000:c5:00.0", "025e:f1ac", "025e:f1ac", 19, "vfio-pci"),
    ("0000:c0/0000:c0:03.2/0000:c6:00.0", "025e:f1ac", "025e:f1ac", 20, "vfio-pci"),
    ("0000:c0/0000:c0:03.3/0000:c7:00.0", "144d:a80a", "144d:a801", 21, "vfio-pci"),
    ("0000:c0/0000:c0:03.4/0000:c8:00.0", "144d:a80a", "144d:a801", 22, "vfio-pci"),
]

# Bus 40 as the 08-28 kernel log recorded it; the other root buses are unchanged except the
# A4000's group, which moved from 97 to 100.
LAN_ON = [
    ("0000:00/0000:00:01.1/0000:01:00.0", "10de:24b0", "1028:14ad", 100, "vfio-pci"),
    ("0000:00/0000:00:01.1/0000:01:00.1", "10de:228b", "1028:14ad", 100, "vfio-pci"),
    ("0000:00/0000:00:03.5/0000:02:00.0", "8086:2525", "8086:380a", 101, "nvme"),
    ("0000:40/0000:40:01.1/0000:41:00.0", "8086:2525", "8086:380a", 69, "nvme"),
    ("0000:40/0000:40:01.3/0000:42:00.0", "8086:1563", "1849:1563", 70, "ixgbe"),
    ("0000:40/0000:40:01.3/0000:42:00.1", "8086:1563", "1849:1563", 71, "ixgbe"),
    ("0000:40/0000:40:01.4/0000:44:00.0", "1b21:2142", "1b21:2142", 73, "xhci_hcd"),
    ("0000:40/0000:40:01.5/0000:45:00.0/0000:46:00.0", "1a03:2000", "1a03:2000", 74, None),
    ("0000:40/0000:40:03.1/0000:47:00.0", "15b3:1015", "15b3:0004", 75, "mlx5_core"),
    ("0000:40/0000:40:03.1/0000:47:00.1", "15b3:1015", "15b3:0004", 76, "mlx5_core"),
    ("0000:40/0000:40:03.3/0000:48:00.0", "8086:2525", "8086:380a", 77, "nvme"),
    ("0000:40/0000:40:03.4/0000:49:00.0", "8086:2525", "8086:380a", 78, "nvme"),
    ("0000:80/0000:80:01.4/0000:83:00.0", "1c5c:2429", "1590:02d0", 44, "vfio-pci"),
    ("0000:80/0000:80:03.1/0000:84:00.0", "1000:00c4", "1000:31a0", 45, "vfio-pci"),
    ("0000:c0/0000:c0:01.1/0000:c1:00.0/0000:c2:01.0/0000:c3:00.0", "8086:e20b", "1849:6021", 17, "vfio-pci"),
    ("0000:c0/0000:c0:01.1/0000:c1:00.0/0000:c2:02.0/0000:c4:00.0", "8086:e2f7", "1849:6021", 18, "vfio-pci"),
    ("0000:c0/0000:c0:03.1/0000:c5:00.0", "025e:f1ac", "025e:f1ac", 19, "vfio-pci"),
    ("0000:c0/0000:c0:03.2/0000:c6:00.0", "025e:f1ac", "025e:f1ac", 20, "vfio-pci"),
    ("0000:c0/0000:c0:03.3/0000:c7:00.0", "144d:a80a", "144d:a801", 21, "vfio-pci"),
    ("0000:c0/0000:c0:03.4/0000:c8:00.0", "144d:a80a", "144d:a801", 22, "vfio-pci"),
]

# The eleven mappings, as declared in host_vars, with what each must resolve to per tree.
MAPPINGS = {
    "nvidia_rtx_a4000": "0000:00/01.1/00.0",
    "intel_arc_b580": "0000:c0/01.1/00.0/01.0/00.0",
    "intel_arc_b580_audio": "0000:c0/01.1/00.0/02.0/00.0",
    "broadcom_9305_24i": "0000:80/03.1/00.0",
    "skhynix_pe6011": "0000:80/01.4/00.0",
    "solidigm_p44_pro_1": "0000:c0/03.1/00.0",
    "solidigm_p44_pro_2": "0000:c0/03.2/00.0",
    "samsung_980_pro_1": "0000:c0/03.3/00.0",
    "samsung_980_pro_2": "0000:c0/03.4/00.0",
    "intel_p1600x_1": "0000:40/03.3/00.0",
    "intel_p1600x_2": "0000:40/03.4/00.0",
}

EXPECTED_LAN_OFF = {
    "nvidia_rtx_a4000": ("0000:01:00.0", "10de:24b0", "1028:14ad", 97),
    "intel_arc_b580": ("0000:c3:00.0", "8086:e20b", "1849:6021", 17),
    "intel_arc_b580_audio": ("0000:c4:00.0", "8086:e2f7", "1849:6021", 18),
    "broadcom_9305_24i": ("0000:84:00.0", "1000:00c4", "1000:31a0", 45),
    "skhynix_pe6011": ("0000:83:00.0", "1c5c:2429", "1590:02d0", 44),
    "solidigm_p44_pro_1": ("0000:c5:00.0", "025e:f1ac", "025e:f1ac", 19),
    "solidigm_p44_pro_2": ("0000:c6:00.0", "025e:f1ac", "025e:f1ac", 20),
    "samsung_980_pro_1": ("0000:c7:00.0", "144d:a80a", "144d:a801", 21),
    "samsung_980_pro_2": ("0000:c8:00.0", "144d:a80a", "144d:a801", 22),
    "intel_p1600x_1": ("0000:46:00.0", "8086:2525", "8086:380a", 74),
    "intel_p1600x_2": ("0000:47:00.0", "8086:2525", "8086:380a", 75),
}

EXPECTED_LAN_ON = dict(
    EXPECTED_LAN_OFF,
    nvidia_rtx_a4000=("0000:01:00.0", "10de:24b0", "1028:14ad", 100),
    intel_p1600x_1=("0000:48:00.0", "8086:2525", "8086:380a", 77),
    intel_p1600x_2=("0000:49:00.0", "8086:2525", "8086:380a", 78),
)


def build_tree(root: Path, devices):
    """Lay out a sysfs-shaped tree: devices/pci<dom>:<bus>/<bridge>/.../<leaf>/{attrs, links}."""
    for chain, ids, subsys, group, driver in devices:
        parts = chain.split("/")
        d = root / "devices" / ("pci" + parts[0])
        for p in parts[1:]:
            d = d / p
        d.mkdir(parents=True, exist_ok=True)
        vendor, device = ids.split(":")
        (d / "vendor").write_text("0x%s\n" % vendor)
        (d / "device").write_text("0x%s\n" % device)
        if subsys is not None:
            sv, sd = subsys.split(":")
            (d / "subsystem_vendor").write_text("0x%s\n" % sv)
            (d / "subsystem_device").write_text("0x%s\n" % sd)
        gdir = root / "kernel" / "iommu_groups" / str(group)
        gdir.mkdir(parents=True, exist_ok=True)
        os.symlink(gdir, d / "iommu_group")
        if driver is not None:
            ddir = root / "bus" / "pci" / "drivers" / driver
            ddir.mkdir(parents=True, exist_ok=True)
            os.symlink(ddir, d / "driver")



TREES = {"lan_off": LAN_OFF, "lan_on": LAN_ON}


def main(argv):
    if len(argv) != 4 or argv[1] != "build" or argv[3] not in TREES:
        sys.stderr.write("usage: fake_sysfs.py build <root> lan_off|lan_on\n")
        return 2
    build_tree(Path(argv[2]), TREES[argv[3]])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
