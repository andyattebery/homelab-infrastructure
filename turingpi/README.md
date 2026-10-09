# Turing Pi 2

Tooling for the Turing Pi 2 board's BMC, used for every node:
- `tpi`, Turing's CLI, pinned in `mise.toml` with the BMC's address;
- `scripts/flash-node.sh`, which writes an image to a node's eMMC.

One directory per kind of node holds what is specific to it: [rk1/](rk1/) for the Turing RK1s,
[jetson/](jetson/) for the Jetson Orin Nano, and [cm4/](cm4/) for the Raspberry Pi CM4.

## Files

| Path | What |
|---|---|
| `nodes.md` | What is in each slot: module, host, IP, storage, add-in card and OS. |
| `mise.toml` | `tpi` 1.0.7 and `TPI_HOSTNAME`, the BMC's IP. |
| `scripts/flash-node.sh` | Writes an image to a node's eMMC through the BMC. Prints its usage with `-h`. |
| `scripts/write-seed.sh` | Writes a cloud-init seed into the FAT partition of a copy of an `.img.xz`, recompressed, for the CM4 and RK1 scripts. Prints its usage with `-h`. |
| `rk1/` | The RK1s: their cloud-init seed, the script that seeds and flashes the latest release, and its downloads (gitignored). |
| `jetson/` | The Jetson Orin Nano: its cloud-init seed for the microSD card, its first QSPI flash, and its downloads (gitignored). |
| `cm4/` | The Raspberry Pi CM4: its cloud-init seed, the script that writes it into Ubuntu's image, and the seeded images (gitignored). |

## Logging in to the BMC

`tpi` asks for the BMC's username and password, then caches a token in
`~/Library/Caches/tpi_token`. In a shell with no terminal it can't ask, and fails with
`Device not configured (os error 6)`. Log in once from a terminal:
`mise -C turingpi exec -- tpi info`.

## Flashing a node

`turingpi/scripts/flash-node.sh <node 1-4> <image>` shows the nodes' power state and writes nothing.
With `--yes` it:
1. checks the image against its `.sha`;
2. powers the node off;
3. streams the image from the Mac, which the BMC checks against the `.sha`;
4. powers the node on.

A `.img.xz` works: the BMC decompresses it, and checks the `.sha` against the compressed stream. An
RK1 `.img.xz` (about 500 MiB, 2.5–3.2 GiB decompressed) flashes in 7–8 minutes; the CM4's raw
4.6 GiB `.img` took about 25. `scripts/write-seed.sh` writes `.img.xz` for that reason.

For an RK1, `turingpi/rk1/scripts/flash-latest-release.sh` downloads the latest image and writes the
node's cloud-init seed into it first, then runs this ([rk1/](rk1/)).

## Traps

- **A BMC restart drops the cached login.** The next `tpi` call needs the login again (above).
- **tpi has no request timeout.** With the BMC unreachable, a flash hangs about 15 minutes before
  failing with `error sending request for url`. Check first: `nc -z -G 5 192.168.1.215 443`.
- **`tpi uart get` is not a live stream.** Each call returns the BMC's whole buffer since the node
  powered on. Call it again to see newer lines.
