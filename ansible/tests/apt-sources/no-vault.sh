#!/bin/sh
# Vault password stub for the apt-source tests ONLY.
#
# ansible.cfg points vault_password_file at scripts/vault-password-op.sh, which
# prompts 1Password. Ansible calls it on essentially every invocation, so an
# unattended test loop generates one prompt per run -- hundreds of them, all
# needing a human, none of them necessary: nothing under tests/apt-sources/ uses
# a vaulted variable.
#
# This returns a string that is deliberately NOT a real password. Any playbook
# that genuinely needs a secret fails to decrypt, loudly, instead of silently
# doing the wrong thing. That is the desired behaviour: it means this stub can
# never quietly become the way real secrets are handled.
echo apt-source-tests-no-vault-required
