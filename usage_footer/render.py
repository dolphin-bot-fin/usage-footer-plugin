"""Pure rendering: snapshot → footer field strings.

Field names exposed through ``display.runtime_footer.fields`` (order in the list is
order in the footer):

* ``cline_5h``       → ``Cline 12%``
* ``oc_rolling``     → ``OC 31%``          (OpenCode rolling window)
* ``oc_weekly``      → ``OCw 12%``
* ``or_today``       → ``OR $1.23``        (OpenRouter daily spend)
* ``openai_5h``      → ``GPT 45% used``    (OpenAI/Codex session window; % used)
* ``anthropic_5h``   → ``Claude 8% used``  (Anthropic session window; % used)

Percent fields show % USED (matches the provider dashboards); OpenAI/Anthropic
values come from core's account-usage windows which are also "used" percentages.
A field with no data is skipped — core's footer contract is partial > placeholder.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .store import UsageStore


def _pct(used_percent: Any) -> str:
    try:
        return f"{max(0, min(100, round(float(used_percent))))}%"
    except (TypeError, ValueError):
        return ""


def _window(snap: Any, index: int = 0) -> Any:
    if snap is None:
        return None
    windows = getattr(snap, "windows", ())
    return windows[index] if len(windows) > index else None


def _pct_field(store: UsageStore, provider: str, index: int = 0) -> str:
    window = _window(store.get(provider), index)
    if window is None or getattr(window, "used_percent", None) is None:
        return ""
    return _pct(window.used_percent)


def _spend_field(store: UsageStore, provider: str, index: int = 0) -> str:
    window = _window(store.get(provider), index)
    if window is None:
        return ""
    return (getattr(window, "detail", "") or "").strip()


def _labelled(label: str, value: str) -> str:
    return f"{label} {value}" if value else ""


def _pct_l(store: UsageStore, provider: str, index: int = 0) -> str:
    return _pct_field(store, provider, index)


RENDERERS: dict[str, Callable[[UsageStore], str]] = {
    "cline_5h": lambda s: _labelled("Cline", _pct_l(s, "cline")),
    "oc_rolling": lambda s: _labelled("OC", _pct_l(s, "opencode", 0)),
    "oc_weekly": lambda s: _labelled("OCw", _pct_l(s, "opencode", 1)),
    "or_today": lambda s: _labelled("OR", _spend_field(s, "openrouter", 0)),
    "or_week": lambda s: _labelled("ORw", _spend_field(s, "openrouter", 1)),
    "openai_5h": lambda s: _labelled("GPT", _pct_l(s, "openai")),
    "anthropic_5h": lambda s: _labelled("Claude", _pct_l(s, "anthropic")),
}

FIELD_LABELS: dict[str, str] = {
    "cline_5h": "Cline", "oc_rolling": "OC", "oc_weekly": "OCw", "or_today": "OR",
    "or_week": "ORw", "openai_5h": "GPT", "anthropic_5h": "Claude",
}
