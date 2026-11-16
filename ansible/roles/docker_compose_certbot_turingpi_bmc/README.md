# docker_compose_certbot_turingpi_bmc

Keeps the certificate a Turing Pi 2 BMC serves in sync with a Let's Encrypt certificate obtained via
`docker_compose_certbot_dns_cloudflare`. Deploys that role as a stack of its own, and adds a
reconciler that installs the certificate over ssh and restarts the BMC's daemon.

## Status: Production

## Required inputs

| Name | Notes |
| --- | --- |
| `certbot_turingpi_bmc_cert_updater_domain_name` | The BMC's hostname, and the certificate's domain. Wrong value means a certificate for the wrong name, and a reconciler that cannot reach the BMC or installs a certificate browsers reject. |
| `certbot_turingpi_bmc_cert_updater_username` | BMC account for ssh, which has to be able to replace files in `/etc/ssl/certs` and restart the daemon. On stock firmware that is `root`. Wrong value fails the backup step with the ssh error in the log; nothing changes on the BMC. |
| `certbot_turingpi_bmc_cert_updater_password` | As above. Written to an ini at mode `0600`. |

Also required, from the calling play: `docker_compose_dst_data_directory_path`, plus the inputs
`docker_compose_certbot_dns_cloudflare` needs (`cloudflare_api_token`, `certbot_email`).

## Optional inputs

| Name | Default | Notes |
| --- | --- | --- |
| `certbot_turingpi_bmc_container_name` | `certbot-turingpi-bmc` | Also the compose service, the compose file's suffix and the data directory, so it must not match any other certbot stack on the host. Change it on a deployed stack and a new one starts with no certificate while the old one keeps running. |
| `certbot_turingpi_bmc_cert_updater_directory_path` | `{{ docker_compose_dst_data_directory_path }}/<container_name>/turingpi-bmc-cert-updater` | Host path for the script, the ini and `known_hosts`. Must stay inside the stack's volume or the container cannot see them. |
| `certbot_turingpi_bmc_cert_updater_container_directory_path` | `/certbot/turingpi-bmc-cert-updater` | The same directory as the container sees it. |

## Example

From the calling playbook:

```yaml
- role: docker_compose_certbot_turingpi_bmc
  vars:
    certbot_turingpi_bmc_cert_updater_domain_name: "<bmc_host>.{{ domain_name }}"
    certbot_turingpi_bmc_cert_updater_username: "{{ turingpi_bmc_username }}"
    certbot_turingpi_bmc_cert_updater_password: "{{ turingpi_bmc_password }}"
```

## What the reconciler does

`files/turingpi_bmc_cert_updater.py` runs once per certbot cycle, roughly every 24 hours:

1. Reads the leaf serial from `fullchain.pem` on disk.
2. Reads the serial the BMC is **actually serving**, over TLS.
3. Equal: exits 0 having done nothing.
4. Different: checks locally that the key matches the certificate and that it is unexpired.
5. Over ssh, copies `/etc/ssl/certs/bmcd_{cert,key}.pem` to `.prev`, writes the new pair to `.new`,
   moves it into place and restarts `bmcd`.
6. Re-probes for up to 180 seconds until the served serial matches.
7. If it never does, restores `.prev`, restarts `bmcd` and probes for the old serial.

Exit codes: `0` in sync, `1` not installed or did not converge, `2` the BMC could not be probed.

`2` deliberately does not install. A broken probe combined with a blind install would restart `bmcd`
every night forever.

There is one install per cycle, not several, because each is a daemon restart. The next cycle retries.

## Why ssh and a daemon restart

Stock firmware has no certificate API and no endpoint that writes a file. `bmcd` reads its pair once,
in `load_tls_config`, before it starts serving. Turing's documented method is the same: copy the
files, restart the daemon. This role installs over the default filenames rather than the custom ones
in that how-to, so `config.yaml` is not edited. `S94bmcd` only generates a pair when a file is missing.

The pair is checked before anything is written because `load_tls_config` runs in `main`: a pair
`bmcd` cannot load stops the daemon, which takes the web UI, the API and `tpi` with it. `sshd` is a
separate process, which is what makes the rollback possible.

## Does a restart touch the nodes?

Not on a v2.5 board running stock firmware v2.1.0. It was measured with
`turingpi/scripts/bmcd-restart-check.sh`: a real restart, on board revision 2.5.1 with `bmcd` 2.3.4,
left all four nodes' `boot_id` and power state unchanged.

- **It rests on Turing's latch patch.** `0001-regulator-fixed-perserve-boot-state.patch` makes
  `gpio_latch_direction_output` leave the line alone, so `bmcd` claiming `nodeN-en` at start does not
  drive it. v2.0.5 predates that patch.
- **A v2.4 board has no latch.** There, `bmcd` starting does drive the line. Do not use this role on
  one without re-running that script.
- **A stale `bmcd.bin` would still change node power.** At start `bmcd` re-applies its saved state, so
  a saved "off" powers off a running node. This is upstream `bmcd` issue #90. It needs a failed flush
  or a corrupt file; `activate_slot` is the only writer.

## Traps

- **Leaf only.** `bmcd` loads the first certificate in the file and sends no intermediates.
  `openssl s_client` reports verify code 21 against it, and clients that verify the same way fail.
  macOS `curl` accepts it, because the platform fetches the missing intermediate.
- **The name, not the IP.** The certificate covers the hostname. `tpi` by IP is unaffected: 1.0.7
  accepts any certificate.
- **Each install restarts `bmcd`.** That drops the cached `tpi` login, and **kills a flash in
  progress**. Installs follow a renewal, about every 60 days, so the window is small, and it is not
  guarded.
- **A persistent failure restarts `bmcd` up to twice a night** until someone reads the log. Monitoring
  sees the result, not the failure: Prometheus's `bmc-cert` job probes what the BMC serves, and
  Grafana's `bmc-cert-expiring` rule fires within 14 days of the served certificate's expiry, or after
  2 hours of failed probes.
- **`apk` runs every cycle.** The certbot image has no ssh client. A failed `apk add` skips the updater
  for that cycle.
- **Hosts share one compose project.** See `docker_compose_certbot_dns_cloudflare` on why the stack
  needs a unique service name and no top-level `name:`.
- **The ini holds the BMC password in plaintext** at mode `0600`. The container runs as root, so it can
  still read it. The script passes it to `sshpass` in the environment, never in argv, and never logs
  it or the private key.
- **`StrictHostKeyChecking=accept-new`.** The first connection trusts whatever answers. A changed host
  key then fails visibly: delete `known_hosts` in the updater directory if the change is expected.
- **Rollback data stays on the BMC.** The `.prev` pair remains until the next install replaces it. To
  go back to a self-signed pair, delete both `bmcd_*.pem` files and restart `bmcd`.
