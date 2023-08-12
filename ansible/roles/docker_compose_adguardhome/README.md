# docker_compose_adguardhome

Deploys [LinuxServer.io Wireguard Docker image](https://github.com/linuxserver/docker-wireguard) via docker compose in server mode.

## Requirements
- `pip3 install bcrypt` on host because AdGuardHome password is generated in template

## Variables

| Name                        | Required?  | Description                                 |
|-----------------------------|------------|---------------------------------------------|
| adguardhome_domain_name     | yes        | External domain for wireguard server        |
