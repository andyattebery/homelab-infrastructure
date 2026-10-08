#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

usage() {
    echo "Usage: $(basename "$0")"
    echo
    echo "Install or update the cluster's front door: the Gateway API CRDs, MetalLB, Istio (only as"
    echo "the Gateway API controller) and cert-manager, then the Gateway, its certificate issuer"
    echo "and the HTTPS redirect, rendered from ingress/ingress.yaml.tpl with one op inject."
    echo "Safe to re-run."
    exit 1
}

[[ $# -eq 0 ]] || usage

GATEWAY_API_VERSION=v1.6.1
METALLB_VERSION=0.16.1
ISTIO_VERSION=1.31.1
# Istio 1.31 publishes its charts only here; istio-release.storage.googleapis.com stops at 1.30.
ISTIO_CHARTS=oci://ghcr.io/istio/release/charts
CERT_MANAGER_VERSION=v1.21.2
RENDERED=generated/ingress.rendered.yaml
RETRY_DELAY="${INGRESS_RETRY_DELAY:-5}"

# The rendered manifest carries the Cloudflare token, and the repo is public. Checked against git
# itself, before anything is written.
if ! git check-ignore -q "$RENDERED"; then
    echo "Error: talos/generated/ is not gitignored; add /talos/generated/ to .gitignore first."
    exit 1
fi

# A webhook can refuse requests for a few seconds after its chart reports ready, until its CA
# bundle is injected.
apply() {
    local attempt
    for attempt in 1 2 3 4 5; do
        if kubectl apply "$@"; then
            return 0
        fi
        echo "kubectl apply failed (attempt $attempt of 5); retrying in ${RETRY_DELAY}s"
        sleep "$RETRY_DELAY"
    done
    return 1
}

apply --server-side -f "https://github.com/kubernetes-sigs/gateway-api/releases/download/$GATEWAY_API_VERSION/standard-install.yaml"
apply -f ingress/namespaces.yaml
helm upgrade --install metallb metallb --repo https://metallb.github.io/metallb \
    --version "$METALLB_VERSION" -n metallb-system --wait
apply -f ingress/metallb-pool.yaml
helm upgrade --install istio-base "$ISTIO_CHARTS/base" --version "$ISTIO_VERSION" \
    -n istio-system --create-namespace --set defaultRevision=default --wait
helm upgrade --install istiod "$ISTIO_CHARTS/istiod" --version "$ISTIO_VERSION" \
    -n istio-system -f ingress/istiod-values.yaml --wait
# After the Gateway API CRDs: cert-manager looks for them only at startup.
helm upgrade --install cert-manager cert-manager --repo https://charts.jetstack.io \
    --version "$CERT_MANAGER_VERSION" -n cert-manager --create-namespace -f ingress/cert-manager-values.yaml --wait

umask 077
mkdir -p generated
trap 'rm -f "$RENDERED"' EXIT
op inject -f -i ingress/ingress.yaml.tpl -o "$RENDERED" >/dev/null
apply -f "$RENDERED"
echo "Applied. Check: kubectl -n istio-ingress get gateway pi-cluster; kubectl -n istio-ingress get certificate"
