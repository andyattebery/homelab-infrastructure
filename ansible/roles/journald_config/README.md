# journald_config

Writes a `systemd-journald` drop-in from a dict of settings, and restarts journald when it
changes.

## Status: Production

## Why it exists

One host in this fleet cuts its own power without warning — a spurious `CPU_THERMTRIP`, three
times between June and September 2026; its file under `hardware/` has the detail. journald's
default `SyncIntervalSec` is five minutes, so a power cut takes the last few minutes of kernel
log with it. In the September event the journal's final entry was three minutes before the trip,
which is exactly the window a crash investigation wants.

The conclusion that time did not depend on the journal, because the BMC event log and the
firmware boot-error record are both non-volatile and both said what was needed. But that was
luck about the failure mode: a panic, a hang or an out-of-memory cascade would leave its evidence
only in the journal.

## Inputs

### `journald_config_settings` (default: `{}`)

Dict of `[Journal]` settings. Empty means the role does nothing and removes any drop-in it wrote
before, so the change is reversible by emptying the dict rather than by editing the host.

```yaml
journald_config_settings:
  SyncIntervalSec: "30s"
```

Keys are written verbatim. The role does not validate them, and **journald silently ignores a key
it does not recognise** — so a typo looks exactly like success. Verify on the host with
`systemd-analyze cat-config systemd/journald.conf`, which prints the merged configuration and
shows which file each value came from.

### `journald_config_dropin_dir` (default `/etc/systemd/journald.conf.d`), `journald_config_dropin_name` (default `10-ansible.conf`)

Where the drop-in goes. Overridable mainly so a future test can point them at a scratch
directory.

## Cost of a shorter sync interval

journald writes to disk every `SyncIntervalSec`, and immediately for messages at `CRIT` and
above regardless. Shortening it increases small writes to the journal's storage. On a host with
an Optane or SSD root that is not measurable; on slow or write-limited storage it would be worth
thinking about before setting it low.

## Playbook

```yaml
- name: Configure journald
  when: journald_config_settings | default({}) | length > 0
  ansible.builtin.import_role:
    name: journald_config
```

The `| default({}) | length > 0` form is deliberate. An imported role's defaults are visible to
the task-level `when`, so `when: journald_config_settings is defined` would never skip.

## Tests

None. The role writes one static file from a dict and restarts a service; a fixture test
asserting that a template renders its input would pass without being able to fail for a reason
that matters. The check that can fail for the right reason is on the host, and it is the one in
the Inputs section above: `systemd-analyze cat-config systemd/journald.conf`.
