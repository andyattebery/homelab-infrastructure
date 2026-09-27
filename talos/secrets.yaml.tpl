# The cluster's secrets bundle (the schema `talosctl gen secrets` writes), read from the
# pi-cluster 1Password item. scripts/gen-config.sh renders it to generated/secrets.yaml with
# one `op inject`. Values are quoted so this template is itself valid YAML.
cluster:
  id: "{{ op://Home Lab/pi-cluster/talos/cluster id }}"
  secret: "{{ op://Home Lab/pi-cluster/talos/cluster secret }}"
secrets:
  bootstraptoken: "{{ op://Home Lab/pi-cluster/talos/bootstrap token }}"
  secretboxencryptionsecret: "{{ op://Home Lab/pi-cluster/talos/secretbox encryption secret }}"
trustdinfo:
  token: "{{ op://Home Lab/pi-cluster/talos/trustd token }}"
certs:
  etcd:
    crt: "{{ op://Home Lab/pi-cluster/talos/etcd crt }}"
    key: "{{ op://Home Lab/pi-cluster/talos/etcd key }}"
  k8s:
    crt: "{{ op://Home Lab/pi-cluster/talos/k8s crt }}"
    key: "{{ op://Home Lab/pi-cluster/talos/k8s key }}"
  k8saggregator:
    crt: "{{ op://Home Lab/pi-cluster/talos/k8s aggregator crt }}"
    key: "{{ op://Home Lab/pi-cluster/talos/k8s aggregator key }}"
  k8sserviceaccount:
    key: "{{ op://Home Lab/pi-cluster/talos/k8s service account key }}"
  os:
    crt: "{{ op://Home Lab/pi-cluster/talos/os crt }}"
    key: "{{ op://Home Lab/pi-cluster/talos/os key }}"
