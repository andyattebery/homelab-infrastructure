# media-01 — upgrading to Ubuntu 26.04

> **Research, written 2026-08-22. Nothing here has been executed.**
>
> This file fills the reference `plans/media-01-restore-scsi0-from-backup.md` left dangling: the
> 26.04 upgrade was deliberately deferred to "on or after 27 August", and that runbook noted the
> follow-up "needs writing up before it is attempted".
>
> Every date below is a fact with a shelf life. 26.04.1's date has already moved once. Re-check
> anything load-bearing rather than trusting this document's age.

## Recommendation

**Upgrade in place, on or after 2026-08-27, after a preparation pass on 24.04.**

1. Fix `fish_install` (it will break every playbook run on 26.04 — see [Role review](#role-review)).
2. Run the full playbook on 24.04 to converge the host with the current roles.
3. Remove the apt sources Ansible does not own (CUDA repo; decide about the fish PPA).
4. Fresh PBS snapshot, then `do-release-upgrade`.
5. Afterwards: **decline `zpool upgrade`**, and re-run the playbook to restore third-party repos.

The upgrade is **the fix** for the ZFS problem that forced August's rollback, not a repeat of it.
That is the single most important thing in this document and the easiest to get backwards.

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

**The NVIDIA toolkit source was never deduped**, despite the nvidia doc saying it was. The host has
both suites plus two commented experimental lines — NVIDIA's stock published file verbatim, i.e.
written by hand from NVIDIA's install docs, not by the role:

    deb … libnvidia-container/stable/deb/$(ARCH) /
    deb … libnvidia-container/stable/ubuntu18.04/$(ARCH) /

**There is one inline-PGP-key source**, and it is not one Ansible manages:

    /etc/apt/sources.list.d/fish-shell-ubuntu-release-4-noble.sources

That is the shape Launchpad bug #2150614 corrupts (below). It was written by `add-apt-repository`
via `fish_install`.

**Confirmed as hoped:** root is `/dev/sda1`, **ext4** — *not* ZFS-on-root, so the ZFS-on-root
upgrade failures (e.g. openzfs#17337, `10_linux_zfs` deadlocking `update-grub`) do not apply here.
Worst case is a pool that does not import, not a host that does not boot. ZFS userspace and module
are currently matched at `2.2.2-0ubuntu9.4`; pool `data` is `ONLINE`.

**The roles have not been applied here in their current state.** `geerlingguy.docker` 8.0.0 uses
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

### Confirmed breakage: `fish_install` calls `apt-key`, which 26.04 does not ship

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

### There is now a proper module for this

`ansible.builtin.deb822_repository` — **`version_added: 2.15`**, present in the installed
ansible-core 2.20.4. It did not exist when the manual apt tasks in this repo were written. Takes
`name`/`types`/`uris`/`suites`/`components`/`signed_by`/`enabled`/`state`.

Candidates: the hand-rolled `copy:`-a-`.list` in `nvidia_container_toolkit`, the `apt_repository`
call in `apt_add_launchpad_ppa`, and the `< 26` branch of `mise`.

**Use `signed_by` as an absolute keyring path, not an inline key block.** The module accepts inline
armored keys, and that is precisely the shape bug #2150614 truncates during `do-release-upgrade` —
its most convenient option is the one to avoid on a host that gets release-upgraded.
`geerlingguy.docker` 8.0.0 is the model: it passes `signed_by` a URL, so the key lands as a file.

### Already migrated

`mise` branches on `distribution_major_version >= 26` and uses `add-apt-repository` there;
`fish_install`'s Debian path templates a deb822 `.sources`.

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

Two things keep it viable:

- **A fresh PBS snapshot immediately before starting.**
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
