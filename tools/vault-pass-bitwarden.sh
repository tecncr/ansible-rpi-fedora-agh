#!/bin/sh
# ansible-vault password client backed by Bitwarden.
#
#   ANSIBLE_VAULT_PASSWORD_FILE=tools/vault-pass-bitwarden.sh ansible-playbook site.yml
#   make site VAULT_PASS_FILE=tools/vault-pass-bitwarden.sh LIMIT=agh01
#
# Uses rbw when installed (unlocks via its agent), otherwise the official bw
# CLI (needs an unlocked session: export BW_SESSION="$(bw unlock --raw)").
# The item name can be overridden with RPI_AGH_VAULT_ITEM.
set -eu

item="${RPI_AGH_VAULT_ITEM:-ansible-vault rpi-agh}"

if command -v rbw >/dev/null 2>&1; then
    exec rbw get "$item"
elif command -v bw >/dev/null 2>&1; then
    exec bw get password "$item"
else
    echo "vault-pass-bitwarden: neither rbw nor bw is installed" >&2
    exit 1
fi
