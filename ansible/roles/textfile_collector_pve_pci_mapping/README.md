# textfile_collector_pve_pci_mapping

Exports the state of a Proxmox node's PCI resource mappings to node_exporter's textfile
collector, so a mapping that PVE would refuse at VM start shows up as a metric within five
minutes of the change instead of as a failed autostart after the next reboot.

## Status: Production

## Metrics

| metric | meaning |
| --- | --- |
| `pve_pci_mapping_check_ok{mapping="<id>"}` | `1` when `pvesh get /cluster/mapping/pci --check-node <node>` reports no check for the mapping; `0` is what a `qm start` would fail on. One series per mapping that has a `map` entry for this node. |
| `pve_pci_mapping_bmc_kcs_ok` | `1` when the kernel's first IPMI exchange this boot found the BMC (`ipmi_si … Found new BMC` before any `BMC returned incorrect response`). On the node this was written for, a boot that POSTed against a BMC still initialising is the boot whose enumeration changes — see that node's file under `hardware/`. |

If `pvesh` fails the script exits non-zero and the `textfile_collector` wrapper does not replace
the `.prom` file, so a stale-but-honest file is left rather than a healthy-looking empty one.

## Inputs

| variable | default | notes |
| --- | --- | --- |
| `textfile_collector_pve_pci_mapping_interval_seconds` | `300` | timer interval |
| `textfile_collector_pve_pci_mapping_node` | `{{ ansible_facts['hostname'] }}` | the node whose mappings are reported |
| `textfile_collector_pve_pci_mapping_script_path` | `/usr/local/sbin/pve-pci-mapping-metrics` | where `files/pve_pci_mapping_metrics.py` is deployed |

Wraps `textfile_collector` (`textfile_collector_name: pve-pci-mapping`), which owns the
wrapper script, service and timer, and the output directory. node_exporter with the textfile
directory is already on every cluster node through `configure_server`.

## Playbook

```yaml
- name: Export PCI mapping check state for Prometheus
  when: pve_pci_mapping_mappings | default([]) | length > 0
  tags: pci_passthrough
  ansible.builtin.import_role:
    name: textfile_collector_pve_pci_mapping
```

Alert on `pve_pci_mapping_check_ok == 0` (Grafana rule `rules-pve-pci-mapping.yaml` in the
monitoring host's provisioning directory under `ansible/files/`).

## Tests

```sh
cd ansible
.venv/bin/pytest roles/textfile_collector_pve_pci_mapping/tests/ -q
```

The script takes `pvesh` and `journalctl` as arguments, and the pytest injects stubs for both:
one clean and one rejected mapping, a mapping on another node (not reported), the three IPMI
log shapes seen on a real node (clean, the 08-28 failure, a late complaint after success), no
IPMI lines at all, and a failing `pvesh`. The `textfile_collector` wiring itself writes to
`/usr/local/bin` and `/etc/systemd/system` and is verified on the host, not in a fixture.
