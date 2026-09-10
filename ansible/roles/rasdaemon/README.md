# rasdaemon

Installs and configures `rasdaemon` to:

1. Soft-offline pages that accumulate too many corrected memory errors (threshold + cycle configurable, defaults to mcelog's 10 errors / 24h convention).
2. On every uncorrectable memory error (UE), write a rich single-line entry to journald via the `rasdaemon-ue` tag at `kern.err` priority. Contents: DIMM label, mc/csrow/channel triple, physical address, syndrome, kernel version, boot ID, and rasdaemon's event message. Sufficient for triage when an alert points at the host.
3. Install board-specific DIMM-label databases under `/etc/ras/dimm_labels.d/` so `$LABEL` in the trigger env (and `ras-mc-ctl --error-count` output) reads as the silk-screen slot name (e.g. `DDR4_A1`) instead of `mc#0csrow#1channel#0`. `ras-mc-ctl.service` (shipped by the package, enabled by this role) re-registers labels on every boot.

## Status: Production

## Notification path (out of role scope)

This role intentionally has no notification logic. Notification is handled separately by **Grafana alerting on `node_edac_uncorrectable_errors_total > 0`** — a metric already exported by `node_exporter`'s built-in `edac` collector. When the alert fires, `journalctl -t rasdaemon-ue` on the host has the per-event detail for triage.

## Variables

### rasdaemon_page_ce_threshold (default: `10`)
### rasdaemon_page_ce_refresh_cycle (default: `"24h"`)

Page-level soft-offline trigger. After this many corrected errors land on the same 4 KiB page within the refresh cycle, rasdaemon soft-offlines that page. Defaults follow mcelog convention.

### rasdaemon_trigger_dir (default: `/etc/ras/triggers`)

Where the UE trigger script gets installed.

### rasdaemon_block_ipmitool_sel (default: `false`)

Stops rasdaemon writing an OEM record to the BMC's event log for every corrected PCIe AER
event. Off by default; turn it on only where that traffic is a problem.

Debian builds rasdaemon with `--enable-amp-ns-decode`, which makes `ras-aer-handler.c` run
`system("ipmitool raw 0x0a 0x44 …")` on **every** corrected PCIe event, writing an OEM record
carrying the segment, bus, device and function. There is no runtime switch: the `--ipmitool`
flag gates the OpenBMC unified-SEL path, a different `#ifdef`, not this one.

On a host with a link that produces corrected errors steadily this fills the SEL. The host this
was written for was seeing about 185 of these a day, which together with the BIOS's own
`PCI PERR` entry for the same event was 72% of a log that holds about 3,600 entries and wraps in
a week. That log is the only record of a crash that cuts the power, so losing it means losing the
evidence.

Related variables: `rasdaemon_ipmitool_path` (default `/usr/bin/ipmitool`) and
`rasdaemon_systemd_dropin_dir` (default `/etc/systemd/system/rasdaemon.service.d`).

#### Why this is not done with PATH

The obvious approach — give the service a `PATH` without `ipmitool` so the `system()` call fails
— **would silently disable uncorrectable-error alerting.** rasdaemon spawns the UE trigger with a
hand-built environment whose only inherited variable is `PATH` (documented at the top of
`templates/mc_ue_trigger.j2`), and that script needs `logger`, `hostname`, `uname` and `cat`. A
broken `PATH` breaks the trigger, and nothing would report it until a real UE arrived and nothing
happened.

So the role writes a drop-in with `InaccessiblePaths=-/usr/bin/ipmitool` instead, which makes one
binary unreachable for one service and leaves `PATH` intact. Clearing the flag removes the
drop-in.

#### Verifying it

```sh
systemctl show rasdaemon -p InaccessiblePaths          # names the binary
systemctl is-active rasdaemon                          # the sandbox did not break the daemon
sudo ras-mc-ctl --errors | tail -1                     # and it is still recording events
```

Then prove the UE trigger still works under the same sandbox. It has to be a transient
**service**, not a scope: `systemd.exec` settings including `InaccessiblePaths=` apply to
service, socket, mount and swap units only, and a scope's processes are started by the caller
rather than forked by systemd, so `--scope` cannot carry the property at all.

```sh
sudo systemd-run --wait --collect -p InaccessiblePaths=-/usr/bin/ipmitool \
  -E ADDRESS=0x0 -E SYNDROME=0x0 -E LABEL=TEST /etc/ras/triggers/mc_ue_trigger
journalctl -t rasdaemon-ue -n1
```

Finally, a day later, the BMC log should have gained no `OEM record` entries while the BIOS's own
`PCI PERR` entries kept coming — that shape is what proves rasdaemon stopped and firmware did not.

## What this role does *not* do

- Notifications — handled by Grafana on existing node_exporter EDAC metrics.
- Correctable error alerting — soft-offline keeps the noise floor down; per-CE alerts would be alarm fatigue.
- Row-level isolation — too coarse for typical single-cell drift.
- CPU isolation — different failure domain with workload impact.
- BMC-side PEF/SMTP — complementary, separate concern; also catches kernel panics this role can't.
- Persisting the offline list across reboots — rasdaemon doesn't auto-replay; if needed, persist via `memmap=` kernel cmdline.

## Reference

- mcelog bad page offlining: <http://www.mcelog.org/badpageofflining.html>
- Memory Errors at Facebook (DSN '15): <https://users.ece.cmu.edu/~omutlu/pub/memory-errors-at-facebook_dsn15.pdf>
- ROMED8-2T DIMM label source: <https://github.com/mchehab/rasdaemon/pull/232>
