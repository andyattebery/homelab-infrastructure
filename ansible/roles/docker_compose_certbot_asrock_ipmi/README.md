# docker_compose_certbot_asrock_ipmi

Keeps the certificate an ASRock Rack BMC serves in sync with a Let's Encrypt certificate obtained
via `docker_compose_certbot_dns_cloudflare`. Deploys no container of its own — it drops a reconciler
script and its config into the certbot volume, then includes that role and hands it a post-run
command.

## Status: Production

## Required inputs

| Name | Notes |
| --- | --- |
| `certbot_asrock_ipmi_cert_updater_domain_name` | The BMC's hostname, and the certificate's domain. Also selects the certbot renewal config this role edits. Wrong value means a certificate for the wrong name and a reconciler that can never converge. |
| `certbot_asrock_ipmi_cert_updater_username` | BMC account with rights to install a certificate. Wrong value fails at login with the HTTP status in the log — no upload is attempted. |
| `certbot_asrock_ipmi_cert_updater_password` | As above. Written to an ini at mode `0600`. |

Also required, from the calling play: `docker_compose_dst_data_directory_path`, plus the inputs
`docker_compose_certbot_dns_cloudflare` needs (`cloudflare_api_token`, `certbot_email`).

## Optional inputs

| Name | Default | Notes |
| --- | --- | --- |
| `certbot_asrock_ipmi_container_name` | `certbot-asrock-ipmi` | Container name for the certbot stack. Change it and the old container is left running under the old name until removed by hand. |
| `certbot_asrock_ipmi_cert_updater_directory_path` | `{{ docker_compose_dst_data_directory_path }}/certbot/asrock-ipmi-cert-updater` | Host path for the script and ini. Must stay inside the certbot volume or the container cannot see them. |
| `certbot_asrock_ipmi_cert_updater_container_directory_path` | `/certbot/asrock-ipmi-cert-updater` | The same directory as the container sees it. |
| `certbot_asrock_ipmi_cert_updater_renewal_config_path` | derived | Certbot's `config/renewal/<domain_name>.conf`. The role strips a legacy `renew_hook` line from it. |

## Example

From the calling playbook:

```yaml
- role: docker_compose_certbot_asrock_ipmi
  vars:
    certbot_asrock_ipmi_cert_updater_domain_name: "ipmi.<bmc_host>.{{ domain_name }}"
    certbot_asrock_ipmi_cert_updater_username: "{{ <bmc_host>_ipmi_username }}"
    certbot_asrock_ipmi_cert_updater_password: "{{ <bmc_host>_ipmi_password }}"
```

## What the reconciler does

`files/asrock_ipmi_cert_updater.py` runs once per certbot cycle, roughly every 24 hours:

1. Reads the leaf serial from `fullchain.pem` on disk.
2. Reads the serial the BMC is **actually serving**, over TLS. Not via the BMC's own JSON API — the
   handshake is what clients see, and it stays truthful when the API is unhappy.
3. Equal → exits 0 having done nothing.
4. Different → logs in, uploads, logs straight back out, then re-probes for up to 180 seconds until
   the served serial matches. Up to three attempts.

Exit codes: `0` in sync, `1` uploaded but never converged, `2` the BMC could not be probed.

`2` deliberately does **not** upload. Installing a certificate soft-resets the BMC web service, so a
permanently broken probe combined with a blind upload would bounce the BMC every night forever. The
`textfile_collector_asrock_ipmi_cert` role covers the unreachable case with a Prometheus metric.

## Why this replaced a `--deploy-hook`

The BMC served an expired certificate from 2026-07-08 to the deploy of this version. Certbot renewed
on schedule throughout; the push failed. Three separate defects were needed to produce that:

- `--deploy-hook` fires only on renewal. A 10-second timeout on 2026-08-08 was never retried,
  because the certificate then had 89 days left and every daily run skipped the lineage.
- The upstream script's error handling never worked. Its four network calls caught the **builtin**
  `ConnectionError`; `requests` raises `requests.exceptions.ConnectionError`, which is not a
  subclass of it. Timeouts became uncaught tracebacks rather than a handled failure.
- Nothing compared the BMC against disk. The upstream script read the BMC's serial and printed it
  without ever using it, so there was no idempotency guard, no verification, and no detector.

`tests/test_asrock_ipmi_cert_updater.py` has a guard for each. Run them with
`cd ansible && .venv/bin/pytest roles/docker_compose_certbot_asrock_ipmi/tests/ -q`.

## Traps

- **The script is vendored, not downloaded.** It derives from `khung/letsencrypt-scripts@1b1cef96`.
  The ASRock endpoints, multipart field names and the two-second logout window come from there —
  someone reverse engineered a BMC to find them, and that is the part worth keeping. The control
  flow does not. A BMC firmware change to `/api/session` or the field names is ours to fix, and
  that repo is the only other place to look.
- **`renew_hook` persists in certbot's state.** This role strips it from
  `config/renewal/<domain_name>.conf`, because certbot records a `--deploy-hook` there and it survives
  removal of the flag.
- **The ini holds the IPMI password in plaintext** at mode `0600`. The container runs as root, so it
  can still read it. The script never logs the password or the session's CSRF token.
- **Renaming the container leaves the old one behind.** Compose recreates under the new name; the
  container running under the previous name has to be removed by hand if compose does not adopt it.
- **`verify=False` on every BMC request.** Unavoidable — the certificate being replaced is usually
  the expired one — so the upload trusts the management network.
