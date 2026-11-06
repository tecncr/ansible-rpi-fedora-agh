# files/agh01

Per-host files read by `inventory/group_vars/rpi_adguard/vars.yml`. Replace this
README with:

| File               | Content                                           | Encrypt? |
|--------------------|---------------------------------------------------|----------|
| `host.pem`         | Certificate (+ chain) for `rpi_agh_fqdn`          | optional |
| `host.key`         | Private key of `host.pem`                         | **yes**  |
| `adguard.pem`      | Certificate (+ chain) for `rpi_agh_adguard_fqdn`  | optional |
| `adguard.key`      | Private key of `adguard.pem`                      | **yes**  |
| `AdGuardHome.yaml` | Full AdGuard Home configuration                   | **yes**  |

```sh
ansible-vault encrypt inventory/files/agh01/host.key \
                      inventory/files/agh01/adguard.key \
                      inventory/files/agh01/AdGuardHome.yaml
```
