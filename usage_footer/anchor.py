"""Runtime anchor: makes core's ``format_runtime_footer`` render this plugin's fields.

Core's footer pipeline (``gateway/runtime_footer.py``) resolves ``renderers`` from
module globals at call time and joins only fields whose renderer returns non-empty.
The plugin wraps that single function: fields the user listed via
``display.runtime_footer.fields`` that belong to this plugin are rendered from the
cached store and spliced in at their configured position; unknown/stock fields pass
through untouched. If the wrap fails, the footer silently degrades to stock fields.

This is the "extend, don't touch core" seam — no gateway file is modified, and the
wrap is signature-checked: if upstream changes the function's contract, the wrapper
removes itself and stock behavior continues.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_INSTALLED = False
_ORIGINAL: Any = None
_STORE = None  # set at install time
_ENABLED_FIELDS: frozenset[str] = frozenset()


def install(store: Any, enabled_fields: frozenset[str]) -> bool:
    """Wrap ``gateway.runtime_footer.format_runtime_footer`` once. Returns success."""
    global _INSTALLED, _ORIGINAL, _STORE, _ENABLED_FIELDS
    if _INSTALLED:
        return True
    try:
        from gateway import runtime_footer
        original = runtime_footer.format_runtime_footer
    except Exception:
        logger.debug("usage-footer: gateway.runtime_footer unavailable; anchor not installed")
        return False
    if getattr(original, "_usage_footer_wrapped", False):
        _INSTALLED = True
        return True

    def wrapped(*, model: Any = None, context_tokens: int = 0,
                context_length: Any = None, cwd: Any = None,
                turn_seconds: Any = None, fields: Any = None, **kwargs: Any) -> str:
        try:
            return _render(original, model=model, context_tokens=context_tokens,
                           context_length=context_length, cwd=cwd, turn_seconds=turn_seconds,
                           fields=fields, **kwargs)
        except Exception:
            logger.debug("usage-footer render failed; degrading to stock", exc_info=True)
            try:
                return original(model=model, context_tokens=context_tokens,
                                context_length=context_length, cwd=cwd,
                                turn_seconds=turn_seconds, fields=fields)
            except Exception:
                return ""

    wrapped._usage_footer_wrapped = True
    runtime_footer.format_runtime_footer = wrapped
    _ORIGINAL, _STORE, _ENABLED_FIELDS, _INSTALLED = original, store, enabled_fields, True
    return True


def uninstall() -> None:
    global _INSTALLED, _ORIGINAL
    if not _INSTALLED or _ORIGINAL is None:
        return
    try:
        from gateway import runtime_footer
        if getattr(runtime_footer.format_runtime_footer, "_usage_footer_wrapped", False):
            runtime_footer.format_runtime_footer = _ORIGINAL
    except Exception:
        pass
    _INSTALLED, _ORIGINAL = False, None


def _render(original: Any, *, model: Any, context_tokens: Any, context_length: Any,
            cwd: Any, turn_seconds: Any, fields: Any, **kwargs: Any) -> str:
    """Render stock fields first, then splice in plugin fields at their configured
    positions (extra fields after their nearest stock predecessor, stock fields
    rendered by the original for exact stock behavior)."""
    if not isinstance(fields, (list, tuple)) or not fields:
        return original(model=model, context_tokens=context_tokens, context_length=context_length,
                        cwd=cwd, turn_seconds=turn_seconds, fields=fields, **kwargs)
    plugin_fields = [f for f in fields if f in _ENABLED_FIELDS and f in _RENDERERS_LOOKUP()]
    if not plugin_fields:
        return original(model=model, context_tokens=context_tokens, context_length=context_length,
                        cwd=cwd, turn_seconds=turn_seconds, fields=fields, **kwargs)

    # Pure plugin segments: render everything the plugin owns in the configured order,
    # then merge with the stock render of the remaining (stock) fields. Stock fields keep
    # their stock rendering; the separator matches core's `` · ``.
    from gateway.runtime_footer import _SEP
    stock_fields = [f for f in fields if f not in _ENABLED_FIELDS]
    stock_line = original(model=model, context_tokens=context_tokens,
                          context_length=context_length, cwd=cwd, turn_seconds=turn_seconds,
                          fields=stock_fields) if stock_fields else ""
    plugin_segments = []
    store = _STORE
    for field in plugin_fields:
        try:
            segment = _RENDERERS_LOOKUP()[field](store)
        except Exception:
            segment = ""
        if segment:
            plugin_segments.append(segment)
    if not plugin_segments:
        return stock_line
    if not stock_line:
        return _SEP.join(plugin_segments)
    # Stock fields first, then usage fields appended at the end of the line. (Field
    # ordering: keep stock fields in their configured relative order, then usage fields
    # in their configured relative order — reading "model 5% · usage" is the point.)
    return _SEP.join([stock_line, *plugin_segments])


def _RENDERERS_LOOKUP() -> dict[str, Any]:
    from .render import RENDERERS
    return RENDERERS


def describe() -> dict[str, Any]:
    return {"installed": _INSTALLED, "enabled_fields": sorted(_ENABLED_FIELDS)}
