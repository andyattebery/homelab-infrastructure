"""flash-sd.sh: what it refuses to write to, and the exact write it makes.

The card is fixtures/diskutil-sd.plist, `diskutil info -plist` captured from a real card in this
Mac (README.md, "Tests"); each refusal case changes one key of that capture. diskutil, curl, sudo
and dd are stubs; plutil, jq and xz are real, and so is talosctl, asked only for its version.
"""

import plistlib

import pytest

from support import FIXTURES, SCHEMATIC, TALOS_VERSION, calls, make_env, run

CARD = FIXTURES / "diskutil-sd.plist"
needs_card = pytest.mark.skipif(
    not CARD.exists(), reason="fixtures/diskutil-sd.plist is captured from a real card (README.md, Tests)"
)
IMAGE = f"images/metal-arm64-{SCHEMATIC}-{TALOS_VERSION}.raw"
# What a 256 GB NVMe drive reports -- the size of a PM991 in a USB enclosure.
PM991_BYTES = 256_060_514_304


def card(tmp_path, **changes):
    info = plistlib.loads(CARD.read_bytes())
    info.update(changes)
    path = tmp_path / "card.plist"
    path.write_bytes(plistlib.dumps(info))
    return path, info["DeviceIdentifier"]


def flash(tmp_path, talos, *args, **changes):
    plist, disk = card(tmp_path, **changes)
    env = make_env(tmp_path, STUB_DISKUTIL_PLIST=plist, STUB_SCHEMATIC_ID=SCHEMATIC)
    return env, disk, run(talos, "flash-sd.sh", disk, *args, env=env)


def image_downloads(env):
    return [c for c in calls(env, "curl") if any(a.startswith("https://factory.talos.dev/image/") for a in c)]


# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [[], ["disk4s1"], ["/dev/disk4"], ["rdisk4"], ["disk4", "--force"], ["disk4", "--yes", "extra"]],
)
def test_refuses_anything_but_a_whole_disk_name_and_yes(tmp_path, talos, args):
    env = make_env(tmp_path)
    result = run(talos, "flash-sd.sh", *args, env=env)
    assert result.returncode == 1
    assert calls(env) == []


@needs_card
def test_without_yes_it_only_shows_the_card(tmp_path, talos):
    env, disk, result = flash(tmp_path, talos)
    assert result.returncode == 1
    assert plistlib.loads(CARD.read_bytes())["MediaName"] in result.stdout
    assert calls(env) == [["diskutil", "info", "-plist", f"/dev/{disk}"]]


@needs_card
@pytest.mark.parametrize(
    "changes",
    [{"RemovableMedia": False}, {"TotalSize": PM991_BYTES}, {"WholeDisk": False}],
    ids=["fixed-disk", "256gb-disk", "not-whole"],
)
def test_refuses_what_is_not_an_sd_card(tmp_path, talos, changes):
    env, _, result = flash(tmp_path, talos, "--yes", **changes)
    assert result.returncode == 1
    assert [c[0] for c in calls(env)] == ["diskutil"]
    assert calls(env, "dd") == []


@needs_card
def test_flashes_the_card(tmp_path, talos):
    env, disk, result = flash(tmp_path, talos, "--yes")
    assert result.returncode == 0, result.stdout + result.stderr
    write = ["dd", f"if={IMAGE}", f"of=/dev/r{disk}", "bs=4m", "status=progress"]
    assert [c for c in calls(env) if c[0] in ("diskutil", "sudo", "dd")] == [
        ["diskutil", "info", "-plist", f"/dev/{disk}"],
        ["diskutil", "info", "-plist", f"/dev/{disk}"],
        ["diskutil", "unmountDisk", f"/dev/{disk}"],
        ["sudo"] + write,
        write,
        ["diskutil", "eject", f"/dev/{disk}"],
    ]
    posts = [c for c in calls(env, "curl") if "https://factory.talos.dev/schematics" in c]
    assert len(posts) == 1 and "@schematic.yaml" in posts[0]
    assert len(image_downloads(env)) == 1
    assert (talos / "schematic.id").read_text() == SCHEMATIC + "\n"


@needs_card
def test_the_built_in_sd_slot_is_accepted(tmp_path, talos):
    """The MacBook Pro's SDXC slot is internal hardware; its cards are still removable media."""
    env, _, result = flash(tmp_path, talos, "--yes", Internal=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(calls(env, "dd")) == 1


@needs_card
def test_the_next_card_reuses_the_image(tmp_path, talos):
    env, _, first = flash(tmp_path, talos, "--yes")
    assert first.returncode == 0, first.stdout + first.stderr
    second = run(talos, "flash-sd.sh", card(tmp_path)[1], "--yes", env=env)
    assert second.returncode == 0, second.stdout + second.stderr
    assert len(image_downloads(env)) == 1
    assert len(calls(env, "dd")) == 2


@needs_card
def test_refuses_a_changed_schematic(tmp_path, talos):
    (talos / "schematic.id").write_text("0" * 64 + "\n")
    env, _, result = flash(tmp_path, talos, "--yes")
    assert result.returncode == 1
    assert calls(env, "dd") == []
    assert image_downloads(env) == []
    assert (talos / "schematic.id").read_text() == "0" * 64 + "\n"
