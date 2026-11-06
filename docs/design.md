# Design notes

How each manual step became an idempotent task, and where the role
deliberately differs from the original procedure.

## Mapping from the manual procedure

| Manual step | Role implementation |
|---|---|
| "Ask for FQDN / AGH FQDN / admin user / keys / certs / YAML" | Inventory variables, validated up front. Nothing is interactive |
| `dnf update -y --refresh` (twice) | `dnf5: name='*' state=latest update_cache=true`, once, before the reboot |
| `dnf install ...` (spread across the procedure) | One install in phase 1, while systemd-resolved still works |
| `hostnamectl set-hostname --static` | `hostname: use=systemd` |
| Remove `/boot` leftovers of other machine IDs | Custom module `bls_cleanup` (see below) |
| `echo ... > /etc/sysctl.d/50-unprivileged-port-start.conf` | `copy`, then `sysctl --load` (handler) |
| Rename / move the NetworkManager profile | Custom module `nm_connection_relocate` (see below) |
| `cat > /etc/systemd/zram-generator.conf` | `template` |
| `cat >> /boot/efi/config.txt` | `lineinfile` per line (appending twice would duplicate the lines) |
| `systemctl reboot`, "separate script after reboot" | `reboot` module mid-play, only when needed (see "Reboot detection"). One playbook covers both phases |
| `/etc/dnf/automatic.conf` + timer | `template` + `systemd_service` |
| `i2cdetect -y 1` "check for UU at 0x68" | Parsed and asserted. Fails with the full table if it isn't `UU` |
| `hwclock -r`, `timedatectl` | Read-only tasks, printed with `debug` |
| `rtc-ds3231.service` | `template`, verbatim content, daemon-reload only when it changed |
| `timedatectl set-ntp true` / `set-local-rtc 0` | Run only if `timedatectl show` says otherwise |
| `hwclock -w` | Only after `NTPSynchronized=yes`, and only when RTC and system time differ by more than 2 s |
| `nano` the certificates/key, check them | Controller-side validation + `copy` with modes (see [secrets.md](secrets.md)) |
| `ln -sf ... /etc/cockpit/ws-certs.d/` | `file: state=link force=true` |
| `pmlogger` | `systemd_service` |
| `groupadd`/`useradd` services | `group` / `user` with fixed IDs |
| `semanage fcontext -a -e /home/services /services` | Run only if `semanage fcontext -l -C` doesn't list the equivalence yet |
| `restorecon -Rv /services` | Reports changed only when something was relabelled |
| `cat > /etc/subuid /etc/subgid` | `template`, then `podman system migrate` (handler) when changed |
| `passwd` ×3 | `user: password=<hash>` from the vault |
| `podman system reset -f` ×2 | `podman info` (see below) |
| `systemctl enable --now podman.socket podman.service` | Same for root and services (see below) |
| `systemctl stop/mask systemd-resolved`, `echo nameserver 9.9.9.9 > /etc/resolv.conf` | See "Resolver" below |
| Paste SSH keys | Exclusive `authorized_keys` for root, admin, services |
| Edit `sshd_config` | `lineinfile` + `sshd -t` validation + restart + `sshd -T` assertion |
| `loginctl enable-linger` | `creates: /var/lib/systemd/linger/<user>` |
| `podman pull` | Only if `podman image exists` says no; retried 5× |
| `mkdir`, paste AGH certs and YAML | `file` / `copy` as the services user |
| `adguardhome.container` | `template`, verbatim content, checked with `quadlet -dryrun` |
| `systemctl --user start adguardhome` | `started`, or `restarted` when the Quadlet/certs/config changed |
| `podman-auto-update.timer` | Enabled for the services user |
| "unit after auto-update's success to prune images" | `podman-image-prune.service` + `OnSuccess=` drop-in on `podman-auto-update.service` |
| `firewall-cmd` services + `--runtime-to-permanent` | `ansible.posix.firewalld` with permanent + immediate (see below) |
| `dig @127.0.0.1` loop (5 s, 300 s max) | `until` loop with the same timing |
| Edit `Ethernet.nmconnection` DNS to 127.0.0.1 | `nmcli connection modify` + `nmcli device reapply`, then check `/etc/resolv.conf` |

## Deliberate differences

### `podman system reset -f` is not used

`podman system reset` deletes all containers, images and volumes. In the
original procedure it ran on an empty system just to create the storage
directories, but on a re-run it would wipe AdGuard Home. `podman info`
initialises storage the same way and is harmless. When `/etc/subuid` or
`/etc/subgid` change, a handler runs `podman system migrate` so podman picks
up the new ranges, which is the other reason the reset was there.

### `podman.service` is enabled, not started

`podman.service` is socket activated and exits after 5 s without API clients.
Requiring it to be "started" would report a change on every run. The socket
is enabled and started, and the service is enabled. In practice this matches
`enable --now`.

### AdGuardHome.yaml path

The procedure mentions `/services/.local/containers/adguardhome/AdGuardHome.yaml`,
but the Quadlet mounts `.../conf` at `/opt/adguardhome/conf`, which is where
the image reads `AdGuardHome.yaml` from. The role writes
`.../adguardhome/conf/AdGuardHome.yaml`.

It writes this file **only if it doesn't exist** unless
`rpi_agh_adguard_config_force: true`, because AdGuard Home rewrites the file
itself. Overwriting it on every run would silently revert UI changes and
report a change each time.

### Resolver

On Fedora, `/etc/resolv.conf` is a symlink into `/run/systemd/resolve/`. Once
systemd-resolved is masked, writing through that symlink lands in `/run` and
is lost on reboot, leaving a dangling symlink. The role:

1. adds `/etc/NetworkManager/conf.d/90-rpi-adguardhome-dns.conf` with
   `dns=default` and `rc-manager=file`, so NetworkManager writes a plain
   `/etc/resolv.conf`;
2. masks systemd-resolved and replaces the symlink with a regular file
   containing `nameserver 9.9.9.9`;
3. sets the `Ethernet` profile to `ipv4.dns 9.9.9.9` + `ignore-auto-dns`
   (and the IPv6 equivalent) so NetworkManager keeps 9.9.9.9 until AdGuard
   Home is up. The image pull needs DNS;
4. after the `dig` check succeeds, switches the profile to `127.0.0.1` and
   asserts that `/etc/resolv.conf` lists only `127.0.0.1`.

On re-runs a profile already set to 127.0.0.1 is left alone. The role never
switches a working Pi back to the bootstrap resolver.

### Cockpit certificate selection

Cockpit uses the certificate in `/etc/cockpit/ws-certs.d/` that sorts **last**
alphabetically. `0-<hostname>.cert` sorts before `0-self-signed.cert`
whenever the hostname starts with a letter before `s`, so the role deletes the
self-signed pair. It then confirms with `cockpit-certificate-ensure --check`
that Cockpit picked `0-<hostname>.cert`.

### sshd

The settings go into `/etc/ssh/sshd_config` itself, as in the procedure, with
`sshd -t` validation before every write. Files in
`/etc/ssh/sshd_config.d/*.conf` are included first and **the first value
wins**, so a drop-in (e.g. from cloud-init) could silently override them. After
the restart, the role compares `sshd -T` (the configuration actually in
effect) with the expected values and fails if they differ.

`authorized_keys` are installed before sshd restarts, and the play connects
as the admin user by key. Restarting sshd does not close existing sessions.

### firewalld

The procedure runs `firewall-cmd` against the runtime configuration, then
`--runtime-to-permanent` and `--reload`. The role applies each service with
`ansible.posix.firewalld` using `permanent: true` and `immediate: true`, which
changes both configurations at once and reports a change only when one was
made. Unlike `--runtime-to-permanent`, it does not persist unrelated
runtime-only rules that happen to exist. It also makes sure firewalld is
enabled and running. The step runs right after the sshd restart, as in the
procedure. The `ssh` and `cockpit` services that Fedora Server enables by
default are left alone, so the firewall change cannot cut off the Ansible
connection.

### Reboot detection

Handlers only know what changed in the current run. If a run upgrades the
kernel or edits `config.txt` and then fails before rebooting, the re-run sees
those tasks as "ok" and a handler-only design would never reboot. So
`tasks/reboot.yml` also reads the running system's state and reboots when any
of these is true:

| Check | Means |
|---|---|
| A phase 1 task notified `Reboot required` in this run | upgrade, zram config or `config.txt` changed |
| `dnf needs-restarting` exits 1 (cache-only, from `dnf5-plugins`) | core packages (kernel, glibc, systemd, ...) were updated since boot |
| `/sys/bus/i2c/devices/<bus>-00<addr>` is missing | the `i2c-rtc` overlay is not loaded. This checks the overlay, not the chip: the kernel creates the I2C client from the device tree even if the chip doesn't answer |
| `/sys/block/zram0/comp_algorithm` doesn't mark `[zstd]` | zram not set up from the current config |

After a reboot, the overlay and zram checks run again and **fail** if still
unmet. A broken `config.txt` or zram config is reported once, instead of the
Pi rebooting on every run.

### IPv6 auto DNS

`rpi_agh_ignore_ipv6_auto_dns: true` (the default) also sets
`ipv6.ignore-auto-dns yes`. Without it, a router advertising IPv6 DNS servers
would add them to `/etc/resolv.conf` next to `127.0.0.1`.

## Custom modules

Both live in `roles/rpi_agh/library/`, support check mode and use only the
Python standard library on the Pi.

### `bls_cleanup`

1. Reads `/etc/machine-id`.
2. If the running kernel has no BLS entry for that machine ID, runs
   `kernel-install add <kver> /lib/modules/<kver>/vmlinuz`, so the Pi always
   has something to boot.
3. **Refuses to continue** if no entry for the current machine ID exists.
4. Removes:
   - every `/boot/loader/entries/*.conf` that does not start with
     `<machine-id>-`;
   - the `linux`/`initrd` files those entries reference, but only when no
     remaining entry references them and they are not the running kernel's;
   - `*0-rescue-<id>*` files (vmlinuz, initramfs, `.hmac`) of other IDs;
   - top-level `/boot/<32-hex>` directories of other IDs.

It runs after the system upgrade, so a kernel installed by the upgrade
already has an entry for the current machine ID.

### `nm_connection_relocate`

1. Finds the only ethernet device (or uses `rpi_agh_ethernet_interface`) and
   the profile active on it.
2. Refuses if another profile already uses the id `Ethernet` or the file
   `Ethernet.nmconnection`.
3. Migrates ifcfg profiles to keyfile, sets `connection.id`, moves the keyfile
   to `/etc/NetworkManager/system-connections/Ethernet.nmconnection` (0600,
   SELinux context restored) and runs `nmcli connection reload`.

The UUID never changes, so NetworkManager treats this as an update of the
same profile and does not drop the active connection. All other settings are
kept byte for byte.

## Idempotency checklist

- Shell/command tasks either read state (`changed_when: false`), are guarded
  by a check of the current state (`creates`, a `when` on registered output),
  or report a change only when they actually changed something.
- Templates hold the complete file content, so drift is corrected rather
  than accumulated.
- Services are restarted through handlers or conditional `restarted` states,
  only when their inputs changed.
- The reboot only happens when this run changed something that needs it, or
  the system state shows a reboot is still pending.
