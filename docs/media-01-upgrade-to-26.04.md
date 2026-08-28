# media-01 — upgrading to Ubuntu 26.04

> **This document is the current state: what is true of the host, and the procedure to follow.**
> It is not a progress tracker — progress lives in `tasks/media-01-26.04-upgrade.md`, which is where
> a new thread should start. Keep this file accurate as things change; do not log work in it.
>
> The upgrade itself has still not been executed.
>
> Written as research on 2026-08-22. Corrections since are marked **UPDATE 2026-08-23** in place
> rather than rewritten away, because what was found on 2026-08-22 is the reason the apt-source
> migration happened.
>
> This file fills the reference `plans/media-01-restore-scsi0-from-backup.md` left dangling: the
> 26.04 upgrade was deliberately deferred to "on or after 27 August", and that runbook noted the
> follow-up "needs writing up before it is attempted".
>
> Every date below is a fact with a shelf life. 26.04.1's date has already moved once. Re-check
> anything load-bearing rather than trusting this document's age.

## Recommendation

**Upgrade in place, on or after 2026-08-27, after a preparation pass on 24.04.**

Already closed, and listed so it is not re-derived: ~~fix `fish_install`~~ — **DONE 2026-08-23**,
the `apt-key` call is gone. See [What has changed since](#changed-since).

1. **Capture `/etc/apt/` first.** Before changing anything, copy `sources.list.d/`,
   `trusted.gpg.d/` and `keyrings/` off the host. Step 6's PBS snapshot is the real rollback; this
   is what makes a *partial* apt problem cheap to undo without restoring a whole disk — and it is
   the thing most likely to be needed, because the upgrade disables every third-party source by
   design.
2. **Confirm 26.04.1 actually released.** Scheduled 2026-08-27, and that date has already moved once
   (from 2026-08-04). It is a schedule, not an event.
3. ~~**Remove the unmanaged CUDA repo.**~~ **NOW PLAYBOOK-OWNED, 2026-08-26** — a `pre_task` in
   `playbook-media-01.yaml` removes `cuda-keyring` with `purge`, which takes the source, the
   `preferences.d` pin and the keyring with it (all three are files that package owns; the first two
   are conffiles, hence `purge`). Runs under `--tags nvidia`. It has not yet been executed against
   the host — until it is, this step is still outstanding, it is just no longer manual.

   **It is a bigger removal than this step assumed.** The repo is not a dormant leftover: eight
   installed packages still resolve to it, including `dkms` and all four
   `nvidia-container-toolkit` packages, which it wins from `nvidia.github.io` on the strength of its
   priority-600 pin. This is the "don't mix sources" hazard actually biting, not a tidy-up.

   The four toolkit packages are neutral — `nvidia.github.io` publishes the identical `1.20.0-1`.
   The rest are left installed above any configured source, and **this upgrade does not fix that**:
   resolute ships `dkms` 3.2.2, `libxnvctrl0`/`nvidia-settings` 510.47.03, all *lower* than what is
   installed, so apt leaves them. Details in `docs/media-01-nvidia-driver.md`.

   (The fish PPA was the other half of this item and is **closed** — Ansible manages it now.)
3a. **Force `dkms` back onto an archive version — early in the upgrade, not after.**
   NVIDIA's `dkms` carries epoch `1:` and Ubuntu's does not, so `1:3.4.1-1ubuntu1` outranks any
   Ubuntu version at any release. Nothing reclaims it on its own, ever:

       apt install --allow-downgrades dkms=3.2.2-1ubuntu1
       apt install --reinstall nvidia-dkms-<branch>-server-open   # regenerate state under 3.2.2
       dkms status                                                # built for the new kernel

   resolute's 3.2.2 rather than noble's 3.0.11 deliberately: 3.4.1 → 3.0.11 crosses dkms 3.0.13's
   module-compression rework and 3.1.7's archived-module relocation; 3.4.1 → 3.2.2 crosses neither.
   Doing it here also means DKMS rebuilds once, since the kernel is moving 6.8 → 7.0 anyway.

   **Early**, because `do-release-upgrade` may treat the sourceless 3.4.1 as an obsolete package and
   remove it — which would take `nvidia-dkms-*` with it.
4. **Run the full untagged playbook on 24.04**, converging the host with the current roles while the
   OS is still known-good. Not yet done: the apt-source rollout deliberately applied only each
   role's `tasks/apt_repo.yaml`, so `docker.list` and the rest of the drift are untouched.
5. ~~**Decide on the `nvidia_driver` role.**~~ **DECIDED 2026-08-24 — adopted, no package change.**
   It is not a package-set change after all: the role owns `nvidia-driver-{branch}-server-open`, the
   set the host already runs, so adoption is idempotent and needs no window of its own. The
   `-headless-…` alternative was rejected because it drops `libnvidia-encode`/`libnvidia-decode`,
   which Plex and Tdarr need injected into their containers. See `docs/media-01-nvidia-driver.md`.
6. **Fresh PBS snapshot immediately before**, then `do-release-upgrade`.
7. **Afterwards: decline `zpool upgrade`**, then re-run the playbook to restore third-party repos.

The list is in execution order. Step 4 is the preparation pass and wants its own window on 24.04 —
do not fold it into the same session as step 6.

The upgrade is **the fix** for the ZFS problem that forced August's rollback, not a repeat of it.
That is the single most important thing in this document and the easiest to get backwards.

<a id="changed-since"></a>
## What has changed since this was written

The apt-source migration was written, container-tested and deployed to this host on 2026-08-23. It
closes two prerequisites outright and makes a third finding moot:

- **`fish_install` no longer calls `apt-key`.** This was the confirmed hard blocker: it runs on
  every host via `configure_server`, early, so it would have failed the whole post-upgrade playbook
  run — including the run that restores the third-party repos.
- **Bug #2150614 no longer applies to this host.** The inline-key fish source is gone. The host now
  has `fish-shell-release-4.sources` with
  `Signed-By: /etc/apt/keyrings/fish-shell-release-4.asc`, and **no source on the host contains an
  inline PGP key**. The "decide about the fish PPA before upgrading" item is closed, and step 3 of
  the Recommendation now names only the CUDA repo.
- **The NVIDIA toolkit source is now deduped for real.** It is one deb822 source with the
  architecture resolved to `amd64`; the legacy `stable/ubuntu18.04` suite is gone.

Host state as read on 2026-08-23 16:51 CDT — Ubuntu 24.04.4, kernel 6.8.0-137-generic,
`zfsutils-linux 2.2.2-0ubuntu9.4`:

    /etc/apt/sources.list.d/   cuda-ubuntu2404-x86_64.list      <- STILL THERE, still priority 600
                               docker.list                       <- STILL a legacy .list
                               fish-shell-release-4.sources      migrated
                               mise.sources                      migrated
                               nvidia-container-toolkit.sources  migrated
                               ubuntu.sources
    /etc/apt/keyrings/         fish-shell-release-4.asc, mise.asc,
                               nvidia-container-toolkit.asc
    inline PGP keys in sources: none

**What is still outstanding is the numbered procedure above.** The migration deliberately applied
only each role's `tasks/apt_repo.yaml`, so the rest of the drift this document found is untouched.

Progress against the procedure above is tracked in `tasks/media-01-26.04-upgrade.md`.

## Why 26.04 fixes the thing that broke in August

On 2026-08-10 a playbook run installed `linux-generic-hwe-24.04` 7.0.0-28 and the host was rolled
back by a full PBS root-disk restore (`plans/media-01-restore-scsi0-from-backup.md`).

**What broke was a ZFS split: the kernel module and the userspace tools stopped matching.** The
restore notes never record this — they say only "the restore removed the symptom". The mechanism is
recorded here from the operator, and this document is the first place it is written down.

| | zfs module | `zfsutils-linux` | |
| --- | --- | --- | --- |
| 24.04 + GA kernel | 2.2.x | 2.2.2 | matched |
| 24.04 + HWE 7.0 | 2.4.x | 2.2.2 | **split — what broke** |
| 26.04 | 2.4.x | 2.4.1 | matched |

The HWE stack moves the *kernel* forward while userspace stays on 24.04's. On a host whose whole
job is a ZFS pool, that is the wrong half to move alone — and it is why this host deliberately sits
on the GA kernel.

**A release upgrade moves both halves together.** 26.04 pairs `linux 7.0.0-30.30` with
`zfsutils-linux 2.4.1-1ubuntu5`. The 7.0 kernel was never the problem; the skew was.

Note for anyone re-deriving this: the 24.04 HWE stack *is* the 26.04 kernel backported —
`linux-hwe-7.0` in noble is `7.0.0-30.30~24.04.1` against resolute's `linux 7.0.0-30.30`. Reading
"7.0 was reverted, 26.04 ships 7.0" as "26.04 repeats the failure" is the wrong conclusion, and an
easy one to reach.

## The 26.04.1 question

**26.04.1 is scheduled for 2026-08-27**, per Ubuntu's own release schedule. It was originally
2026-08-04 (per the 23 April release announcement) and moved in a schedule update around 10 June.

**No reason for the slip was ever published.** Checked: the `ubuntu-release` mailing list archives
for July and August 2026 (nothing but automated `component-mismatches` traffic), the schedule page
itself, and Release Team/Discourse announcements. The two prior LTS point releases that slipped were
announced *with* reasons — 24.04.1's was "multiple issues affecting the upgrade from 22.04 LTS to
24.04 LTS". That is precedent, not evidence about 26.04.1.

### Is waiting a formality?

**For where you land: essentially yes.** A point release is refreshed *installation media*, not new
content — accumulated SRUs rolled into images, with `-proposed` disabled before the final build. A
fully-updated 26.04 is identical to one installed from 26.04.1 media. This host is not installing
from media: `do-release-upgrade` pulls from `resolute` + `-updates` + `-security` either way, so
upgrading today with `-d` and upgrading on the 28th land on the **same packages**. 26.04.1 brings no
newer kernel either — HWE stacks land in later point releases of the *older* LTS.

**For how you get there: no.** Two concrete things:

- The gate itself. With `Prompt=lts` in `/etc/update-manager/release-upgrades`, 26.04 is not offered
  to a 24.04 host until 26.04.1 exists. Before then the only route is `do-release-upgrade -d`, which
  Canonical documents as being for test systems.
- **Upgrade fixes are being milestoned against it.** Launchpad bug #2156727 ("upgrade from
  24.04/25.10 leaves the user at a TTY") is In Progress with a merge proposal against the
  `ubuntu-26.04.1` milestone, patching `DistUpgradeQuirks.py`.

The upgrade is driven by `ubuntu-release-upgrader` **running on this 24.04 host**, not by anything
in resolute — and that package updates in noble like any other. So `apt update && apt full-upgrade`
immediately before starting matters more than the calendar.

Stated plainly because it is widely repeated and this research could not source it: the release
team's published point-release process covers image building and SRU roll-up and does **not**
document formal LTS-to-LTS upgrade testing as a gate.

## What is actually on the machine

Read from the host on 2026-08-22. **Three of these contradict the repo's own documentation**, which
is why the check was worth doing.

**The CUDA repo was never removed.** `docs/media-01-nvidia-driver.md` records the CUDA stack as
"purged by hand" in March 2026. The packages were; the source was not:

    /etc/apt/sources.list.d/cuda-ubuntu2404-x86_64.list
    deb [signed-by=…/cuda-archive-keyring.gpg] \
        https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ /

`apt-cache policy` shows it live at **priority 600**, above the archive's 500. Canonical still wins
the driver today only because this repo does not carry `nvidia-driver-595-server-open` (installed
from `noble-updates/multiverse`) — but a 600-priority third-party driver source is exactly the
"don't mix sources" hazard the nvidia doc warns about, sitting armed. It is pinned to `ubuntu2404`
and has no resolute path. **Remove it before upgrading.**

**The NVIDIA toolkit source was never deduped**, despite the nvidia doc saying it was.
**UPDATE 2026-08-23: it is now** — one deb822 source, legacy suite removed. As found on 2026-08-22
the host had
both suites plus two commented experimental lines — NVIDIA's stock published file verbatim, i.e.
written by hand from NVIDIA's install docs, not by the role:

    deb … libnvidia-container/stable/deb/$(ARCH) /
    deb … libnvidia-container/stable/ubuntu18.04/$(ARCH) /

**There is one inline-PGP-key source**, and it is not one Ansible manages.
**UPDATE 2026-08-23: removed** — the fish source is now deb822 with the key at a keyring path, and
no source on the host has an inline key. As found on 2026-08-22:

    /etc/apt/sources.list.d/fish-shell-ubuntu-release-4-noble.sources

That is the shape Launchpad bug #2150614 corrupts (below). It was written by `add-apt-repository`
via `fish_install`.

**Confirmed as hoped:** root is `/dev/sda1`, **ext4** — *not* ZFS-on-root, so the ZFS-on-root
upgrade failures (e.g. openzfs#17337, `10_linux_zfs` deadlocking `update-grub`) do not apply here.
Worst case is a pool that does not import, not a host that does not boot. ZFS userspace and module
are currently matched at `2.2.2-0ubuntu9.4`; pool `data` is `ONLINE`.

**The roles have not been applied here in their current state.**
**UPDATE 2026-08-23: partially addressed.** The apt-source roles have now been applied, but only
their `tasks/apt_repo.yaml` half — `docker.list` is still a legacy `.list`, so the point below
stands and the full untagged run is still the right pre-flight. `geerlingguy.docker` 8.0.0 uses
`deb822_repository` and explicitly deletes `/etc/apt/sources.list.d/docker.list` and
`/etc/apt/trusted.gpg.d/docker.asc` — both of which are still present. That is the same reason the
NVIDIA file is still hand-written. **The host's apt configuration is an older generation of this
repo than the repo now contains**, which is what makes a full playbook run the right pre-flight.

## Role review

<a id="role-review"></a>

media-01's transitive role set is larger than the playbook's list: `configure_server` →
`standard.yaml` also pulls in `geerlingguy.security`, `fish_install`, `configure_dotfiles`,
`beszel_agent`, `topgrade`, `oefenweb.locales`, `ubuntu_disable_ads`,
`prometheus.prometheus.node_exporter`, `textfile_collector_apt_updates`.

### ~~Confirmed breakage~~ FIXED 2026-08-23: `fish_install` called `apt-key`, which 26.04 does not ship

`roles/fish_install/tasks/install_ubuntu.yaml:2-5` runs

    apt-key --keyring /etc/apt/trusted.gpg del '59FD A1CE …'

with `changed_when: false` and **no `failed_when`**. apt goes **2.8.3 → 3.2.0**, and `apt-key` is
gone — extracting `apt_3.2.0_amd64.deb` shows the shipped binaries are `apt`, `apt-cache`,
`apt-cdrom`, `apt-config`, `apt-get`, `apt-mark`.

This is the worst-placed failure available: `fish_install` runs via `configure_server` on **every**
host, early — so it takes down the whole playbook, including the post-upgrade run that would restore
the third-party repos. It is a one-shot cleanup for a key moved out of the deprecated `trusted.gpg`
long ago, so deleting the task is likely the right fix. **Do this before upgrading.**

### Legacy `.list` still works

apt 3.2.0 still ships `/etc/apt/sources.list.d/` and `sources.list.5`. `nvidia_container_toolkit`,
Docker and the `apt_repository`-based roles keep functioning. Migration is tidiness, not a blocker.

### There is now a proper module for this — and it is now in use

**UPDATE 2026-08-23:** all nine apt-source roles were migrated onto `deb822_repository` with
`signed_by` as a keyring path, exactly as recommended below, and are covered by a container test
harness at `ansible/tests/apt-sources/`.

`ansible.builtin.deb822_repository` — **`version_added: 2.15`**, present in the installed
ansible-core 2.20.4. It did not exist when the manual apt tasks in this repo were written. Takes
`name`/`types`/`uris`/`suites`/`components`/`signed_by`/`enabled`/`state`.

The candidates identified on 2026-08-22 were the hand-rolled `copy:`-a-`.list` in
`nvidia_container_toolkit`, the `apt_repository` call in `apt_add_launchpad_ppa`, and the `< 26`
branch of `mise`. **All three were migrated on 2026-08-23**, along with six more roles the original
scan missed. This list is kept as the record of where the work started, not as an open list.

**Use `signed_by` as an absolute keyring path, not an inline key block.** The module accepts inline
armored keys, and that is precisely the shape bug #2150614 truncates during `do-release-upgrade` —
its most convenient option is the one to avoid on a host that gets release-upgraded.
`geerlingguy.docker` 8.0.0 is the model: it passes `signed_by` a URL, so the key lands as a file.

### Already migrated

**UPDATE 2026-08-23: this section described a half-way state that no longer exists.** As found on
2026-08-22, `mise` branched on `distribution_major_version >= 26` and shelled out to
`add-apt-repository` there, and `fish_install`'s Debian path templated a deb822 `.sources` by hand.

Both are gone. Each role now has a single `tasks/apt_repo.yaml` using `deb822_repository`, and
`fish_install`'s per-distro install files and its `shells_fish_release_4.sources.j2` template were
deleted. `mise`'s PPA branch survives only as a call to `apt_add_launchpad_ppa`, gated on
`>= 26` **and** `x86_64` — Launchpad publishes no arm64 build. No task file in any role invokes
`add-apt-repository` or `apt_key` any more.

### Watch, not blockers

- `ubuntu_disable_ads` runs `pro config show apt_news` with no `failed_when`, and its `which pro`
  guard is commented out.
- `textfile_collector_apt_updates` greps `apt list --upgradable` and ships an `apt_info.py` using
  python3-apt. apt 3.x changed CLI output; re-check after the upgrade.
- `geerlingguy.docker` is **unpinned** in `requirements.yaml`.

### Coverage

A targeted scan for release-pinned strings (`noble`, `jammy`, `24.04`, `ubuntu2404`, `python3.N`,
`distribution_release`) across `zfs_conf`, `power_saving`, `beszel_agent`, `topgrade`,
`configure_dotfiles`, `textfile_collector` and every `docker_compose_*` role came back empty.
`geerlingguy.security` 3.0.1 is clean. **Not read:** `oefenweb.locales`, the Prometheus collection.

## Known upgrade bugs that apply here

**Bug #2150614 — `do-release-upgrade` truncates inline `Signed-By` keys.** Reported 2026-04-29,
Triaged Medium, **still unfixed** as of 2026-08-22. When rewriting `.sources` to add `Enabled: no`,
the parser mishandles multi-line inline PGP keys whose blank lines use space-only continuation.
Applies to the fish PPA source on this host. Nothing Ansible writes is affected.

**Bug #2156727 — TTY after upgrade.** Affects 24.04.4→26.04, but is Budgie-specific (LightDM→SDDM on
minimal installs). Does not apply to a headless server. Milestoned for 26.04.1.

**Third-party repos are the dominant failure mode.** Ubuntu Discourse's best-practice guide calls
disabling them the "#1 cause of broken upgrades" and "100% preventable". The upgrader disables them
by design. Here that is largely handled: Docker and the NVIDIA toolkit are playbook-managed, so
restoring them is a play run.

**Field evidence is thin, and that is not reassurance.** Nearly every published 26.04 upgrade report
is from 25.10 or a forced `-d`, because the 24.04 gate has kept that population out. This host will
be an early data point. (Ask Ubuntu could not be searched — it blocks automated access.)

## Rollback

**Disk-level, not package-level — and that is deliberate.** August's rollback used a whole-disk
restore rather than purging the HWE stack because the same playbook run had upgraded a batch of
other packages, and an in-place downgrade cannot guarantee returning to the original package set.

A release upgrade rewrites essentially every package, so "undo it with apt" is not available at any
scale. The rollback is the PBS snapshot, restored per
`plans/media-01-restore-scsi0-from-backup.md` — proven on 2026-08-10, ~18 minutes, root disk only,
ZFS pool untouched.

Three things keep it viable:

- **A fresh PBS snapshot immediately before starting.**
- **A file-level copy of `/etc/apt/` before that** — step 1. Restoring a whole disk to undo one
  mangled `.sources` file is a poor trade, and third-party sources are exactly what the upgrader
  rewrites. The apt-source migration took its own pre-deploy captures of this host on 2026-08-23 and
  they were **deleted on the same day, deliberately**: a rollback inherited from unrelated work is
  only correct for as long as nobody touches apt in between. Take a fresh one at the time it is
  needed.
- **Do not run `zpool upgrade` afterwards.** Importing an older pool under ZFS 2.4 is fine and is
  all that is needed. *Upgrading* it is one-way and enables features 24.04's 2.2.2 cannot read —
  which silently destroys the rollback, because the restore reverts only the root disk (`scsi0`) and
  leaves the pool on `scsi1` alone. ZFS will invite this: `zpool status` prints a notice that the
  pool can be upgraded. **Decline it.** This is the one irreversible step available during the
  upgrade.

## Related

- `docs/media-01-nvidia-driver.md` — driver sourcing (Canonical archive vs NVIDIA CUDA repo) and the
  `nvidia_driver` role design. Adopting that role on 24.04 first is recommended: it is a package-set
  change (`-driver-` → `-headless-`) and should not share a window with a release upgrade.
- `plans/media-01-restore-scsi0-from-backup.md` — the rollback runbook.

## Sources

Queries, so the claims can be re-derived rather than trusted:

| Claim | How to re-check |
| --- | --- |
| 26.04.1 date | `documentation.ubuntu.com/release-notes/26.04/schedule/` |
| kernel equality | Launchpad `getPublishedSources` for `linux-hwe-7.0` in noble vs `linux` in resolute |
| ZFS versions | same, `zfs-linux` in noble vs resolute |
| apt 3.2.0 drops `apt-key` | extract `apt_3.2.0_amd64.deb`, list `./usr/bin/` |
| Docker publishes resolute | `download.docker.com/linux/ubuntu/dists/` |
| driver branches in resolute | `apt-cache search '^nvidia-headless-[0-9]\+-server-open$'` on the host after upgrade |
| `deb822_repository` availability | `ansible-doc ansible.builtin.deb822_repository` |
| bugs #2150614, #2156727 | `bugs.launchpad.net/ubuntu/+source/ubuntu-release-upgrader` |

Two facts here come from the operator rather than from any repo or public source, and are recorded
because nothing else captures them: the HWE symptom being a ZFS module/userspace split, and the
reason the August remedy was a whole-disk restore.
