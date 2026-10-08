# Talos cluster on the DeskPi Super6C

Six Raspberry Pi CM4 8 GB Lite modules on a DeskPi Super6C, running Talos Linux v1.14.1 and
Kubernetes 1.36.5 (pinned in `scripts/gen-config.sh`) as a lab cluster: rebuildable, no backup
target. Each node boots from its own microSD card; its Samsung PM991 256 GB NVMe carries Talos's
EPHEMERAL volume and a Longhorn disk.

## Status: Built

Built 2026-09-27; rebuilt on Kubernetes 1.36.5 and verified 2026-10-04 (see "Verification"). The
research and the reasons behind each choice are in
[research/super6c-cluster/](../research/super6c-cluster/README.md); the front door's are in
[research/cluster-ingress/](../research/cluster-ingress/README.md).

## Layout

| Name | IP | Role |
|---|---|---|
| `pi-cluster-01..03` | 192.168.1.181–183 | control plane; also runs workloads (no taint) |
| `pi-cluster-04..06` | 192.168.1.184–186 | worker |
| `pi-cluster-k8s` | 192.168.1.187 | Kubernetes API VIP, held by one control plane |
| `pi-cluster-ingress` | 192.168.1.188 | the Gateway's address, announced by MetalLB (see "Ingress and certificates") |

- The six node addresses are UniFi DHCP reservations that the network inventory manager writes
  from `network-inventory/network_hosts_inventory.yaml.tpl`; the VIP and the Gateway's address
  get DNS entries from the same file. The MACs are in the `pi-cluster` 1Password item.
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
| `ingress/` | The front door: namespaces, MetalLB's address pool, the cert-manager and istiod chart values, and `ingress.yaml.tpl` (see "Ingress and certificates"). |
| `scripts/` | `flash-sd.sh`, `store-secrets.sh`, `gen-config.sh`, `wipe-disk.sh`, `reset-node.sh`, `temps.sh`, `ingress.sh`. Each prints its usage with `-h`. |
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
   and `rm -f generated/kubeconfig && talosctl -n 192.168.1.181 kubeconfig generated/kubeconfig`.
   `kubeconfig` merges into an existing file by default (`--merge`), so a previous cluster's
   kubeconfig goes first.
9. **Longhorn:** `kubectl apply -f longhorn/namespace.yaml`, then
   `helm install longhorn longhorn --repo https://charts.longhorn.io --version 1.12.1 -n longhorn-system -f longhorn/values.yaml`.
10. **Front door:** `scripts/ingress.sh` (see "Ingress and certificates").

### Rebuild

Nothing on the cluster is kept: every node's STATE and NVMe drive are wiped, and the same secrets
bundle builds it again. Reset the workers first and the control planes last, so the API stays up
longest: 04, 05, 06, 03, 02, 01.

1. **Reset each node:** `scripts/reset-node.sh pi-cluster-0N <serial>` shows the match (the
   serials are in `talosctl get disks -n 192.168.1.18N`), then add `--yes`. It wipes STATE and the
   whole NVMe drive, keeps the SD card's boot partitions, and returns once the node answers in
   maintenance mode.
2. **Check each drive came back blank:** `talosctl get discoveredvolumes --insecure -n 192.168.1.18N`
   must show EFI, BOOT and META on `mmcblk0`, no STATE, and no partitions on `nvme0n1`. The reset's
   success doesn't prove it (see Traps, "A reset can hang a drive").
   - No `nvme0n1` at all: the drive hung. Power-cycle the board, then check again.
   - `nvme0n1` still has partitions: `scripts/wipe-disk.sh pi-cluster-0N <serial> --insecure --yes`.
3. **Build again:** steps 6–10. Skip steps 2, 3 and 5: the reservations exist, the cards keep
   their boot partitions, and `store-secrets.sh` refuses a second run.

## Verification

Checked on 2026-09-27. After the 2026-10-04 rebuild, everything again except the two reboot tests
(the VIP moving, and "Node down"). Repeat after any rebuild.

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

## Ingress and certificates

The cluster's front door: one LAN address, a Gateway API Gateway, and a Let's Encrypt wildcard
certificate for `*.picluster.<domain_name>`. `scripts/ingress.sh` installs or updates all of it,
is safe to re-run, and asks 1Password once.

| Component | Version | Role here |
|---|---|---|
| Gateway API CRDs | v1.6.1, standard channel | `Gateway`, `HTTPRoute` and the rest of the standard channel. |
| MetalLB | chart 0.16.1, L2 mode | Gives the Gateway's Service 192.168.1.188 (`ingress/metallb-pool.yaml`). The chart's default frr-k8s BGP backend also runs on each node, idle under L2. |
| Istio | 1.31.1, `base` and `istiod` charts | The Gateway API controller only: no namespace is labelled for injection, so there are no sidecars. istiod's memory request is lowered to 512Mi (`ingress/istiod-values.yaml`). |
| cert-manager | v1.21.2 | Issues the Gateway's certificate over Cloudflare DNS-01, through the ClusterIssuer `letsencrypt`. |

- `ingress/ingress.yaml.tpl` holds the Cloudflare token Secret, the ClusterIssuer, the Gateway
  `pi-cluster` in namespace `istio-ingress`, its `parametersRef` ConfigMap and the HTTP-to-HTTPS
  redirect. `ingress.sh` renders it into `generated/` with one `op inject` and deletes it after
  the apply.
- Istio generates the Deployment and LoadBalancer Service `pi-cluster-istio` from the Gateway.
  The two replicas on different nodes and the PodDisruptionBudget (`minAvailable: 1`) come from
  the ConfigMap `pi-cluster-gateway`.
- cert-manager writes the certificate to the Secret `wildcard-picluster-tls` in `istio-ingress`,
  prompted by the Gateway's `cert-manager.io/cluster-issuer` annotation.
- DNS: the inventory's `"*.picluster"` service makes one AdGuard rewrite,
  `*.picluster.<domain_name>` → 192.168.1.188, so every name under it reaches the Gateway.

**A service plugs in** with an `HTTPRoute` in its own namespace. The wildcard certificate and the
wildcard rewrite already cover its name:

```yaml
spec:
  parentRefs:
    - name: pi-cluster
      namespace: istio-ingress
      sectionName: https
  hostnames:
    - <service>.picluster.<domain_name>
  rules:
    - backendRefs:
        - name: <service>
          port: <port>
```

The host name carries the domain, so a service's manifests are `.tpl` files rendered with
`op inject`, like `ingress.yaml.tpl`.

**Verification** (2026-10-04):
- `kubectl -n istio-ingress get gateway pi-cluster` shows `PROGRAMMED True` at 192.168.1.188, and
  `kubectl -n istio-ingress get certificate` shows `wildcard-picluster-tls` Ready.
- `openssl s_client -connect 192.168.1.188:443 -servername x.picluster.<domain_name>` presents a
  Let's Encrypt certificate for `*.picluster.<domain_name>`. `curl -sI http://192.168.1.188/`
  returns 301 to `https://`.
- A test route kept answering over HTTPS while one `pi-cluster-istio` pod was deleted, and while
  the node announcing .188 rebooted: MetalLB moved the address to another node within a second.
  `kubectl -n metallb-system get servicel2statuses` shows the announcing node.
- `dig +short anything.picluster.<domain_name>` returns 192.168.1.188, and the test route answered
  by name over HTTPS.

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
  for diskutil, dd, sudo, curl, op, helm, kubectl and talosctl's calls that reach a node
  (`get disks`, `wipe disk`, `reset`, `list`, `read`). The rest of talosctl (`gen`,
  `machineconfig`, `validate`, `version`) is the real pinned binary, which works offline.
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
- **Talos reuses its own old volumes** rather than wiping them. A rebuild must wipe each NVMe
  drive (`reset-node.sh`), or a control plane's old etcd data makes bootstrap fail with "etcd
  data directory is not empty".
- **A reset can hang a drive and still report success.** On 2026-10-04, two of the six drives
  (in 04 and 06) hung during `reset-node.sh`. Both nodes still reached maintenance mode, and
  talosctl reported success. The drives stayed invisible (`brcm-pcie … link down`) until a board
  power cycle, then came back with their old partitions. The Rebuild check (step 2) catches it.
- **Istio 1.31's charts are only at `oci://ghcr.io/istio/release/charts`;** the
  `istio-release.storage.googleapis.com` Helm repository stops at 1.30.
- **A Gateway's `spec.infrastructure.annotations` replace its own annotations** on the Service
  and Deployment Istio generates, so MetalLB's `metallb.io/loadBalancerIPs` goes there, not in
  `metadata.annotations`.
- **An unknown key in the `parametersRef` ConfigMap fails Istio's render** of the gateway. The
  keys it takes are `deployment`, `service`, `serviceAccount`, `horizontalPodAutoscaler` and
  `podDisruptionBudget`.
- **DNS-01 checks must not ask AdGuard,** which answers a fresh `_acme-challenge` TXT with
  NXDOMAIN and caches it. cert-manager asks only 1.1.1.1 and 1.0.0.1
  (`ingress/cert-manager-values.yaml`).
- **`metallb-system` is privileged:** MetalLB's speaker needs host networking and raw sockets.
  `istio-ingress` stays at baseline. kube-proxy runs in nftables mode, so MetalLB's strictARP
  setting (for IPVS mode) doesn't apply.
- **MetalLB logs `AdditionalAssignFailed … PreferDualStack`** for `pi-cluster-istio`: Istio's
  Service asks for dual-stack, and the pool is IPv4 only. The IPv4 address is assigned.
- **The inventory's `"*.picluster"` key stays quoted:** a bare `*` starts a YAML alias. NIM
  before 0.2.2 rejects the key and skips the whole sync.
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
