# podman_quadlet_tdarr

Deploys a Tdarr **node** as a Podman Quadlet unit, and optionally the CIFS mounts holding the
library it works on. Wraps `podman_quadlet`.

Node only. The **server** is a different deployment with a web UI, a reverse proxy and a
database — see `docker_compose_tdarr` for a Docker-Compose one.

## Status: Production

## Inputs

### Required — all asserted, because every wrong value here fails silently

- `podman_quadlet_tdarr_server_ip` — the Tdarr server. Wrong or unset: the node starts,
  retries forever and never appears in the server's node list. **Changing it later is a
  no-op** — see "Changing the server address after first start".
- `podman_quadlet_tdarr_mounts` — the library, as a list of mounts. At least one entry, each
  with `src` and `dest`. Empty or wrong `src`: the node registers, reports healthy, scans
  nothing, and every flow reports zero files — which reads as a Tdarr misconfiguration
  rather than a path one. See "The mounts list".
- `podman_quadlet_tdarr_puid` / `_pgid` — the identity Tdarr runs as. Must match the owner of
  the library mounts. Wrong: the node reads the library and cannot write to it, which
  surfaces as flow failures rather than a permissions error. See "PUID must match the
  mount's owner".
- `podman_quadlet_tdarr_data_dir` — holds `configs` and `logs`. Wrong: the node registers as
  a brand-new node with fresh config; correcting the path later orphans the old identity in
  the server's node list. This directory also pins the server address.
- `podman_quadlet_tdarr_transcode_cache_dir` — mounted at `/temp`, where in-progress
  transcodes are written. Wrong: a batch fills whichever filesystem it lands on. No default
  for exactly this reason — any plausible one is a root filesystem somewhere.

### Optional

- `podman_quadlet_tdarr_server_port` — default `8266`.
- `podman_quadlet_tdarr_node_name` — default `{{ inventory_hostname }}`. The name shown in
  the server's node list.
- `podman_quadlet_tdarr_api_key` — default empty, which is correct while the server runs with
  auth off. Rendered into an `EnvironmentFile` at mode `0600`, never into the unit.
- `podman_quadlet_tdarr_transcode_gpu_workers` / `_transcode_cpu_workers` — default `0` / `2`.
- `podman_quadlet_tdarr_healthcheck_gpu_workers` / `_healthcheck_cpu_workers` — default
  `0` / `1`. All four are environment-variable-only on a node: they cannot be changed from
  the Tdarr UI, so changing them here is the only way.
- `podman_quadlet_tdarr_ffmpeg_dir` — default empty, meaning the image's bundled ffmpeg.
  Set to a host directory and it is bind-mounted read-only with `ffmpegPath` pointed inside
  it. **Must contain the ffmpeg payload and nothing else** — see "Bringing your own ffmpeg".
- `podman_quadlet_tdarr_ffmpeg_container_dir` — default `/ffmpeg`. Where the above is
  mounted inside the container. Only read when `_ffmpeg_dir` is set.
- `podman_quadlet_tdarr_devices` — default `[]`, one `AddDevice=` per entry. Empty means the
  node transcodes on CPU. See "Accelerators are a device list".
- `podman_quadlet_tdarr_group_add` — default `[]`, one `GroupAdd=` per entry.
- `podman_quadlet_tdarr_networks` — default `[]`, one `Network=` per entry. Empty means the
  default rootful Podman network, which is all a node needs. See "No ports, no labels".
- `podman_quadlet_tdarr_install_wanted_by` — default `multi-user.target`. Empty omits the
  `[Install]` section, so the node does not start at boot. See "Handing boot policy to
  something else".
- `podman_quadlet_tdarr_image` — default `ghcr.io/haveagitgat/tdarr_node:latest`.
- `podman_quadlet_tdarr_timezone` — default `{{ timezone }}`.

### Required only when `podman_quadlet_tdarr_manage_mounts` is true

Left at its default of `false`, none of these is read or asserted, and the role never handles
a credential.

- `podman_quadlet_tdarr_storage_host` — the host serving the shares over SMB.
- `podman_quadlet_tdarr_smb_username` / `_smb_password`.
- a `share` key on every `podman_quadlet_tdarr_mounts` entry.
- `podman_quadlet_tdarr_storage_domain` — default `{{ domain_name }}`.
- `podman_quadlet_tdarr_smb_credentials_path` — default `/etc/tdarr-smb-credentials`. Written
  at mode `0600`. A role-owned file rather than host layout, so any self-consistent value
  works.

## Example

From the calling playbook, with the role mounting the shares itself:

```yaml
- name: Deploy Tdarr node quadlet
  tags: tdarr
  ansible.builtin.include_role:
    name: podman_quadlet_tdarr
    apply:
      tags: tdarr
  vars:
    podman_quadlet_tdarr_server_ip: "tdarr.{{ domain_name }}"
    podman_quadlet_tdarr_puid: "{{ smb_storage_uid }}"
    podman_quadlet_tdarr_pgid: "{{ smb_storage_gid }}"
    podman_quadlet_tdarr_data_dir: /var/data/tdarr-node
    podman_quadlet_tdarr_transcode_cache_dir: /var/data/tdarr-node/temp
    podman_quadlet_tdarr_manage_mounts: true
    podman_quadlet_tdarr_storage_host: <storage_host>
    podman_quadlet_tdarr_smb_username: "{{ smb_storage_username }}"
    podman_quadlet_tdarr_smb_password: "{{ smb_storage_password }}"
    podman_quadlet_tdarr_devices: [/dev/dri]
    podman_quadlet_tdarr_mounts:
      - {src: /mnt/library, dest: /media, share: storage, options: noserverino}
```

`apply:` is required when tagging an `include_role` — a tag on the include gates only the
include itself, not the tasks inside the role.

## The mounts list

One flat list, not named slots, because how a library is split across mounts is a property of
the storage behind it rather than of Tdarr. One entry, ten entries, a merged pool plus
per-disk shares, or a plain local directory are all the same to this role.

| Key | When | Meaning |
| --- | --- | --- |
| `src` | always | Host path bind-mounted in. Also the mountpoint when `manage_mounts` is true. |
| `dest` | always | Container path. **Not free choice** — see below. |
| `share` | `manage_mounts` | Share name on the storage host. |
| `options` | `manage_mounts` | Extra CIFS options, appended after the ones the role sets. Optional. |

**`dest` must be the path the server uses.** The node runs with `nodeType=mapped`, which means
the server hands it absolute paths from the server's own view of the library. A node that
mounts the same data somewhere else cannot act on the work it is given. Flow plugins can
constrain this further: one that derives a search root from a file's leading path components
requires a specific `dest` shape, not merely a consistent one.

A multi-mount example, where a merged pool and the per-disk shares behind it are mounted
separately so that inode-based sibling detection works. This is one deployment's arrangement,
not a mode this role knows about:

```yaml
podman_quadlet_tdarr_mounts:
  - {src: /mnt/pool,      dest: /media,             share: storage, options: noserverino}
  - {src: /mnt/raw/disk1, dest: /media-raw/disk1,   share: disk1}
  - {src: /mnt/raw/disk2, dest: /media-raw/disk2,   share: disk2}
```

`mount.cifs(8)` says server-provided inode numbers are "enabled by default", so the per-disk
entries pass no options and the pool opts *out* with `noserverino`.

## Two mount modes

`podman_quadlet_tdarr_manage_mounts` is a two-valued input, and both values have a defined
failure:

- **`false` (default)** — the caller has already mounted every `src`, by whatever means:
  `smb_add_mount`, a `.mount` unit the playbook writes, fstab, NFS, or a local filesystem.
  If a path is not actually mounted, the deploy fails at the mountpoint assert.
- **`true`** — the role writes the credentials file and one CIFS `.mount` unit per entry. If
  the caller has *also* mounted those paths by other means, two definitions fight over the
  same mountpoint.

Default `false` because the mount is the part most likely to already exist, and a role that
silently takes ownership of someone else's mount is worse than one that asks.

### Why `.mount` units and not `.volume` quadlets

Only relevant when `manage_mounts` is true.

`podman_quadlet` writes every unit at mode `0644`. A Quadlet `.volume` unit carrying CIFS
`Options=` would therefore put the SMB password in a world-readable file, and `credentials=`
cannot rescue it: `mount.cifs(8)` documents that option as read by the userspace helper, which
Podman's local volume driver does not invoke. A systemd `.mount` unit runs `/bin/mount`, so
`credentials=<0600 file>` works.

`smb_add_mount` is not reused, because it installs `cifs-utils` with `ansible.builtin.package`
— on an rpm-ostree host that means a layered package and a reboot. On a host where
`smb_add_mount` is the right tool, run it and leave `manage_mounts` at `false`.

### The mountpoint assert is not redundant

Both modes end by asserting every `src` is a real mountpoint. That is not belt-and-braces
alongside the unit's `RequiresMountsFor=`, because `RequiresMountsFor=` does not catch this:
`systemd.unit(5)` says it adds dependencies for the mount units *required to access* the
path, so a path that is not itself a mount point resolves to its nearest **parent** mount,
which exists. Worse, `podman_quadlet` creates a directory for every `Volume=` bind source, so
an unmounted path is silently created on the way past. Without the assert the node starts
cleanly and scans an empty library.

## PUID must match the mount's owner

`podman_quadlet` chowns every `Volume=` bind source to a single owner, and this role passes
the PUID rather than root. That is deliberate: a network filesystem's ownership is pinned by
its mount options, so chowning it to anything else does not stick and reports *changed* on
every run. Using the PUID is a no-op on those mounts and is simultaneously correct for
`configs`, `logs` and the transcode cache, which Tdarr writes as that user.

When the role manages the mounts it uses the same PUID/PGID for the CIFS `uid=`/`gid=`, so
the two cannot drift. When it does not, matching them is the caller's job — which is why
they are inputs rather than derived from an SMB uid that may not exist.

## Changing the server address after first start

The node writes its resolved server URL into `configs` on first start, and **changing
`podman_quadlet_tdarr_server_ip` afterwards does not update it** (HaveAGitGat/Tdarr#912). The
playbook will report *changed*, the unit will restart, and the node will keep contacting the
old address.

To actually move a node: stop it, delete the persisted config under
`<data_dir>/configs`, then start it. It re-registers against the new address.

## Bringing your own ffmpeg

`podman_quadlet_tdarr_ffmpeg_dir` bind-mounts a host directory read-only and sets
`ffmpegPath` to `<container_dir>/ffmpeg`. Use it when the image's bundled builds lack an
encoder the host's GPU actually has — the usual case being a card whose vendor is not the one
the bundled builds were tuned for.

**The whole directory is mounted**, so it must hold the ffmpeg payload and nothing else.
Pointing this at a general-purpose `bin` directory hands the container every binary in it.
A dedicated directory per build is the right shape.

Two things this does *not* do:

- It does not set `ffmpegVersion`. That selects among the builds inside the image and is a
  separate setting; the image still wants a valid value for it. Which one wins when both are
  present is Tdarr's business, not this role's — confirm against a job report rather than
  assuming, because a silently-ignored `ffmpegPath` looks exactly like a working one until
  you check which binary ran.
- It does not make a flow work. A flow written around one vendor's encoder still fails on
  another's; mounting a capable ffmpeg is necessary, not sufficient.

The directory becomes a `Volume=` source like any other, so `podman_quadlet` will chown it to
the PUID on every run — create it with that ownership, or it reports *changed* forever. See
"PUID must match the mount's owner".

## Accelerators are a device list

`podman_quadlet_tdarr_devices` and `_group_add` are lists rather than a `gpu: true` flag,
because "GPU" is not one thing — `/dev/dri` is the VAAPI/DRM path, an NVIDIA host wants
`nvidia.com/gpu=all` through CDI, and a ROCm host also wants `/dev/kfd`. A boolean would bake
one host's accelerator into the role.

Setting a device does not by itself make the GPU usable. The worker counts have to be
non-zero, and the flows the server assigns have to use an encoder the card actually has —
a flow built around one vendor's encoder fails on another's, and translating it is a new
measurement rather than a substitution.

## No ports, no labels

The unit publishes nothing and carries no labels, because of what a node *is*: `nodeIP` and
`nodePort` have been legacy since Tdarr 2.00.17, the node connects outbound to `serverPort`,
and it has no web UI to reverse-proxy.

`podman_quadlet_tdarr_networks` is still an input rather than an omission, because "no
`Network=` line" is itself a claim about the host's networking. The failure to avoid is a role
that hardcodes one deployment's reverse proxy and consequently cannot deploy to a host whose
proxy is something else.

## Handing boot policy to something else

`podman_quadlet_tdarr_install_wanted_by` defaults to `multi-user.target`, so the node starts
at boot. Setting it to an empty string omits `[Install]` entirely, which leaves the unit
deployable but not boot-started — for a host where an arbiter outside this role decides
whether the node runs at all, typically by adding and removing a
`<unit>.container.d/*.conf` drop-in.

Empty is not the safer choice: it means a freshly provisioned host has a node that never
starts until that arbiter has run once. Set it deliberately or leave it alone.
