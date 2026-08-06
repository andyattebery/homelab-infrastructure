# docker_compose_hardlink_manager

Deploys hardlink-manager: a small FastAPI service that finds a file's hardlink siblings and
atomically replaces them when the primary is rewritten. Tdarr flow plugins call it over
HTTP so a transcode does not break hardlinks that a media library depends on.

The application source is vendored in this role and built on the host — upstream is this
repo, not a registry.

## Status: Production

## Inputs

- `hardlink_manager_data_path` — default `/mnt/data`. Host path bind-mounted into the
  container at the **same path**, with `rslave` propagation so per-disk mounts appearing
  underneath become visible without recreating the container.
- `hardlink_manager_allowed_path_prefix` — default `<data_path>/`. The prefix the API
  refuses to operate outside of. **The trailing slash matters**: `app.py` compares with
  `str.startswith`, so without it `/mnt/database` would also pass.

Both paths must contain every file the manager may hardlink. Sibling detection and
replacement never cross the boundary, so a file outside it is invisible to `/detect` and
rejected by `/replace`.

## Example

```yaml
- role: docker_compose_hardlink_manager
  vars:
    hardlink_manager_data_path: /mnt/data
```

## Runs where the files are local

Hardlinks cannot cross filesystems, and creating one over SMB is not possible. The role has
to run on the host that owns the storage, not on whichever host runs Tdarr.

## Operator scripts live outside this role

`fix-hlm-hardlinks.sh` (recovers hardlinks lost to an old same-extension bug) and
`test-hardlink-manager.sh` (API tests against a live instance) are under
`ansible/files/<host>/hardlink-manager/`. They are run by hand and are not deployed.

They were moved out for a second reason: this role ships its directory to the host as a
Docker **build context**, so anything left in it is baked into the image for no purpose.

Both require a URL from the environment or argv rather than carrying a default, because
this repository is public.
