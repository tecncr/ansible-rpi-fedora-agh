# Variables

All role variables start with `rpi_agh_`. The authoritative sources are
[`roles/rpi_agh/defaults/main.yml`](../roles/rpi_agh/defaults/main.yml) and
[`roles/rpi_agh/meta/argument_specs.yml`](../roles/rpi_agh/meta/argument_specs.yml).

## Required

The run stops before changing anything if any of these is undefined
(argument spec), empty, or malformed (`tasks/validate.yml`).

| Variable | Type | Checked for | Example inventory source |
|---|---|---|---|
| `rpi_agh_fqdn` | str | lowercase `hostname.domain.tld`; the short hostname is the first label | `host_vars/<host>/vars.yml` |
| `rpi_agh_admin_user` | str | valid user name, not `root`, not the services user; UID 1000 free or already this user | `group_vars/rpi_adguard/vars.yml` |
| `rpi_agh_root_password_hash` | str | crypt(3) hash | `vault_root_password_hash` |
| `rpi_agh_admin_password_hash` | str | crypt(3) hash | `vault_admin_password_hash` |
| `rpi_agh_services_password_hash` | str | crypt(3) hash | `vault_services_password_hash` |
| `rpi_agh_root_authorized_keys` | list[str] | non-empty, one OpenSSH public key per item | `group_vars/.../vars.yml` |
| `rpi_agh_admin_authorized_keys` | list[str] | same | `group_vars/.../vars.yml` |
| `rpi_agh_services_authorized_keys` | list[str] | same | `group_vars/.../vars.yml` |
| `rpi_agh_host_tls_cert` | str (PEM) | valid, not expired, SAN covers `rpi_agh_fqdn` | `files/<host>/host.pem` |
| `rpi_agh_host_tls_key` | str (PEM) | parses, matches the certificate | `files/<host>/host.key` (vault) |
| `rpi_agh_adguard_tls_cert` | str (PEM) | valid, not expired, SAN covers `rpi_agh_adguard_fqdn` | `files/<host>/adguard.pem` |
| `rpi_agh_adguard_tls_key` | str (PEM) | parses, matches the certificate | `files/<host>/adguard.key` (vault) |
| `rpi_agh_adguard_config` | str (YAML) | parses as a YAML mapping; with `tls.enabled`, `server_name` must be `rpi_agh_adguard_fqdn` and `certificate_path`/`private_key_path` must be `/opt/adguardhome/certs/<rpi_agh_adguard_fqdn>.pem`/`.key` (or the PEM inline). The host FQDN is only for Cockpit | `files/<host>/AdGuardHome.yaml` (vault) |

Connection variables needed by `site.yml` (set in the example `group_vars`):

| Variable | Value |
|---|---|
| `ansible_user` | must equal `rpi_agh_admin_user` (asserted, because root SSH login gets disabled) |
| `ansible_become_password` | `"{{ vault_admin_become_password }}"` |
| `ansible_host` | address of the Pi, per host |

## Optional (with defaults)

### Identity

| Variable | Default | Notes |
|---|---|---|
| `rpi_agh_adguard_fqdn` | `rpi_agh_fqdn` | FQDN of the AdGuard Home certificate and file names |

### Base system

| Variable | Default | Notes |
|---|---|---|
| `rpi_agh_packages` | see defaults | installed in phase 1, before systemd-resolved is masked |
| `rpi_agh_dnf_conf` | `fastestmirror=True`, `gpgcheck=True`, `installonly_limit=2`, `clean_requirements_on_remove=True` | `/etc/dnf/dnf.conf` is replaced with exactly these `[main]` options, before the upgrade |
| `rpi_agh_unprivileged_port_start` | `23` | `/etc/sysctl.d/50-unprivileged-port-start.conf` |
| `rpi_agh_zram_size` | `ram` | `/etc/systemd/zram-generator.conf` |
| `rpi_agh_zram_compression_algorithm` | `zstd` | |
| `rpi_agh_firmware_config` | `/boot/efi/config.txt` | |
| `rpi_agh_firmware_config_lines` | `dtparam=i2c_arm=on`, `dtoverlay=i2c-rtc,ds3231` | each line added once if missing |
| `rpi_agh_boot_cleanup` | `true` | remove `/boot` artefacts of other machine IDs |
| `rpi_agh_reboot_timeout` | `900` | seconds to wait for the Pi after the phase 1 reboot |
| `rpi_agh_serial` | `1` | play-level: hosts processed at a time (set in inventory or `-e`) |

### Networking / DNS

| Variable | Default | Notes |
|---|---|---|
| `rpi_agh_ethernet_interface` | `""` | empty = the only ethernet device (`end0` on Pi 4) |
| `rpi_agh_ethernet_connection_id` | `Ethernet` | profile id and keyfile name |
| `rpi_agh_bootstrap_nameserver` | `9.9.9.9` | resolver used until AdGuard Home answers |
| `rpi_agh_ignore_ipv6_auto_dns` | `true` | also ignore DHCPv6/RA DNS, so `127.0.0.1` is the only resolver |
| `rpi_agh_firewalld_services_removed` | `[dhcpv6-client]` | removed from the default zone, permanent + runtime |
| `rpi_agh_firewalld_services_added` | `[dns, https, http3, dns-over-tls, dns-over-quic]` | added to the default zone, permanent + runtime |
| `rpi_agh_dns_check_domain` | `tecncr.com` | queried with `dig @127.0.0.1` |
| `rpi_agh_dns_check_timeout` | `300` | seconds |
| `rpi_agh_dns_check_interval` | `5` | seconds between attempts |

### Updates

| Variable | Default |
|---|---|
| `rpi_agh_dnf_automatic_timer` | `dnf-automatic.timer` |
| `rpi_agh_dnf_automatic_apply_updates` | `true` |
| `rpi_agh_dnf_automatic_reboot` | `when-needed` (`never`, `when-changed`, `when-needed`) |

### RTC / time

| Variable | Default | Notes |
|---|---|---|
| `rpi_agh_rtc_i2c_bus` | `1` | |
| `rpi_agh_rtc_i2c_address` | `"0x68"` | must show `UU` in `i2cdetect` |
| `rpi_agh_rtc_max_drift_seconds` | `2` | `hwclock -w` only when RTC and NTP time drift further apart |
| `rpi_agh_ntp_sync_timeout` | `300` | seconds to wait for `NTPSynchronized=yes` |

### Users

| Variable | Default |
|---|---|
| `rpi_agh_admin_uid` / `rpi_agh_admin_gid` | `1000` / `1000` |
| `rpi_agh_admin_groups` | `[wheel]` (appended) |
| `rpi_agh_services_user` / `rpi_agh_services_group` | `services` / `services` |
| `rpi_agh_services_uid` / `rpi_agh_services_gid` | `2000` / `2000` |
| `rpi_agh_services_home` | `/services` |
| `rpi_agh_services_comment` | `Services` |
| `rpi_agh_admin_subid_start` | `100000` |
| `rpi_agh_services_subid_start` | `500000` |
| `rpi_agh_subid_count` | `65536` |

`/etc/subuid` and `/etc/subgid` are **replaced** with exactly these two lines,
as in the original procedure.

### AdGuard Home

| Variable | Default | Notes |
|---|---|---|
| `rpi_agh_adguard_image` | `docker.io/adguard/adguardhome:latest` | must be fully qualified for `AutoUpdate=registry` |
| `rpi_agh_adguard_container_name` | `adguardhome` | also the unit, host and Quadlet file name |
| `rpi_agh_adguard_timezone` | `America/Lima` | `TZ` inside the container |
| `rpi_agh_adguard_dir` | `/services/.local/containers/adguardhome` | holds `certs/`, `work/`, `conf/` |
| `rpi_agh_adguard_published_ports` | 53, 443, 853 (tcp+udp) | Quadlet `PublishPort=` values |
| `rpi_agh_adguard_config_force` | `false` | `false`: only seed `AdGuardHome.yaml`. `true`: overwrite it every run |
