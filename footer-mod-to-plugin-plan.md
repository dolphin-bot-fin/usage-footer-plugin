# Footer-Mod → Plugin Conversion Plan (SKETCH — not for execution yet)

> **Status:** DRAFT sketch per Curtis 2026-09-03. Examine-only session; do NOT implement without explicit go-ahead.
> **Backup of current core-mod diff:** `/home/fin/footer-mod-backup-2026-09-03.patch` (745 lines, 11 files)

---

## Goal

Turn the hand-patched Telegram runtime footer (context %, provider usage/limits) into a proper Hermes **plugin** so `hermes update` / `git pull` on `hermes-agent` stops nuking it.

## Current state (what exists today)

The footer mod is **11 modified core files** in `~/.hermes/hermes-agent/` (+451/−24 lines, 745-line diff):

| File | Role in the mod |
|---|---|
| `gateway/runtime_footer.py` | Main logic (+206): `_get_cline_five_hour_percent()` (Cline `usage-limits` API, 30s cache), `_get_codex_five_hour_remaining_percent()` (via `agent.account_usage.fetch_account_usage`), `_get_openrouter_daily_spend()` (OpenRouter `auth/key` endpoint), provider detection/labels, context-% → "progress toward compaction point" (×200 not ×100), new footer fields |
| `gateway/run.py` | Call site: passes `provider` into `build_footer_line` (~L19858) |
| `agent/turn_finalizer.py` etc. | Result-dict plumbing so the provider reaches the footer |
| `tests/gateway/test_runtime_footer.py`, `tests/gateway/test_turn_context.py` | 38 passing targeted tests |
| `hermes_cli/config_defaults.py`, `gateway/config.py`, `website/docs/user-guide/configuration.md` | Config plumbing + doc line |

**Key behaviors worth preserving:**
- Provider-adaptive: ClinePass → `N% 5h limit`; OpenAI Codex → `N% 5h left`; OpenRouter → `$X.XX daily`
- Context % = progress toward the ~50% compaction threshold (`context_tokens/context_length * 200`)
- 30s in-memory caches per provider (no per-turn API hammering)
- Explicit provider beats model-name inference (a GPT model via openai-codex is NOT OpenRouter)
- Fields skipped silently when data missing

## New extensibility surface (verified 2026-09-03)

1. **`transform_llm_output` hook** — fired once per turn in `agent/turn_finalizer.py:568-583` after the tool loop, for `final_response and not interrupted`. First plugin returning a non-empty string wins. Args: `response_text, session_id, model, platform`.
   ⚠️ **Gap:** the hook does NOT receive `context_tokens/context_length` or the turn's provider — a plugin would need side channels for those (see Open Questions).
2. **Plugin ABC + PluginManager** (`hermes_cli/plugins.py`, 6,479 lines): manifests (`plugin.yaml`, see `plugins/model-providers/opencode-zen/plugin.yaml` as minimal example), discovery from `~/.hermes/plugins/` (standalone installs) + bundled `plugins/`, enable/disable via config `plugins.enabled`, `PluginContext` with state/config namespaces, hooks/middleware/subscriptions, `PluginToolOverrideError` permission gate.
3. **Community plugin index + marketplace CLI** — `hermes plugins install/search/update/remove/list/enable/disable/capabilities/doctor/pack`. Searchable index (`hermes plugins search <term>`); installable from Git URL or `owner/repo`.
4. **AGENTS.md contribution rubric** — plugins must NOT touch core files; standalone plugin repos go in `~/.hermes/plugins/`; publishable via the index + Nous Discord `#plugins-skills-and-skins`.

## Marketplace scan (2026-09-03)

`hermes plugins search` for `footer`, `usage`, `status`, `widget`, `context`, `quota`, `token`: **no matches**. Full index = 5 plugins (hermes-media-studio, hermes-plugin-chrome-profiles, hermes-telegram-business-mode, plugin-llm-async-*, plugin-llm-example). **Nobody has built this — genuinely open niche.**

## OpenCode Go limits finding (NOTED, DO NOT FIX NOW)

- `GET https://opencode.ai/zen/go/v1/usage` (Bearer key) → **HTTP 200**:
  ```json
  {"usage": {"rolling": {"status": "ok", "percent": 7, "resetsAt": "..."},
             "weekly":  {"status": "ok", "percent": 5, "resetsAt": "..."},
             "monthly": {"status": "ok", "percent": 2, "resetsAt": "..."}}}
  ```
- So **weekly/daily(rolling) data exists server-side**; the opencode-zen provider plugin (`plugins/model-providers/opencode-zen/__init__.py`) simply exposes no usage/limits interface, and the footer has no opencode branch (it only knows cline/codex/openrouter).
- Future footer/plugin work: add an `opencode` branch calling `/zen/go/v1/usage` → `rolling.percent` (≈5h) and `weekly.percent`. Probe script saved at `~/.hermes/cache/probe_opencode_limits.py`.

## Proposed approach (sketch)

**Standalone plugin repo** (per AGENTS.md), installed to `~/.hermes/plugins/usage-footer/`:

1. **Shape:** `plugin.yaml` manifest (name/kind/version/description/author) + `__init__.py` registering a `transform_llm_output` hook that appends the footer line to `response_text`.
2. **Move the three provider fetchers + caches** into the plugin module nearly verbatim (they're self-contained; urllib + 30s dict caches).
3. **Provider detection** stays in the plugin (explicit-provider-first, model-name fallback).
4. **Context-% problem (the real design decision):** `transform_llm_output` lacks context-token info. Options, in order of preference:
   - a) Track a thread-local/session-scoped counter via `pre_llm_call`/`post_api_request` hooks (they see request payloads) and compute % in the transform hook — no core changes.
   - b) Ask upstream (Discord/issue) for `usage`/`context` kwargs on `transform_llm_output` — zero local hack, but timeline unknown.
   - c) Keep a *minimal* core patch for plumbing only (reject: defeats the purpose).
5. **Config:** footer fields/format in `plugins.config` section (plugin config namespace exists in `PluginContext`).
6. **Tests:** port the 38 existing tests to plugin context; add cases for the opencode branch (mock `/usage` response).
7. **After it works:** optionally add opencode limits branch (the noted feature), then `hermes plugins pack` and consider publishing.

### Files (future)

- Create: `~/.hermes/plugins/usage-footer/plugin.yaml`, `__init__.py`, `providers.py`, `tests/` (plugin-local or repo `tests/plugins/`)
- Eventually delete the 11-file core diff (git checkout) once the plugin reaches parity — after `hermes update` lands upstream changes.

## Risks / open questions

- **Hook args gap:** `transform_llm_output` doesn't pass context/provider — option (a) hook-chaining is the likely path; needs a spike to verify `pre_llm_call`/`post_api_request` kwargs actually carry token counts (they may only carry model/session IDs).
- First-string-wins semantics: another transform plugin would conflict (only one exists today in the index; both are examples).
- Interaction with the built-in `runtime_footer` (enabled in config?): plugin must disable/duplicate gracefully.
- `hermes plugins doctor` should be the acceptance gate for the manifest + hooks.
- OpenCode `/usage` percent semantics (rolling = 5h?) worth confirming against a billing page before trusting labels.

## Verification plan (when executed)

1. `hermes plugins list` shows `usage-footer` enabled.
2. `hermes plugins doctor usage-footer` passes.
3. Ported test suite passes (≥38 tests).
4. Live check on Telegram: footer appears, provider-adaptive per current provider (test with opencode-go + cline), no double-footer.
5. `git -C ~/.hermes/hermes-agent status` clean after `hermes update` → the survival test that motivated all this.
