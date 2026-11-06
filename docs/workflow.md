# Workflow

## 1. One-time controller setup

```sh
make setup              # .venv/ with ansible-core, cryptography, ansible-lint + collections/
cp -r inventory.example inventory
```

`inventory/` is git-ignored. Keep it somewhere safe (it holds your encrypted
secrets), e.g. a private repository or a backed-up directory symlinked here.
To use an inventory stored elsewhere, pass `INVENTORY_DIR=/path` to `make`
or `-i /path/hosts.yml` to `ansible-playbook`. Always point `-i` at
`hosts.yml`, not at the directory. With a directory, Ansible tries to parse
every file under it as inventory, including the certificates, keys and
`AdGuardHome.yaml` in `files/`. `ansible.cfg` also ignores `files/` when a
directory is passed, as a safety net.

Fill in the inventory as described in [variables.md](variables.md) and
[secrets.md](secrets.md), then run `make encrypt`.

## 2. Flash the Pi

Write the Fedora Server aarch64 raw image to the SD card / SSD, for example:

```sh
sudo arm-image-installer --image=Fedora-Server-45-*.aarch64.raw.xz \
  --target=rpi4 --media=/dev/sdX --resizefs \
  --addkey=$HOME/.ssh/id_ed25519.pub --norootpass
```

You can get onto the Pi in one of two ways:

- **Root SSH key only** (`--addkey`): run `bootstrap.yml` first (step 4). It
  creates the admin user.
- **initial-setup**: create the admin user on the console with the name from
  `rpi_agh_admin_user`, make it an administrator (wheel), and set the password
  that matches `vault_admin_become_password`. Skip `bootstrap.yml`.

The admin user must end up with UID 1000. The role checks this and stops if
UID 1000 belongs to someone else.

## 3. Forget the old host key

A reflashed Pi has new SSH host keys, and SSH (correctly) refuses to connect
until you drop the old ones:

```sh
make forget-hostkey HOST=agh01.lan.example.com
make forget-hostkey HOST=192.168.1.53          # if you also connected by IP
```

## 4. Bootstrap (root-key images only)

```sh
make bootstrap LIMIT=agh01
```

Connects as `root` and creates the admin user (UID/GID 1000, `wheel`) with its
password hash and `authorized_keys`. It then reconnects as the admin user to
check that sudo works. Once `site.yml` has run, root can no longer log in over
SSH, so `bootstrap.yml` only works on a freshly flashed Pi.

## 5. Full setup

```sh
make site LIMIT=agh01
# or: ansible-playbook site.yml --limit agh01 --vault-password-file ...
```

The play connects as the admin user and uses sudo with
`vault_admin_become_password`. It runs:

1. **Validation.** Controller-side checks on every value, then target checks
   (Fedora, aarch64, Raspberry Pi model, UIDs). Nothing on the Pi has changed
   at this point.
2. **Phase 1.** Upgrade, packages, hostname, sysctl, zram, `config.txt`, the
   NetworkManager profile, `/boot` cleanup.
3. **Reboot**, but only when one is needed: phase 1 changed packages, zram
   or `config.txt` in this run, **or** the system still shows a pending
   reboot (`dnf needs-restarting`, RTC overlay not loaded, zram not using the
   configured algorithm). The second check covers an earlier run that failed
   before it could reboot. The play prints the reasons, waits for the Pi to
   come back (`rpi_agh_reboot_timeout`, 900 s by default), and then confirms
   that the overlay and zram are active.
4. **Phase 2.** Everything else, ending with the DNS health check and the
   switch to 127.0.0.1.

Without `LIMIT`, every host in `rpi_adguard` is processed **one at a time**
(`serial: 1`). If a host fails, the play stops before touching the next one.
Override with `-e rpi_agh_serial=2` (or `100%`) if you really want parallel
runs.

## 6. Re-runs

`site.yml` is idempotent. On a finished Pi, a second run reports `changed=0`
(the system upgrade may still report changes when updates are available).
Typical partial runs:

```sh
make site LIMIT=agh01 TAGS=tls             # renewed host certificate -> restart cockpit
make site LIMIT=agh01 TAGS=adguardhome     # renewed AGH certificate / new Quadlet -> restart AGH
make site LIMIT=agh01 TAGS=users           # rotated passwords or SSH keys
make site TAGS=ssh                         # sshd settings on every Pi
```

Validation is tagged `always`, so it runs with every tag selection.

Available tags: `phase1`, `packages`, `base`, `network`, `boot`, `reboot`,
`phase2`, `updates`, `time`, `tls`, `pcp`, `users`, `podman`, `dns`, `ssh`,
`firewall`, `adguardhome`.

> Running only `phase2` on a fresh Pi does not work: phase 2 depends on the
> packages, the `Ethernet` profile and the RTC overlay from phase 1.

### AdGuardHome.yaml on re-runs

AdGuard Home rewrites its configuration at runtime (schema migrations,
changes made in the web UI). By default the role **only seeds** the file when
it does not exist, so it never reverts changes made through the UI. To push
the inventory copy, overwriting the one on the Pi:

```sh
make site LIMIT=agh01 TAGS=adguardhome EXTRA='-e rpi_agh_adguard_config_force=true'
```

Before a reflash, copy the live file back into the inventory so the rebuilt
Pi starts from the latest configuration:

```sh
ssh services@agh01 cat .local/containers/adguardhome/conf/AdGuardHome.yaml \
  > inventory/files/agh01/AdGuardHome.yaml
ansible-vault encrypt inventory/files/agh01/AdGuardHome.yaml
```

### Dry runs

`make diff LIMIT=agh01` runs `--check --diff`. This is useful on a host that
has already been set up, to preview changes. On a freshly flashed host it is
only a rough preview: later tasks depend on users, packages and files that
check mode never creates.

## Adding a Pi

1. Add the host under `rpi_adguard` in `inventory/hosts.yml`.
2. Create `inventory/host_vars/<host>/vars.yml` with `rpi_agh_fqdn` (and
   `rpi_agh_adguard_fqdn` if it differs).
3. Put `host.pem`, `host.key`, `adguard.pem`, `adguard.key` and
   `AdGuardHome.yaml` in `inventory/files/<host>/`, then run `make encrypt`.
4. Per-host secrets that differ from the shared ones (for example a different
   root password) go in `inventory/host_vars/<host>/vault.yml`, which
   overrides group values.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | The Pi was reflashed: `make forget-hostkey HOST=...` |
| `Missing sudo password` / `Incorrect sudo password` | `vault_admin_become_password` does not match the admin user's current password (e.g. the one set in initial-setup) |
| `missing required arguments: ...` | A required variable is not defined: see [variables.md](variables.md) |
| `... is required and must be a non-empty string` | The variable is defined but empty |
| `certificate is not usable` | Expired, wrong SAN, or the key does not belong to the certificate. The message says which |
| `Reboot \| RTC overlay is loaded now` fails | The Pi rebooted but `/sys/bus/i2c/devices/1-0068` is missing: check the `dtoverlay=` line in `/boot/efi/config.txt` |
| `Reboot \| zram uses the configured algorithm now` fails | Check `/etc/systemd/zram-generator.conf` and `systemctl status systemd-zram-setup@zram0` |
| `Expected UU at 0x68 on i2c-1` | RTC not wired, overlay not loaded (no reboot yet?), or a different address: check `i2cdetect -y 1` |
| `expected exactly one ethernet device` | Set `rpi_agh_ethernet_interface` (e.g. `end0`) |
| `another profile ... already uses id 'Ethernet'` | A second profile is already called `Ethernet`. Delete or rename it with `nmcli` |
| `refusing to clean up: no BLS entry exists for current machine ID` | `kernel-install` could not create an entry: check `/boot/loader/entries` and `/etc/machine-id` |
| `sshd effective settings differ` | A file in `/etc/ssh/sshd_config.d/` overrides `sshd_config` (first value wins). Remove it or change it |
| DNS health check times out | `systemctl --user -M services@ status adguardhome`, `journalctl --user -M services@ -u adguardhome`, check `AdGuardHome.yaml` (bind addresses, TLS paths) |
| Locked out of SSH | Use the console: root and the admin user still have passwords. Only SSH is key-only |
