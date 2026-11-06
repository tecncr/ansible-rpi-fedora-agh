#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Remove /boot leftovers that belong to machine IDs other than the current one."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: bls_cleanup
short_description: Remove /boot artefacts that do not belong to the current machine ID
description:
  - Fedora ARM images are built on a machine with a different C(/etc/machine-id). After the
    first boot the system gets a new machine ID, leaving Boot Loader Specification (BLS)
    entries, rescue kernels and initramfs images from the build machine behind.
  - This module makes sure the running kernel has a BLS entry for the current machine ID
    (calling C(kernel-install add) when it does not), then removes every BLS entry, rescue
    image and per-machine-ID directory under the boot directory that belongs to a different
    machine ID.
  - Kernel and initramfs files referenced by removed entries are deleted only when no
    remaining entry references them and they do not belong to the running kernel.
  - Supports check mode.
options:
  boot_dir:
    description: Directory where BLS entries and kernels live.
    type: path
    default: /boot
  machine_id_file:
    description: File holding the current machine ID.
    type: path
    default: /etc/machine-id
  ensure_running_kernel_entry:
    description: Create a BLS entry for the running kernel and current machine ID if missing.
    type: bool
    default: true
"""

RETURN = r"""
machine_id:
  description: The current machine ID.
  type: str
  returned: always
kept_entries:
  description: BLS entries that belong to the current machine ID.
  type: list
  elements: str
  returned: always
removed:
  description: Paths removed (or that would be removed in check mode).
  type: list
  elements: str
  returned: always
created_entry:
  description: Whether a BLS entry for the running kernel was created.
  type: bool
  returned: always
"""

import glob
import os
import re
import shutil

from ansible.module_utils.basic import AnsibleModule

MACHINE_ID_RE = re.compile(r"^[0-9a-f]{32}$")
RESCUE_RE = re.compile(r"0-rescue-([0-9a-f]{32})")


def read_machine_id(path):
    with open(path, encoding="utf-8") as handle:
        value = handle.read().strip()
    if not MACHINE_ID_RE.match(value):
        raise ValueError("invalid machine ID %r in %s" % (value, path))
    return value


def entry_files(entry_path, boot_dir):
    """Return absolute paths of linux/initrd files referenced by a BLS entry."""
    files = set()
    with open(entry_path, encoding="utf-8") as handle:
        for raw in handle:
            parts = raw.strip().split(None, 1)
            if len(parts) != 2 or parts[0] not in ("linux", "initrd"):
                continue
            for ref in parts[1].split():
                # Skip grub variables such as $tuned_initrd
                if "$" in ref:
                    continue
                files.add(os.path.normpath(os.path.join(boot_dir, ref.lstrip("/"))))
    return files


def main():
    module = AnsibleModule(
        argument_spec=dict(
            boot_dir=dict(type="path", default="/boot"),
            machine_id_file=dict(type="path", default="/etc/machine-id"),
            ensure_running_kernel_entry=dict(type="bool", default=True),
        ),
        supports_check_mode=True,
    )

    boot_dir = os.path.realpath(module.params["boot_dir"])
    entries_dir = os.path.join(boot_dir, "loader", "entries")
    kver = os.uname().release

    try:
        machine_id = read_machine_id(module.params["machine_id_file"])
    except (OSError, ValueError) as exc:
        module.fail_json(msg=str(exc))

    if not os.path.isdir(entries_dir):
        module.fail_json(msg="BLS entries directory %s does not exist" % entries_dir)

    def list_entries():
        return sorted(glob.glob(os.path.join(entries_dir, "*.conf")))

    created_entry = False
    running_entry = os.path.join(entries_dir, "%s-%s.conf" % (machine_id, kver))
    if module.params["ensure_running_kernel_entry"] and not os.path.exists(running_entry):
        vmlinuz = "/lib/modules/%s/vmlinuz" % kver
        if not os.path.exists(vmlinuz):
            module.fail_json(msg="cannot create BLS entry: %s is missing" % vmlinuz)
        created_entry = True
        if not module.check_mode:
            rc, out, err = module.run_command(["kernel-install", "add", kver, vmlinuz])
            if rc != 0 or not os.path.exists(running_entry):
                module.fail_json(
                    msg="kernel-install add %s failed or did not create %s" % (kver, running_entry),
                    rc=rc, stdout=out, stderr=err,
                )

    entries = list_entries()
    prefix = machine_id + "-"
    kept = [e for e in entries if os.path.basename(e).startswith(prefix)]
    stale = [e for e in entries if e not in kept]

    if not kept and not (created_entry and module.check_mode):
        module.fail_json(
            msg="refusing to clean up: no BLS entry exists for current machine ID %s" % machine_id,
            entries=entries,
        )

    kept_refs = set()
    for entry in kept:
        kept_refs |= entry_files(entry, boot_dir)
    # Never touch the running kernel's own images
    protected = kept_refs | {
        os.path.join(boot_dir, "vmlinuz-%s" % kver),
        os.path.join(boot_dir, "initramfs-%s.img" % kver),
    }

    to_remove = []
    for entry in stale:
        to_remove.append(entry)
        for ref in sorted(entry_files(entry, boot_dir)):
            if ref not in protected and os.path.isfile(ref) and ref.startswith(boot_dir + os.sep):
                to_remove.append(ref)

    # Rescue images (vmlinuz-0-rescue-<id>, initramfs-0-rescue-<id>.img, .hmac files, ...)
    for path in sorted(glob.glob(os.path.join(boot_dir, "*0-rescue-*")) +
                       glob.glob(os.path.join(boot_dir, ".*0-rescue-*"))):
        match = RESCUE_RE.search(os.path.basename(path))
        if match and match.group(1) != machine_id and os.path.isfile(path):
            to_remove.append(path)

    # Per-machine-ID directories (systemd-boot style layout)
    for path in sorted(glob.glob(os.path.join(boot_dir, "*"))):
        name = os.path.basename(path)
        if MACHINE_ID_RE.match(name) and name != machine_id and os.path.isdir(path):
            to_remove.append(path)

    # De-duplicate while keeping order
    seen = set()
    to_remove = [p for p in to_remove if not (p in seen or seen.add(p))]

    if not module.check_mode:
        for path in to_remove:
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                elif os.path.lexists(path):
                    os.unlink(path)
            except OSError as exc:
                module.fail_json(msg="failed to remove %s: %s" % (path, exc), removed=to_remove)

    module.exit_json(
        changed=bool(to_remove) or created_entry,
        machine_id=machine_id,
        kept_entries=[os.path.basename(e) for e in kept],
        removed=to_remove,
        created_entry=created_entry,
    )


if __name__ == "__main__":
    main()
