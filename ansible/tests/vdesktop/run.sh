#!/bin/sh
# Wrapper for the vdesktop harness. USE THIS instead of calling ansible directly.
#
#   cd ansible
#   tests/vdesktop/run.sh setup.yml
#   tests/vdesktop/run.sh setup.yml verify-sunshine-repo.yml
#   tests/vdesktop/run.sh lint
#
# Same reason as tests/apt-sources/run.sh: ansible.cfg points vault_password_file
# at a script that prompts 1Password, and ansible calls it on nearly every
# invocation. A test loop run without this wrapper queues one prompt per run.
# Nothing here reads a vaulted variable, so the stub password is sufficient.
#
# The stub is shared with the apt-source harness rather than copied -- it is not
# specific to either subject, as tests/apt-sources/no-vault.sh says itself.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
root=$(CDPATH= cd -- "$here/../.." && pwd)
export ANSIBLE_VAULT_PASSWORD_FILE="$here/../apt-sources/no-vault.sh"

cd "$root"

if [ "${1:-}" = "lint" ]; then
    shift
    exec .venv/bin/ansible-lint --exclude tests/vdesktop/roles \
        "${@:-tests/vdesktop/*.yml}"
fi

[ $# -gt 0 ] || { echo "usage: $0 <playbook.yml> [playbook.yml ...] | lint" >&2; exit 2; }

set -- $(for p in "$@"; do printf '%s ' "tests/vdesktop/$(basename "$p")"; done)
exec .venv/bin/ansible-playbook -i tests/vdesktop/inventory.ini "$@"
