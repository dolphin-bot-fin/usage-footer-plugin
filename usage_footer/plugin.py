"""register(ctx) — config, refresher lifecycle, anchor install, /usage-footer command.

Config (``plugins.entries.usage-footer.settings`` in ~/.hermes/config.yaml):

    plugins:
      entries:
        usage-footer:
          settings:
            enabled: true              # default
            fields: [...]              # usage fields to fetch/render (see README)
            refresh_seconds: 60        # clamped 15-900
            auto_enable_footer: true   # log a config snippet when footer is off

Per-provider switches: ``cline.enabled``, ``opencode.enabled``,
``openrouter.enabled``, ``openai.enabled``, ``anthropic.enabled`` (all default
true; a disabled provider's fields are dropped).

Defaults keep the stock footer fields (model, context_pct, cwd) and append the
usage fields after them. The plugin never writes config.yaml: ``auto_enable_footer``
only logs a ready-to-paste snippet when ``display.runtime_footer.enabled`` isn't
already true (the gateway re-reads config per turn, so the snippet applies on save).
"""

from __future__ import annotations

import logging

from . import anchor, render
from .store import UsageStore, get_store

logger = logging.getLogger(__name__)

_PLUGIN_ID = "usage-footer"

_ALL_FIELDS = tuple(render.RENDERERS)
_DEFAULT_FIELDS = ("cline_5h", "oc_rolling", "oc_weekly", "or_today",
                   "openai_5h", "anthropic_5h")

_FIELD_PROVIDER_MAP: dict[str, str] = {
    "cline_5h": "cline", "oc_rolling": "opencode", "oc_weekly": "opencode",
    "or_today": "openrouter", "or_week": "openrouter",
    "openai_5h": "openai", "anthropic_5h": "anthropic",
}

_refresh_stop = None
_started = False


def register(ctx) -> None:
    global _started
    settings = _settings(ctx)

    if settings.get("enabled") is False:
        logger.info("usage-footer disabled via config")
        return

    if settings.get("auto_enable_footer", True):
        _footer_enabled_or_hint()

    fields = _resolve_fields(settings)
    if not fields:
        logger.info("usage-footer: no fields resolved; not starting")
        return

    store = get_store()

    if not anchor.install(store, frozenset(fields)):
        logger.warning("usage-footer: anchor install failed; plugin idle")
        return

    if not _started:
        needed = sorted({_FIELD_PROVIDER_MAP[f] for f in fields})
        store.start(needed, ttl=settings.get("refresh_seconds"))
        _started = True

    try:
        ctx.register_command("usage-footer", handler=_handle_status,
                             description="Provider usage footer status")
    except Exception:
        logger.debug("usage-footer command registration skipped", exc_info=True)


def any_fields(fields: list[str]) -> list[str]:
    """Fields that have a provider mapping (all of them, by construction)."""
    return [f for f in fields if f in _FIELD_PROVIDER_MAP]


def _settings(ctx) -> dict:
    """Read leaf settings via the plugin-relative API (``settings`` root is reserved,
    so fetch each known key individually with its default)."""
    out: dict = {}
    for key, default in (
        ("enabled", True), ("fields", None), ("refresh_seconds", 60),
        ("auto_enable_footer", True),
        ("cline.enabled", True), ("opencode.enabled", True),
        ("openrouter.enabled", True), ("openai.enabled", True),
        ("anthropic.enabled", True),
    ):
        try:
            out[key] = ctx.get_config(key, default)
        except Exception:
            out[key] = default
    return out


def _resolve_fields(settings: dict) -> list[str]:
    requested = settings.get("fields")
    fields = list(_DEFAULT_FIELDS) if not requested else list(requested)
    # Validate
    fields = [f for f in fields if f in _ALL_FIELDS]
    # Per-provider switches
    disabled = {name.split(".")[0] for name, val in settings.items()
                if name.endswith(".enabled") and val is False}
    fields = [f for f in fields if _FIELD_PROVIDER_MAP.get(f) not in disabled]
    return fields or list(_DEFAULT_FIELDS)


def _footer_enabled_or_hint() -> None:
    """Log a ready-to-paste config snippet when the stock footer isn't enabled."""
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
        display = (cfg.get("display") or {}).get("runtime_footer") or {}
        if display.get("enabled"):
            return
        fields = list(dict.fromkeys(
            ["model", "context_pct", "cwd", *_DEFAULT_FIELDS]))  # stock + usage, deduped
        logger.warning(
            "usage-footer: display.runtime_footer is not enabled. Add to config.yaml:\n%s",
            yaml_snippet(fields))
    except Exception:
        logger.debug("usage-footer: footer-enabled check failed", exc_info=True)


def yaml_snippet(fields: list[str]) -> str:
    return (
        "display:\n"
        "  runtime_footer:\n"
        "    enabled: true\n"
        f"    fields: [{', '.join(fields)}]"
    )


def _handle_status(raw_args: str) -> str:
    store = get_store()
    snaps = store.all_snapshots()
    desc = anchor.describe()
    if desc["installed"]:
        fields = ", ".join(sorted(desc["enabled_fields"])) or "(none)"
        lines = [f"**Usage footer active** — fields: {fields}"]
    else:
        lines = ["Usage footer NOT installed (anchor failed)."]
    if not snaps:
        lines.append("No usage data yet — refresher may still be starting, "
                     "or no API keys are set.")
    for prov in ("cline", "opencode", "openrouter", "openai", "anthropic"):
        snap = snaps.get(prov)
        if snap is None:
            continue
        parts = []
        for w in snap.windows:
            if w.detail:
                parts.append(w.detail)
            elif w.used_percent is not None:
                parts.append(f"{w.label or 'usage'} {w.used_percent:.0f}%")
        lines.append(f"- {prov}: {' · '.join(parts) if parts else '(no windows)'}")
    age = None
    for prov in ("cline", "opencode", "openrouter", "openai", "anthropic"):
        a = store.age_seconds(prov)
        if a is not None and (age is None or a < age):
            age = a
    if age is not None:
        lines.append(f"Freshest data: {age:.0f}s old")
    return "\n".join(lines)
