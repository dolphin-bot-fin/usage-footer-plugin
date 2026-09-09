"""Tests for the usage-footer plugin — pure functions + anchor contract, no network.

Run:  python -m pytest tests/ -q   (from the repo root)
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIR = Path(__file__).resolve().parent.parent
REAL_PKG_DIR = PLUGIN_DIR / "usage_footer"

# Import the implementation package directly (valid identifier, no hyphens).
_pkg_path = str(PLUGIN_DIR)
if _pkg_path not in sys.path:
    sys.path.insert(0, _pkg_path)

import usage_footer.plugin as plugin_mod  # noqa: E402
import usage_footer.render as render_mod  # noqa: E402
import usage_footer.anchor as anchor_mod  # noqa: E402
import usage_footer.providers as providers_mod  # noqa: E402
import usage_footer.store as store_mod  # noqa: E402

UsageStore = store_mod.UsageStore


# ---------------------------------------------------------------- render ----


class _Win:
    def __init__(self, label, used_percent=None, detail=None):
        self.label, self.used_percent, self.detail = label, used_percent, detail


class _Snap:
    def __init__(self, windows):
        self.windows = windows


def _store_with(snapshots: dict) -> UsageStore:
    store = UsageStore()
    with store._lock:
        store._snapshots.update(snapshots)
    return store


def test_pct_field_renders_labelled_percent():
    store = _store_with({"cline": _Snap([_Win("Cline 5h", used_percent=12.4)])})
    assert render_mod.RENDERERS["cline_5h"](store) == "Cline 12%"


def test_missing_provider_renders_empty():
    assert render_mod.RENDERERS["cline_5h"](_store_with({})) == ""


def test_spend_field_uses_window_detail():
    store = _store_with({"openrouter": _Snap([_Win("today", detail="$1.23 spent")])})
    assert render_mod.RENDERERS["or_today"](store) == "OR $1.23 spent"


def test_opencode_indexed_windows():
    snap = _Snap([_Win("rolling", 31), _Win("weekly", 12), _Win("monthly", 17)])
    store = _store_with({"opencode": snap})
    assert render_mod.RENDERERS["oc_rolling"](store) == "OC 31%"
    assert render_mod.RENDERERS["oc_weekly"](store) == "OCw 12%"


def test_clamps_out_of_range_percent():
    store = _store_with({"openai": _Snap([_Win("Session", used_percent=148.0)])})
    assert render_mod.RENDERERS["openai_5h"](store) == "GPT 100%"


# ------------------------------------------------------------- providers ----


def test_fetch_cline_parses_five_hour(monkeypatch):
    prov = providers_mod
    captured = {}

    def fake_get(url, token):
        captured["url"], captured["token"] = url, token
        return {"data": {"limits": [{"type": "five_hour", "percentUsed": 44.6}]}}

    monkeypatch.setattr(prov, "_bearer_get_json", fake_get)
    monkeypatch.setattr(prov, "_env_first", lambda *n: "tok")
    snap = prov.fetch_cline()
    assert snap.windows[0].used_percent == 44.6
    assert "usage-limits" in captured["url"]


def test_fetch_opencode_parses_all_windows(monkeypatch):
    prov = providers_mod
    payload = {"usage": {"rolling": {"percent": 31, "resetsAt": "2026-09-09T03:19:28.864Z"},
                         "weekly": {"percent": 12}, "monthly": {"percent": 17}}}
    monkeypatch.setattr(prov, "_bearer_get_json", lambda url, tok: payload)
    monkeypatch.setattr(prov, "_env_first", lambda *n: "tok")
    snap = prov.fetch_opencode()
    assert [w.used_percent for w in snap.windows] == [31.0, 12.0, 17.0]


def test_fetch_openrouter_daily(monkeypatch):
    prov = providers_mod
    monkeypatch.setattr(prov, "_bearer_get_json", lambda url, tok: {"data": {"usage_daily": 3.5}})
    monkeypatch.setattr(prov, "_env_first", lambda *n: "tok")
    snap = prov.fetch_openrouter()
    assert "$3.50" in snap.windows[0].detail


def test_fetch_missing_key_returns_none(monkeypatch):
    prov = providers_mod
    monkeypatch.setattr(prov, "_env_first", lambda *n: "")
    assert prov.fetch_cline() is None
    assert prov.fetch_opencode() is None


# ---------------------------------------------------------------- anchor ----


def _fake_runtime_footer(sep=" · "):
    """Stub gateway.runtime_footer with a stock format function; returns (module, calls)."""
    mod = types.ModuleType("gateway.runtime_footer")
    mod._SEP = sep
    calls = []

    def stock(*, model=None, context_tokens=0, context_length=None, cwd=None,
              turn_seconds=None, fields=None):
        calls.append(list(fields or []))
        parts = []
        if fields and "model" in fields:
            parts.append("m1")
        if fields and "context_pct" in fields:
            parts.append("5%")
        return sep.join(parts)

    mod.format_runtime_footer = stock
    gw = types.ModuleType("gateway")
    gw.runtime_footer = mod
    sys.modules["gateway"] = gw
    sys.modules["gateway.runtime_footer"] = mod
    return mod, calls


def test_anchor_splices_usage_after_stock(monkeypatch):
    mod, _calls = _fake_runtime_footer()
    store = _store_with({"cline": _Snap([_Win("Cline 5h", 12)])})
    assert anchor_mod.install(store, frozenset(["cline_5h"]))
    out = mod.format_runtime_footer(context_tokens=10, context_length=100,
                                    fields=["model", "context_pct", "cline_5h"])
    assert out == "m1 · 5% · Cline 12%"
    anchor_mod.uninstall()


def test_anchor_preserves_stock_only_call(monkeypatch):
    mod, _calls = _fake_runtime_footer()
    store = _store_with({})
    assert anchor_mod.install(store, frozenset(["cline_5h"]))
    out = mod.format_runtime_footer(context_tokens=10, context_length=100,
                                    fields=["model", "context_pct"])
    assert out == "m1 · 5%"
    anchor_mod.uninstall()


def test_anchor_fails_open_without_runtime_footer(monkeypatch):
    """A raising gateway.runtime_footer module → install returns False (no crash)."""
    import importlib
    saved = {k: v for k, v in sys.modules.items() if k == "gateway" or k.startswith("gateway.")}
    for key in list(saved):
        sys.modules.pop(key, None)
    boom = types.ModuleType("gateway.runtime_footer")

    def _raise(*a, **k):
        raise RuntimeError("simulated missing/broken runtime_footer")

    boom.__getattr__ = _raise  # module-level __getattr__ (PEP 562) — any attribute access fails
    gw = types.ModuleType("gateway")
    gw.__path__ = []  # make it a package so "gateway.runtime_footer" resolves as submodule
    gw.runtime_footer = boom
    sys.modules["gateway"] = gw
    sys.modules["gateway.runtime_footer"] = boom
    try:
        assert anchor_mod.install(UsageStore(), frozenset(["cline_5h"])) is False
    finally:
        sys.modules.update(saved)


# ------------------------------------------------------------ plugin reg ----


def test_resolve_fields_defaults_and_validation():
    assert plugin_mod._resolve_fields({}) == list(plugin_mod._DEFAULT_FIELDS)
    assert plugin_mod._resolve_fields({"fields": ["cline_5h", "bogus"]}) == ["cline_5h"]
    assert plugin_mod._resolve_fields({"fields": ["bogus"]}) == list(plugin_mod._DEFAULT_FIELDS)


def test_field_provider_map_covers_all_fields():
    for field in plugin_mod._ALL_FIELDS:
        assert field in plugin_mod._FIELD_PROVIDER_MAP
