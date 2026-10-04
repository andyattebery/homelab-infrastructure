# Turing RK1 nodes

Flashing the Turing RK1 nodes, in Turing Pi 2 slots 1 and 2, with the generic image from
[rk1-armbian-minimal](https://github.com/andyattebery/rk1-armbian-minimal): Debian 13 on Rockchip's
vendor kernel, with the most RK1 hardware support (GPU, NPU, video). Nothing of this homelab is in
it. First boot is Armbian's default first-login setup.

## Files

| Path | What |
|---|---|
| `scripts/flash-latest-release.sh` | Downloads the latest release and flashes it to node 1 or 2. Prints its usage with `-h`. |
| `images/` | Gitignored. The script's downloads, one directory per release tag, and images from earlier local builds. |

## Flashing a node

From the repo root:
1. `turingpi/rk1/scripts/flash-latest-release.sh <node>` downloads the latest release into
   `turingpi/rk1/images/<tag>/`, checks it against its `.sha`, and shows the nodes' power state. A
   release is downloaded only once.
2. Run it again with `--yes` to flash: it powers the node off, writes the image through
   [../scripts/flash-node.sh](../scripts/flash-node.sh), and powers the node on. About 7 minutes.
3. Forget the node's old host key: `ssh-keygen -R <ip>`, with the node's IP from
   [../hardware.md](../hardware.md).
4. Log in: `ssh root@<ip>`, password `1234`. Armbian's setup asks for a new root password and a
   user; the other hosts' user is `services`.
