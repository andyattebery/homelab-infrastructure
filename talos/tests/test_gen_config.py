"""gen-config.sh: one op call at most, and six machine configs that say what the plan says.

The real talosctl renders and validates the configs, from a throwaway bundle; only `op` is a
stub. What this cannot show is that the configs boot and lay the disks out as designed -- that is
the first-node gate in README.md, "Build".
"""

import stat
import subprocess

import pytest
import yaml

from support import (
    REAL_TALOSCTL,
    SCHEMATIC,
    TALOS_VERSION,
    calls,
    gen_secrets,
    make_env,
    make_talos_copy,
    run,
)

NODES = [f"pi-cluster-0{n}" for n in range(1, 7)]
CONTROL_PLANES = NODES[:3]
WORKERS = NODES[3:]
VIP = "192.168.1.187"
KUBERNETES_VERSION = "v1.36.5"


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """One run on a copy that already has a bundle, as it does after store-secrets.sh."""
    tmp = tmp_path_factory.mktemp("gen")
    talos = make_talos_copy(tmp / "repo")
    (talos / "schematic.id").write_text(SCHEMATIC + "\n")
    gen_secrets(talos / "generated" / "secrets.yaml")
    env = make_env(tmp)
    result = run(talos, "gen-config.sh", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    return talos, env


def docs(talos, node):
    return list(yaml.safe_load_all((talos / "generated" / f"{node}.yaml").read_text()))


def doc(documents, kind, name=None):
    found = [d for d in documents if d.get("kind") == kind and (name is None or d.get("name") == name)]
    assert len(found) <= 1, found
    return found[0] if found else None


def machine(documents):
    (legacy,) = [d for d in documents if d.get("version") == "v1alpha1" and "kind" not in d]
    return legacy["machine"]


# ---------------------------------------------------------------------------------------------


def test_an_existing_bundle_means_no_op_call(generated):
    _, env = generated
    assert calls(env, "op") == []


def test_a_missing_bundle_is_one_op_inject(tmp_path, talos):
    (talos / "schematic.id").write_text(SCHEMATIC + "\n")
    env = make_env(tmp_path, STUB_OP_INJECT_SOURCE=gen_secrets(tmp_path / "from-1password.yaml"))
    result = run(talos, "gen-config.sh", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert calls(env, "op") == [["op", "inject", "-i", "secrets.yaml.tpl", "-o", "generated/secrets.yaml"]]


def test_refuses_without_a_schematic_id(tmp_path, talos):
    env = make_env(tmp_path)
    result = run(talos, "gen-config.sh", env=env)
    assert result.returncode == 1
    assert calls(env) == []
    assert not (talos / "generated").exists()


def test_refuses_when_generated_is_not_gitignored(tmp_path, talos):
    (talos / "schematic.id").write_text(SCHEMATIC + "\n")
    (talos.parent / ".gitignore").unlink()
    env = make_env(tmp_path)
    result = run(talos, "gen-config.sh", env=env)
    assert result.returncode == 1
    assert calls(env) == []
    assert not (talos / "generated").exists()


def test_every_node_config_validates_for_metal(generated):
    talos, _ = generated
    for node in NODES:
        path = talos / "generated" / f"{node}.yaml"
        result = subprocess.run(
            [REAL_TALOSCTL, "validate", "--config", str(path), "--mode", "metal"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (node, result.stdout + result.stderr)


def test_three_control_planes_and_three_workers(generated):
    talos, _ = generated
    assert [machine(docs(talos, node))["type"] for node in NODES] == ["controlplane"] * 3 + ["worker"] * 3


def test_each_node_has_its_hostname(generated):
    talos, _ = generated
    for node in NODES:
        assert doc(docs(talos, node), "HostnameConfig") == {
            "apiVersion": "v1alpha1",
            "kind": "HostnameConfig",
            "hostname": node,
        }


def test_the_vip_is_only_on_control_planes(generated):
    talos, _ = generated
    for node in CONTROL_PLANES:
        vip = doc(docs(talos, node), "Layer2VIPConfig", VIP)
        assert vip is not None, node
        assert vip["link"] == doc(docs(talos, node), "DHCPv4Config")["name"]
    for node in WORKERS:
        assert doc(docs(talos, node), "Layer2VIPConfig") is None, node


def test_control_planes_take_workloads_and_never_use_the_vip_as_node_ip(generated):
    talos, _ = generated
    for node in CONTROL_PLANES:
        kube_node = doc(docs(talos, node), "KubeNodeConfig")
        assert "taints" not in kube_node, node
        assert kube_node["nodeIP"]["validSubnets"] == ["192.168.1.0/24", f"!{VIP}/32"]


def test_every_node_installs_to_sd_and_puts_its_volumes_on_nvme(generated):
    talos, _ = generated
    nvme = 'disk.transport == "nvme" && !system_disk'
    for node in NODES:
        documents = docs(talos, node)
        install = doc(documents, "UnattendedInstallConfig")
        assert install["provisioning"]["diskSelector"]["match"] == 'disk.transport == "mmc"', node
        assert install["provisioning"]["wipe"] is False, node
        ephemeral = doc(documents, "VolumeConfig", "EPHEMERAL")["provisioning"]
        assert ephemeral == {"diskSelector": {"match": nvme}, "maxSize": "40GiB"}, node
        longhorn = doc(documents, "UserVolumeConfig", "longhorn")["provisioning"]
        assert longhorn == {"diskSelector": {"match": nvme}, "minSize": "150GB", "grow": False}, node
        assert doc(documents, "DHCPv4Config") is not None, node


def test_every_node_runs_the_pinned_kubernetes(generated):
    talos, _ = generated
    for node in NODES:
        assert doc(docs(talos, node), "KubeletConfig")["image"] == f"ghcr.io/siderolabs/kubelet:{KUBERNETES_VERSION}", node
    for node in CONTROL_PLANES:
        for kind, name in [("KubeAPIServerConfig", "kube-apiserver"), ("KubeControllerManagerConfig", "kube-controller-manager"),
                           ("KubeSchedulerConfig", "kube-scheduler"), ("KubeProxyConfig", "kube-proxy")]:
            assert doc(docs(talos, node), kind)["image"] == f"registry.k8s.io/{name}:{KUBERNETES_VERSION}", (node, kind)


def test_the_installer_carries_the_schematic(generated):
    talos, _ = generated
    expected = f"factory.talos.dev/metal-installer/{SCHEMATIC}:{TALOS_VERSION}"
    for node in NODES:
        assert doc(docs(talos, node), "UnattendedInstallConfig")["installer"]["image"] == expected, node


def test_talosconfig_points_at_the_control_planes_not_the_vip(generated):
    talos, _ = generated
    talosconfig = yaml.safe_load((talos / "generated" / "talosconfig").read_text())
    context = talosconfig["contexts"][talosconfig["context"]]
    assert context["endpoints"] == ["192.168.1.181", "192.168.1.182", "192.168.1.183"]
    assert context["nodes"] == ["192.168.1.181"]


def test_generated_files_are_private(generated):
    talos, _ = generated
    files = sorted((talos / "generated").iterdir())
    assert len(files) == 10, files
    for path in files:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path


def test_a_second_run_keeps_the_bundle(generated):
    talos, env = generated
    before = (talos / "generated" / "secrets.yaml").read_bytes()
    result = run(talos, "gen-config.sh", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (talos / "generated" / "secrets.yaml").read_bytes() == before
    assert calls(env, "op") == []
