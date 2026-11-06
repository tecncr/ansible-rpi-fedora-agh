# ansible-rpi-fedora-agh

Ansible playbooks and the `rpi_agh` role that turn a freshly flashed **Fedora
Server (aarch64) Raspberry Pi** into an **AdGuard Home** DNS server, running
as a rootless Podman Quadlet.

Fedora on Raspberry Pi cannot do release upgrades, so each new release means
reflashing every Pi and setting it up again. This repo replaces the manual
procedure with something you can re-run as often as you like:

- **Idempotent.** The second run changes nothing. A run after a reflash
  rebuilds the Pi from scratch.
- **Fail-fast validation.** Every required value has to be present and
  well formed before anything on the Pi changes: FQDNs, users, password
  hashes, SSH keys, certificates (not expired, carry the FQDN, match the key)
  and `AdGuardHome.yaml`.
- **Secrets in ansible-vault.** Password hashes, private keys and
  `AdGuardHome.yaml` are encrypted at rest. The real inventory is git-ignored.
- **One Pi at a time** (`serial: 1`), so the rest of your DNS fleet keeps
  answering while one Pi upgrades and reboots.

## What it does

| Phase | Step | Tag |
|---|---|---|
| — | Validate all inputs on the controller, then check the target is a Raspberry Pi running Fedora aarch64 | `always` |
| 1 | `/etc/dnf/dnf.conf` (fastestmirror, gpgcheck, `installonly_limit=2`, clean_requirements_on_remove), `dnf upgrade --refresh`, install every needed package | `packages` |
| 1 | Static hostname, `ip_unprivileged_port_start=23`, zram (`ram`, zstd), I2C + DS3231 overlay in `/boot/efi/config.txt` | `base` |
| 1 | Rename the ethernet NetworkManager profile to `Ethernet` and store it as `Ethernet.nmconnection` (all other settings unchanged) | `network` |
| 1 | Remove BLS entries, rescue images and initramfs files that belong to a different machine ID | `boot` |
| 1 | **Reboot**, only when something above requires it | `reboot` |
| 2 | dnf5 automatic updates (`apply_updates=True`, `reboot=when-needed`) | `updates` |
| 2 | Check the DS3231 shows up as `UU` at 0x68, add `rtc-ds3231.service`, enable NTP, keep the RTC in UTC, write the RTC once NTP is synced | `time` |
| 2 | Host TLS certificate and key, wired into Cockpit | `tls` |
| 2 | PCP / pmlogger | `pcp` |
| 2 | Admin user (UID/GID 1000), `services` user (UID/GID 2000, home `/services` with the SELinux home label), subuid/subgid, passwords for all three accounts, exclusive `authorized_keys` | `users` |
| 2 | Podman (root and rootless), sockets, lingering, cockpit-podman | `podman` |
| 2 | Mask systemd-resolved and use the bootstrap resolver (9.9.9.9) | `dns` |
| 2 | sshd: public keys only, no root login, `LoginGraceTime 0`, `ClientAliveCountMax 2`, then confirm the settings actually in effect | `ssh` |
| 2 | firewalld: remove `dhcpv6-client`, add `dns`, `https`, `http3`, `dns-over-tls`, `dns-over-quic` (permanent and runtime) | `firewall` |
| 2 | AdGuard Home as a rootless Quadlet: certificates, `AdGuardHome.yaml`, image, auto-update timer, image prune after each auto-update | `adguardhome` |
| 2 | Wait up to 300 s for `dig @127.0.0.1 tecncr.com`, then point the `Ethernet` profile's DNS at 127.0.0.1 | `dns` |

## Quick start

```sh
# 1. Tooling (project-local venv + collections)
make setup

# 2. Inventory with your hosts and secrets (git-ignored)
cp -r inventory.example inventory
$EDITOR inventory/hosts.yml inventory/host_vars/*/vars.yml inventory/group_vars/rpi_adguard/vars.yml
$EDITOR inventory/group_vars/rpi_adguard/vault.yml
cp ~/certs/agh01.* inventory/files/agh01/                 # host.pem, host.key, adguard.pem, adguard.key
cp ~/agh/agh01/AdGuardHome.yaml inventory/files/agh01/
make encrypt                                              # encrypts vault.yml, *.key and AdGuardHome.yaml

# 3. After flashing a Pi
make forget-hostkey HOST=agh01.lan.example.com            # the reflashed Pi has new host keys
make bootstrap LIMIT=agh01                                # only if root is the only account that can log in
make site LIMIT=agh01
```

To run `ansible-playbook` directly, activate the venv (`. .venv/bin/activate`)
and pass a vault password with `--ask-vault-pass`, `--vault-password-file`, or
`ANSIBLE_VAULT_PASSWORD_FILE` (see [docs/secrets.md](docs/secrets.md)).

## Repository layout

```
ansible.cfg                 project config (inventory, roles, collections, pipelining)
site.yml                    full setup: phase 1 + reboot + phase 2
bootstrap.yml               optional: create the admin user as root on a fresh image
requirements.txt / -dev.txt pinned ansible-core, cryptography (and ansible-lint)
requirements.yml            pinned collections: community.crypto, ansible.posix
Makefile                    setup, lint, encrypt, bootstrap, site, ...
inventory.example/          template inventory; copy it to inventory/
tools/vault-pass-bitwarden.sh  vault password client backed by Bitwarden (bw / rbw)
roles/rpi_agh/              the role (see its README)
docs/                       detailed documentation
```

## Documentation

- [docs/workflow.md](docs/workflow.md): flashing, bootstrap, first run, re-runs, tags, adding Pis, troubleshooting
- [docs/variables.md](docs/variables.md): every variable, required or optional
- [docs/secrets.md](docs/secrets.md): vault layout, password hashes, certificates, the Bitwarden vault client
- [docs/design.md](docs/design.md): how each manual step was made idempotent, and where the role deliberately differs from the original procedure
- [roles/rpi_agh/README.md](roles/rpi_agh/README.md): role interface, tags, custom modules

## Requirements

- Controller: Python 3.12+ and `make`. `make setup` installs ansible-core 2.22,
  cryptography and the collections into `.venv/` and `collections/`.
- Targets: Raspberry Pi 3 or 4 running Fedora Server aarch64 (44, 45, ...),
  reachable over SSH, with a DS3231 RTC on I2C bus 1.
