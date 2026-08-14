# textfile_collector_asrock_ipmi_cert

Exports the expiry of the certificate an ASRock Rack BMC is **actually serving**, as node_exporter
textfile metrics. Wraps `textfile_collector`.

## Status: Production

## Required inputs

| Name | Notes |
| --- | --- |
| `textfile_collector_asrock_ipmi_cert_host` | Hostname to probe. The role asserts it is set; an unreachable or wrong name yields `probe_success 0` rather than a failed play, which is the point — a broken probe must alert, not stop the deploy. |

## Optional inputs

| Name | Default | Notes |
| --- | --- | --- |
| `textfile_collector_asrock_ipmi_cert_interval_seconds` | `3600` | Timer period. Longer than an hour delays detection; a certificate problem is never urgent to the minute. |
| `textfile_collector_asrock_ipmi_cert_port` | `443` | |
| `textfile_collector_asrock_ipmi_cert_timeout_seconds` | `15` | Caps `openssl s_client`. Too short on a slow BMC produces false `probe_success 0`. |
| `textfile_collector_asrock_ipmi_cert_attempts` | `3` | Probes before reporting failure. Raising it risks exceeding systemd's default `TimeoutStartSec` of 90 s — worst case is `attempts × timeout + (attempts - 1) × retry_delay`. |
| `textfile_collector_asrock_ipmi_cert_retry_delay_seconds` | `5` | Gap between probes. |

## Example

From the calling playbook:

```yaml
- role: textfile_collector_asrock_ipmi_cert
  vars:
    textfile_collector_asrock_ipmi_cert_host: "ipmi.<bmc_host>.{{ domain_name }}"
```

## Metrics

```
asrock_ipmi_cert_probe_success{host="…"}      1 or 0
asrock_ipmi_cert_not_after_seconds{host="…"}  epoch seconds, only when the probe succeeded
```

Alert on both, as the host's Grafana alerting rules does:

```
asrock_ipmi_cert_probe_success == 0
  or (asrock_ipmi_cert_not_after_seconds - time()) < 14 * 86400
```

## Why this exists separately from the updater

It measures the outcome, not the mechanism. `docker_compose_certbot_asrock_ipmi` is what pushes
certificates to the BMC; this role is deliberately independent of it, so the metric stays truthful
if that container is stopped, broken, or was never deployed. A monitor that asks the fixer whether
it succeeded cannot report that the fixer is gone.

## Traps

- **`probe_success` is emitted on both branches** so the series never vanishes, and a `0` is a
  probe that genuinely failed rather than a collector that stopped running. Those are different
  faults and the alert distinguishes them: the `== 0` arm catches the first, an `absent()` arm
  catches the second.
- **Do not alert on this metric with `noDataState: Alerting`.** The rule's arms are filtering
  comparisons, so a *healthy* BMC returns no samples too — `NoData` therefore cannot tell healthy
  from missing, and setting it to `Alerting` makes the rule fire continuously while everything is
  fine. That shipped once and had to be undone. `absent()` is the correct tool for a missing series.
- **A probe that lands during a certificate rotation fails, legitimately.** Installing a
  certificate soft-resets the BMC web service. This was observed on the first deploy: the collector
  ran in the same minute as the upload and wrote `probe_success 0` on a BMC that was fine seconds
  later. Two things guard it — the retry loop here, and a Grafana `for:` longer than this role's
  interval, so a single bad sample can never fire on its own. Shortening `for:` below the interval
  re-opens it, because one sample persists for a whole interval.
- **A stale `.prom` still alerts.** node_exporter serves the file indefinitely if the timer dies, so
  `probe_success` would stay `1`. `time()` keeps advancing, though, so a frozen
  `not_after_seconds` trips the 14-day threshold on its own. `node_textfile_mtime_seconds` is the
  direct signal if you want it.
- **`date -u -d` is GNU-specific.** It parses openssl's `Jul  8 12:31:40 2026 GMT`. This will not
  work as written on a BSD or macOS host.
- **The metric does not check that the served certificate is the *right* one**, only when it
  expires. A BMC serving a valid self-signed certificate looks healthy here; the updater's serial
  comparison is what catches that.
