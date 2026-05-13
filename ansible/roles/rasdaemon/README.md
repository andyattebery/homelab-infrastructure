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
