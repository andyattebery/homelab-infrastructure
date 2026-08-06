"""Make SearXNG actually fetch page content in local-deep-research.

Loaded automatically by CPython's `site` module at interpreter start, because the container
sets `PYTHONPATH=/patches` and ships this file there. Nothing imports it explicitly.

THE BUG (LDR v1.10.0, still present in v1.10.1 and main as of 2026-08-02)
------------------------------------------------------------------------
Full page content is produced by wrapping the engine:

    # web_search_engines/search_engine_factory.py:449-451
    if kwargs.get("use_full_search", False) and engine_config.get("supports_full_search", False):
        return _create_full_search_wrapper(...)

SearXNG **declares** `supports_full_search: true` (CONFIGURATION.md:443) — it advertises the
capability — but `use_full_search` is only set at `:673-679`, for
duckduckgo/serpapi/google_pse/brave/mojeek. **searxng is in neither that list nor the
snippets list at :684-695**, so the flag that activates its own advertised capability is
never passed, and `search_engine_base.py:697` short-circuits to snippets.

Measured, not inferred: with `search.snippets_only: False` set through the real path, the
constructed engine still reports `search_snippets_only == True`, and every source came back
at 35-400 characters where a fetched page is thousands.

Searched before writing this: no upstream issue mentions `snippets_only`, `use_full_search`
or `supports_full_search`; no open PR touches the factory; the relevant branch is byte
identical in v1.10.1 and main. **We are not filing it upstream**, so this patch is permanent
and its guards (bench/harness/test_patch.py) matter more than they would for a stopgap.

WHY A WRAPPER AND NOT A PATCHED FILE
------------------------------------
Bind-mounting a modified `search_engine_factory.py` would (a) hard-code
`/install/.venv/lib/python3.14/...` into the mount path, on an image pinned `:latest` with
AutoUpdate=registry, where a Python bump silently breaks it — and a bind mount whose source
does not match its target creates a *directory*, breaking the package outright; and (b)
freeze upstream's file, masking every future fix to that module. A wrapper defers to upstream
for everything else and simply stops firing if this is ever fixed.

WHY LAZY
--------
Importing the factory module costs **5.70 s** against a 0.02 s bare-interpreter baseline
(measured in this container). Patching eagerly here would add ~6 s to *every* python process
in the container, including the app's own startup and each `ldr_trial.py` subprocess. So this
installs a meta-path hook and does nothing at all until something actually imports the target.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import os
import sys

TARGET = "local_deep_research.web_search_engines.search_engine_factory"
ENGINE = "searxng"

_LOG = "[ldr-patch]"


def _log(msg: str) -> None:
    # stderr, not logging: this runs before the app configures its logger.
    print(f"{_LOG} {msg}", file=sys.stderr, flush=True)


def _snippets_only(settings_snapshot) -> bool:
    """The user's `search.snippets_only`, defaulting to upstream's True.

    The patch **respects** this rather than forcing full content — otherwise the setting
    becomes a lie in the other direction and both arms can no longer be measured.
    """
    snap = settings_snapshot or {}
    v = snap.get("search.snippets_only")
    if isinstance(v, dict):
        v = v.get("value")
    return True if v is None else bool(v)


def _apply(mod) -> None:
    """Wrap `create_search_engine` so searxng receives the flag it advertises support for."""
    orig = getattr(mod, "create_search_engine", None)
    if orig is None:                      # signature/layout changed upstream
        _log(f"NOT APPLIED: {TARGET}.create_search_engine is missing")
        return
    if getattr(orig, "_ldr_patch_applied", False):
        return

    def create_search_engine(*args, **kw):
        # *args/**kw, never a named signature: journal_reputation_filter.py:278 calls
        # create_search_engine("searxng", llm=..., ...) POSITIONALLY, so naming the
        # parameters here would silently rebind its arguments.
        name = args[0] if args else kw.get("engine_name")
        if (
            name == ENGINE
            and "use_full_search" not in kw          # never override an explicit choice
            and "max_results" in kw                  # see the scoping note below
            and kw.get("search_snippets_only") is not True
        ):
            kw["use_full_search"] = not _snippets_only(kw.get("settings_snapshot"))
        return orig(*args, **kw)

    # SCOPING — `max_results` is the discriminator, verified against all four call sites:
    #
    #   factory.py:716 (via get_search)          sets max_results (:656-658)  -> PATCHED
    #   langgraph_agent_strategy.py:274, :324    no max_results               -> untouched
    #   journal_reputation_filter.py:278         no max_results               -> untouched
    #   mcp/server.py:734                        max_results + search_snippets_only=True
    #                                            -> untouched, it opts out explicitly
    #
    # The reputation filter genuinely searches (`:732 self.__engine.run(query)`) to score a
    # journal; making that crawl full pages would be pure cost for a lookup that needs none.
    # Excluding langgraph is deliberate too: it is the deployed UI default and is NOT what
    # Part 2 measures, so it keeps its current behaviour until we have evidence full content
    # is worth having. Widening later is a one-line change to this condition.
    create_search_engine._ldr_patch_applied = True          # type: ignore[attr-defined]
    create_search_engine._ldr_patch_orig = orig             # type: ignore[attr-defined]
    mod.create_search_engine = create_search_engine
    _log(f"applied: {ENGINE} now receives use_full_search via {TARGET}")


class _Loader(importlib.abc.Loader):
    """Delegates to the real loader, then patches the module it just produced."""

    def __init__(self, real):
        self._real = real

    def create_module(self, spec):
        return self._real.create_module(spec)

    def exec_module(self, module):
        self._real.exec_module(module)
        try:
            _apply(module)
        except Exception as e:                          # noqa: BLE001
            # Never break the import. A missing patch degrades to snippets, which the
            # harness detects; an exception here would take down the whole application.
            _log(f"NOT APPLIED ({type(e).__name__}: {e})")


class _Finder(importlib.abc.MetaPathFinder):
    """Fires once, when something first imports the factory module."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != TARGET:
            return None
        sys.meta_path.remove(self)                      # avoid recursing into ourselves
        try:
            spec = importlib.util.find_spec(fullname)
        finally:
            if self not in sys.meta_path:
                sys.meta_path.insert(0, self)
        if spec is None or spec.loader is None:
            return None
        sys.meta_path.remove(self)                      # one-shot: real loader takes over
        spec.loader = _Loader(spec.loader)
        return spec


if os.environ.get("LDR_DISABLE_SEARXNG_FULLTEXT_PATCH") != "1":
    sys.meta_path.insert(0, _Finder())
