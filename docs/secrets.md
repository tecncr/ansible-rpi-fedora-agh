# Secrets

## Layout

```
inventory/                                  (git-ignored)
├── hosts.yml
├── group_vars/rpi_adguard/
│   ├── vars.yml        plain: settings, public SSH keys, mapping vault_* -> rpi_agh_*
│   └── vault.yml       ENCRYPTED: become password, password hashes
├── host_vars/<host>/
│   ├── vars.yml        plain: rpi_agh_fqdn, rpi_agh_adguard_fqdn, ansible_host
│   └── vault.yml       optional, ENCRYPTED: per-host overrides of vault_* values
└── files/<host>/
    ├── host.pem        certificate (+ chain) for rpi_agh_fqdn
    ├── host.key        ENCRYPTED: its private key
    ├── adguard.pem     certificate (+ chain) for rpi_agh_adguard_fqdn
    ├── adguard.key     ENCRYPTED: its private key
    └── AdGuardHome.yaml  ENCRYPTED: full AdGuard Home config (contains the UI password hash)
```

`vars.yml` only refers to secrets (`"{{ vault_admin_password_hash }}"`, or
`lookup('ansible.builtin.file', ...)` for files), so you can read it without
the vault password, and `grep` can find where every value comes from. Ansible
decrypts vault-encrypted files transparently, both `vault.yml` and the files
read through the `file` lookup.

`make encrypt` encrypts every `vault.yml`, `*.key` and `AdGuardHome.yaml` that
is still plaintext. `make site` / `make bootstrap` refuse to run while any of
them is unencrypted (`make check-encrypted`). Certificates are public and may
stay plaintext.

Edit an encrypted file in place with:

```sh
ansible-vault edit inventory/group_vars/rpi_adguard/vault.yml
ansible-vault view inventory/files/agh01/AdGuardHome.yaml
```

## Vault values

| Variable | What |
|---|---|
| `vault_admin_become_password` | **Plaintext** sudo password of the admin user. Ansible uses it for privilege escalation, so it must match `vault_admin_password_hash` |
| `vault_root_password_hash` | crypt(3) hash for root |
| `vault_admin_password_hash` | crypt(3) hash for the admin user |
| `vault_services_password_hash` | crypt(3) hash for `services` |

The role validates that every hash looks like a crypt(3) string (`$y$`,
`$gy$`, `$6$`, `$5$`, `$2b$`, ...), so a plaintext password put there by
mistake is rejected rather than written to `/etc/shadow`.

### Generating hashes

```sh
sudo dnf install -y mkpasswd
mkpasswd --method=yescrypt            # Fedora's default scheme
# or
openssl passwd -6                     # SHA-512 crypt
```

Hashes are stored, not plaintext passwords. Because the hash string stays the
same, the `user` module is idempotent (`update_password: always` changes
nothing on re-runs). It also avoids a passlib dependency on the controller.
The single plaintext value, the become password, is unavoidable: sudo needs
it.

## Vault password

Any standard mechanism works:

```sh
ansible-playbook site.yml --ask-vault-pass
ansible-playbook site.yml --vault-password-file ~/.config/rpi-agh/vault-pass   # chmod 600
export ANSIBLE_VAULT_PASSWORD_FILE=~/.config/rpi-agh/vault-pass
make site VAULT_PASS_FILE=~/.config/rpi-agh/vault-pass LIMIT=agh01
```

### Bitwarden

`tools/vault-pass-bitwarden.sh` is an executable vault password client. It
prints the password of the Bitwarden item `ansible-vault rpi-agh` (override
the name with `RPI_AGH_VAULT_ITEM`), using `rbw` when installed and `bw`
otherwise:

```sh
export BW_SESSION="$(bw unlock --raw)"        # bw only; rbw uses its agent
make site VAULT_PASS_FILE=tools/vault-pass-bitwarden.sh LIMIT=agh01
```

The vault password then never touches the disk.

## Certificates

Validation runs on the controller (community.crypto + cryptography in the
venv) **before** anything on the Pi changes. For both the host and the
AdGuard Home certificate it checks that:

- the PEM parses and is not expired (it warns when expiry is within 14 days);
- a SAN is `DNS:<fqdn>` or a matching single-label wildcard `DNS:*.<domain>`;
- the private key's public key equals the certificate's public key.

A file may contain the full chain (leaf first). Supported keys are RSA, EC and
Ed25519 in PKCS#8 or traditional PEM, unencrypted.

Where they end up on the Pi:

| Source | Destination | Mode |
|---|---|---|
| `host.pem` | `/etc/pki/tls/certs/<fqdn>.pem`, linked as `/etc/cockpit/ws-certs.d/0-<hostname>.cert` | 0644 root |
| `host.key` | `/etc/pki/tls/private/<fqdn>.pem`, linked as `/etc/cockpit/ws-certs.d/0-<hostname>.key` | 0400 root |
| `adguard.pem` | `/services/.local/containers/adguardhome/certs/<adguard_fqdn>.pem` | 0644 services |
| `adguard.key` | `/services/.local/containers/adguardhome/certs/<adguard_fqdn>.key` | 0400 services |

Inside the container these are `/opt/adguardhome/certs/<adguard_fqdn>.pem|.key`.
Point `tls.certificate_path` and `tls.private_key_path` in `AdGuardHome.yaml`
at them. The role warns when they differ.

### Renewal

Replace the files in `inventory/files/<host>/`, re-encrypt the key, and run:

```sh
make site LIMIT=agh01 TAGS=tls,adguardhome
```

Cockpit and AdGuard Home are restarted only when their files changed.

## Logging

Every task that handles a private key, a password hash or `AdGuardHome.yaml`
uses `no_log: true`, and the role's argument spec marks those options
`no_log`. As a side effect, Ansible may print `$REDACTED$` where a log line
contains a substring of a secret (for example the AdGuard FQDN, which also
appears in `AdGuardHome.yaml`).
