# docker_compose_distro_iso_feed_downloader

Deploys distro-iso-feed-downloader: keeps a local mirror of current Linux distribution ISOs,
fetching by torrent where available and pruning superseded releases.

## Status: Production

## Inputs

- `distro_iso_feed_downloader_select` — default `[]`. List of `distro:variant` keys to
  track, e.g. `debian:netinst`. **An empty list downloads nothing**, so this is effectively
  required.
- `distro_iso_feed_downloader_output_dir` — default
  `<data_dir>/distro-iso-feed-downloader/isos`. Mounted at `/isos`.
- `distro_iso_feed_downloader_interval` — default `86400` seconds between feed checks.
- `distro_iso_feed_downloader_preferred_download_method` — default `torrent`.
- `distro_iso_feed_downloader_torrent` — default `true`.
- `distro_iso_feed_downloader_prune` — default `true`. Removes ISOs no longer current.

## Example

```yaml
- role: docker_compose_distro_iso_feed_downloader
  vars:
    distro_iso_feed_downloader_output_dir: "/mnt/storage/Software/Linux"
    distro_iso_feed_downloader_select:
      - debian:netinst
      - fedora:workstation
      - nixos:minimal
      - proxmox:ve
```

## Host networking

The container runs with `network_mode: host` so the torrent client can accept incoming
connections. That means it is **not** on the Traefik network and has no web interface — it
is a background fetcher, not a service.

## Pruning deletes files

`prune: true` removes ISOs that drop out of the feed. Point `output_dir` at a directory this
role owns, not at a general-purpose share holding anything you want to keep.
