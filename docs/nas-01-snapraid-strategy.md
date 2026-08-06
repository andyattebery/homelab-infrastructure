# SnapRAID install + btrfs strategy on nas-01

## Context

Goal: move off `ironicbadger.snapraid` (docker-build-from-source) on nas-01, get to a modern install path for both `snapraid` and the new `snapraid-daemon`, and clean up the snapraid-btrfs wrapper/runner stack.

**Premise changed mid-plan.** Initial direction was: upgrade to snapraid v14.4 via `github_release_install`, fork snapraid-btrfs and snapraid-btrfs-runner to patch v14 compatibility, install the daemon, manage the integration friction. After reading [snapraid#41](https://github.com/amadvance/snapraid/issues/41) and the design preview in `doc/snapraid.txt` at master, that whole strategy is **about to be obsoleted by upstream**:

- SnapRAID master (post-v14.4, 37 commits ahead, active as of today 2026-05-11) now contains **native btrfs snapshot support** that does what `snapraid-btrfs` has been doing externally. Same `stable`/`pending` semantics, automatic and transparent, no external scripts.
- Snapshots live at `.snapraid/` inside each data subvolume root (not snapper-managed `.snapshots/`).
- New content-file format stores metadata for files modified/deleted during sync, so `fix` can recover even when a sync was interrupted — handles the corner case that snapraid-btrfs explicitly doesn't.
- UUID detection rewritten using btrfs IOCTLs (the headline of issue #41) — fixes file-move detection across subvolumes.
- Also lands: Bcachefs and ZFS snapshot support, AVX512GFNI, configurable external-tool paths.
- No tagged release yet, but the work appears feature-complete. Given the v14.1→v14.4 cadence (3 weeks), a v14.5 / v15.0 release looks imminent.

The right move is **wait** rather than do the fork work just to throw it away.

## Recommendation

Three-phase rollout. Each phase is independently revertible.

### Phase 1 — Now: stop bleeding, do nothing risky

- Leave snapraid v12.2 installed.
- Leave the snapraid-btrfs wrapper + runner stack as-is on the host. It works, it's stable, it doesn't need a v14 upgrade.
- **Don't** flip `# #`-commented blocks back on in [playbook-nas-01.yaml](ansible/playbook-nas-01.yaml). Re-running with `ironicbadger.snapraid` is currently a no-op (dpkg-query check sees `snapraid` installed and skips the build), but if anything ever invalidates that check — package rename, fresh provision, manual `apt remove` — you silently get latest (v14.4 today), which breaks the runner's diff parser (no `relocate` handling) and the wrapper's command dispatch (no `read`/`smart`/`probe`/`locate`).
- The lowest-risk way to neutralize that surprise: leave the install task commented exactly as it is now.

### Phase 2 — When upstream cuts a release with native btrfs snapshot support

When `releases/latest` for `amadvance/snapraid` jumps past v14.4 with the snapshot feature in the changelog (watch for "Add Btrfs snapshot support" in release notes, or check the doc has the `8 SNAPSHOTS` section), do the install switchover. By then `amadvance/snapraid-daemon` will also have caught up.

**Install layer** — swap `ironicbadger.snapraid` for two calls to the existing [`github_release_install`](ansible/roles/github_release_install/) role. Both projects publish signed amd64 .debs on every release (verified by extracting v14.4 and daemon v1.9):

```yaml
- name: Install snapraid CLI
  ansible.builtin.include_role:
    name: github_release_install
  vars:
    github_release_install_repo: amadvance/snapraid
    github_release_install_asset_patterns: { x86_64: "_amd64.deb" }
    github_release_install_archive_type: deb
    github_release_install_binary_path: /usr/bin/snapraid
    github_release_install_version_command: "/usr/bin/snapraid --version"
    github_release_install_version_regex: 'v([0-9]+\.[0-9]+)'

- name: Install snapraid-daemon
  ansible.builtin.include_role:
    name: github_release_install
  vars:
    github_release_install_repo: amadvance/snapraid-daemon
    github_release_install_asset_patterns: { x86_64: "_amd64.deb" }
    github_release_install_archive_type: deb
    github_release_install_binary_path: /usr/bin/snapraidd
    github_release_install_version_command: "/usr/bin/snapraidd --version"
    github_release_install_version_regex: 'v([0-9]+\.[0-9]+)'
```

Verified caller-side gotchas:
- Debs install to **`/usr/bin/`**, not `/usr/local/bin/` where `ironicbadger.snapraid` puts things.
- Both projects use two-component versions (`14.4`, `1.9`) — the role's default three-component regex doesn't match, hence the override.
- Daemon deb also installs `/etc/snapraidd.conf` (default config) and `/usr/lib/systemd/system/snapraidd.service`. Lay down a templated config after this task; SIGHUP via handler.

**Migration to native snapshots** — in [snapraid.conf](ansible/files/nas-01/snapraid.conf), add the `snapshot` directive (exact syntax TBD pending release; per the doc preview it'll be a single config option). Leave everything else unchanged — data lines, parity lines, content lines, excludes. The on-disk parity format isn't changing; the content file format extends with `dealloc` metadata, which is backwards-compatible at the parser level.

The existing data layout (`/mnt/data/dataN` mounted from `subvol=/data` of each btrfs filesystem) is exactly what native snapshots expect. No fstab changes, no remount, no resync. SnapRAID will create `/mnt/data/dataN/.snapraid/{stable,pending}/` on the first `sync` after enabling the option.

**Decommission the wrapper stack** in the same change:
- Remove the role include for `snapraid_btrfs_runner_install` from the play.
- Disable the runner's systemd timer (`systemctl disable --now snapraid-btrfs-runner.timer`).
- Optionally: also delete the `snapraid_btrfs_install` and `snapper_install` roles from the play. The `snapraid-btrfs` binary in `/usr/local/bin/` becomes dead code — safe to leave installed, doesn't run unless invoked.
- Snapper-created `.snapshots/` directories on each data disk are now orthogonal to SnapRAID. Decide separately whether to keep snapper as a generic "oops recovery" tool (configurable timer-snapshots) or remove it.

**Remove from [requirements.yaml](ansible/requirements.yaml)**: `- name: ironicbadger.snapraid`.

**The daemon** is purpose-built to work with native snapshots — it's amadvance's other project, evolving in lockstep (e.g., daemon v1.6 needed snapraid v14.2's content-file mtime log tag). The wrapper/daemon compatibility problems analyzed earlier in this plan disappear because there's no wrapper anymore.

### Phase 3 — Disk add/replace ergonomics

The `_todo.taskpaper` notes the `snapraid_btrfs_add_data_disk` role is WIP and disk-adds are manual. After Phase 2, the disk-add procedure shrinks to:

1. wipefs + sgdisk-partition
2. mkfs.btrfs `/dev/disk/by-id/...-part1`
3. Mount fs root, `btrfs subvolume create data` (and `content` if it's a content-host disk), unmount
4. Append fstab line, `mount -a`
5. Append `data dN /mnt/data/dataN` to snapraid.conf
6. `snapraid sync`

No more snapper config setup, no `ALLOW_USERS` coordination, no per-disk wrapper bookkeeping. **The `snapraid_btrfs_add_data_disk` role becomes a plain disk-add role** — finishable as a ~30-line task while doing the next disk-add manually. Worth completing then.

## Why this plan and not "do the v14.4-with-forks work now"

Concretely, the fork work I previously sketched would be:
- Fork `automorphism88/snapraid-btrfs`, add ~5 lines of passthrough for `read|smart|probe|status|up|dup|locate`. Maintain it.
- Fork `fmoledina/snapraid-btrfs-runner`, patch ~5 lines for `relocate` handling. Vendor it into `files/nas-01/`. Maintain it.
- Update [snapraid_btrfs_install/tasks/main.yaml](ansible/roles/snapraid_btrfs_install/tasks/main.yaml) to point at the fork.
- Update [snapraid_btrfs_runner_install/tasks/main.yaml](ansible/roles/snapraid_btrfs_runner_install/tasks/main.yaml) to `copy` the vendored runner.
- Update [snapraid-btrfs-runner.conf.j2](ansible/files/nas-01/snapraid-btrfs-runner.conf.j2) binary path from `/usr/local/bin/snapraid` to `/usr/bin/snapraid`.

All of that becomes dead code when native snapshots ship. The forks aren't being maintained by anyone else; carrying them is a permanent low-grade tax even if v14.5 takes longer than expected. The v12.2-in-place state has none of those costs and has worked for 2+ years.

The only scenario where doing the fork work now makes sense is if you specifically need a feature from v14 (`.snapraidignore`, `**` globbing, `locate`, the daemon's UI) and you need it within weeks rather than waiting on the release.

## Watchpoints — how to know Phase 2 is ready

In approximate signal strength:

1. New release on `amadvance/snapraid` (any version > 14.4) with "snapshot" or "Btrfs" in the release notes. `gh release view --repo amadvance/snapraid` or watch `gh api repos/amadvance/snapraid/releases/latest`.
2. The `8 SNAPSHOTS` section in `doc/snapraid.txt` stops being labeled "preview" in the issue thread.
3. `amadvance/snapraid-daemon` release notes start referencing the new snapshot lifecycle (`pending`/`stable` directories).
4. Independent confirmation: a third-party blog, PMS wiki update, or a thread on r/DataHoarder noting the native snapshot feature is live.

Any of (1) is sufficient to start Phase 2 planning. Wait for (1)+(3) before doing the work, since you want the daemon's understanding of the new content file format to be live too.

## Files touched in Phase 2 (preview)

| File | Change |
|---|---|
| [ansible/playbook-nas-01.yaml](ansible/playbook-nas-01.yaml) | Replace the (currently commented) snapraid install task block with two `github_release_install` calls + a daemon config copy task. Remove `snapraid_btrfs_install` and `snapraid_btrfs_runner_install` includes. |
| [ansible/files/nas-01/snapraid.conf](ansible/files/nas-01/snapraid.conf) | Add the `snapshot` directive. Everything else stays. |
| [ansible/files/nas-01/snapraidd.conf.j2](ansible/files/nas-01/) (new) | Template the daemon config (binding, ACL, schedule, notifications). |
| [ansible/requirements.yaml](ansible/requirements.yaml) | Remove `ironicbadger.snapraid`. |
| [ansible/files/nas-01/snapraid-btrfs-runner.conf.j2](ansible/files/nas-01/snapraid-btrfs-runner.conf.j2) | Delete. |
| [ansible/files/nas-01/snapper_snapraid_data_template](ansible/files/nas-01/snapper_snapraid_data_template) | Delete (or keep if snapper stays as a generic timer-snapshots tool). |
| [ansible/roles/snapraid_btrfs_install/](ansible/roles/snapraid_btrfs_install/) | Remove role (or leave dormant — unused but harmless). |
| [ansible/roles/snapraid_btrfs_runner_install/](ansible/roles/snapraid_btrfs_runner_install/) | Remove role. |
| [ansible/roles/snapraid_btrfs_add_data_disk/](ansible/roles/snapraid_btrfs_add_data_disk/) | Rename to `snapraid_add_data_disk`. Finish the WIP implementation as a plain-snapraid disk-add (no snapper coordination). |

## Open questions (worth checking when v14.5 lands, not now)

- Does the `snapshot` directive go on the global level or per-`data` line? Doc preview doesn't specify; release notes will.
- Backwards-compatibility on content file: opening a v14.5+ content file with v12.2 binary (in case of rollback). Probably one-way migration, worth confirming.
- Does the daemon require a corresponding minimum snapraid version like v14.4 → daemon v1.8? Will likely be called out.
- Behavior when `.snapraid/` already exists with stale state (e.g. you disable then re-enable the option). Probably fine; worth checking.

## Files referenced

- [ansible/playbook-nas-01.yaml](ansible/playbook-nas-01.yaml)
- [ansible/requirements.yaml](ansible/requirements.yaml)
- [ansible/files/nas-01/snapraid.conf](ansible/files/nas-01/snapraid.conf)
- [ansible/roles/github_release_install/](ansible/roles/github_release_install/)
- Upstream: [snapraid#41](https://github.com/amadvance/snapraid/issues/41), [doc/snapraid.txt master § 8](https://github.com/amadvance/snapraid/blob/master/doc/snapraid.txt#L1505), [snapraid-daemon](https://github.com/amadvance/snapraid-daemon)
