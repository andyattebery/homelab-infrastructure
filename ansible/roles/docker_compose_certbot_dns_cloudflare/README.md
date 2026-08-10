# docker_compose_certbot_dns_cloudflare

Issues and renews one Let's Encrypt certificate using the Cloudflare DNS-01 challenge, in a
long-lived container that re-checks every 24 hours. Certificates land in a shared volume for other
services on the host to read.

## Status: Production

## Required inputs

| Name | Notes |
| --- | --- |
| `docker_compose_certbot_dns_cloudflare_domain_name` | The certificate's single domain. Wrong value means a certificate for the wrong name, and Let's Encrypt rate limits apply to retries. |
| `cloudflare_api_token` | From `group_vars/all/vars.yaml`, backed by vault. Needs DNS edit rights on the zone; a token without them fails the challenge after the 30 s propagation wait. |
| `certbot_email` | From `group_vars/all/vars.yaml`. Used for expiry notices. |

## Optional inputs

| Name | Default | Notes |
| --- | --- | --- |
| `docker_compose_certbot_dns_cloudflare_container_name` | `certbot` | The **container** name, not the compose service name. Also what `service_name_to_restart` restarts, because `docker_compose/tasks/restart_container.yaml` runs `docker restart` with it. Give each stack a distinct value if a host ever runs more than one. |
| `certbot_post_run_command` | unset | A shell command run after every `certbot renew`, inside the container. Unset means the loop only renews. See "Why post-run and not `--deploy-hook`". |

## Example

From `roles/docker_compose_certbot_asrock_ipmi/tasks/main.yaml`:

```yaml
- name: Initial docker compose setup
  vars:
    docker_compose_certbot_dns_cloudflare_domain_name: "{{ certbot_asrock_ipmi_cert_updater_domain_name }}"
    docker_compose_certbot_dns_cloudflare_container_name: certbot-asrock-ipmi
    certbot_post_run_command: "python {{ certbot_asrock_ipmi_cert_updater_container_bin_path }} --config-file {{ certbot_asrock_ipmi_cert_updater_container_ini_path }}"
  ansible.builtin.include_role:
    name: docker_compose_certbot_dns_cloudflare
```

## Why post-run and not `--deploy-hook`

`--deploy-hook` fires only when a lineage is actually renewed. If the hook fails — the target is
down, slow, or briefly unreachable — certbot has already written the new certificate to disk, so
every subsequent daily run reports "Certificate not yet due for renewal" and the hook is never
retried. One transient failure then persists for a full renewal period.

This cost a live outage: the ASRock BMC served an expired certificate for a month after a single
10-second timeout on 2026-08-08, with 30 daily runs in between that each did nothing.

`certbot_post_run_command` runs on **every** cycle instead. The command is expected to be a
reconciler: cheap and silent when there is nothing to do, corrective when there is. The entrypoint
has no `set -e`, so a non-zero exit is ignored and the next cycle retries — that is deliberate.

## Where certificates land

`{{ docker_compose_dst_data_directory_path }}/certbot/config/live/<domain_name>/`, mounted in the
container at `/certbot/config/live/<domain_name>/`. Consumers read them from the host path or by sharing
the same volume — `docker_compose_adguardhome` does the latter.

## Traps

- **The renew loop is `sleep 24h`, anchored to container start.** Not cron, not a timer. Any
  `docker restart` resets the phase and triggers an immediate `certbot renew`, which is how a
  configuration change takes effect without waiting a day.
- **Initial issuance does not run the post-run command.** `files/certbot_create_cert.sh` runs
  `certbot certonly` once from Ansible, and passes no hooks. A reconciler-shaped post-run command
  covers this on its next cycle; a fire-once command does not.
- **`--keep-until-expiring` makes re-running the playbook a no-op** for issuance, so a certificate
  problem cannot be fixed by re-running Ansible alone.
- **The image tag floats.** `amd64-latest` / `arm64v8-latest`, selected by architecture. Nothing
  pins a version.
- **The compose service is always `certbot`,** whatever the container is called. `certbot_create_cert.sh`
  addresses the service, `service_name_to_restart` addresses the container. They are not
  interchangeable.
- **`renew_hook` persists in certbot's own state.** Once a `--deploy-hook` has run, certbot records
  it in `config/renewal/<domain_name>.conf` under `[renewalparams]`, where it survives removal of the
  command-line flag. Removing a hook means editing that file too.
