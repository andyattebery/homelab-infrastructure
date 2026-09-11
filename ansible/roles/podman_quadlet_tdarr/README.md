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

## Example

From the calling playbook. The shares are mounted before this runs, by `systemd_cifs_mount`:

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
    podman_quadlet_tdarr_devices: [/dev/dri]
    podman_quadlet_tdarr_mounts:
      - {src: /mnt/library, dest: /media}
```

`apply:` is required when tagging an `include_role` — a tag on the include gates only the
include itself, not the tasks inside the role.

## The mounts list

One flat list, not named slots, because how a library is split across mounts is a property of
the storage behind it rather than of Tdarr. One entry, ten entries, a merged pool plus
per-disk shares, or a plain local directory are all the same to this role.

| Key | When | Meaning |
| --- | --- | --- |
| `src` | required | Host path bind-mounted in. Asserted to be a real mountpoint owned by the PUID. |
| `dest` | required | Container path. **Not free choice** — see below. |
| anything else | ignored | Deliberate — see below. |

**Extra keys are ignored on purpose.** This role does not mount anything, so it has no use for
a `share` or CIFS `options`. It tolerates them so that a caller can keep **one** list and hand
it to both this role and whatever performs the mount, rather than maintaining two lists that
describe the same filesystems. Two lists is how they drift.

**`dest` must be the path the server uses.** The node runs with `nodeType=mapped`, which means
the server hands it absolute paths from the server's own view of the library. A node that
mounts the same data somewhere else cannot act on the work it is given. Flow plugins can
constrain this further: one that derives a search root from a file's leading path components
requires a specific `dest` shape, not merely a consistent one.

A multi-mount example, where a merged pool and the per-disk shares behind it are mounted
separately so that inode-based sibling detection works. This is one deployment's arrangement,
not a mode this role knows about. The `share`/`options` keys are there for the mount role that
consumes the same list; this one reads straight past them:

```yaml
podman_quadlet_tdarr_mounts:
  - {src: /mnt/pool,      dest: /media,             share: storage, options: noserverino}
  - {src: /mnt/raw/disk1, dest: /media-raw/disk1,   share: disk1}
  - {src: /mnt/raw/disk2, dest: /media-raw/disk2,   share: disk2}
```

## This role does not mount anything

Every `src` must already be mounted when the role runs, by whatever means — `systemd_cifs_mount`,
a `.mount` unit the playbook writes, fstab, NFS, or a plain local filesystem. A path that is not
actually mounted fails the mountpoint assert, and one mounted by the wrong owner fails the owner
assert.

It used to mount CIFS shares itself, behind a `manage_mounts` flag. That is gone: a role that
deploys one application should not also be the only way to mount a filesystem, and keeping it
meant a second consumer on the same host grew its own parallel implementation — two mount
templates that drifted, and two files holding one credential.

### Why the mount is a `.mount` unit and not a `.volume` quadlet

Relevant to whoever does mount it, and the reason `systemd_cifs_mount` exists in the shape it
does.

`podman_quadlet` writes every unit at mode `0644`. A Quadlet `.volume` unit carrying CIFS
`Options=` would therefore put the SMB password in a world-readable file, and `credentials=`
cannot rescue it: `mount.cifs(8)` documents that option as read by the userspace helper, which
Podman's local volume driver does not invoke. A systemd `.mount` unit runs `/bin/mount`, so
`credentials=<0600 file>` works.

### The mountpoint assert is not redundant

The role asserts every `src` is a real mountpoint. That is not belt-and-braces
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

Matching the PUID to the mount's owner is the caller's job, which is why they are inputs
rather than derived from an SMB uid that may not exist — the mount could be CIFS, NFS or
local, and only the caller knows.

The role used to mount the shares itself and reuse PUID/PGID for the CIFS `uid=`/`gid=`, so
the two could not drift by construction. That is gone, and is replaced by something better:
the role reads each mountpoint's **actual** owner and asserts it against the PUID. A wrong
uid is not a mount failure — the node reads the library and cannot write to it, which
surfaces much later as a flow failure — so it is worth failing the deploy over.

For a CIFS mount that owner comes from the mount's own `uid=` option, not from the
filesystem, so a mismatch is fixed where the mount is defined. `chown` does not stick.

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
