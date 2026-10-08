"""ingress.sh: the front door goes on in order with one op call, and the rendered manifest, which
holds the Cloudflare token, never outlives the run.

helm, kubectl and op are stubs, so nothing reaches the cluster, a chart repository or 1Password.
The template and the address pool are checked as files; what Istio, MetalLB and cert-manager make
of them is checked on the cluster.
"""

import re

import yaml

from support import TALOS_DIR, calls, make_env, run

RENDERED = "generated/ingress.rendered.yaml"
SENTINEL = "sentinel-cloudflare-token-0f3a"


def ingress(tmp_path, talos, **stubs):
    source = tmp_path / "rendered-by-op.yaml"
    source.write_text(f'stringData:\n  api-token: "{SENTINEL}"\n')
    env = make_env(tmp_path, STUB_OP_INJECT_SOURCE=source, INGRESS_RETRY_DELAY=0, **stubs)
    return env, run(talos, "ingress.sh", env=env)


def applies_of_rendered(env):
    return [c for c in calls(env, "kubectl") if RENDERED in c]


def documents(path):
    return list(yaml.safe_load_all((TALOS_DIR / path).read_text()))


def resource(kind, path="ingress/ingress.yaml.tpl"):
    (found,) = [d for d in documents(path) if d["kind"] == kind]
    return found


# ---------------------------------------------------------------------------------------------


def test_refuses_arguments_before_any_call(tmp_path, talos):
    env = make_env(tmp_path)
    result = run(talos, "ingress.sh", "--yes", env=env)
    assert result.returncode == 1
    assert result.stdout.startswith("Usage:")
    assert calls(env) == []


def test_installs_in_order_with_one_op_call(tmp_path, talos):
    env, result = ingress(tmp_path, talos)
    assert result.returncode == 0, result.stdout + result.stderr
    charts = "oci://ghcr.io/istio/release/charts"
    assert calls(env) == [
        ["kubectl", "apply", "--server-side", "-f",
         "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.1/standard-install.yaml"],
        ["kubectl", "apply", "-f", "ingress/namespaces.yaml"],
        ["helm", "upgrade", "--install", "metallb", "metallb", "--repo", "https://metallb.github.io/metallb",
         "--version", "0.16.1", "-n", "metallb-system", "--wait"],
        ["kubectl", "apply", "-f", "ingress/metallb-pool.yaml"],
        ["helm", "upgrade", "--install", "istio-base", f"{charts}/base", "--version", "1.31.1",
         "-n", "istio-system", "--create-namespace", "--set", "defaultRevision=default", "--wait"],
        ["helm", "upgrade", "--install", "istiod", f"{charts}/istiod", "--version", "1.31.1",
         "-n", "istio-system", "-f", "ingress/istiod-values.yaml", "--wait"],
        ["helm", "upgrade", "--install", "cert-manager", "cert-manager", "--repo", "https://charts.jetstack.io",
         "--version", "v1.21.2", "-n", "cert-manager", "--create-namespace",
         "-f", "ingress/cert-manager-values.yaml", "--wait"],
        ["op", "inject", "-f", "-i", "ingress/ingress.yaml.tpl", "-o", RENDERED],
        ["kubectl", "apply", "-f", RENDERED],
    ]


def test_the_rendered_manifest_is_deleted_and_never_printed(tmp_path, talos):
    env, result = ingress(tmp_path, talos)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not (talos / RENDERED).exists()
    assert SENTINEL not in result.stdout + result.stderr


def test_refuses_when_generated_is_not_gitignored(tmp_path, talos):
    (talos.parent / ".gitignore").unlink()
    env, result = ingress(tmp_path, talos)
    assert result.returncode == 1
    assert calls(env) == []
    assert not (talos / RENDERED).exists()


def test_a_refused_apply_is_retried_without_a_second_op_call(tmp_path, talos):
    env, result = ingress(tmp_path, talos, STUB_KUBECTL_FAIL=f"{RENDERED}:1")
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(applies_of_rendered(env)) == 2
    assert len(calls(env, "op")) == 1


def test_gives_up_after_five_refusals_and_still_deletes_the_manifest(tmp_path, talos):
    env, result = ingress(tmp_path, talos, STUB_KUBECTL_FAIL=f"{RENDERED}:5")
    assert result.returncode != 0
    assert len(applies_of_rendered(env)) == 5
    assert len(calls(env, "op")) == 1
    assert not (talos / RENDERED).exists()


def test_the_template_holds_exactly_the_five_resources_and_three_references():
    text = (TALOS_DIR / "ingress" / "ingress.yaml.tpl").read_text()
    assert [d["kind"] for d in documents("ingress/ingress.yaml.tpl")] == [
        "Secret", "ClusterIssuer", "ConfigMap", "Gateway", "HTTPRoute",
    ]
    assert set(re.findall(r"\{\{\s*(op://[^}]*?)\s*\}\}", text)) == {
        "op://Personal/Cloudflare API Token - Ansible Vault DNS Edit/credential",
        "op://Personal/Certbot Email/notesPlain",
        "op://Home Lab/Home Lab/domains/internal",
    }


def test_the_gateway_serves_the_wildcard_on_80_and_443():
    gateway = resource("Gateway")
    assert gateway["spec"]["gatewayClassName"] == "istio"
    listeners = {listener["name"]: listener for listener in gateway["spec"]["listeners"]}
    assert [listener["port"] for listener in gateway["spec"]["listeners"]] == [80, 443]
    assert listeners["https"]["hostname"].startswith("*.picluster.")
    assert listeners["https"]["tls"]["certificateRefs"] == [{"name": "wildcard-picluster-tls"}]


def test_the_gateway_configmap_holds_only_keys_istio_knows():
    # Istio fails the gateway's render on a key it doesn't know.
    data = resource("ConfigMap")["data"]
    assert set(data) == {"deployment", "podDisruptionBudget"}
    deployment = yaml.safe_load(data["deployment"])
    assert yaml.safe_load(data["podDisruptionBudget"]) == {"spec": {"minAvailable": 1}}
    (spread,) = deployment["spec"]["template"]["spec"]["topologySpreadConstraints"]
    assert spread["labelSelector"]["matchLabels"] == {
        "gateway.networking.k8s.io/gateway-name": resource("Gateway")["metadata"]["name"],
    }


def test_the_pool_holds_the_address_the_gateway_asks_for():
    (address,) = resource("IPAddressPool", "ingress/metallb-pool.yaml")["spec"]["addresses"]
    annotations = resource("Gateway")["spec"]["infrastructure"]["annotations"]
    assert address == annotations["metallb.io/loadBalancerIPs"] + "/32"
