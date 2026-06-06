homelab_domain: omegaho.me

homelab_hosts:

  # Home Lab Bare Metal
  backup-01:
    ip: 192.168.1.249
    mac: {{ op://Home Lab/backup-01/hardware/mac address }}
    skip_dhcp: true
  management.backup-01:
    ip: 192.168.1.248
    mac: {{ op://Home Lab/backup-01/hardware/management mac address }}
    skip_dhcp: true
  nas-host-01:
    ip: 192.168.1.231
    mac: {{ op://Home Lab/nas-host-01/hardware/mac address }}
    skip_dhcp: true
  bmc.nas-host-01:
    ip: 192.168.1.230
  ipmi.nas-host-01:
    ip: 192.168.1.230
    mac: {{ op://Home Lab/nas-host-01/hardware/ipmi mac address }}
  jetson-01:
    ip: 192.168.1.193
    mac: {{ op://Home Lab/jetson-01/hardware/mac address }}
  mac-mini-01:
    ip: 192.168.1.201
    mac: {{ op://Home Lab/mac-mini-01/hardware/mac address }}
  pi-rack:
    ip: 192.168.1.226
    mac: {{ op://Home Lab/pi-rack/hardware/mac address }}
  vm-host-01:
    ip: 192.168.1.241
    mac: {{ op://Home Lab/vm-host-01/hardware/mac address }}
    skip_dhcp: true
  vm-host-02:
    ip: 192.168.1.242
    mac: {{ op://Home Lab/vm-host-02/hardware/mac address }}
    skip_dhcp: true

  # Workstations
  eta:
    ip: 192.168.1.207
    mac: {{ op://Home Lab/eta/hardware/mac address }}

  # VMs
  docker-01:
    ip: 192.168.1.238
    mac: {{ op://Home Lab/docker-01/hardware/mac address }}
  nas-01:
    ip: 192.168.1.232
    mac: {{ op://Home Lab/nas-01/hardware/mac address }}
  network-01:
    ip: 192.168.1.224
    mac: {{ op://Home Lab/network-01/hardware/mac address }}
  network-03:
    ip: 192.168.1.228
    mac: {{ op://Home Lab/network-03/hardware/mac address }}
  media-01:
    ip: 192.168.1.233
    mac: {{ op://Home Lab/media-01/hardware/mac address }}

  # Single Purpose
  pi-camera:
    ip: 192.168.1.191
    mac: {{ op://Home Lab/pi-camera/hardware/mac address }}
  pi-turntable:
    ip: 192.168.1.192
    mac: {{ op://Home Lab/pi-turntable/hardware/mac address }}

  # Infrastructure
  pikvm:
    ip: 192.168.1.227
    mac: {{ op://Home Lab/pikvm/hardware/mac address }}
  pikvm-hid:
    ip: 192.168.1.196
    mac: {{ op://Home Lab/pikvm-hid/hardware/mac address }}
  pdu-rack-network:
    ip: 192.168.1.194
    mac: {{ op://Home Lab/pdu-rack-network/hardware/mac address }}
  ups-rack:
    ip: 192.168.1.197
    mac: {{ op://Home Lab/ups-rack/hardware/mac address }}

  # Appliances
  tuneshine:
    ip: 192.168.1.120

  # Smart Home
  homeassistant:
    ip: 192.168.1.225
    mac: {{ op://Home Lab/Home Assistant/hardware/mac address }}
  tubeszb:
    ip: 192.168.1.198
    mac: {{ op://Home Lab/tubeszb/hardware/mac address }}

  # Network
  unifi:
    ip: 192.168.1.1

  # Turing Pi
  turingpi:
    ip: 192.168.1.215
  turingpi-rk1-01:
    ip: 192.168.1.216
  turingpi-rk1-02:
    ip: 192.168.1.217
  turingpi-cm4-01:
    ip: 192.168.1.218
  turingpi-cm4-02:
    ip: 192.168.1.219

  # Pi Cluster (legacy)
  pi-cluster-01:
    ip: 192.168.1.181
  pi-cluster-02:
    ip: 192.168.1.182
  pi-cluster-03:
    ip: 192.168.1.183
  pi-cluster-04:
    ip: 192.168.1.184
  pi-cluster-05:
    ip: 192.168.1.185
  pi-cluster-06:
    ip: 192.168.1.186

  # Gaming
  htpc-01:
    ip: 192.168.1.180
    mac: {{ op://Home Lab/bazzite/hardware/mac address }}
  rg35xxsp:
    ip: 192.168.1.171
  rg35xxh:
    ip: 192.168.1.172
  miyooa30:
    ip: 192.168.1.173
  trimui-brick:
    ip: 192.168.1.174
  trimuibrick:
    ip: 192.168.1.174
  retroid-pocket-5:
    ip: 192.168.1.175
  rgcubexx:
    ip: 192.168.1.176

# Services (that work like ones returns by dashboard-services-manager)
services:
  calibre-web:
    hostname: docker-01
  comfyui.htpc-01:
    hostname: htpc-01
  dashboard-services-manager:
    hostname: docker-01
  dashy:
    hostname: docker-01
  home:
    hostname: docker-01
  homepage:
    hostname: docker-01
  influxdb:
    hostname: docker-01
  loki:
    hostname: docker-01
  netbootxyz-assets:
    hostname: nas-01
  obico-ml:
    hostname: media-01
  ollama:
    hostname: media-01
  plex:
    hostname: media-01
  s3:
    hostname: nas-01
  network-inventory-manager:
    hostname: network-01
  # aliases
  bazzite:
    hostname: htpc-01
  network-02:
    hostname: pi-rack
  ups-monitor-rack:
    hostname: pi-rack

# Hosts on a different domain (e.g., Tailscale)
other_hosts:
  - hostname: offsite-nas.taile0128.ts.net
    ip: 100.108.158.127
  - hostname: offsite-pikvm.taile0128.ts.net
    ip: 100.113.201.54
