# Convenience targets. Every target uses the project-local venv.
#
#   make setup                         create .venv and install collections
#   make lint                          ansible-lint + syntax checks
#   make encrypt                       vault-encrypt secrets in inventory/
#   make bootstrap LIMIT=agh01         create the admin user as root
#   make site LIMIT=agh01 [TAGS=tls]   full (or partial) setup
#
# Vault password: set VAULT_PASS_FILE (file or executable client, e.g.
# tools/vault-pass-bitwarden.sh). Otherwise you are prompted for it.

VENV        ?= .venv
PYTHON      ?= python3
BIN         := $(VENV)/bin
INVENTORY_DIR ?= inventory
INVENTORY   ?= $(INVENTORY_DIR)/hosts.yml
LIMIT       ?=
TAGS        ?=
EXTRA       ?=
VAULT_PASS_FILE ?=

ifeq ($(VAULT_PASS_FILE),)
VAULT_ARGS := --ask-vault-pass
else
VAULT_ARGS := --vault-password-file $(VAULT_PASS_FILE)
endif

PLAY_ARGS := -i $(INVENTORY) $(VAULT_ARGS) \
	$(if $(LIMIT),--limit $(LIMIT)) $(if $(TAGS),--tags $(TAGS)) $(EXTRA)

SECRET_FILES = $(wildcard $(INVENTORY_DIR)/group_vars/*/vault.yml $(INVENTORY_DIR)/host_vars/*/vault.yml \
	$(INVENTORY_DIR)/files/*/*.key $(INVENTORY_DIR)/files/*/AdGuardHome.yaml)

.PHONY: help setup venv collections lint syntax encrypt check-encrypted \
	bootstrap site diff forget-hostkey clean distclean

help:
	@sed -n 's/^#   //p' $(MAKEFILE_LIST)

setup: venv collections

venv: $(BIN)/ansible-playbook

$(BIN)/ansible-playbook: requirements.txt requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -r requirements-dev.txt
	@touch $@

collections: venv requirements.yml
	$(BIN)/ansible-galaxy collection install -r requirements.yml -p collections

syntax: setup
	$(BIN)/ansible-playbook -i inventory.example/hosts.yml site.yml --syntax-check
	$(BIN)/ansible-playbook -i inventory.example/hosts.yml bootstrap.yml --syntax-check

# Lint against the example inventory; never creates or touches inventory/
lint: setup syntax
	ANSIBLE_INVENTORY=inventory.example/hosts.yml $(BIN)/ansible-lint

# Encrypt every secret file that is not encrypted yet
encrypt: venv
	@for f in $(SECRET_FILES); do \
		if head -n1 "$$f" | grep -q '^\$$ANSIBLE_VAULT;'; then echo "already encrypted: $$f"; \
		else $(BIN)/ansible-vault encrypt $(VAULT_ARGS) "$$f"; fi; \
	done

# Fail when a secret file is still in plaintext
check-encrypted:
	@rc=0; for f in $(SECRET_FILES); do \
		head -n1 "$$f" | grep -q '^\$$ANSIBLE_VAULT;' || { echo "NOT ENCRYPTED: $$f"; rc=1; }; \
	done; exit $$rc

bootstrap: setup check-encrypted
	$(BIN)/ansible-playbook bootstrap.yml $(PLAY_ARGS)

site: setup check-encrypted
	$(BIN)/ansible-playbook site.yml $(PLAY_ARGS)

# Dry run with diffs (best effort: see docs/workflow.md)
diff: setup check-encrypted
	$(BIN)/ansible-playbook site.yml $(PLAY_ARGS) --check --diff

# A reflashed Pi has new SSH host keys
forget-hostkey:
	@test -n "$(HOST)" || { echo "usage: make forget-hostkey HOST=<name or address>"; exit 1; }
	ssh-keygen -R "$(HOST)"

clean:
	rm -rf collections

distclean: clean
	rm -rf $(VENV)
