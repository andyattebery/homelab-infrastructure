#!/usr/bin/env bash
set -euo pipefail

# Fail if nix/secrets/vars.nix is not the populated file that op inject produces.
#
# This exists because the failure is otherwise silent and lands somewhere unrelated.
# vars.nix is the one secrets file marked assume-unchanged (git ls-files -v shows a
# lowercase `h`), so `git status` never reports it and `git diff --quiet HEAD` says
# "unchanged" even when it is populated -- the check has to inspect content.
#
# When it reverts to the committed placeholder, the symptoms are:
#   * update.sh dies at its final flake check with "attribute 'network-01' missing",
#     AFTER it has already rewritten nix-image and flake.lock
#   * deploy-host.sh reads domainName = "example.com" and quietly builds an FQDN of
#     <host>.example.com, so the run fails looking like a DNS problem
#
# Called first by update.sh and before the DOMAIN lookup in deploy-host.sh, so the
# failure is immediate and names the fix.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VARS="$SCRIPT_DIR/../secrets/vars.nix"
TPL="$SCRIPT_DIR/../secrets/vars.nix.tpl"

fail() {
    echo "Error: $*" >&2
    echo "  Run: $SCRIPT_DIR/populate-secrets-from-op.sh" >&2
    exit 1
}

[[ -f "$VARS" ]] || fail "nix/secrets/vars.nix does not exist."

# The template defines what "populated" means, so its absence has to be fatal. Without
# this check the guard FAILS OPEN: keys_of on a missing file yields nothing, comm finds
# nothing missing, and the placeholder is accepted. Measured, not assumed.
[[ -f "$TPL" ]] || fail "nix/secrets/vars.nix.tpl is missing -- cannot verify vars.nix."

# op inject never ran: template tokens survived into the output. Written as an explicit
# if rather than `grep ... && fail`, which works only because set -e exempts a failing
# command inside an && list -- correct, but easy to "fix" into a bug.
if grep -q "{{ *op://" "$VARS"; then
    fail "vars.nix still contains op:// tokens -- it was copied, not injected."
fi

# Top-level keys must cover the template's. Top-level entries are indented two spaces;
# nested ones (network-01.adguardhomeUsername and friends) are indented four, so this
# matches only the outer set. The committed placeholder has the four scalars and none
# of the per-host attrsets, which is exactly what breaks evaluation.
keys_of() { sed -n 's/^  \([A-Za-z0-9_-][A-Za-z0-9_-]*\) *=.*/\1/p' "$1" | sort -u; }

missing=$(comm -23 <(keys_of "$TPL") <(keys_of "$VARS") | tr '\n' ' ')
if [[ -n "${missing// /}" ]]; then
    # Key names only -- these are structural (network-01, nim, nut), never values.
    fail "vars.nix is missing top-level keys: ${missing}-- this looks like the committed placeholder."
fi
