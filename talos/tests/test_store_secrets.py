"""store-secrets.sh: the guards around a live cluster's PKI, and what reaches 1Password.

The real talosctl generates the bundle; op is a stub. The item below is modelled on
`op item get --format json` output as op 2.39.0 documents it -- sections[{id, label}] and
fields[{id, type, label, value, section{id, label}, reference}]. It is not captured from the real
pi-cluster item, which holds vaulted MACs. The real round trip (store, then op inject back) is
checked by hand, README.md "Build".
"""

import json
import stat

import yaml

from support import TALOS_DIR, calls, leaves, make_env, run

# Stand-ins, not MAC-shaped: the repo keeps MACs out of committed files, and the script never
# parses these values -- it only has to send them back unchanged.
MACS = {f"pi-cluster-0{n}": f"mac of pi-cluster-0{n}" for n in range(1, 7)}
GET = ["op", "item", "get", "pi-cluster", "--vault", "Home Lab", "--format", "json"]
EDIT = ["op", "item", "edit", "pi-cluster", "--vault", "Home Lab"]


def item(*extra_sections):
    sections = [{"id": "mac7t5jmkqzq2xbwd4r3ad6cte", "label": "mac address"}]
    sections += [{"id": f"s{i}", "label": label} for i, label in enumerate(extra_sections)]
    return {
        "id": "k3yf7pxq2lbwnhsd4mzr6tceua",
        "title": "pi-cluster",
        "version": 7,
        "vault": {"id": "v2d4m6q8s0u2w4y6a8c0e2g4i6", "name": "Home Lab"},
        "category": "SERVER",
        "sections": sections,
        "fields": [
            {
                "id": "notesPlain",
                "type": "STRING",
                "purpose": "NOTES",
                "label": "notesPlain",
                "reference": "op://Home Lab/pi-cluster/notesPlain",
            }
        ]
        + [
            {
                "id": f"f{host[-1]}",
                "section": {"id": "mac7t5jmkqzq2xbwd4r3ad6cte", "label": "mac address"},
                "type": "STRING",
                "label": host,
                "value": mac,
                "reference": f"op://Home Lab/pi-cluster/mac address/{host}",
            }
            for host, mac in MACS.items()
        ],
    }


def store(tmp_path, talos, current, **extra):
    (tmp_path / "item.json").write_text(json.dumps(current))
    env = make_env(
        tmp_path,
        STUB_OP_ITEM=tmp_path / "item.json",
        STUB_OP_CAPTURE=tmp_path / "template.json",
        **extra,
    )
    return env, run(talos, "store-secrets.sh", env=env)


def expected_fields(bundle):
    """(label, value) per template leaf: the label it names, the bundle value at its path."""
    template = yaml.safe_load((TALOS_DIR / "secrets.yaml.tpl").read_text())
    expected = []
    for path, reference in leaves(template):
        value = bundle
        for key in path:
            value = value[key]
        label = reference.removeprefix("{{ op://Home Lab/pi-cluster/talos/").removesuffix(" }}")
        expected.append((label, value))
    return expected


# ---------------------------------------------------------------------------------------------


def test_stores_the_bundle_in_a_new_talos_section(tmp_path, talos):
    current = item()
    env, result = store(tmp_path, talos, current)
    assert result.returncode == 0, result.stdout + result.stderr

    # One read, one write.
    assert calls(env, "op") == [GET, EDIT]

    bundle = yaml.safe_load((talos / "generated" / "secrets.yaml").read_text())
    values = [value for _, value in leaves(bundle)]
    assert len(values) == 14

    sent = json.loads((tmp_path / "template.json").read_text())
    assert sent["sections"] == current["sections"] + [{"id": "talos", "label": "talos"}]
    # Everything already in the item goes back unchanged -- the template replaces the item.
    assert sent["fields"][: len(current["fields"])] == current["fields"]
    added = sent["fields"][len(current["fields"]):]
    assert [(f["label"], f["value"]) for f in added] == expected_fields(bundle)
    assert all(f["type"] == "CONCEALED" and f["section"] == {"id": "talos"} for f in added)

    # op echoes the item it edited; none of it may reach the terminal.
    for value in values + list(MACS.values()):
        assert value not in result.stdout and value not in result.stderr

    assert [p.name for p in (talos / "generated").iterdir()] == ["secrets.yaml"]
    assert stat.S_IMODE((talos / "generated" / "secrets.yaml").stat().st_mode) == 0o600


def test_refuses_when_the_item_already_has_a_talos_section(tmp_path, talos):
    env, result = store(tmp_path, talos, item("talos"))
    assert result.returncode == 1
    assert calls(env, "op") == [GET]
    assert calls(env, "talosctl") == []
    assert not (talos / "generated" / "secrets.yaml").exists()


def test_refuses_when_a_bundle_already_exists(tmp_path, talos):
    (talos / "generated").mkdir()
    (talos / "generated" / "secrets.yaml").write_text("the bundle a live cluster runs on\n")
    env, result = store(tmp_path, talos, item())
    assert result.returncode == 1
    assert calls(env) == []
    assert (talos / "generated" / "secrets.yaml").read_text() == "the bundle a live cluster runs on\n"


def test_refuses_when_generated_is_not_gitignored(tmp_path, talos):
    (talos.parent / ".gitignore").unlink()
    env, result = store(tmp_path, talos, item())
    assert result.returncode == 1
    assert calls(env) == []
    assert not (talos / "generated").exists()


def test_a_failed_store_leaves_no_bundle_so_it_can_be_rerun(tmp_path, talos):
    env, result = store(tmp_path, talos, item(), STUB_OP_EDIT_EXIT=1)
    assert result.returncode != 0
    assert calls(env, "op") == [GET, EDIT]
    assert not (talos / "generated" / "secrets.yaml").exists()
