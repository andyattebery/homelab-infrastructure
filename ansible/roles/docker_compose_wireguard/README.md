# wireguard_docker_compose

Deploys [LinuxServer.io Wireguard Docker image](https://github.com/linuxserver/docker-wireguard) via docker compose in server mode.

## Variables

| Name                        | Required?  | Description                                 |
|-----------------------------|------------|---------------------------------------------|
| wireguard_external_domain   | yes        | External domain for wireguard server        |
| wireguard_port              | yes        | External port for wireguard server          |
| wireguard_peers             | yes        | Number of peers to create confs for. Required for server mode. Can also be a list of names: myPC,myPhone,myTablet (alphanumeric only) |
| wireguard_internal_subnet   | yes        | Wireguard peer subnets                      |
