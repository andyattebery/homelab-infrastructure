#!/bin/sh
# Wrapper for the apt-source tests. USE THIS instead of calling ansible directly.
#
#   cd ansible
#   tests/apt-sources/run.sh setup.yml
#   tests/apt-sources/run.sh setup.yml verify-fish.yml
#   tests/apt-sources/run.sh lint
#
# It exists for one reason: ansible.cfg points vault_password_file at a script
# that prompts 1Password, and ansible calls it on nearly every invocation. A test
# loop run without this wrapper opens a 1Password prompt per run and leaves
# hundreds of them queued waiting for a human. Nothing here uses a vaulted
# variable, so the stub password is correct and sufficient.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/../.." && pwd)
export ANSIBLE_VAULT_PASSWORD_FILE="$here/no-vault.sh"

cd "$root"

if [ "${1:-}" = "lint" ]; then
    shift
    exec .venv/bin/ansible-lint --exclude tests/apt-sources/roles \
        "${@:-tests/apt-sources/*.yml}"
fi

[ $# -gt 0 ] || { echo "usage: $0 <playbook.yml> [playbook.yml ...] | lint" >&2; exit 2; }

set -- $(for p in "$@"; do printf '%s ' "tests/apt-sources/$(basename "$p")"; done)
exec .venv/bin/ansible-playbook -i tests/apt-sources/inventory.ini "$@"
