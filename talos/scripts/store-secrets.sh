#!/usr/bin/env bash
set -euo pipefail

TALOS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$TALOS_DIR"

VAULT="Home Lab"
ITEM="pi-cluster"

usage() {
    echo "Usage: $(basename "$0")"
    echo
    echo "Generate the cluster's secrets bundle into generated/secrets.yaml and store its 14 values"
    echo "in a new 'talos' section of the $ITEM 1Password item. Run once per cluster, before"
    echo "gen-config.sh. Refuses if the item already has a talos section: that is a live cluster's"
    echo "PKI, and replacing it locks every node out."
    exit 1
}

[[ $# -eq 0 ]] || usage

# The bundle is the cluster's keys, and the repo is public. Checked against git itself rather
# than assumed from .gitignore, before anything is written.
if ! git check-ignore -q generated/secrets.yaml; then
    echo "Error: talos/generated/ is not gitignored; add /talos/generated/ to .gitignore first."
    exit 1
fi
if [[ -e generated/secrets.yaml ]]; then
    echo "Error: generated/secrets.yaml already exists; this machine has made a bundle before."
    exit 1
fi

umask 077
mkdir -p generated

# The item's only read. Values stay in memory and go to jq and op on stdin, never in argv
# (visible to other processes) or a here-string (a temp file in bash 3.2).
CURRENT="$(op item get "$ITEM" --vault "$VAULT" --format json)"
HAS_TALOS="$(printf '%s' "$CURRENT" | jq 'any(.sections[]?; .label == "talos")')"
if [[ "$HAS_TALOS" != false ]]; then
    echo "Error: $ITEM already has a talos section; it holds a cluster's PKI. Not replacing it."
    exit 1
fi

# From here on, a failure removes the new bundle, so the script can simply be re-run.
STORED=""
cleanup() {
    [[ -n "$STORED" ]] || rm -f generated/secrets.yaml
}
trap cleanup EXIT

talosctl gen secrets -o generated/secrets.yaml

# secrets.yaml.tpl is the one map between bundle and item: each of its leaves names the field
# that holds the bundle value at the same path. op inject reads the fields back through it.
TEMPLATE="$(printf '%s' "$CURRENT" | jq \
    --slurpfile tpl <(yq -o json secrets.yaml.tpl) \
    --slurpfile bundle <(yq -o json generated/secrets.yaml) \
    --arg open "{{ op://$VAULT/$ITEM/talos/" '
    def field_label($ref):
        ($ref | ltrimstr($open) | rtrimstr(" }}")) as $l
        | if $open + $l + " }}" == $ref then $l else error("unexpected reference in secrets.yaml.tpl: \($ref)") end;
    def bundle_value($p):
        ($bundle[0] | getpath($p)) as $v
        | if ($v | type) == "string" and $v != "" then $v else error("bundle has no value at \($p | join("."))") end;
    .sections = (.sections // []) + [{id: "talos", label: "talos"}]
    | .fields = (.fields // []) + [
        $tpl[0] | paths(type == "string") as $p
        | {section: {id: "talos"}, type: "CONCEALED", label: field_label($tpl[0] | getpath($p)), value: bundle_value($p)}
      ]')"

printf '%s\n' "$TEMPLATE" | op item edit "$ITEM" --vault "$VAULT" >/dev/null
STORED=1
echo "Stored the bundle in the talos section of $ITEM; kept generated/secrets.yaml."
