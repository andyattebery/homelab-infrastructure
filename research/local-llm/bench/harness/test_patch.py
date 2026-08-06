#!/usr/bin/env python3
"""Guards for the SearXNG full-content patch.

    python3 test_patch.py       # Mac, no GPU, no container, no LDR

The patch lives at
`ansible/roles/docker_compose_local_deep_research/files/patches/sitecustomize.py` and is
loaded by CPython's `site` module in the LDR container.

WHY THESE GUARDS ARE STRICTER THAN USUAL
----------------------------------------
We are **not filing this upstream**, so nothing external will ever make the patch redundant
and nobody else will notice if it rots. The image is `:latest` with `AutoUpdate=registry`, so
upstream can change `create_search_engine`'s name or signature under us at any time. If that
happens the wrapper becomes a silent no-op and **every subsequent measurement quietly returns
to snippets with no other signal** — the same shape as the kwargs defect that cost this
project its configuration labels.

So: one test that the patch does what it claims, one that it leaves everything else alone,
and one that fails loudly if it ever stops applying.
"""

import importlib.util
import sys
import types
from pathlib import Path

PATCH = (Path(__file__).resolve().parents[4] / "ansible" / "roles"
         / "docker_compose_local_deep_research" / "files" / "patches" / "sitecustomize.py")


def load():
    assert PATCH.exists(), f"patch missing at {PATCH}"
    spec = importlib.util.spec_from_file_location("_ldr_patch_under_test", PATCH)
    mod = importlib.util.module_from_spec(spec)
    # dont_write_bytecode, because PATCH lives in an Ansible `files/` directory that the
    # docker_compose role copies WHOLESALE to the container (copy_config_dirs.yaml:19-25 —
    # ansible.builtin.copy has no exclude). Without this, running the tests leaves a
    # Mac-built __pycache__ that then ships to /patches, which is mounted READ-ONLY: CPython
    # cannot refresh a stale .pyc there, and only the source-mtime check stands between us
    # and importing one. test_the_patch_dir_ships_nothing_but_the_patch is the guard.
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prev
    return mod


def wrapped(**engine_kw):
    """A fake factory module with the wrapper applied, plus a record of what got through."""
    sc = load()
    seen = []
    fake = types.ModuleType("fake_factory")

    def create_search_engine(*args, **kw):
        seen.append((args, dict(kw)))
        return "ENGINE"

    fake.create_search_engine = create_search_engine
    sc._apply(fake)
    fake.create_search_engine(**engine_kw) if engine_kw else None
    return fake, seen


def call(**kw):
    """Invoke the wrapper and return the use_full_search it forwarded (or None)."""
    fake, seen = wrapped()
    fake.create_search_engine(**kw)
    return seen[-1][1].get("use_full_search")


FULL = {"search.snippets_only": {"value": False}}
SNIP = {"search.snippets_only": {"value": True}}


# ----------------------------------------------------------------- does what it claims

def test_research_path_gets_full_content_when_the_setting_asks_for_it():
    """`get_search` is the only caller that sets `max_results` (factory.py:656-658), and it
    is the research path. This is the whole point of the patch."""
    assert call(engine_name="searxng", max_results=10, settings_snapshot=FULL) is True


def test_the_setting_is_respected_not_overridden():
    """The patch must not force full content — otherwise `search.snippets_only` becomes a lie
    in the other direction and we can no longer measure both arms of Step A."""
    assert call(engine_name="searxng", max_results=10, settings_snapshot=SNIP) is False


def test_absent_setting_keeps_upstreams_default():
    """Upstream's default is snippets-only; an unset key must not silently flip behaviour."""
    assert call(engine_name="searxng", max_results=10, settings_snapshot={}) is False
    assert call(engine_name="searxng", max_results=10) is False


# ----------------------------------------------------------------- leaves everything else alone

def test_the_reputation_filter_is_untouched():
    """`journal_reputation_filter.py:278` builds a searxng engine POSITIONALLY and without
    `max_results`, to score a journal (`:732 self.__engine.run(query)`). Making that crawl
    full pages is pure cost for a lookup that does not need them."""
    fake, seen = wrapped()
    fake.create_search_engine("searxng", llm="model", settings_snapshot=FULL)
    assert "use_full_search" not in seen[-1][1]


def test_langgraph_per_call_engines_are_untouched():
    """`langgraph_agent_strategy.py:274,324` — the deployed UI default. Deliberately excluded
    until there is evidence full content is worth having; widening is one condition."""
    assert call(engine_name="searxng", llm="m", settings_snapshot=FULL) is None


def test_mcp_server_opt_out_is_honoured():
    """`mcp/server.py:734` passes max_results AND search_snippets_only=True — it has already
    chosen snippets, so the patch must not override it."""
    assert call(engine_name="searxng", max_results=5, search_snippets_only=True,
                settings_snapshot=FULL) is None


def test_other_engines_are_untouched():
    assert call(engine_name="brave", max_results=10, settings_snapshot=FULL) is None


def test_an_explicit_caller_choice_wins():
    assert call(engine_name="searxng", max_results=10, use_full_search=False,
                settings_snapshot=FULL) is False


def test_positional_calls_do_not_rebind_arguments():
    """A named wrapper signature would bind `llm` to `settings_snapshot` for the positional
    caller. This is why the wrapper takes *args/**kwargs."""
    fake, seen = wrapped()
    fake.create_search_engine("searxng", llm="model-object", settings_snapshot=FULL)
    args, kw = seen[-1]
    assert args == ("searxng",) and kw["llm"] == "model-object"
    assert kw["settings_snapshot"] is FULL


# ----------------------------------------------------------------- fails loudly if it rots

def test_patch_reports_when_it_cannot_apply():
    """THE guard. If upstream renames or removes `create_search_engine`, the wrapper must say
    so rather than silently doing nothing and returning every measurement to snippets."""
    sc = load()
    empty = types.ModuleType("no_such_symbol")
    sc._apply(empty)                       # must not raise
    assert not hasattr(empty, "create_search_engine"), (
        "the patch invented a symbol upstream does not have")


def test_applying_twice_does_not_double_wrap():
    """Two interpreters, one module: re-application must be a no-op, or `use_full_search`
    could be computed from a stale snapshot."""
    sc = load()
    fake = types.ModuleType("f")
    fake.create_search_engine = lambda *a, **k: None
    sc._apply(fake)
    first = fake.create_search_engine
    sc._apply(fake)
    assert fake.create_search_engine is first


def test_the_wrapper_keeps_a_handle_on_the_original():
    """So a future test — or a human — can prove what upstream did before we intervened."""
    sc = load()
    fake = types.ModuleType("f")
    orig = lambda *a, **k: None                                    # noqa: E731
    fake.create_search_engine = orig
    sc._apply(fake)
    assert fake.create_search_engine._ldr_patch_orig is orig


def test_the_kill_switch_is_documented_and_named():
    """An operator needs a way to turn this off without editing a mounted file."""
    src = PATCH.read_text()
    assert "LDR_DISABLE_SEARXNG_FULLTEXT_PATCH" in src


def test_the_patch_explains_the_bug_it_works_around():
    """This file is permanent and nobody upstream will ever explain it for us. The citations
    are the only thing that makes it re-checkable against a future LDR version."""
    src = PATCH.read_text()
    for cite in ("search_engine_factory.py:449-451", "supports_full_search",
                 "use_full_search", "search_engine_base.py:697"):
        assert cite in src, f"the patch no longer explains {cite}"


def test_the_patch_dir_ships_nothing_but_the_patch():
    """The role copies this directory wholesale to /patches in the container, so anything
    left here is deployed. This caught a real one: `load()` above used to write
    __pycache__/sitecustomize.cpython-314.pyc, which reached the container — same interpreter
    tag, read-only mount, so CPython could never refresh it if it went stale."""
    strays = sorted(p.name for p in PATCH.parent.iterdir() if p.name != PATCH.name)
    assert not strays, f"these would be deployed to /patches alongside the patch: {strays}"


def test_patch_is_lazy_not_eager():
    """Importing the factory module costs ~5.7 s against a 0.02 s baseline in the container.
    An eager import here would add that to every python process, including each ldr_trial
    subprocess."""
    src = PATCH.read_text()
    assert "meta_path" in src, "the hook must be lazy"
    top = src.split("class _Loader")[0]
    assert "import local_deep_research" not in top, (
        "the patch imports LDR at interpreter start — that is ~6s on every process")


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"  FAIL  {name}: {e}")
    print(f"\n{fails} failure(s)")
    sys.exit(1 if fails else 0)
