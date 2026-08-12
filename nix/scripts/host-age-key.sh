#!/usr/bin/env sh
# Ensure a host has a sops age key, and print its PUBLIC half on stdout.
#
# The key is generated on the Mac, stored in 1Password, and -- with --target -- installed
# on the host over ssh. Storing it is the point: a re-image then restores the same key, so
# .sops.yaml keeps its recipient list and secrets.yaml never needs re-encrypting.
#
# TWO single-line fields, not one multi-line one:
#
#   op://Home Lab/<host>/nix/age key          AGE-SECRET-KEY-...
#   op://Home Lab/<host>/nix/age public key   age1...
#
# 1Password flattens newlines in these fields, so storing age-keygen's three-line output
# verbatim comes back as one line beginning with "# created:". age treats a leading "#" as
# a comment, so such a file contains NO identity at all -- sops-nix would fail to decrypt
# on that host, silently until first boot. Splitting the two halves into their own
# single-line fields means there is nothing to flatten, and the public half never has to be
# derived back out of the secret.
#
# The on-host file is reconstructed at install time as:
#
#   # public key: age1...
#   AGE-SECRET-KEY-...
#
# The comment is what lets a later run read the public half off the host with grep, with no
# age binary needed there.
#
# Secret handling. The secret is never printed and never written to a local file; it
# reaches the host as ssh stdin rather than inside the remote command string. It IS passed
# to `op` as a command argument, which 1Password warns can be visible to other processes.
# That is deliberate: the key goes into a section on the host's own item, and those items
# already hold other credentials -- pi-rack's carries the NUT passwords for five clients.
# `op item edit --template` REPLACES rather than merges (its documented flow is
# `op item get --format=json` -> edit -> push back, and its passkey warning confirms
# omissions are overwritten), so the template route would mean reading every existing
# secret on the item just to add a field, and risking their loss on write. Assignment
# statements touch only the named fields and create the section if missing.
#
# This runs inside a script, so nothing lands in interactive shell history.
set -euo pipefail

VAULT="Home Lab"
KEY_PATH="/var/lib/sops-nix/key.txt"
KEY_DIR="/var/lib/sops-nix"

usage() {
  cat >&2 <<'EOF'
Usage: host-age-key.sh [--target <ssh-target>] <hostname>

Prints the host's age PUBLIC key on stdout. Idempotent.

  --target <ssh-target>   also install the key on that host (needs ssh + passwordless sudo)

Without --target the key is created and stored in 1Password only, which is what a machine
that does not exist yet needs. Run again with --target on the day it is built and the same
stored key is installed.

Feed the printed public key to add-sops-recipient.sh.
EOF
  exit 1
}

TARGET=""
while [ $# -gt 0 ]; do
  case "$1" in
    --target) [ $# -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    -h|--help) usage ;;
    -*) echo "Unknown option: $1" >&2; usage ;;
    *) break ;;
  esac
done

[ $# -eq 1 ] || usage
HOST="$1"
OP_SECRET_REF="op://$VAULT/$HOST/nix/age key"
OP_PUBLIC_REF="op://$VAULT/$HOST/nix/age public key"

# --- helpers -----------------------------------------------------------------

op_has_key() { op read "$OP_SECRET_REF" >/dev/null 2>&1; }

host_has_key() {
  [ -n "$TARGET" ] || return 1
  ssh -o StrictHostKeyChecking=accept-new "$TARGET" "sudo test -f $KEY_PATH"
}

# $1 = public key, $2 = secret key. age ignores the comment line; the comment exists so the
# public half can be read back off the host later without an age binary there.
key_file_text() { printf '# public key: %s\n%s\n' "$1" "$2"; }

install_on_target() {
  ssh "$TARGET" "sudo sh -c 'umask 077; mkdir -p $KEY_DIR && cat > $KEY_PATH'"
  echo "==> Installed key at $TARGET:$KEY_PATH" >&2
}

# $1 = public key, $2 = secret key. Both single-line by construction.
store_in_op() {
  if op item get "$HOST" --vault "$VAULT" >/dev/null 2>&1; then
    op item edit "$HOST" --vault "$VAULT" \
      "nix.age key[password]=$2" "nix.age public key[text]=$1" >/dev/null
    echo "==> Added a 'nix' section to the existing '$HOST' item in $VAULT" >&2
  else
    op item create --category Server --title "$HOST" --vault "$VAULT" \
      "nix.age key[password]=$2" "nix.age public key[text]=$1" >/dev/null
    echo "==> Created the '$HOST' item (Server) in $VAULT with a 'nix' section" >&2
  fi

  # Read back rather than trust the write. The public half is compared exactly -- it is not
  # a secret, so a mismatch can be shown. The secret half is only shape-checked.
  stored_pub=$(op read "$OP_PUBLIC_REF")
  [ "$stored_pub" = "$1" ] \
    || { echo "Error: stored public key does not match: got '$stored_pub', expected '$1'" >&2; exit 1; }
  op read "$OP_SECRET_REF" | grep -q '^AGE-SECRET-KEY-' \
    || { echo "Error: '$OP_SECRET_REF' is not an AGE-SECRET-KEY- value" >&2; exit 1; }
  echo "==> Stored and verified $OP_SECRET_REF" >&2
}

# --- the states --------------------------------------------------------------

# 1. Key already on the host. Read its public half there; no age binary needed remotely.
if host_has_key; then
  PUB=$(ssh "$TARGET" "sudo grep '^# public key: ' $KEY_PATH" | sed 's/^# public key: //')
  [ -n "$PUB" ] || { echo "Error: $KEY_PATH on $TARGET has no '# public key:' line" >&2; exit 1; }
  if ! op_has_key; then
    {
      echo "WARNING: $HOST has a key on the host but no copy at $OP_SECRET_REF."
      echo "         If that disk is lost or re-imaged the key goes with it, and the host"
      echo "         needs a new sops recipient plus a full re-encrypt."
      echo "         Backfill runbook: plans/flake-host-enumeration-and-age-keys.md"
    } >&2
  fi
  printf '%s\n' "$PUB"
  exit 0
fi

# 2. Key in 1Password but not on the host -- the re-image case. Also the no-target case,
#    where there is nothing to install and we just report the public half.
if op_has_key; then
  PUB=$(op read "$OP_PUBLIC_REF")
  [ -n "$PUB" ] \
    || { echo "Error: $OP_SECRET_REF exists but $OP_PUBLIC_REF is empty" >&2; exit 1; }
  if [ -n "$TARGET" ]; then
    key_file_text "$PUB" "$(op read "$OP_SECRET_REF")" | install_on_target
  fi
  printf '%s\n' "$PUB"
  exit 0
fi

# 3. Nothing anywhere: generate, store, and install if there is somewhere to install to.
command -v age-keygen >/dev/null 2>&1 \
  || { echo "Error: age-keygen not found. Install it with: brew install age" >&2; exit 1; }

KEY=$(age-keygen 2>/dev/null)
PUB=$(printf '%s\n' "$KEY" | sed -n 's/^# public key: //p')
SECRET=$(printf '%s\n' "$KEY" | grep '^AGE-SECRET-KEY-')
[ -n "$PUB" ] && [ -n "$SECRET" ] \
  || { echo "Error: could not parse age-keygen output" >&2; exit 1; }

store_in_op "$PUB" "$SECRET"
if [ -n "$TARGET" ]; then
  key_file_text "$PUB" "$SECRET" | install_on_target
else
  echo "==> No --target given; key stored only. Re-run with --target once the host exists." >&2
fi
printf '%s\n' "$PUB"
