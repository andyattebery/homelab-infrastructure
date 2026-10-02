# Talos cluster on the DeskPi Super6C

Six Raspberry Pi CM4 8 GB Lite modules on a DeskPi Super6C, running Talos Linux v1.14.1 and
Kubernetes 1.37 as a lab cluster: rebuildable, no backup target. Each node boots from its own
microSD card; its Samsung PM991 256 GB NVMe carries Talos's EPHEMERAL volume and a Longhorn disk.

## Status: Built

Built and verified 2026-09-27 (see "Verification"). The research and the reasons behind each
choice are in [research/super6c-cluster/](../research/super6c-cluster/README.md).

## Layout

| Name | IP | Role |
|---|---|---|
| `pi-cluster-01..03` | 192.168.1.181–183 | control plane; also runs workloads (no taint) |
| `pi-cluster-04..06` | 192.168.1.184–186 | worker |
| `pi-cluster-k8s` | 192.168.1.187 | Kubernetes API VIP, held by one control plane |

- The addresses are UniFi DHCP reservations that the network inventory manager writes from
  `network-inventory/network_hosts_inventory.yaml.tpl`. The MACs are in the `pi-cluster`
  1Password item.
- Each SD card holds Talos itself, including META and STATE. Each PM991 holds EPHEMERAL (40 GiB:
  etcd, container images, logs) and the `longhorn` user volume (the rest, 198 GiB, mounted at
  `/var/mnt/longhorn`).
- Longhorn 1.12.1, v1 engine, 2 replicas per volume; `longhorn` is the default StorageClass.

## Files

| Path | What it is |
|---|---|
| `mise.toml` | Pins talosctl (= the cluster's Talos version), kubectl and helm. Points `TALOSCONFIG`, `KUBECONFIG`, kubectl's cache and helm's home into `generated/`. `mise run nodes <command>` runs talosctl against all six nodes, e.g. `mise run nodes memory`; `mise run temps` shows every sensor on every node (see Traps, "Temperatures"). Both take the node list from `TALOS_NODES`. |
| `schematic.yaml`, `schematic.id` | The Image Factory schematic (`rpi_generic` overlay, `iscsi-tools`, `util-linux-tools`, `nvme_core.default_ps_max_latency_us=0`) and its ID, which names the disk image and the installer. |
| `secrets.yaml.tpl` | The Talos secrets bundle as `op://` references into the `pi-cluster` item's `talos` section. |
| `patches/` | Machine config patches: `all.yaml` (every node), `controlplane.yaml` (VIP, no taint), `nodes/pi-cluster-0N.yaml` (hostname). |
| `longhorn/` | The namespace, the chart values and the smoke test. |
| `scripts/` | `flash-sd.sh`, `store-secrets.sh`, `gen-config.sh`, `wipe-disk.sh`, `temps.sh`. Each prints its usage with `-h`. |
| `tests/` | pytest for the scripts; see "Tests". |
| `generated/`, `images/` | Gitignored: the secrets bundle, machine configs, talosconfig and kubeconfig; the downloaded disk images. |

## Build

Run everything from `talos/`: mise puts the pinned tools on PATH and sets `TALOSCONFIG` and
`KUBECONFIG`. Outside `talos/`, the shims have no version to run.

1. `mise install`.
2. **Reservations first.** Push the inventory entries, then force a sync:
   `curl -X POST http://192.168.1.224:8090/sync`. Power the board on only after that: a node that
   boots first keeps its pool lease until it renews.
3. **Flash each card on the Mac.** `scripts/flash-sd.sh diskN` shows which card that is;
   `scripts/flash-sd.sh diskN --yes` writes it (`sudo` asks for the password). The first run
   registers `schematic.yaml` with Image Factory and downloads the image.
4. **Cards in, power on.** Each node comes up in maintenance mode at its reserved address:
   `talosctl get links --insecure -n 192.168.1.18N` answers, and
   `talosctl get disks --insecure -n 192.168.1.18N` lists `mmcblk0` and `nvme0n1`.
5. **Secrets, once per cluster:** `scripts/store-secrets.sh`. It refuses if the item already has a
   `talos` section. Check the round trip without printing a value:
   ```sh
   op inject -i secrets.yaml.tpl -o generated/secrets.check.yaml
   cmp -s <(yq -o=json -I=0 'sort_keys(..)' generated/secrets.yaml) \
          <(yq -o=json -I=0 'sort_keys(..)' generated/secrets.check.yaml) && echo match || echo MISMATCH
   rm generated/secrets.check.yaml
   ```
6. **Configs:** `scripts/gen-config.sh`, then
   `talosctl validate --config generated/pi-cluster-0N.yaml --mode metal` for each node.
7. **Apply, node by node:** `talosctl apply-config --insecure -n 192.168.1.18N -f generated/pi-cluster-0N.yaml`.
   Until bootstrap, address a node as its own endpoint:
   `talosctl -e 192.168.1.18N -n 192.168.1.18N get volumestatus` must show STATE and META on
   `mmcblk0`, EPHEMERAL (40 GiB) and `u-longhorn` (198 GiB) on `nvme0n1`. If EPHEMERAL failed with
   "not enough space", the PM991 still has old partitions: `scripts/wipe-disk.sh pi-cluster-0N <serial>`
   shows the match, then add `--yes`. The volumes appear within seconds, without a reboot.
8. **Bootstrap, once:** `talosctl -e 192.168.1.181 -n 192.168.1.181 bootstrap`, then
   `talosctl -n 192.168.1.181 health --control-plane-nodes 192.168.1.181,192.168.1.182,192.168.1.183 --worker-nodes 192.168.1.184,192.168.1.185,192.168.1.186`
   and `talosctl -n 192.168.1.181 kubeconfig generated/kubeconfig`.
9. **Longhorn:** `kubectl apply -f longhorn/namespace.yaml`, then
   `helm install longhorn longhorn --repo https://charts.longhorn.io --version 1.12.1 -n longhorn-system -f longhorn/values.yaml`.

## Verification

Checked on 2026-09-27; repeat after any rebuild.

- `talosctl health` (step 8) passes. `kubectl get nodes -o wide` shows 6 Ready, INTERNAL-IP
  .181–.186 and never .187, and no node has a taint. `talosctl -n 192.168.1.181 etcd members` lists 3.
- **VIP:** `kubectl --server https://192.168.1.187:6443 get --raw /version` answers.
  `talosctl -n <node> get addresses` shows which control plane holds `192.168.1.187/32`; after
  `talosctl reboot` of that node, another control plane held it and the API answered within 10 s.
- **Longhorn:** 6 schedulable Longhorn nodes, each with a disk at `/var/mnt/longhorn`.
  `kubectl apply -f longhorn/smoke-test.yaml`: both PVCs bind; the RWO volume is healthy with 2
  replicas on two nodes; `kubectl -n longhorn-smoke-test exec rwx-a -- cat /data/shared.txt` shows
  both pods' lines.
- **Node down:** `talosctl reboot` a node that holds one of the RWO volume's replicas. The volume
  turns degraded, then healthy once the node is back and the replica has rebuilt (about 2.5 min
  here), and the file is intact. `kubectl delete -f longhorn/smoke-test.yaml` removes the test.
- **Addresses:** after a board power cycle, all six come back at .181–.186.

## Upgrades

- **Always pass the node's own installer:**
  `talosctl -n <node> upgrade --image factory.talos.dev/metal-installer/$(cat schematic.id):<version>`.
  Without `--image`, talosctl uses the empty schematic: no Pi overlay, no extensions, no NVMe kernel
  argument.
- Step through every intermediate minor release, to the latest patch of each.
- Bump talosctl in `mise.toml` first: `flash-sd.sh` and `gen-config.sh` take the Talos version from it.
- Before the Kubernetes API exists, add `--drain=false`. `--wait` (the default) also waits for the
  Kubernetes node to be ready, so before bootstrap it never returns; use `--wait=false`.
- **Check every upgrade took.** `talosctl -n <node> read /proc/cmdline` shows the new boot slot
  (`BOOT_IMAGE=/B/…` after the first upgrade) and `nvme_core.default_ps_max_latency_us=0`;
  `talosctl -n <node> get metakeys` shows key 6 = the previous slot. On 2026-09-27, node 3 came
  back on its old slot twice before the third attempt took. Rerun until it does.
- **Changing the schematic:** edit `schematic.yaml`, `POST` it to
  `https://factory.talos.dev/schematics` for the new ID, and upgrade every node to that installer.
  Then write the ID to `schematic.id`, run `scripts/gen-config.sh`, and `apply-config` each node
  (only the installer line changes; no reboot). `flash-sd.sh` refuses when `schematic.yaml` no
  longer gives the ID in `schematic.id`, so a reflash with a new schematic starts with
  `rm schematic.id`.

## Tests

```
cd ansible && .venv/bin/pytest ../talos/tests -q
```

- The scripts run for real on a copy of `talos/` in a temporary git repo. `tests/stubs/` stand in
  for diskutil, dd, sudo, curl, op and talosctl's calls that reach a node (`get disks`,
  `wipe disk`, `list`, `read`). The rest of talosctl (`gen`, `machineconfig`, `validate`,
  `version`) is the real pinned binary, which works offline.
- Fixtures are captured from real output, never written by hand. Tests that need one skip until
  it exists:
  - `tests/fixtures/talos-disks.json`: `talosctl get disks --insecure -n 192.168.1.181 -o json`
    from a node in maintenance mode.
  - `tests/fixtures/talos-sysfs.json`: `tests/capture_sysfs.py 192.168.1.181`, run from `talos/`.
    It holds talosctl's output for each directory `temps.sh` lists and each file it reads.
  - `tests/fixtures/diskutil-sd.plist`: `diskutil info -plist diskN` with an SD card in the Mac.
    Not captured yet, so `test_flash_sd.py`'s card cases skip.
- A test that has never failed proves nothing. When changing a script's guard, remove the guard,
  watch its test go red, and put it back.

## Traps

- **PM991 drives hang with NVMe power saving (APST) on.** The console shows
  `nvme nvme0: Device not ready; aborting reset, CSTS=0x1`, or the kernel log shows
  `brcm-pcie … link down` after a reboot. Two of the six drives hung within minutes of load on
  2026-09-26. The schematic turns APST off with `nvme_core.default_ps_max_latency_us=0`;
  `talosctl -n <node> read /sys/class/nvme/nvme0/power/pm_qos_latency_tolerance_us` must say `0`.
  **A hung drive recovers only when its M.2 slot loses power, which takes the board's power
  switch.** CM4 reboots and the board's reset button do not cut it.
- **Temperatures:** `mise run temps` (`scripts/temps.sh`) reads every hwmon sensor through the
  Talos API. A node that doesn't answer shows `no answer` after about 20 s, and the run exits 1.
  What the columns mean here:
  - `cpu_thermal` has no limits of its own. Its CRIT is the kernel's critical trip, 110 °C, where
    the node shuts down. The firmware throttles well before that: "When the core temperature is
    between 80°C and 85°C, the Arm cores will be progressively throttled back", and at 85 °C the
    GPU too (Raspberry Pi docs).
  - `nvme` Composite has the drive's own limits: MAX is its warning point (80.85–82.85 °C across
    these six drives) and CRIT is 84.85 °C. Its Sensor 1 reports no limits.
  - `rpi_volt` `in0_lcrit` is the firmware's under-voltage alarm (kernel docs, raspberrypi-hwmon).
    1 means the firmware reports under-voltage.
  - With a fan on the board, the drives stayed at 23–47 °C through the install.
- **SD boot race** (siderolabs/talos#14359, fix not in 1.14.1). A node can come up in maintenance
  mode after a reboot; re-run `talosctl apply-config --insecure` for it. The reverted upgrades
  above may be the same race (unconfirmed).
- **The VIP is never a talosconfig endpoint.** It is elected through etcd, so it is missing before
  bootstrap and whenever etcd is broken, exactly when talosctl is needed most.
- **Reused PM991s:** old partitions block EPHEMERAL ("not enough space"); `wipe-disk.sh` clears
  them by serial. EPHEMERAL's size is fixed when it is first provisioned.
- **Boot order:** if a node won't boot from its SD card, its EEPROM `BOOT_ORDER` must include SD.
  Fix it with Raspberry Pi Imager's "SD Card Boot" bootloader image.
- **Super6C power:** there is no per-node power control. A node shut down with `talosctl shutdown`
  comes back only with a board power cycle, which restarts all six. To stop the whole cluster,
  `mise run nodes shutdown --force` (`--force` skips the drains, which would need the API the
  control planes are taking down), then switch the board off. Switching it on starts the cluster again;
  etcd and Longhorn resume from the NVMe drives.
- **bcmgenet:** watch `talosctl dmesg` for `NETDEV WATCHDOG` (siderolabs/sbc-raspberrypi#72,
  reported fixed in Linux 6.18.33; Talos 1.14.1 runs 6.18.51).
- **Longhorn node-down:** `node-down-pod-deletion-policy` is Longhorn's default, `do-nothing`, so
  StatefulSet pods on a dead node need a force delete. `node-drain-policy` is
  `block-if-contains-last-replica`: draining the node that holds a volume's last replica is blocked.
- **PodSecurity warnings during `helm install` are expected.** `longhorn-system` enforces
  `privileged`, but Talos's cluster default still warns at `restricted`.
- **PM991s have no power-loss protection.** Power the board from a UPS outlet.
- **Secrets** live only in the `pi-cluster` 1Password item (sections `talos` and `mac address`)
  and in `generated/`.
