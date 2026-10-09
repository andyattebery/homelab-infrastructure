# Turing Pi 2 nodes

What is in each slot of the Turing Pi 2 board (v2.5), and the OS each node runs. The BMC is
`turingpi`, 192.168.1.215.

| Slot | Module | Host | IP | Storage | Add-in card |
|---|---|---|---|---|---|
| 1 | Turing RK1: RK3588, 16 GB RAM, 32 GB eMMC | `turingpi-rk1-01` | 192.168.1.216 | Samsung 960 PRO 512 GB NVMe, in M.2 T1 | Realtek RTL8125 2.5 GbE, in the mini-PCIe slot |
| 2 | Turing RK1: RK3588, 16 GB RAM, 32 GB eMMC | `turingpi-rk1-02` | 192.168.1.217 | Samsung 970 EVO 500 GB NVMe, in M.2 T2 | Realtek RTL8125 2.5 GbE, in the mini-PCIe slot |
| 3 | Raspberry Pi CM4: 8 GB RAM, 32 GB eMMC, on Turing's CM4 adapter | `turingpi-cm4-01` | 192.168.1.218 | eMMC only | — |
| 4 | NVIDIA Jetson Orin Nano 8 GB (P3767-0005) | `turingpi-jetson-01` | 192.168.1.219 | The OS on the module's microSD card; HP EX950 1 TB NVMe, in M.2 T4, for data | — |

## OS

| Slot | Host | OS | Kernel | Installed from |
|---|---|---|---|---|
| 1 | `turingpi-rk1-01` | Ubuntu 26.04 (resolute), Armbian minimal | Rockchip's vendor 6.1.172, held at that version | The `_resolute_` image of an [rk1-armbian-minimal](https://github.com/andyattebery/rk1-armbian-minimal) release, with this repo's cloud-init seed ([rk1/](rk1/README.md)) |
| 2 | `turingpi-rk1-02` | Ubuntu 26.04 (resolute), Armbian minimal | Rockchip's vendor 6.1.172, held at that version | The `_resolute_` image of an [rk1-armbian-minimal](https://github.com/andyattebery/rk1-armbian-minimal) release, with this repo's cloud-init seed ([rk1/](rk1/README.md)) |
| 3 | `turingpi-cm4-01` | Canonical's Ubuntu Server 26.04.1 for Raspberry Pi | `linux-raspi` 7.0, updated by apt through A/B boot (`piboot-try`) | Canonical's preinstalled image with this repo's cloud-init seed ([cm4/](cm4/README.md)) |
| 4 | `turingpi-jetson-01` | NVIDIA L4T R39.2.1 (JetPack 7.2.1) on NVIDIA's minimal Ubuntu 24.04 (noble) root filesystem | NVIDIA's 6.8.12-tegra, which moves with each L4T release | A [jetson-orin-nano-l4t-minimal](https://github.com/andyattebery/jetson-orin-nano-l4t-minimal) image on the microSD card, with this repo's cloud-init seed ([jetson/](jetson/README.md)) |

## What each slot connects to

From Turing's Turing Pi 2 specifications; the sources are in
[research/turing-pi-cluster/hardware-support.md](../research/turing-pi-cluster/hardware-support.md).

| Slot | Board I/O |
|---|---|
| 1 | mini-PCIe + SIM, HDMI, DSI, GPIO, USB 2.0, M.2 T1 |
| 2 | mini-PCIe, M.2 T2 |
| 3 | 2× SATA 3 (ASMedia), M.2 T3 |
| 4 | 4× USB 3.0 (VL805), M.2 T4 |

The M.2 slots run PCIe 3.0 x4 for the RK1 and the Orin Nano. The CM4 has no NVMe support, so M.2 T3
is unused; slot 3's SATA ports are empty.
