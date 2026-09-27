"""secrets.yaml.tpl against the bundle the pinned talosctl really writes.

The template is the only map between the secrets bundle and the pi-cluster 1Password item:
store-secrets.sh fills the item through it and gen-config.sh reads the bundle back through it. A
bundle key the template lacks would never reach 1Password, and the cluster could not be
regenerated from the item.
"""

import re

import yaml

from support import TALOS_DIR, gen_secrets, leaves

TEMPLATE = TALOS_DIR / "secrets.yaml.tpl"
REFERENCE = re.compile(r"\{\{ op://Home Lab/pi-cluster/talos/([a-z0-9]+(?: [a-z0-9]+)*) \}\}")


def test_template_has_exactly_the_bundles_keys(tmp_path):
    template = yaml.safe_load(TEMPLATE.read_text())
    bundle = yaml.safe_load(gen_secrets(tmp_path / "secrets.yaml").read_text())

    template_paths = [path for path, _ in leaves(template)]
    bundle_paths = [path for path, _ in leaves(bundle)]
    assert len(bundle_paths) == 14, bundle_paths
    assert sorted(template_paths) == sorted(bundle_paths)


def test_every_value_names_a_distinct_talos_field():
    template = yaml.safe_load(TEMPLATE.read_text())
    values = [value for _, value in leaves(template)]
    assert len(values) == 14

    labels = []
    for value in values:
        match = REFERENCE.fullmatch(value)
        assert match, value
        labels.append(match.group(1))
    assert len(set(labels)) == len(labels), labels
