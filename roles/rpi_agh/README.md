# Role `rpi_agh`

Sets up a Fedora Server aarch64 Raspberry Pi as an AdGuard Home DNS server
running as a rootless Podman Quadlet. Used by [`site.yml`](../../site.yml).
See the [top-level README](../../README.md) and [docs/](../../docs/) for the
complete workflow.

## Usage

```yaml
- hosts: rpi_adguard
  serial: 1
  gather_facts: true      # required: validation checks distribution/architecture
  become: true            # set in ansible.cfg
  roles:
    - role: rpi_agh
```

The connection user must be `rpi_agh_admin_user` with working sudo.

## Interface

- **Required variables** (no defaults): `rpi_agh_fqdn`, `rpi_agh_admin_user`,
  `rpi_agh_{root,admin,services}_password_hash`,
  `rpi_agh_{root,admin,services}_authorized_keys`,
  `rpi_agh_host_tls_{cert,key}`, `rpi_agh_adguard_tls_{cert,key}`,
  `rpi_agh_adguard_config`.
- **Optional variables**: [`defaults/main.yml`](defaults/main.yml), documented
  in [docs/variables.md](../../docs/variables.md).
- **Argument spec**: [`meta/argument_specs.yml`](meta/argument_specs.yml),
  enforced by Ansible before any role task runs.
  [`tasks/validate.yml`](tasks/validate.yml) adds emptiness, format,
  certificate and target checks.

## Task files

| File | Tags | Purpose |
|---|---|---|
| `validate.yml` | `always` | input and target validation (read-only) |
| `packages.yml` | `phase1`, `packages` | system upgrade and package installation |
| `base.yml` | `phase1`, `base` | hostname, sysctl, zram, firmware config |
| `network.yml` | `phase1`, `network` | rename/move the ethernet profile |
| `boot_cleanup.yml` | `phase1`, `boot` | foreign machine-ID cleanup in `/boot` |
| `reboot.yml` | `phase1`, `reboot` | flush handlers, detect pending reboots (changes, `dnf needs-restarting`, overlay, zram), reboot and re-check |
| `updates.yml` | `phase2`, `updates` | dnf5 automatic |
| `time.yml` | `phase2`, `time` | DS3231 check, RTC unit, NTP, RTC sync |
| `tls.yml` | `phase2`, `tls` | host certificate, Cockpit |
| `pcp.yml` | `phase2`, `pcp` | pmlogger |
| `users.yml` | `phase2`, `users` | admin/services users, SELinux label, sub-IDs, passwords, SSH keys |
| `podman.yml` | `phase2`, `podman` | root/rootless podman, lingering |
| `resolver.yml` | `phase2`, `dns` | mask systemd-resolved, bootstrap resolver |
| `ssh.yml` | `phase2`, `ssh` | sshd hardening + effective-config check |
| `firewall.yml` | `phase2`, `firewall` | firewalld services (dns, https, http3, DoT, DoQ; no dhcpv6-client) |
| `adguardhome.yml` | `phase2`, `adguardhome` | rootless AdGuard Home Quadlet, auto-update, prune |
| `dns_switch.yml` | `phase2`, `dns` | health check, switch to 127.0.0.1 |
| `nm_dns.yml` | (included) | helper: set the profile DNS and reapply |

## Modules

- `library/bls_cleanup.py`: removes BLS entries and kernel/initramfs/rescue
  images belonging to other machine IDs, and refuses if the current machine ID
  has no entry.
- `library/nm_connection_relocate.py`: renames the active ethernet profile
  and moves its keyfile without changing its UUID or any other setting.

Details: [docs/design.md](../../docs/design.md#custom-modules).

## Files written on the Pi

| Path | Source |
|---|---|
| `/etc/sysctl.d/50-unprivileged-port-start.conf` | `base.yml` |
| `/etc/systemd/zram-generator.conf` | `templates/zram-generator.conf.j2` |
| `/boot/efi/config.txt` (lines added) | `base.yml` |
| `/etc/NetworkManager/system-connections/Ethernet.nmconnection` | `nm_connection_relocate` |
| `/etc/NetworkManager/conf.d/90-rpi-adguardhome-dns.conf` | `resolver.yml` |
| `/etc/dnf/automatic.conf` | `templates/automatic.conf.j2` |
| `/etc/systemd/system/rtc-ds3231.service` | `templates/rtc-ds3231.service.j2` |
| `/etc/pki/tls/{certs,private}/<fqdn>.pem` | `tls.yml` |
| `/etc/cockpit/ws-certs.d/0-<hostname>.{cert,key}` (symlinks) | `tls.yml` |
| `/etc/subuid`, `/etc/subgid` | `templates/subid.j2` |
| `~/.ssh/authorized_keys` (root, admin, services) | `users.yml` |
| `/etc/ssh/sshd_config` (lines edited) | `ssh.yml` |
| `/services/.local/containers/adguardhome/{certs,conf,work}/` | `adguardhome.yml` |
| `/services/.config/containers/systemd/adguardhome.container` | `templates/adguardhome.container.j2` |
| `/services/.config/systemd/user/podman-image-prune.service` | `templates/podman-image-prune.service.j2` |
| `/services/.config/systemd/user/podman-auto-update.service.d/50-image-prune.conf` | `adguardhome.yml` |

## Requirements

- Collections: `community.crypto` (controller-side certificate checks),
  `ansible.posix` (firewalld).
- Controller Python: `cryptography`.
- `pipelining = true` is recommended. It avoids temporary-file permission
  problems when becoming the unprivileged `services` user.
