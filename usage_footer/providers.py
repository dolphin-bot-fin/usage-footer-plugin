"""Provider usage fetchers. Each returns an ``AccountUsageSnapshot`` (core's shape,
``agent/account_usage.py``) or ``None`` when the provider has no credentials / the
fetch fails. Network calls are short-timeout and never raise into the caller.

APIs:
* Cline        GET https://api.cline.bot/api/v1/users/me/plan/usage-limits
               → data.limits[] where type=="five_hour" → percentUsed (0-100 used)
* OpenCode     GET https://opencode.ai/zen/go/v1/usage  (Bearer OPENCODE_GO_API_KEY)
               → usage.{rolling,weekly,monthly}.percent (0-100 used) + resetsAt
* OpenRouter   GET https://openrouter.ai/api/v1/credits + /key  (Bearer OPENROUTER_API_KEY)
               → daily spend is key.usage_daily; credits give the balance
* OpenAI       native ``fetch_account_usage("openai-codex")`` — Session/Weekly windows
* Anthropic    native ``fetch_account_usage("anthropic")`` — OAuth-only session/week

Credentials come from the environment (gateway loads ``~/.hermes/.env``); no
plugin-side env parsing. Env key names are read case-insensitively per provider
below, so ``Cline_API_KEY`` and ``CLINE_API_KEY`` both work.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 8.0
_USER_AGENT = "hermes-usage-footer/1.0"

PROVIDER_ORDER: tuple[str, ...] = ("cline", "opencode", "openrouter", "openai", "anthropic")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _bearer_get_json(url: str, token: str) -> Optional[dict[str, Any]]:
    """Bearer-authorized JSON GET; any failure → None (fail-open by design)."""
    try:
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                          "User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — provider outages must never break a reply
        logger.debug("usage-footer fetch failed for %s: %s", url.split("?")[0], exc)
        return None


@dataclass(frozen=True)
class _Snapshot:
    """Minimal structural twin of ``agent.account_usage.AccountUsageSnapshot`` so the
    plugin has no import-time dependency on the core module (which may move again)."""

    provider: str
    source: str
    fetched_at: datetime
    windows: tuple = ()
    details: tuple = ()
    unavailable_reason: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self.windows or self.details) and not self.unavailable_reason


class _Window:
    """Structural twin of ``AccountUsageWindow`` (label, used_percent, reset_at, detail)."""

    __slots__ = ("label", "used_percent", "reset_at", "detail")

    def __init__(self, label: str, used_percent: Optional[float] = None,
                 reset_at: Optional[datetime] = None, detail: Optional[str] = None):
        self.label = label
        self.used_percent = used_percent
        self.reset_at = reset_at
        self.detail = detail


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# --- direct fetchers ---------------------------------------------------------


def fetch_cline() -> Optional[_Snapshot]:
    token = _env_first("CLINE_API_KEY", "Cline_API_KEY")
    if not token:
        return None
    data = _bearer_get_json("https://api.cline.bot/api/v1/users/me/plan/usage-limits", token)
    limits = (data or {}).get("data", {}).get("limits", []) if isinstance(data, dict) else []
    for lim in limits:
        if lim.get("type") == "five_hour":
            pct = lim.get("percentUsed")
            if pct is None:
                continue
            window = _Window(label="Cline 5h", used_percent=float(pct))
            return _Snapshot(provider="cline", source="cline_limits_api", fetched_at=_utc_now(),
                             windows=(window,))
    return None


def fetch_opencode() -> Optional[_Snapshot]:
    token = _env_first("OPENCODE_GO_API_KEY")
    if not token:
        return None
    data = _bearer_get_json("https://opencode.ai/zen/go/v1/usage", token)
    usage = (data or {}).get("usage", {}) if isinstance(data, dict) else {}
    windows = []
    for key, label in (("rolling", "OpenCode rolling"), ("weekly", "OpenCode weekly"),
                       ("monthly", "OpenCode monthly")):
        entry = usage.get(key) or {}
        pct = entry.get("percent")
        if pct is None:
            continue
        windows.append(_Window(label=label, used_percent=float(pct),
                               reset_at=_parse_iso(entry.get("resetsAt"))))
    if not windows:
        return None
    return _Snapshot(provider="opencode", source="zen_go_usage", fetched_at=_utc_now(),
                     windows=tuple(windows))


def fetch_openrouter() -> Optional[_Snapshot]:
    token = _env_first("OPENROUTER_API_KEY")
    if not token:
        return None
    key_data = (_bearer_get_json("https://openrouter.ai/api/v1/auth/key", token) or {}).get("data") or {}
    daily = key_data.get("usage_daily")
    weekly = key_data.get("usage_weekly")
    monthly = key_data.get("usage_monthly")
    windows = []
    if daily is not None:
        windows.append(_Window(label="OpenRouter today", used_percent=None,
                               detail=f"${float(daily):.2f} spent"))
    if weekly is not None:
        windows.append(_Window(label="OpenRouter week", used_percent=None,
                               detail=f"${float(weekly):.2f} spent"))
    if monthly is not None:
        windows.append(_Window(label="OpenRouter month", used_percent=None,
                               detail=f"${float(monthly):.2f} spent"))
    if not windows:
        return None
    return _Snapshot(provider="openrouter", source="auth_key_api", fetched_at=_utc_now(),
                     windows=tuple(windows))


# --- native fetchers (reuse core; lazy import keeps the plugin importable standalone) ---


def fetch_openai() -> Optional[_Snapshot]:
    try:
        from agent.account_usage import fetch_account_usage
        snap = fetch_account_usage("openai-codex")
    except Exception:
        return None
    return _adopt("openai", snap)


def fetch_anthropic() -> Optional[_Snapshot]:
    try:
        from agent.account_usage import fetch_account_usage
        snap = fetch_account_usage("anthropic")
    except Exception:
        return None
    return _adopt("anthropic", snap)


def _adopt(provider: str, snap: Any) -> Optional[_Snapshot]:
    """Normalize a native snapshot into the plugin's structural twin (or None)."""
    if snap is None or not getattr(snap, "available", False):
        return None
    windows = tuple(_Window(label=w.label, used_percent=w.used_percent,
                            reset_at=w.reset_at, detail=w.detail) for w in getattr(snap, "windows", ()))
    return _Snapshot(provider=provider, source=getattr(snap, "source", "native"),
                     fetched_at=_utc_now(), windows=windows,
                     details=tuple(getattr(snap, "details", ())))


_FETCHERS: dict[str, Callable[[], Optional[_Snapshot]]] = {
    "cline": fetch_cline,
    "opencode": fetch_opencode,
    "openrouter": fetch_openrouter,
    "openai": fetch_openai,
    "anthropic": fetch_anthropic,
}


def fetch_provider(name: str) -> Optional[_Snapshot]:
    return _FETCHERS.get(name, lambda: None)()
