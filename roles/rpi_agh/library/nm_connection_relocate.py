#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Rename the active NetworkManager profile of an interface and move its keyfile."""

from __future__ import annotations

DOCUMENTATION = r"""
---
module: nm_connection_relocate
short_description: Give the profile managing an ethernet interface a fixed id and keyfile name
description:
  - Finds the NetworkManager connection profile that is active on the given interface (or
    on the only ethernet device when no interface is given), sets its C(connection.id) and
    makes sure it is stored as C(<keyfile_dir>/<id>.nmconnection).
  - Every other setting of the profile is preserved; the UUID does not change, so the
    active connection is not interrupted.
  - ifcfg profiles are migrated to keyfiles first. Profiles without a backing file
    (in-memory only) are rejected.
  - Supports check mode.
options:
  interface:
    description:
      - Interface the profile is active on. When empty, the only ethernet device known to
        NetworkManager is used, and the module fails if there is not exactly one.
    type: str
    default: ""
  id:
    description: Desired C(connection.id) and keyfile base name.
    type: str
    default: Ethernet
  keyfile_dir:
    description: Directory of persistent keyfiles.
    type: path
    default: /etc/NetworkManager/system-connections
"""

RETURN = r"""
interface:
  description: Interface the profile is active on.
  type: str
  returned: success
uuid:
  description: UUID of the profile.
  type: str
  returned: success
previous_id:
  description: Profile id before the change.
  type: str
  returned: success
previous_filename:
  description: Keyfile path before the change.
  type: str
  returned: success
filename:
  description: Keyfile path after the change.
  type: str
  returned: success
"""

import os
import shutil

from ansible.module_utils.basic import AnsibleModule


def split_terse(line):
    """Split one line of `nmcli -t` output, honouring backslash escapes."""
    fields, buf, escape = [], [], False
    for char in line:
        if escape:
            buf.append(char)
            escape = False
        elif char == "\\":
            escape = True
        elif char == ":":
            fields.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    fields.append("".join(buf))
    return fields


class Nmcli:
    def __init__(self, module):
        self.module = module

    def run(self, *args):
        rc, out, err = self.module.run_command(["nmcli"] + list(args))
        if rc != 0:
            self.module.fail_json(msg="nmcli %s failed" % " ".join(args), rc=rc, stdout=out, stderr=err)
        return out

    def rows(self, *args):
        return [split_terse(l) for l in self.run("-t", *args).splitlines() if l.strip()]

    def profile(self, uuid):
        for row_uuid, name, filename in self.rows("-f", "UUID,NAME,FILENAME", "connection", "show"):
            if row_uuid == uuid:
                return name, filename
        self.module.fail_json(msg="connection %s disappeared" % uuid)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            interface=dict(type="str", default=""),
            id=dict(type="str", default="Ethernet"),
            keyfile_dir=dict(type="path", default="/etc/NetworkManager/system-connections"),
        ),
        supports_check_mode=True,
    )
    nm = Nmcli(module)
    target_id = module.params["id"]
    keyfile_dir = module.params["keyfile_dir"]
    target_path = os.path.join(keyfile_dir, target_id + ".nmconnection")

    iface = module.params["interface"]
    if not iface:
        ethernet = [r[0] for r in nm.rows("-f", "DEVICE,TYPE", "device", "status") if r[1] == "ethernet"]
        if len(ethernet) != 1:
            module.fail_json(
                msg="expected exactly one ethernet device, found %d (%s); set the interface explicitly"
                % (len(ethernet), ", ".join(ethernet)))
        iface = ethernet[0]

    active = [r[0] for r in nm.rows("-f", "UUID,DEVICE", "connection", "show", "--active") if r[1] == iface]
    if len(active) != 1:
        module.fail_json(msg="expected one active connection on %s, found %d" % (iface, len(active)))
    uuid = active[0]

    # Refuse to clobber a different profile that already uses the target id or file
    for row_uuid, name, filename in nm.rows("-f", "UUID,NAME,FILENAME", "connection", "show"):
        if row_uuid != uuid and (name == target_id or filename == target_path):
            module.fail_json(msg="another profile (%s, %s) already uses id %r or file %s"
                             % (row_uuid, filename, target_id, target_path))

    previous_id, previous_filename = nm.profile(uuid)
    result = dict(changed=False, interface=iface, uuid=uuid,
                  previous_id=previous_id, previous_filename=previous_filename)

    if not previous_filename:
        module.fail_json(msg="profile %s has no backing file (in-memory only); save it first" % uuid, **result)

    if previous_id == target_id and previous_filename == target_path:
        module.exit_json(filename=target_path, **result)

    result["changed"] = True
    if module.check_mode:
        module.exit_json(filename=target_path, **result)

    if not previous_filename.endswith(".nmconnection"):
        nm.run("connection", "migrate", "--plugin", "keyfile", uuid)

    if previous_id != target_id:
        nm.run("connection", "modify", uuid, "connection.id", target_id)

    _, filename = nm.profile(uuid)
    if filename != target_path:
        if os.path.lexists(target_path):
            module.fail_json(msg="%s already exists and is not owned by %s" % (target_path, uuid), **result)
        # copy + unlink also covers profiles living in /run (different filesystem)
        shutil.copy2(filename, target_path)
        os.chown(target_path, 0, 0)
        os.chmod(target_path, 0o600)
        module.run_command(["restorecon", target_path])
        os.unlink(filename)
        nm.run("connection", "reload")
        _, filename = nm.profile(uuid)
        if filename != target_path:
            module.fail_json(msg="NetworkManager still reports %s for %s after reload" % (filename, uuid), **result)

    module.exit_json(filename=filename, **result)


if __name__ == "__main__":
    main()
