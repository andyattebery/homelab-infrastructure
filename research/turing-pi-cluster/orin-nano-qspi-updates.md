# Jetson Orin Nano in a Turing Pi slot: QSPI updates through apt

Researched 2026-10-03. **[I]** marks inference; **U** means unverified.

Pinned to Jetson Linux R39.2.1 (JetPack 7.2.1):
- `nvidia-l4t-bootloader` and `nvidia-l4t-bootloader-utils` `39.2.1-20260806224157`
- the R39.2.1 BSP
- edk2-nvidia tag `r39.2.1`
- apt on Ubuntu 24.04

This follows [orin-nano-install.md](orin-nano-install.md), "Firmware updates after the first flash".

The question:
- The module's QSPI gets NVIDIA's firmware with `cvb_eeprom_read_size = <0x0>` from an x86 host ([turingpi/jetson/qspi-flash.md](../../turingpi/jetson/qspi-flash.md)).
- The node is then locked against `nvidia-l4t-bootloader`, so that NVIDIA's stock capsule can't undo that ([turingpi/jetson/README.md](../../turingpi/jetson/README.md)).
- Can the patched firmware come through the normal `nvidia-l4t-bootloader` update instead, so that a new L4T release reaches QSPI with apt and a reboot?

## Bottom line

- **Yes: a private apt repo that carries each L4T release, with NVIDIA's `nvidia-l4t-bootloader` rebuilt.**
  - The rebuild replaces one file, `TEGRA_BL_3767_super.Cap`, with a capsule made from the BSP with the EEPROM fix applied.
  - The Jetson updates itself with `apt upgrade` and a reboot.
  - Everything that applies the capsule stays NVIDIA's: the package's install script, the boot-time version check, fwupd, and UEFI's A/B capsule update.
- **NVIDIA documents the rebuild.**
  - R39.2.1: "You can customize Debian packages to help you implement your solution, for example, by adding support for your carrier board". The tool is `tools/Debian/nvdebrepack.sh`.
  - The R32 guide said it of this very package: "The distributed versions of the Bootloader package support only Jetson reference carrier boards. If you are using a custom carrier board you may have to customize this package".
  - The three tools it takes are all in the BSP: `l4t_generate_soc_bup.sh`, `generate_capsule/l4t_generate_soc_capsule.sh` and `nvdebrepack.sh`.
- **A capsule from those tools is the same kind of file NVIDIA ships.** NVIDIA's own `TEGRA_BL_3767_super.Cap` is signed with EDK2's public test certificates and carries FW version `0x270201`. That is what the BSP's script produces by default (parsed 2026-10-03).
- **The repo carries the whole release, not only the bootloader, because that makes the repo the release gate.**
  - NVIDIA's packages for a release arrive before the rebuild for it exists.
  - Exact-version dependencies connect 54 of the release's 72 packages to the bootloader, the kernel among them: `-kernel-nvgpu` pins `-kernel` and `-init`, and `-cuda-nvgpu` pins `-init` and `-core`. Packages joined by exact pins move together, so the bootloader holds back whatever is connected to it through installed packages. The other 18 have no such link and would move ahead of QSPI, among them `-firmware`, `-initrd`, `-optee` and `-extlinux` (the BSP's control files, 2026-10-03).
  - The BSP already holds the release's packages. Of its 77 debs, 74 are byte-identical to NVIDIA's apt pool: the 72 L4T packages and two GPIO libraries. The other 3 are dGPU packages the pool doesn't carry (sha256 against the `som` index, 2026-10-03).
  - So the repo holds those 74, with NVIDIA's bootloader swapped for the rebuilt one: about 700 MB per release. One static pin file makes it the node's source for them, so a release reaches the node only when the repo publishes it with its rebuilt bootloader. The publish itself isn't atomic (Open).
- **What it costs:**
  - **An x86-64 build per L4T release.** The capsule comes out of NVIDIA's i386 signing tools, and nothing on the Jetson can make it.
  - **A repo on the LAN:** Forgejo's Debian registry, which writes and signs the index itself ("Where it is built and served").
  - **fwupd and udisks2 on the node.** The install script stages the capsule with `fwupdtool` and exits 1 without it. fwupd finds the ESP through udisks2, which it only recommends. Without udisks2 it reports "UEFI ESP partition not detected", and the staging fails without a message. NVIDIA's desktop rootfs has both, its minimal one neither, so the generic image adds both to its package list (`jetson-orin-nano-l4t-minimal`'s `files/extra-packages`). NVIDIA's own bootloader updates need them on any carrier.
  - **One-time node setup.** The repo's source, its key and the pin go in [turingpi/jetson/cloud-init/user-data.tpl](../../turingpi/jetson/cloud-init/user-data.tpl), a 1Password template rendered onto the card with `op inject`, because the source URL contains the domain. A first-boot check replaces the `apt-mark hold`. No Ansible is involved.
- **What it replaces:** for each release, moving the module to the dev kit carrier and flashing QSPI from ideapad3. The first flash ([turingpi/jetson/qspi-flash.md](../../turingpi/jetson/qspi-flash.md)) is still needed, and its backup stays the way back.
- **Two decisions** are argued below: what the repo carries ("What the repo carries"), and where it is built and served ("Where it is built and served"). A Launchpad private PPA is one of the hosting options there. It needs Canonical's approval, takes source uploads only, and so could carry only the bootloader.
- **Correction:** the capsule command in [orin-nano-install.md](orin-nano-install.md) builds the wrong capsule for this module. It uses `t23x_3767_bl_spec`, NVIDIA's documented example; this module needs `t23x_3767_bl_super_spec` ("Which capsule").
- **Status:** decided 2026-10-03 ("Where it is built and served"). Built and published the same day: R39.2.1, with `nvidia-l4t-bootloader 39.2.1-20260806224157+tp1`. No step has run on the module yet.

## How NVIDIA's update reaches QSPI

**The package** (`nvidia-l4t-bootloader 39.2.1-20260806224157`)
- It is 154,448,266 bytes. The copy in the BSP's `bootloader/` is identical to the one in NVIDIA's apt pool (sha256 `76d5c770…903f`).
- It holds `/opt/ota_package/t23x/BOOTAA64.efi` (L4TLauncher) and eight T234 capsules. `TEGRA_BL_3767_super.Cap` is 51,959,712 bytes.
- Its only maintainer script is `postinst`.
- `Depends: nvidia-l4t-bootloader-utils (= 39.2.1-20260806224157)`.

**The install script** (`postinst`, line numbers from 39.2.1)
- It does nothing when `/opt/nvidia/l4t-packages/.nv-l4t-disable-boot-fw-update-in-preinstall` exists (line 30).
  - `apply_binaries.sh` creates that file only while it installs the packages into a rootfs (`nv-apply-debs.sh:227-234`).
  - So building an image stages nothing.
- It picks the capsule from `COMPATIBLE_SPEC` in `/etc/nv_boot_control.conf` (line 180). `*jetson-orin-nano-devkit-super-` and `*jetson-orin-nano-devkit-super-maxn-` get `TEGRA_BL_3767_super.Cap` (lines 139-150).
- It stages the capsule with `yes N | fwupdtool install-blob <capsule> <device id>` (line 475). The device id is fwupd's "System Firmware". This path checks no versions.
- Without fwupd it stops with "ERROR. fwupdmgr is not installed." and exit 1 (lines 458-462).
- Only the ISO installer's path checks versions.
  - That path is chosen by `autoinstall` on the kernel command line (line 501).
  - It stages with NVIDIA's helper `nv_bootloader_capsule_updater.sh`.
- After staging, it copies `BOOTAA64.efi` to the ESP and edits `extlinux.conf` (lines 573-575).
- It asks for a reboot only through update-notifier's script, if that script exists (lines 51-52).

**The boot-time check** (`nvidia-l4t-bootloader-utils`)
- `nv-l4t-bootloader-config.service` runs `nv-l4t-bootloader-config.sh -v` on every boot.
- For `jetson-orin-nano-devkit*` with SKU `0005` (`nv-l4t-bootloader-update.sh:181-186`), it compares two versions (lines 26-48):
  - the installed bootloader package's, up to the first `-`, as `(39<<16)|(2<<8)|1` (`nv-l4t-version-utils.sh:43-63`);
  - QSPI's, from ESRT `fw_version`, or failing that from DMI `bios_version` (lines 73-116).
- A newer package triggers `dpkg-reconfigure nvidia-l4t-bootloader`, which re-runs the install script.
- `ENABLE_AUTO_QSPI_UPDATE="0"` turns off only this check. Its file isn't a conffile (the package's only conffile is `/etc/fwupd/uefi_capsule.conf`), so a `-utils` upgrade sets it back to `"1"`.
- The board identity comes from the module, not the carrier:
  - the script reads the module EEPROM at i2c-0 address `0x50` (`nv-l4t-board-config.sh:389-429`);
  - it names SKU `0005` `jetson-orin-nano-devkit-super`, whatever config flashed it (lines 347-352);
  - it writes the results to the UEFI variables `TegraPlatformSpec` and `TegraPlatformCompatSpec` (`nv-l4t-bootloader-config.sh:184-196`).

**UEFI**
- "The UEFI updates the non-current slot Bootloader when a Capsule update is triggered. The device boots from the updated non-current slot after the Capsule update has finished."
- `nvbootctrl dump-slots-info` then reports the "Capsule update status":
  - 1, success
  - 2, "Capsule install successfully but boot new firmware failed"
  - 3, "Capsule install failed"
- Signing:
  - The BSP's capsule script signs with "'test' keys/certs that are public in the edk2 source. They are enabled in the uefi build." (`l4t_generate_soc_capsule.sh:169-171`).
  - NVIDIA's own capsule carries the same three certificates: `TestCert`, `TestSub` and `TestRoot`.
  - NVIDIA's docs: "Without specifying your own certificates, UEFI Capsule update security is highly vulnerable". Using your own means "you must also rebuild UEFI".
  - So the stock UEFI applies any capsule signed with those public keys. That holds on every stock Jetson; this approach relies on it and doesn't change it.
- UEFI chooses images from a capsule by the two UEFI variables above (`TegraFmp.c:36-37, 245-320`).
  - `FwPackageCheckTnSpec` (`FwPackageLib.c`) splits both specs on `-` and requires the same number of fields.
  - It treats an empty field as a wildcard and compares the rest exactly.
  - No carrier EEPROM is involved.

## Why the patched capsule fits that path

- **Where the fix lands.** `cvb_eeprom_read_size` is set in the MB2 BCT (`p3767.conf.common:219`). The flash tools join the MB2 BCT to MB2 (`tegraflash_impl_t234.py:527`), and the capsule carries the result as each board's `mb2` image.
  - It is NVIDIA's documented setting for any carrier without an EEPROM, not a Turing Pi patch: "EEPROM is an optional component for a customized carrier board. If the carrier board is designed without an EEPROM, the following modifications will be needed on the MB2 BCT file" (r39.2 Developer Guide, Jetson Module Adaptation and Bring-Up, Jetson Orin NX and Nano Series, "EEPROM Modifications").
- **Which capsule.** NVIDIA's `TEGRA_BL_3767_super.Cap` holds 119 images: 15 board-specific images for each of seven specs, plus 14 common ones.
  - The seven specs are `t23x_3767_bl_super_spec` in `jetson_board_spec.cfg:86-99`: SKUs 0000, 0001, 0003, 0004 and 0005, plus `-maxn` variants for 0000 and 0001.
  - This module uses the images specced `3767-000-0005--1-0-jetson-orin-nano-devkit-super-`. Its compat spec, `3767--0005--1--jetson-orin-nano-devkit-super-`, matches them field by field [I: from `nv-l4t-board-config.sh:336-382`].
  - `t23x_3767_bl_spec` (lines 73-84) is NVIDIA's documented example. It names the board `jetson-orin-nano-devkit`, one `-`-separated field short of this module's spec, so `FwPackageCheckTnSpec` never matches its images.
  - That capsule would carry no `mb2` for this module [I: UEFI then fails the update].
- **Version.** The capsule script takes the FW version and the lowest supported version from `nv_tegra/bsp_version` (`l4t_generate_soc_capsule.sh:176-185`).
  - For 39.2.1 that is `0x270201`, the same as NVIDIA's.
  - After the update ESRT reads 39.2.1, so the boot-time check finds package and QSPI equal and does nothing.
- **Package version.**
  - `nvdebrepack.sh` sets `<original>+<custom>` (line 88), for example `39.2.1-20260806224157+tp1`.
  - dpkg orders that after NVIDIA's `39.2.1-20260806224157` and before any `39.2.2-…` (checked with `dpkg --compare-versions`).
  - The boot-time check reads only `39.2.1`.
  - No package depends on `nvidia-l4t-bootloader` exactly. `nvidia-l4t-bsp` wants `(>> 39.2-0), (<< 39.3-0)`, which the rebuilt version satisfies. `apply_binaries.sh` installs `nvidia-l4t-bsp` by default (`nv-deb-skiplist.sh`).
  - So no other package needs rebuilding.

## The build, per L4T release

On x86-64 Ubuntu, in that release's `Linux_for_Tegra/`, as root:

1. Apply the EEPROM fix.
   - This is the edit [turingpi/jetson/qspi-flash.md](../../turingpi/jetson/qspi-flash.md) step 7 makes, to `bootloader/tegra234-mb2-bct-common.dtsi` and `bootloader/generic/BCT/tegra234-mb2-bct-misc-p3767-0000.dts`.
   - These are the only T234 files with the setting that the p3767 configs use. The other files that carry `cvb_eeprom_read_size` are for T264 and P3701.
2. `./l4t_generate_soc_bup.sh -e t23x_3767_bl_super_spec t23x` writes `bootloader/payloads_t23x/bl_only_payload`.
   - It runs `flash.sh --no-flash --sign --bup` once per spec, with the board IDs passed as variables (`l4t_generate_soc_bup.sh:290-296`, `build_l4t_bup.sh:149`).
   - So no module is attached.
3. `./generate_capsule/l4t_generate_soc_capsule.sh -i bootloader/payloads_t23x/bl_only_payload -o TEGRA_BL_3767_super.Cap t234`
4. `tools/Debian/nvdebrepack.sh -v tp1 -i "$PWD/TEGRA_BL_3767_super.Cap:/opt/ota_package/t23x/TEGRA_BL_3767_super.Cap" -m "<what changed>" -n "<name> <email>" bootloader/nvidia-l4t-bootloader_<version>_arm64.deb`
   - It recalculates the md5sums and Installed-Size and adds a changelog entry (lines 190-221).
   - It writes `nvidia-l4t-bootloader_<version>+tp1_arm64.deb` into `tools/Debian/`.
   - It needs only `dpkg-deb` and `fakeroot`.
   - A second build of the same release needs a higher suffix, such as `tp2`, or apt won't upgrade to it.
   - Nothing else in the package changes: its scripts and dependencies stay NVIDIA's. The fwupd its install script needs comes with the generic image.
5. Publish to the repo.
   - Take the BSP's debs from `nv_tegra/l4t_deb_packages/`, `kernel/`, `bootloader/` and `tools/`, leaving out NVIDIA's `nvidia-l4t-bootloader` and the three dGPU packages the pool doesn't carry: `-dgpu-apt-source`, `-dgpu-config` and `-dgpu-x11`. `-dgpu-tools` is in NVIDIA's pool and stays.
   - Upload them to Forgejo's Debian registry, NVIDIA's debs first and the rebuilt bootloader last. Forgejo writes the index and a `Release` with `Codename: l4t-bootloader-no-carrier-eeprom`, which the pin names, and signs it.

The package's other capsules stay NVIDIA's. On SKU 0005 the install script can only choose `_super`, so this module never uses them. But the rebuilt package isn't safe for other modules on this carrier.

**Checks before publishing.** The BUP format is in `bootloader/BUP_generator.py`: a 40-byte header, then 184-byte entries giving name, offset, length, version, mode and spec.
- The edit changed exactly two lines, both to `<0x0>`.
- The patched build differs from NVIDIA's `TEGRA_BL_3767_super.Cap` only in three kinds of image:
  - `VER`, which holds the build time (NVIDIA's reads `20260806224715`);
  - the seven `mb2` images, every one of which differs, which shows the patch landed;
  - the QSPI's backup GPTs (`secondary_gpt`, `secondary_gpt_backup`). Every build gives them new random disk and partition GUIDs: NVIDIA's own capsule has seven different ones, one per spec, with identical layouts. So they're compared with those GUIDs and their CRCs zeroed, and the rebuild's CRCs must check out.
- The first build, in the workflow's `ubuntu:24.04` container (2026-10-03), reproduced every other image byte for byte, so the build is deterministic apart from those three.
- Every package in the repo except the bootloader matches NVIDIA's `som` index by sha256.

## What the repo carries

**The question.** Does the private repo hold only the rebuilt bootloader, or the whole release?

**A. The release: the BSP's packages, with the bootloader swapped.**

The node's pin, written once:

```
# /etc/apt/preferences.d/l4t-private
Package: nvidia-l4t-bootloader
Pin: release o=Nvidia
Pin-Priority: -1

Package: *
Pin: release n=l4t-bootloader-no-carrier-eeprom
Pin-Priority: 990
```

- How apt applies it, from `apt-pkg/policy.cc`, byte-identical in apt 2.7.14 and 2.8.3 (noble's release and updates):
  - A `Package: *` record is a default for each index file it matches, not a pin on versions. Line 440 turns `*` into an empty name, and line 180 stores the record among the defaults. For each file, the first matching default wins (lines 116-128). NVIDIA's own `Pin: origin "*.nvidia.com"` record in `nvidia-repo-pin` (from `nvidia-l4t-apt-source`) works the same way.
  - A version's priority is the highest of the files it appears in (line 351). The BSP's debs are byte-identical to NVIDIA's pool, so a version both repos carry gets max(600, 990) = 990. NVIDIA's next release, present only in NVIDIA's repo, stays at 600 and loses. So nothing moves until the repo publishes the next release, kernel packages included.
  - A record that names a package pins every version it matches, ahead of any file priority (lines 254-266, 327-334). So NVIDIA's bootloader is -1 in every version, and "P < 0 prevents the version from being installed". The rebuild's `+tp1` versions are never in NVIDIA's repo, so the -1 never touches them.
  - The pin follows the version, not the repo: identical copies in two repos merge into one cached version (`pkgcachegen.cc` lines 400-438). If the repo ever carried NVIDIA's own bootloader version, that version would be -1 there too, so the repo leaves it out.
  - The order of the two records doesn't matter, nor this file's order against `nvidia-repo-pin`. apt_preferences(5) says records "using patterns in the Pin field other than "*" are treated like specific-form records", but that doesn't describe this code for `Package: *` records.
  - `o=` matches a `Release` file's `Origin:` (NVIDIA's is `Nvidia`) and `n=` its `Codename:`. Both are fields in the files, not hostnames, so repos made of local files can test the pin.
  - Packages the repo doesn't carry keep NVIDIA's priority. That covers CUDA and the rest of `common`, which includes three `nvidia-l4t-*` packages: `-cudadebuggingsupport`, `-gstreamer` and `-jetson-multimedia-api`. NVIDIA's host serves both repos, so a blanket -1 on `nvidia-l4t-*` from it would block those three too.
- For:
  - The gate is the repo's content. It therefore holds for `apt upgrade`, for `apt dist-upgrade` (which the `system_upgrade` role runs) and for anything else that takes apt's candidates.
  - The pin file never changes between releases.
  - `apt-cache policy` shows it working: the repo's versions at 990, NVIDIA's bootloader at -1.
  - Apart from the bootloader, the packages are NVIDIA's own files, byte for byte.
- Against:
  - About 700 MB per release on the host.
  - L4T updates wait for the build, NVIDIA's fixes included.
  - If the node loses the repo's index (lists deleted, source removed), NVIDIA's versions become candidates again for everything except the bootloader.

**B. Only the rebuilt bootloader.** NVIDIA's repo supplies the rest.
- For: one package of about 154 MB per release, and the node keeps getting NVIDIA's packages directly.
- Against:
  - The gate would have to come from the package.
    - The exact-version links cover at most 54 of the 72 packages (Bottom line).
    - The rest would need `Breaks: <package> (>> <version>)` lines, generated per release.
    - `nvidia-l4t-kernel` 39.2.1 declares no dependencies at all, though NVIDIA's package page lists `nvidia-l4t-tools`, `nvidia-l4t-init` and a matching `-core`.
  - `dist-upgrade` can resolve such a conflict by removing the package that declares it [I].
    - Preventing that takes `Protected: yes`, which APT has had "basic support" for since 2.1.7.
    - APT treats the older `Important` as "a synonym to Essential". It might then fail the whole upgrade rather than keep packages back [I].
    - Neither is tested.
  - Between NVIDIA's release and the rebuild, whatever the gate misses lands first. NVIDIA: "NVIDIA advises against installing a combination of packages from different releases."

**Recommendation: A.**
- Reasons:
  - The gate is structural and static: the repo's content, plus a pin file that never changes.
  - There are no generated `Breaks`, no `Protected` field and no resolver behaviour to trust.
  - The files are NVIDIA's own.
- What would change it:
  - If NVIDIA gave every L4T package an exact dependency on `-core`, the chain alone would gate a release under `apt upgrade`, and B would need no `Breaks`. The `dist-upgrade` removal path would remain.
  - If 700 MB per release is too much for the host.

## Where it is built and served

**The question.** Which x86-64 machine builds each release, and where is the repo served privately?

**Decided 2026-10-03:** Forgejo's Debian registry on nas-01, built by a Forgejo Actions runner on nas-01.
- The registry belongs to a public org, `homelab`, because Forgejo isn't exposed publicly. It serves the distribution `l4t-bootloader-no-carrier-eeprom`, component `main`.
- The build lives in `jetson-orin-nano-l4t-bootloader`, a Forgejo repo push-mirrored to GitHub. A push that changes its `versions.env` builds, checks and publishes a release. A daily check does the same for each new NVIDIA release with the same major version, using the image repo's `check-release.py` unchanged; it commits the new `versions.env` once the build passes, then publishes.
- An apt repo can be a static host: apt only fetches files, so any web server can serve one. It should use the official `dists/` layout, because the Debian wiki says flat repos "lack support for pinning".
- Existing tools include reprepro, aptly and Pulp (Debian wiki, DebianRepository/Setup). Forgejo's registry was chosen because it already runs here, and it writes and signs the index itself. What it lacks is an atomic publish (Open).

Options A-D below are the record.

**A. The host that serves the repo, in an `ubuntu:24.04` container, by one committed script.**
- For:
  - Build and publish are one step on one machine, with nothing to copy.
  - The script is the procedure.
- Against:
  - NVIDIA's build environment lives on a homelab host: root in the container, NVIDIA's prerequisite packages, and a few GB of scratch [I].
  - Whether NVIDIA's tools run in a container is U. The image workflow runs the same `flash.sh --sign` on GitHub's runner, itself a VM, so its result will show whether they work off bare metal. (Answered 2026-10-03: they do. The first build ran them in the workflow's `ubuntu:24.04` container.)

**B. ideapad3, by hand, then copied to the server.**
- For: it already has a patched tree after a QSPI flash.
- Against: a manual build and a copy every release, on a partly provisioned laptop.

**C. GitHub Actions, as for the image.**
- For: the image's CI already downloads the BSP.
- Against:
  - A GitHub-hosted runner can't reach a LAN repo. It needs a self-hosted runner in the homelab, or a pull step.
  - GitHub can't host the private repo itself: Pages sites are public.

**D. A Launchpad private PPA, which Launchpad builds, signs and serves.**
- What Launchpad's manual says:
  - "Visibility: Public by default; private PPAs available with Canonical approval".
  - "Use of commercial-only features is granted on a case-by-case basis for a defined time period". The last published price was "US$250/year/project" (Launchpad blog, 2012); the current tour page says only "Contact us".
  - "Uploadable artefacts: Source packages only; pre-built binary uploads are rejected."
  - arm64 isn't built by default and is enabled per PPA. The disk quota is 8 GiB.
  - Each subscriber gets their own password for the source line.
- For: nothing to host in the homelab, and the Jetson's apt reads the PPA directly.
- Against:
  - It isn't self-service: it needs Canonical's approval, which has historically meant a paid subscription.
  - It takes source only. The capsule still has to be built on x86 somewhere else and carried inside a source package that Launchpad "builds" by copying files. So it removes the web server, not the build host, and adds Debian source packaging and signed uploads.
  - It can't carry the release's other packages, because NVIDIA's debs are binaries. The repo would hold only the rebuilt bootloader: "What the repo carries" option B, with its untested gate.

**Recommendation: A**, superseded by the decision above.
- Reasons: one machine and one command per release, and nothing private leaves the LAN.
- What would change it:
  - If NVIDIA's tools won't run in a container: B.
  - If releases should build without a person: A's script run by a self-hosted runner, at the cost of that runner.
  - If Canonical grants a private PPA and the bootloader-only gate tests clean under the apt commands the node uses: D, which removes the homelab web server.

## What changes on the node

**One-time, in [turingpi/jetson/cloud-init/user-data.tpl](../../turingpi/jetson/cloud-init/user-data.tpl)**, so a fresh card uses the repo from its first boot:
- The repo's source, its public key and the pin file, written with `write_files`.
  - The source URL contains the domain, which this public repo keeps out of committed files. So `user-data` is a 1Password template, rendered onto the card with `op inject`.
- A first-boot check takes the place of the `apt-mark hold`, which would block every upgrade.
  - `/usr/local/sbin/l4t-private-repo-check` runs last in `runcmd`. It runs `apt-get update`, then holds every installed `nvidia-l4t-*` package unless `nvidia-l4t-bootloader`'s candidate is the rebuild (its version contains `+`).
  - So a card that can't reach the repo stays locked as before. The check looks only at the bootloader's candidate, so the pin itself is tested elsewhere (`ansible/tests/apt-sources/`).
- `ENABLE_AUTO_QSPI_UPDATE="0"` stays in `bootcmd`.
  - A fresh card boots with NVIDIA's own package until the first `apt upgrade` replaces it.
  - After that the switch doesn't matter, and a `-utils` upgrade resets it to `"1"` anyway.
- fwupd and udisks2 come with the generic image.

The traps in [turingpi/jetson/README.md](../../turingpi/jetson/README.md) about `--reinstall` and `dpkg-reconfigure` stop applying: with the rebuilt package installed, both re-stage the patched capsule.

**Each release after that**
1. `jetson-orin-nano-l4t-bootloader`'s daily check finds the release, then builds it, runs the checks, commits `versions.env` and publishes. By hand, set the new BSP's URL and sha256 in `versions.env` and push.
2. Once the workflow has finished, run `sudo apt update && sudo apt upgrade` on the Jetson, as NVIDIA's point-release procedure says. A minor release (r39.3) is the same publish, and NVIDIA's procedure for it uses `apt dist-upgrade`.
3. Reboot. UEFI updates the non-current slot and boots from it.
   - On the minimal image nothing asks for this reboot [I].
   - The install script asks only through update-notifier, which the minimal rootfs lacks.
4. `nvbootctrl dump-slots-info` shows status 1, and ESRT shows the new version.

The first `apt upgrade` after setup happens at the release QSPI already runs, which makes it the low-stakes test. Run 2026-10-04:
- fwupd staged the same-version capsule once udisks2 was installed ("Side finding").
- UEFI applied it at the reboot: capsule status 1, slot B current and active, `last_attempt_status` 0.
- The reset after the update hung, with no ssh and no ping, until node 4 was power-cycled through the BMC. From the cold boot, slot B booted normally.
- A plain warm reboot afterwards came back in about 50 s, so the hang belongs to the reset after the capsule update.

## Other ways, and why not

- **An Ansible play that fetches the package into a local repo on the node** (this doc's first draft). It works, but puts Ansible in every update.
- **fwupd with a local remote.** NVIDIA documents LVFS for Jetson: a `.cab` made from the capsule and a `metainfo.xml`.
  - It splits firmware and L4T packages into two update channels.
  - NVIDIA's bootloader package would still have to be kept off the node.
  - The boot-time check that ties the package version to the QSPI version would stop meaning anything.
- **A companion package that diverts NVIDIA's capsule** (`dpkg-divert`). It keeps NVIDIA's package bytes, but:
  - nothing orders NVIDIA's install script after the companion's unpack;
  - if `dist-upgrade` removes the companion, the diversion goes with it, and NVIDIA's capsule is back where the next configure stages it.
- **Image-based OTA** (`l4t_generate_ota_package.sh`). It writes partitions, the rootfs among them, from a payload built on a host. That replaces apt and the card image rather than working with them.
- **Patching NVIDIA's capsule on the node.** The `mb2` image comes out of NVIDIA's i386 signing tools. So it would mean either running those tools on an arm64 node or editing a signed binary by hand.
- **An EEPROM on the carrier.** It would make NVIDIA's stock path work unchanged. Not researched: where the module's I2C bus goes on the Turing Pi 2.5.

## Side finding: the generic image and fwupd

- On the generic image, configuring NVIDIA's `nvidia-l4t-bootloader` fails with "ERROR. fwupdmgr is not installed." (postinst lines 461-462). That leaves the package half-configured.
- NVIDIA's minimal package list has no fwupd, though its desktop list does.
- On a dev kit, that means `apt upgrade` across a point release errors out instead of updating QSPI.
- On this carrier it was accidental protection. The image now adds fwupd and udisks2 (`files/extra-packages`, 2026-10-03 and 2026-10-04), so the pin and the first-boot check ("What changes on the node") are the protection instead.
- fwupd alone wasn't enough. On the first card with it, the install script ran, but fwupd couldn't find the ESP without udisks2, so nothing was staged, and the script still printed "Trigger Capsule update is done." With udisks2 installed by hand, a reinstall staged the rebuilt capsule on the ESP (2026-10-04).
- Not yet seen on a booted card.

## Open

- **A same-version capsule.** Answered 2026-10-04: fwupd stages it, and UEFI applies it (status 1). See "What changes on the node".
- **The reset after a capsule update hung** (2026-10-04) until a BMC power cycle.
  - It is that reset only: a plain `sudo reboot` right after, with nothing staged, came back in about 50 s.
  - Open: whether it hangs every time. NVIDIA's next point release will show. Until then, the README's "Updating" step says to power-cycle if the node isn't back within about five minutes.
- **fwupd on the minimal rootfs.** Answered 2026-10-04:
  - It lists "System Firmware" (capsule-on-disk; the firmware's `OsIndicationsSupported` has the file-delivery bit).
  - It stages only with udisks2 installed ("Side finding").
  - Of fwupd's other recommends (bolt, secureboot-db, fwupd-signed, jq), none is in the capsule path on this board.
- **ESP space.** Answered 2026-10-04: it fits.
  - The SD layout's ESP is 64 MiB (`flash_t234_qspi_sd.xml`) and holds only `BOOTAA64.efi` (114,688 bytes), leaving 63M free.
  - NVIDIA's fwupd config asks for 60 MiB free (`RequireESPFreeSpace=0x3C00000`; fwupd 2.x moves it into `fwupd.conf`).
  - The 51,959,712-byte capsule staged, leaving 14M free.
  - Any refusal is silent, because the install script discards `install-blob`'s output and exit status (line 475). `EFI/UpdateCapsule/` on the ESP shows whether it staged; the capsule status after the reboot shows whether UEFI applied it.
- **The publish isn't atomic.** It is 74 uploads, and Forgejo rebuilds the index after each one. Tested with fixtures in `ansible/tests/apt-sources/verify-l4t-pin.yml`, in the state where every new package is published except the rebuilt bootloader:
  - `apt upgrade` keeps everything tied to the bootloader by exact versions (Bottom line) back. Only the untied packages move: the 18 L4T packages, `-firmware`, `-initrd` and `-optee` among them, and the two GPIO libraries.
  - `apt dist-upgrade` (also `full-upgrade`, and the `system_upgrade` role) removes `nvidia-l4t-bootloader`, and with it `nvidia-l4t-bsp`, which depends on it by version range. It moves everything tied to the bootloader to the new release, kernel included. Later upgrades don't reinstall a removed package, so QSPI would silently stop getting updates.
  - No upload order closes the window, because the tied group is consistent only once its last package arrives. So run apt only after the workflow has finished, and never `dist-upgrade` while it runs. That is a rule to follow, not something enforced.
- **A bad capsule:**
  - NVIDIA: "If a bootable slot fails to boot, Bootloader sets its status attribute as unbootable and switches the roles".
  - Whether an MB2 hang counts as failing to boot is U. On a cold boot, BootRom picks the slot from the BR-BCT.
  - The x86 restore in [turingpi/jetson/qspi-flash.md](../../turingpi/jetson/qspi-flash.md) is the backstop.
- **The first flash without x86 [I]:**
  - On its dev kit carrier the module boots stock firmware, so the rebuilt package could put the patched firmware on QSPI by capsule.
  - It would run twice, once per slot ("Manually Sync Bootloader A/B Slots" in NVIDIA's docs).
  - U: the dev kit's current QSPI release, and whether its UEFI accepts a 39.2.1 capsule.

## Sources

**NVIDIA documentation**
- Jetson Linux R39.2.1 Developer Guide, https://docs.nvidia.com/jetson/archives/r39.2.1/DeveloperGuide/
  - "Software Packages and the Update Mechanism": Repackaging Debian Packages; Customizing Debian Packages; Over-the-Air Update and the point-release procedure; the kernel package's listed dependencies.
  - "Update and Redundancy": A/B system update; the bootloader version in QSPI; generating the BUP and the capsule payload; fwupdtool and the helper script; capsule status codes; LVFS.
- Jetson Linux R32 Developer Guide, "BSP Customization", "Building the Debian Bootloader Package Yourself": https://docs.nvidia.com/jetson/l4t/Tegra%20Linux%20Driver%20Package%20Development%20Guide/getting_started.html
- Jetson Linux r39.2 Developer Guide, Jetson Module Adaptation and Bring-Up, Jetson Orin NX and Nano Series, "EEPROM Modifications": https://docs.nvidia.com/jetson/archives/r39.2/DeveloperGuide/HR/JetsonModuleAdaptationAndBringUp/JetsonOrinNxNanoSeries.html

**NVIDIA packages** (repo.download.nvidia.com/jetson, suite r39.2)
- `nvidia-l4t-bootloader` and `nvidia-l4t-bootloader-utils` `39.2.1-20260806224157`:
  - control and `postinst`;
  - the `nv-l4t-*` scripts and the service;
  - `nv_bootloader_capsule_updater.sh` and `/etc/fwupd/uefi_capsule.conf`.
- `nvidia-l4t-apt-source`: its sources list and `nvidia-repo-pin`.
- The `som`, `common` and `ffmpeg` Packages indexes for r39.2 (`som` dated 2026-09-14, `common` 2026-09-17):
  - versions and dependencies;
  - the three `nvidia-l4t-*` packages in `common`;
  - no package depending on fwupd;
  - SHA256s, against which the BSP's 77 debs were compared.
- `TEGRA_BL_3767_super.Cap` and `TEGRA_BL_3767.Cap` from the package: the FMP header, signer certificates, FW version and BUP image table.

**BSP R39.2.1** (`Jetson_Linux_R39.2.1_aarch64.tbz2`, sha256 `2e5619…e6b`)
- the control files of its 77 debs: the exact-version dependencies
- `l4t_generate_soc_bup.sh`, `build_l4t_bup.sh` and `jetson_board_spec.cfg`
- `generate_capsule/l4t_generate_soc_capsule.sh`
- `tools/Debian/nvdebrepack.sh` and `nvdebrepack.txt`
- `bootloader/BUP_generator.py`, `bootloader/tegraflash_impl_t234.py` and `p3767.conf.common`
- `nv_tegra/nv-apply-debs.sh`, `nv_tegra/nv-deb-skiplist.sh` and `nv_tools/scripts/nv_l4t_get_package_install_list.sh`
- `tools/samplefs/nvubuntu-noble-{minimal,desktop}-aarch64-packages`
- `bootloader/generic/cfg/flash_t234_qspi_sd.xml`

**edk2-nvidia, tag `r39.2.1`**
- `Silicon/NVIDIA/Library/FmpDeviceLib/TegraFmp.c` and `FmpDeviceLib.c`
- `Silicon/NVIDIA/Library/FwPackageLib/FwPackageLib.c`

**APT and dpkg**
- apt_preferences(5), Ubuntu noble: https://manpages.ubuntu.com/manpages/noble/man5/apt_preferences.5.html
- apt's `apt-pkg/policy.cc` and `apt-pkg/pkgcachegen.cc` at tags 2.7.14 and 2.8.3, identical at both: https://salsa.debian.org/apt-team/apt/-/raw/2.7.14/apt-pkg/policy.cc
- Debian wiki, the `Protected` field: https://wiki.debian.org/Teams/Dpkg/Spec/ProtectedField
- Debian wiki, setting up a repository: https://wiki.debian.org/DebianRepository/Setup

**Forgejo v15**
- Docs: the Debian package registry, https://forgejo.org/docs/v15.0/user/packages/debian/; package access, https://forgejo.org/docs/v15.0/user/packages/; Actions, https://forgejo.org/docs/v15.0/user/actions/; runner registration, https://forgejo.org/docs/v15.0/admin/actions/registration/
- Source, branch `v15.0/forgejo` (https://codeberg.org/forgejo/forgejo): `services/packages/debian/repository.go`, the `Release` fields and the signing key; `routers/api/packages/debian/debian.go`, the index rebuilt after each upload

**Launchpad**
- Manual, "Personal Package Archive": https://documentation.ubuntu.com/launchpad/user/reference/packaging/ppas/ppa/
- Manual, "Install software from private PPAs": https://documentation.ubuntu.com/launchpad/user/how-to/packaging/private-ppa-install/
- Manual, "Proprietary git repository hosting": https://ubuntu.com/docs/launchpad/user/reference/proprietary-hosting/
- Tour, "Commercial subscriptions and joining Launchpad": https://launchpad.net/+tour/join-launchpad
- Blog, "Setting up commercial projects quickly" (2012-04-18): https://blog.launchpad.net/cool-new-stuff/setting-up-commercial-projects-quickly

**This repo:** `turingpi/jetson/README.md`, `turingpi/jetson/qspi-flash.md`, `turingpi/jetson/cloud-init/user-data.tpl` and `ansible/roles/system_upgrade/`.

**`andyattebery/jetson-orin-nano-l4t-minimal`:** `versions.env`, `scripts/build.sh`, `scripts/check-release.py` and `files/extra-packages`.
