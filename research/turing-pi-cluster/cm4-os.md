# turingpi-cm4-01: which OS

Researched 2026-10-08. **[I]** marks inference. Nothing was run on the node. Kernel configs, firmware and first-boot files were read from the published packages and images, at the versions named. The source keys are listed at the end.

**The question (owner, 2026-10-08):**
- The CM4 in Turing Pi slot 3 runs Armbian. It went on to match the RK1s, which no longer holds: the RK1s run a custom Armbian build on Rockchip's vendor kernel.
- Is Ubuntu better? Ubuntu 24.04 would roughly match the Jetson, which runs NVIDIA's L4T on an Ubuntu 24.04 root filesystem.

**The node:**
- `turingpi-cm4-01`: CM4 8 GB with 32 GB eMMC, on Turing's adapter in slot 3.
- 1 GbE through the board's switch. Two SATA ports (ASM1061, PCIe 2.0 x1), empty.
- USB0 goes to the BMC's flashing hub. No HDMI in slot 3.
- The BMC writes the OS to eMMC (`turingpi/scripts/flash-node.sh`).
- Today: stock Armbian `rpi4b` 26.8.1, trixie minimal, kernel 6.18.42, installed during the RK1 work of 2026-10-01.

**Compared:**
- Armbian `rpi4b`: Debian 13 as now, and the same build on Ubuntu 26.04.
- Canonical's Ubuntu Server 24.04 and 26.04 for Raspberry Pi.
- Raspberry Pi OS Lite trixie (64-bit), the Pi vendor's own OS.

## Bottom line

**Decided (owner, 2026-10-08): Ubuntu 26.04 on the RK1s and the CM4; the Jetson stays on Ubuntu 24.04.**
- **The Jetson** is "going to stuck on whatever nvidia supports", which is 24.04 "for now and probably for a long time". It "will need special handling anyway". That is already true here: NVIDIA's kernel and BSP, and a private L4T repo with apt pins and holds ([turingpi/jetson/](../../turingpi/jetson/README.md)).
- **The result:** Ubuntu on all four nodes, in two releases. That is the same count of userspace versions as Ubuntu 24.04 plus Debian 13, but newer, and one distro.
- **Support:** 26.04's standard support runs to 2031-05, against 24.04's 2029-05 and Debian 13's 2028-08 (LTS 2030-06).
- **k3s, if it's ever used:** SUSE validates current k3s (v1.36, v1.37) on both Ubuntu 26.04 and 24.04, and on no Debian release ([kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md), "A separate k3s cluster on the Turing Pi"). 24.04 has the longer test record; 26.04 will stay on the matrix longer [I].

**For the CM4, Ubuntu 26.04 comes two ways. Recommendation: Canonical's Ubuntu Server 26.04 for Raspberry Pi.**
- **Canonical's image:**
  - Canonical certifies the CM4.
  - Its A/B boot falls back by itself when a kernel update fails.
  - Its first boot is cloud-init, the same declarative mechanism as the Jetson's card.
  - Its 7.0 kernel gets new builds every one to four weeks.
- **What it needs:**
  - an EEPROM dated 2022-11-25 or later, read once and updated over rpiboot if not;
  - a small committed script that puts the `user-data` seed onto the image the BMC writes.
- **The CM4 kernel-update reports are thin.** There are two, each from a single user. The main one (LP #2167775) is on an EEPROM below Canonical's minimum, and is probably misdiagnosed. The widespread `piboot-try` failure (LP #2155094) is a low-RAM dracut problem, being fixed, that doesn't apply to an 8 GB CM4 [I].
- **Armbian's `rpi4b` 26.04 image** shares the RK1s' tooling.
  - **Against it:** Armbian doesn't test the CM4, its first boot is a manual wizard, and its packaging can leave `/boot/firmware` unbootable with no fallback (the v26.08 `postrm` bug, the 26.11 firmware move).
  - **It is the fallback** if the EEPROM or the seeding doesn't work out.

**For the RK1s, 26.04 means building a minimal image Armbian doesn't publish.**
- Armbian builds and publishes Ubuntu 26.04 on this board's vendor kernel, but only as GNOME and KDE desktops.
- The homelab's `rk1-armbian-minimal` is written for Debian 13: `customize-image.sh` stops on any other release.
- Moving it means:
  - Ubuntu package names, and Jellyfin's `resolute` suite (`jellyfin-ffmpeg8` is published for it);
  - keeping the separate Python 3.12 for the RKNN wheel, because 26.04's Python is 3.14;
  - re-running the GPU, NPU and video checks on hardware.

## What a newer kernel gives this CM4

The CM4's kernel choices are Ubuntu 24.04's 6.8 (`rpi-6.8.y` as of 2024-04, with Ubuntu's security and stable fixes since) or Raspberry Pi's 6.18. What 6.18 adds, item by item:
- **HEVC decode:**
  - 6.18 has the current `rpi-hevc-dec` driver. 6.8 has its staging predecessor, `rpivid`.
  - Either one is a stateless decoder that needs a request-API client: GStreamer's `v4l2codecs`, or an FFmpeg with v4l2-request. Ubuntu's FFmpeg has no such support.
  - Frigate's HEVC preset uses the stateful `hevc_v4l2m2m`, so it probably misses the decoder, and Jellyfin has deprecated V4L2 on the Pi.
  - So hardware HEVC decoding is marginal on this board whatever the kernel [I].
- **H.264 decode and encode, V3D, SATA with the CLKREQ# fix, Ethernet, eMMC:** the same on both.
- **Raspberry Pi driver fixes after April 2024:** not in Ubuntu's 6.8 unless Ubuntu backported them.
  - Launchpad searches found no CM4 Ethernet or eMMC bug on it.
  - The one CM4 PCIe report, a link down after a panic reboot (LP #2099935), was on 24.10's 6.11 and matters only with SATA in use.
  - Newer isn't automatically better either: Raspberry Pi's 6.18.19 and 6.18.20 had a `bcmgenet` regression that dropped the network (raspberrypi/linux #7304).
- **Security:** Ubuntu 24.04's `linux-raspi` gets new builds every one to four weeks until 2029-05. It is maintained, just not moved to newer Pi trees.
- **Boot firmware:** Ubuntu 24.04's `start4.elf` dates from 2024-02.
  - Canonical's open SRU (LP #2158366): "Users with newer models of Pi 4 and Pi 5 may find they have no boot-compatible firmwares on their Ubuntu install." The test plan names variants such as "a Pi 4 3GB".
  - Whether this CM4 is such a unit is unknown, and booting it once tells.
- **Where Ubuntu comes out ahead:** the memory cgroup is on by default, and ZFS modules ship prebuilt.
- **For a CM4 running containers, nothing in 6.18 is required [I].**

## The four, side by side

| | Armbian `rpi4b` 26.8 | Ubuntu 24.04 | Ubuntu 26.04 | Raspberry Pi OS Lite trixie |
|---|---|---|---|---|
| Kernel | `raspberrypi/linux` `rpi-6.18.y` with Armbian's defconfig; 6.18.42 installed, 6.18.44 in the repo | `linux-raspi` 6.8.0-1065 (6.8.12 + `rpi-6.8.y` as of 2024-04) | `linux-raspi` 7.0.0-1020 (7.0.14 + `rpi-7.0.y`) | `raspberrypi/linux` `rpi-6.18.y` with `bcm2711_defconfig`; 6.18.50 |
| Kernel updates | One per Armbian release, about quarterly (6.18.10 → .35 → .44 in 2026) | Every 1–4 weeks, but security and stable fixes only, on 6.8 for the life of the release | Every 1–4 weeks | Every 2–6 weeks (seven kernels so far in 2026) |
| H.264 decode/encode | yes | yes | yes | yes |
| HEVC decode | **no**: not built in any branch | old staging `rpivid` only | yes (`rpi-hevc-dec`) | yes (`rpi-hevc-dec`) |
| V3D GPU | yes | yes | yes | yes |
| SATA (ASM1061), CLKREQ# fix | yes | yes | yes | yes |
| Boot firmware | `raspi-firmware` through Armbian's repo; moving into the BSP package in 26.11 | `linux-firmware-raspi`, `start4.elf` from 2024-02 | 2026-02 | `raspi-firmware` 1.20260915 |
| `rpi-eeprom` package | Ubuntu's 2022-era 20.4 (2023 bootloaders) | 28.14 | 28.14 | 28.33 (2026-09-23 bootloader) |
| First boot after `tpi flash`, image unedited | **reachable**: root/1234 over ssh, then the first-login wizard | **unreachable over ssh**: `ubuntu`/`ubuntu` with forced change, `ssh_pwauth: false`, no key; serial console only | same as 24.04 | **unreachable**: ssh off, root locked, no usable user, cloud-init seed empty |
| Memory cgroup (Docker or k3s memory limits) | on: `cgroup_enable=memory` in `cmdline.txt` | on (Canonical's patch) | on | off until `cmdline.txt` gets `cgroup_enable=memory cgroup_memory=1` |
| Userspace | Debian 13 or Ubuntu 26.04 (Armbian publishes both for `rpi4b`) | Ubuntu 24.04 (like the Jetson) | Ubuntu 26.04 | Debian 13 |
| Support | Debian 13: 2028-08-09, LTS 2030-06-30; Armbian kernels while `rpi4b` stays in its Standard tier | 2029-05 (ESM 2034) | 2031-05 (ESM 2036) | Debian 13 dates; Raspberry Pi states no end date but still updates bookworm |
| Vendor-tested on CM4 | no: CM4 isn't an Armbian board, though the image boots it | yes: Canonical lists CM4 "SDC" (server, desktop, certified) | yes; two single-user CM4 reports, unconfirmed | yes |

## Armbian `rpi4b`, as installed

- **Two releases from the same build.** Armbian publishes the same `rpi4b` build on Debian 13 (installed now) and on Ubuntu 26.04: `Armbian_26.8.1_Rpi4b_resolute_current_6.18.42_minimal.img.xz`. Everything below applies to both, since the kernel, firmware packaging and first boot come from Armbian, not the distro [I]. Nothing is published on Ubuntu 24.04 (`Noble_current_minimal` returns 404).
- **Kernel.** The kernel is the Raspberry Pi tree, unpatched, built with Armbian's own defconfig (`config/sources/families/bcm2711.conf:25-41`; `config/kernel/linux-bcm2711-current.config`). It leaves out `VIDEO_RPI_HEVC_DEC`, a symbol with no default (line 5163, and likewise in the edge and legacy configs). The 26.8.1 image has no `rpi-hevc-dec.ko`. The decoder is in the hardware; this kernel just doesn't drive it.
- **Updates.** Each Armbian release carries one kernel, at the end of February, May, August and November. Between releases a branch gets only "severe bugs and security vulnerabilities".
- **Support.** `rpi4b.conf` is in the Standard tier, with two maintainers. One image covers "All 64b Raspberry models". Armbian's catalog has pages for the CM3 and CM3+ but none for the CM4, and an Armbian PR from 2026-09-28 says "There's no Pi 4 in the lab". The CM4 works through the generic `[cm4]` section of `config.txt` and the shipped `bcm2711-rpi-cm4.dtb` [I].
- **Packaging churn around the boot partition:**
  - **The v26.08 kernel `postrm` hook deletes the kernel and DTBs from `/boot/firmware` unconditionally.** PR #10783 reproduced an unbootable board by installing edge and then purging current. It is fixed on `main`, not on v26.08. Whether a plain same-package upgrade triggers it is unverified.
  - **In 26.11, Armbian moves the Pi firmware out of `raspi-firmware` into its BSP package** (PR #10855). On an existing install both packages would write `start4.elf`, and the BSP's copy is older [I].
- **EEPROM.** The bundled `rpi-eeprom` is Ubuntu noble's 20.4, whose newest BCM2711 bootloader is 2023-05-11.
- **No cloud-init, on either release (checked 2026-10-08).**
  - The streamed 26.04 minimal image doesn't have it installed. In its dpkg status, `systemd` shows `install ok installed`, while `cloud-init` appears only as an index entry. The trixie image doesn't have it either.
  - Armbian's only cloud-init path is the opt-in `cloud-init` build extension. It installs whichever distro's own package: Debian 13's cloud-init 25.1.4, or Ubuntu 26.04's 26.1. It has no Ubuntu-specific code.
  - **The extension is unchanged since the 2026-10-03 RK1 evaluation rejected it** (no commit between armbian/build `8eb7e43e` and `main`). Its defects are distro-independent:
    - it forces a FAT `/boot`;
    - its netplan cleanup `rm /etc/netplan/armbian-*` (`cloud-init.sh:65`) matches nothing;
    - its default `meta-data` says `instance_id: armbian`, where cloud-init reads `instance-id`;
    - it leaves root/1234, and `armbian-firstrun` still regenerates host keys.
  - Armbian's "cloud" image targets are UEFI virtual-machine images (qcow2, vhdx) that don't use the extension.
  - **So an Armbian node's first boot is Armbian's first-login on Debian and Ubuntu alike.** Canonical's own Ubuntu image is the one with cloud-init built in.
- **What it gets right:**
  - a first boot reachable over ssh without touching the image;
  - the memory cgroup already on;
  - the same userspace as the RK1s on either release they run: Debian 13 now, Ubuntu 26.04 as decided.

## Ubuntu Server 24.04 (and 26.04)

**24.04 is a 6.8 kernel for the life of the release.**
- `linux-raspi` 6.8.0-1065.69 was last synced to `rpi-6.8.y` in 6.8.0-1002.2 (2024-04-17). Every release since is Ubuntu stable and security fixes on that base.
- There is no newer Pi kernel for 24.04: noble-updates has only `linux-raspi`, `linux-image-raspi-6.8` and a 6.8 realtime flavour. The generic `linux-hwe-7.0` is a different flavour, which the Pi image doesn't use.

**The firmware is old.**
- `linux-firmware-raspi` 12-0ubuntu1.1 carries a `start4.elf` built 2024-02-29.
- LP #2158366: Pi 4 and CM4 boards with newer SDRAM need newer firmware. It is Triaged and still unfixed for noble. Whether this CM4 has that RAM is unknown.

**HEVC.** Only the old staging decoder, `rpivid` (`VIDEO_RPIVID=m`). `VIDEO_RPI_HEVC_DEC` is absent.

**First boot.**
- The shipped `system-boot/user-data` sets `ubuntu`/`ubuntu`, `expire: true` and `ssh_pwauth: false`. With no key, an unedited image can't be reached over ssh.
- So 24.04 needs the same image seeding as Raspberry Pi OS, without Raspberry Pi OS's kernel.

**What "matching the Jetson" amounts to:**
- The same Ubuntu suite: Python 3.12.3, systemd 255, cloud-init and the `noble` Ansible facts.
- Not the kernel, firmware or drivers. The Jetson runs NVIDIA's 6.8 kernel and BSP; the CM4 would run Canonical's raspi 6.8. The shared "6.8" is a coincidence of two unrelated trees.
- Docker comes from Docker's own repo either way (`geerlingguy.docker`), and the roles already branch on Debian vs Ubuntu. So the match buys little [I].

**26.04 fixes the kernel and firmware, and changes how updates boot.**
- It boots through `piboot-try` A/B slots, which need a CM4 EEPROM dated 2022-11-25 or later. This CM4's EEPROM date is unknown.
- Two CM4 reports are open and untriaged, each from a single user ("Decision", below):
  - LP #2167775 (2026-09-19): "A/B kernel updates never apply", on an EEPROM below Canonical's minimum;
  - LP #2161936 (2026-07-28): a `-proposed` kernel's trial boot failed.
- The confirmed, widespread `piboot-try` failure is the low-RAM dracut problem (LP #2155094), on Pi 3B/3B+/Zero 2W/4B.
- Its Python is 3.14, so it no longer matches the Jetson.

## Raspberry Pi OS Lite trixie

**Kernel.**
- `raspberrypi/linux` `rpi-6.18.y` with `bcm2711_defconfig`, 6.18.50 today.
- `linux-image-rpi-v8` brings new kernels through apt: 6.12.62, 6.12.75, 6.18.29, .33, .34, .39 and .50 so far in 2026.
- `VIDEO_RPI_HEVC_DEC=m` (config line 5166), along with `bcm2835-codec`, V3D, SATA and the CLKREQ# fix.

**Boot partition upkeep.**
- `raspi-firmware` keeps `start4.elf`, the DTBs, the overlays and `kernel8.img` current through its kernel hook.
- `rpi-eeprom` 28.33 carries the 2026-09-23 bootloader.

**First boot: cloud-init NoCloud from the boot partition.**
- Images have carried it since 2025-11-24. The 2026-10-06 Lite image's bootfs has `user-data` (all commented), `network-config` and `meta-data`.
- Unseeded, the node is unreachable: ssh is off, root is locked, and the rename-the-user dialog waits on a console that slot 3 doesn't have.
- **A seed needs:**
  - a `users:` entry: the first one renames the image's uid-1000 user and skips the dialog;
  - `enable_ssh: true`;
  - an explicit `sudo:` rule, since passwordless sudo has been off by default since 2026-04-13.
- **That is the shape of the Jetson's `turingpi/jetson/cloud-init/user-data.tpl`:** user `services`, uid 1000, `NOPASSWD` sudo, keys only. A CM4 version would drop the Jetson's L4T and apt sections [I].

**Getting the seed onto an image the BMC writes [I: neither tested on this board]:**
- **Before flashing:** decompress the image, `mcopy` `user-data` and `meta-data` into its FAT partition, and write a new `.sha` for `flash-node.sh`.
- **After flashing:** `tpi advanced msd --node 3` makes the BMC rpiboot the CM4 into mass storage. Mount `/dev/sda1` on the BMC and copy the files in (Turing: "accessing nodes' filesystems").
- **Either way, a one-off command sequence is not acceptable** (AGENTS.md, "Nothing ad-hoc on a managed host"). The seeding becomes a committed script beside `flash-node.sh`.

**Memory cgroup.** It is off by default: the CM4 device tree's bootargs carry `cgroup_disable=memory`. `cmdline.txt` needs `cgroup_enable=memory cgroup_memory=1` before Docker memory limits or k3s work. That is one Ansible-managed line.

## EEPROM, whichever OS

- **In-OS EEPROM updates are disabled on every CM4,** whatever the OS: "These Compute Modules disable the `rpi-eeprom-update` service by default, because eMMC is not removable."
- The supported path is rpiboot from another machine. The Turing BMC can put the CM4 into rpiboot mode itself; that is how `tpi advanced msd` works.
- An in-OS opt-in exists, using flashrom and three `config.txt` lines. It is untested on Turing's adapter.
- **The EEPROM's date matters for two of the options:** Ubuntu 26.04 needs 2022-11-25 or later, and newer-SDRAM boards need recent firmware. Read it once on the node: `vcgencmd bootloader_version` on Raspberry Pi OS. Its availability on Armbian was not checked.

## Not compared

- **NixOS** (as on `pi-rack`, the other CM4) would make this node the only Turing Pi node outside Ansible.
- **Talos** would only matter for joining the Super6C cluster, which [kubernetes-on-vendor-os.md](kubernetes-on-vendor-os.md) rules out for these boards. It also has no codecs on the CM4.

## Decision: the CM4's OS

**The question:** which OS should `turingpi-cm4-01` run?

**The criterion (owner, 2026-10-08): "matching the userspace is the main point for the os upgrades".**
- Fewer userspace versions means fewer kinds of release upgrade, apt source and package set to manage.
- The kernels stay three regardless, one per hardware vendor.

**The frame (owner, 2026-10-08): Ubuntu 26.04 on the RK1s and the CM4, and Ubuntu 24.04 on the Jetson.**
- **The Jetson's userspace is NVIDIA's choice.** L4T's root filesystem is Ubuntu 24.04. Debian runs on the Orin only on mainline, which has no driver for the GPU ([orin-nano-install.md](orin-nano-install.md), "Other distros on NVIDIA's kernel"). It already gets special handling.
- **Set aside: Ubuntu 24.04 on all four,** the exact match.
  - Armbian publishes nothing on noble for the RK1.
  - The CM4's Ubuntu 24.04 kernel stays on 2024's Pi tree.
  - 26.04 is newer, and it is the Ubuntu release Armbian builds for both boards.
- **Set aside: Debian 13 on the RK1s and the CM4** (today's RK1 image, plus Raspberry Pi OS or Armbian trixie on the CM4). Also two userspace versions, but from two distros.

**Armbian `rpi4b` 26.04 minimal.**
- **For:**
  - The same OS vendor, apt repo and BSP packaging as the RK1s.
  - Reachable over ssh on first boot without editing the image, through an interactive first-login wizard answered by hand on each node.
  - The memory cgroup is on.
  - Published by Armbian today: `Armbian_26.8.1_Rpi4b_resolute_current_6.18.42_minimal.img.xz`.
- **Against:**
  - Armbian doesn't list or test the CM4.
  - **Packaging risk on `/boot/firmware`, with no fallback:**
    - The v26.08 kernel `postrm` bug can leave the board unbootable. It is fixed on `main`, not on v26.08.
    - The 26.11 move of the Pi firmware into the BSP package is coming.
    - Recovery from either is a reflash through the BMC.
  - **Kernel builds come with each quarterly Armbian release.** Between releases, a branch gets only fixes for "severe bugs and security vulnerabilities".
  - No HEVC decoder (marginal here; see above).
  - No cloud-init: first boot isn't declarative, unlike the Jetson's.
  - Its `rpi-eeprom` is stale. EEPROM updates go through rpiboot on any OS anyway ("EEPROM, whichever OS").

**Canonical's Ubuntu Server 26.04 for Raspberry Pi.**
- **For:**
  - **Canonical certifies the CM4** for 26.04 (server, desktop, certified).
  - **A/B boot (`piboot-try`) is a safety net.** A new kernel or new boot files are tried once, and a failed boot falls back to the known-good set by itself.
  - **First boot is cloud-init NoCloud,** the same declarative mechanism as the Jetson's card. Re-provisioning is rewriting a `user-data` file, not answering a wizard.
  - A 7.0 kernel (`rpi-7.0.y`) with new builds every one to four weeks, and 2026 boot firmware.
  - ZFS ships prebuilt, and the memory cgroup is on.
- **Against:**
  - **It needs a CM4 EEPROM dated 2022-11-25 or later.** This CM4's is unknown. Read it once; if it's older, update it over rpiboot ("EEPROM, whichever OS").
  - **The seed has to reach an image the BMC writes.** That means one committed script beside `flash-node.sh`: `mcopy` into the image's FAT partition before flashing, or `tpi advanced msd` after. This is new work, and neither route has been tested on this board.
  - **`piboot-try` is new in 26.04.** Its one confirmed, widespread failure (LP #2155094: 44 messages, 4 duplicates, Pi 3B/3B+/Zero 2W/4B) was traced by Canonical's maintainer to dracut truncating the initramfs on low-RAM boards. The fix (compression settings, plus `tmp.mount` off below 8 GB) is going out as an update. An 8 GB CM4 isn't in that failure class [I].
  - **Two CM4 reports exist, each from a single user:**
    - LP #2167775 (2026-09-19): one affected user, no duplicates, untriaged. The reporter's EEPROM (2022-04-26) is below Canonical's minimum, and their systemd-259 diagnosis tested `systemctl reboot` rather than the `reboot` command `piboot-try` calls [I: probably misdiagnosed].
    - LP #2161936 (2026-07-28): one message, about a `-proposed` kernel since superseded, never followed up.
  - A different OS vendor from the RK1s (Canonical, not Armbian), on the same Ubuntu 26.04 userspace.

**Recommendation: Canonical's Ubuntu Server 26.04 for Raspberry Pi.**
- It gives the 26.04 userspace with:
  - the vendor's CM4 certification;
  - automatic fallback when a kernel update fails;
  - the same declarative first boot as the Jetson.

  For a node meant to be maintained, not hand-tended, those three are worth more than sharing Armbian's tooling with the RK1s.
- **Its preconditions are checkable once:**
  - the EEPROM date;
  - a seeding script, which the Jetson's `user-data.tpl` already shows the shape of.
- **An earlier version of this decision recommended Armbian's image, which was wrong.**
  - It weighed the two CM4 bug reports as if they were established; each is one user's report, one of them on a below-minimum EEPROM.
  - It counted seeding as a cost, though it is the same mechanism the Jetson uses.
  - It counted Armbian's wizard as a benefit, though it is a manual step on every reinstall.

**What would change it:**
- **If the EEPROM can't be brought to 2022-11-25 or later,** or the first kernel update on the node doesn't apply (`uname -r` after the reboot shows the old kernel): Armbian's `rpi4b` 26.04 image.
- **If seeding through the BMC proves unworkable on this board:** Armbian's image, which boots reachable without it.
- **If the RK1s' 26.04 build fails its hardware checks and they stay on Debian 13:** the CM4 follows them to Debian 13, on Raspberry Pi OS or Armbian trixie.

### The RK1 half: building the RK1 image on 26.04

**Why the RK1s are on Debian 13 today** ([rk1-custom-image.md](rk1-custom-image.md), "Distro"). The owner picked it on 2026-10-01 after asking "what is ubuntu gaining us here":
- **Ubuntu would gain little then:** Python 3.12 for the RKNN wheel, and a 2024 PPA video stack.
- **Debian 13 minimal is the only minimal image Armbian builds for this board.**

Matching userspace across nodes wasn't a criterion then.

**What Armbian supports and publishes for the RK1 on the vendor kernel (checked 2026-10-08):**
- **Releases:** the build framework marks Ubuntu 24.04 (`noble`), Ubuntu 26.04 (`resolute`, since 2026-04-12) and Debian 13 (`trixie`) as supported (`config/distributions/<release>/support`).
- **Published images:** `dl.armbian.com/turing-rk1/` serves only:
  - Debian 13 minimal (`Armbian_community_26.11.0-trunk.62_Turing-rk1_trixie_vendor_6.1.172_minimal`);
  - Ubuntu 26.04 GNOME and KDE desktops (`…_resolute_vendor_6.1.172_gnome_desktop`, `…_kde-plasma_desktop`).

  Nothing is published for noble, and there's no 26.04 minimal or server image.
- **A correction:** `armbian/os`'s release target file still lists the RK1 under "noble GNOME" (`targets-release-community-maintained.yaml:215`), and the 2026-10-01 research repeated it. What Armbian actually publishes is 26.04.

**The work:**
- **`rk1-armbian-minimal`:**
  - `userpatches/config-rk1.conf` sets `RELEASE=trixie`;
  - `customize-image.sh` stops on any other release (line 14);
  - `versions.env` pins `jellyfin-ffmpeg8` 8.1.3-1-trixie.
- **Ubuntu package names**, and Jellyfin's `resolute` suite, where `jellyfin-ffmpeg8` is published.
- **The separate Python 3.12 for the RKNN wheel (cp312) stays,** because 26.04's Python is 3.14. The libmali deb is a plain arm64 package [I].
- **The image's GPU, NPU and video checks** (`check-image.sh`, `check-node.sh`) have to pass again on hardware.

**What it costs:**
- **It leaves the one minimal configuration Armbian builds and tests for the RK1.** Armbian does build 26.04 on this board's vendor kernel, as desktops, so the release, kernel and BSP together are exercised. The minimal package set is not [I]. The homelab's CI and hardware checks are the only test of a 26.04 minimal RK1 image.
- **The kernel is the same either way.** The vendor 6.1 series reaches end of life upstream in December 2027 whatever the userspace ([rk1-gpu-npu.md](rk1-gpu-npu.md)).

## Open

- **The CM4's EEPROM date and SDRAM type,** read on the node (see "EEPROM, whichever OS"). Canonical's 26.04 needs 2022-11-25 or later.
- **Whether the first kernel update on the CM4 applies under `piboot-try`:** check `uname -r` after the reboot.
- **Only if the CM4 falls back to Armbian:** whether Armbian's v26.08 `postrm` bug fires on a plain same-package kernel upgrade, and what an existing install does when the 26.11 firmware move arrives.
- **A 26.04 minimal RK1 image built from `rk1-armbian-minimal`:** untested until it is built and passes `check-image.sh` and `check-node.sh`.
- **Which seeding route works on this board:** `tpi advanced msd --node 3` (BMC firmware v2.1.0), or the mtools edit before flashing.
- **Whether the CM4's serial console shows up in `tpi uart`.** Neither Armbian's nor Raspberry Pi OS's `config.txt` sets `enable_uart`.
- **`raspberrypi/linux` #7675** (opened 2026-10-07): the `bcm2835-codec` H.264 encoder stops after a while. Open; it affects every OS on the Pi kernel.

## Sources

**Armbian**
- armbian/build v26.08: `config/sources/families/bcm2711.conf`, `config/boards/rpi4b.conf`, `config/kernel/linux-bcm2711-{current,edge,legacy}.config`, `config/sources/git_sources.json`; `main` for the 26.11 changes.
- PRs and issues: [#10783](https://github.com/armbian/build/pull/10783), [#10848](https://github.com/armbian/build/pull/10848), [#10855](https://github.com/armbian/build/pull/10855), [#10802](https://github.com/armbian/build/issues/10802).
- `apt.armbian.com` trixie and trixie-utils indexes; `linux-image-current-bcm2711` 26.8.3 (6.18.44); the streamed `Armbian_26.8.1_Rpi4b_trixie_current_6.18.42_minimal.img.xz`.
- [armbian.com/rpi4b](https://www.armbian.com/rpi4b/); armbian/documentation `release-model.md`, `board-support-rules.md`, `autoconfig.md`.
- Release support and published images, checked 2026-10-08:
  - armbian/build `main` `config/distributions/{noble,resolute,trixie}/support` (all `supported`; resolute since 2026-04-12);
  - armbian/os `userpatches/targets-release-community-maintained.yaml`;
  - `dl.armbian.com/rpi4b/{Resolute,Trixie,Noble}_current_minimal`;
  - `dl.armbian.com/turing-rk1/{Trixie,Noble,Resolute}_vendor_{minimal,server,gnome,kde-plasma}` (which redirect to a file and which return 404).
- k3s: SUSE's k3s support matrix for v1.36 and v1.37; [k3s#14576](https://github.com/k3s-io/k3s/issues/14576) (Ubuntu 26.04 validation).

**Ubuntu**
- ports.ubuntu.com noble and resolute indexes (2026-10-08): `linux-raspi` 6.8.0-1065.69 and 7.0.0-1020.20 (configs from `linux-headers-6.8.0-1065-raspi` and `linux-buildinfo-7.0.0-1020-raspi`); `linux-raspi_6.8.0-1065.69.diff.gz` and `debian.raspi/changelog`.
- `linux-firmware-raspi` 12-0ubuntu1.1 and 14-0ubuntu1.1; `rpi-eeprom` 28.14; flash-kernel 3.107ubuntu13~24.04.6 (`db/all.db`, `functions`); `piboot-try` 1.1ubuntu0.1.
- The streamed `ubuntu-24.04.5-preinstalled-server-arm64+raspi.img.xz` (`config.txt`, `cmdline.txt`, `user-data`); canonical/pi-gadget `classic/configs/{noble,resolute}-arm64-server/`.
- Canonical's Raspberry Pi hardware-support page; ubuntu-release-notes `docs/26.04/`; [ubuntu.com/about/release-cycle](https://ubuntu.com/about/release-cycle).
- Launchpad bugs: [#2167775](https://bugs.launchpad.net/bugs/2167775), [#2161936](https://bugs.launchpad.net/bugs/2161936), [#2155094](https://bugs.launchpad.net/bugs/2155094), [#2158366](https://bugs.launchpad.net/bugs/2158366), [#2099935](https://bugs.launchpad.net/bugs/2099935). Affected-user counts, duplicates and task status were read from the Launchpad API on 2026-10-08, along with the full `piboot-try` bug list (9 bugs).

**Raspberry Pi OS**
- archive.raspberrypi.com trixie indexes and pool dates; `linux-image-6.18.50+rpt-rpi-v8`; `raspi-firmware` 1.20260915-1; `rpi-eeprom` 28.33-1; `cloud-init` 25.2-1~bpo13+1+rpt20 and `rpi-cloud-init-mods` 20260119; `userconf-pi` 0.19; `raspberrypi-sys-mods` 20260914.
- The streamed `2026-10-06-raspios-trixie-arm64-lite.img.xz`; [RPi-Distro/pi-gen@arm64](https://github.com/RPi-Distro/pi-gen/tree/arm64); [Raspberry Pi OS release notes](https://downloads.raspberrypi.com/raspios_lite_arm64/release_notes.txt); [cloud-init on Raspberry Pi OS](https://www.raspberrypi.com/news/cloud-init-on-raspberry-pi-os/) (2025-11-27).
- [raspberrypi/linux](https://github.com/raspberrypi/linux) `rpi-6.18.y` (`bcm2711_defconfig`, `bcm2711-rpi-ds.dtsi`, `pcie-brcmstb.c`); issues #7675 and #7304.
- [rpi-eeprom `rpi-eeprom-update`](https://github.com/raspberrypi/rpi-eeprom/blob/master/rpi-eeprom-update); raspberrypi/documentation `compute-module/cm-bootloader.adoc`, `config_txt/boot.adoc`.

**Turing Pi and general**
- Turing Pi docs: [CM4 flashing](https://docs.turingpi.com/docs/raspberry-pi-cm4-flashing-os), [accessing nodes' filesystems](https://docs.turingpi.com/docs/tpi-accessing-nodes-filesystems.md), [v2.5 changelog](https://docs.turingpi.com/changelog/turing-pi2-v25-list-of-improvements); turing-machines/bmcd (`rpiboot.rs`), turing-machines/tpi (`src/cli.rs`).
- [Debian trixie](https://www.debian.org/releases/trixie/) and [LTS](https://wiki.debian.org/LTS); docker/docs `engine/install/{ubuntu,debian,raspberry-pi-os}.md`; k3s-io/docs `installation/requirements.md`.
