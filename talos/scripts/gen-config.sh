#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0")"
    echo
    echo "Render the machine configs for pi-cluster-01..06 and the talosconfig into generated/,"
    echo "from the secrets bundle and the committed patches. The bundle is rendered from the"
    echo "pi-cluster 1Password item (one op inject) unless generated/secrets.yaml already exists."
    exit 1
}

[[ $# -eq 0 ]] || usage

# Everything written below carries the cluster's keys, and the repo is public. Checked against
# git itself rather than assumed from .gitignore, before anything is written.
if ! git check-ignore -q generated/secrets.yaml; then
    echo "Error: talos/generated/ is not gitignored; add /talos/generated/ to .gitignore first."
    exit 1
fi
if [[ ! -f schematic.id ]]; then
    echo "Error: schematic.id is missing; scripts/flash-sd.sh writes it."
    exit 1
fi

# The installer is always the talosctl version mise.toml pins, so the two cannot drift apart.
VERSION="$(talosctl version --client --short | awk '/^Talos/ {print $2}')"
if [[ ! "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: could not read the talosctl version; run this from talos/ so mise provides it"
    exit 1
fi

umask 077
mkdir -p generated

# One op call, so one 1Password prompt.
if [[ ! -f generated/secrets.yaml ]]; then
    op inject -i secrets.yaml.tpl -o generated/secrets.yaml
fi

talosctl gen config pi-cluster https://192.168.1.187:6443 \
    --with-secrets generated/secrets.yaml \
    --install-image "factory.talos.dev/metal-installer/$(cat schematic.id):$VERSION" \
    --config-patch @patches/all.yaml \
    --config-patch-control-plane @patches/controlplane.yaml \
    --output-types controlplane,worker,talosconfig \
    --output generated \
    --force

for N in 1 2 3 4 5 6; do
    if (( N <= 3 )); then
        ROLE=controlplane
    else
        ROLE=worker
    fi
    talosctl machineconfig patch "generated/$ROLE.yaml" \
        --patch "@patches/nodes/pi-cluster-0$N.yaml" \
        --output "generated/pi-cluster-0$N.yaml"
done

# The talosconfig talks to the control planes' own addresses, never the VIP. The VIP is elected
# through etcd, so it is missing before bootstrap and whenever etcd is broken -- the times
# talosctl is needed most.
talosctl --talosconfig generated/talosconfig config endpoint 192.168.1.181 192.168.1.182 192.168.1.183
talosctl --talosconfig generated/talosconfig config node 192.168.1.181

echo "Wrote generated/pi-cluster-01.yaml .. pi-cluster-06.yaml and generated/talosconfig."
