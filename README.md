# Hermes Footer Mod — Core Patch Backup

Backup of the hand-patched **Telegram runtime footer** customization for a
self-hosted [Hermes Agent](https://github.com/NousResearch/hermes-agent)
instance (`dolphin-bot`, systemd user service `hermes-gateway.service`).

This repo is **documentation + snapshot only**. The live code is applied as a
working-tree modification inside `~/.hermes/hermes-agent/` — nothing here is
meant to be installed directly. See [Next Steps](#next-steps) for the plan to
convert this into a proper plugin (not yet implemented).

## What the mod does

Adds a provider-adaptive usage footer to the Telegram reply footer line:

| Provider | Footer shows |
|---|---|
| Cline / ClinePass | `N%` of the 5-hour usage limit (Cline `usage-limits` API) |
| OpenAI Codex | `N%` of the 5-hour window remaining |
| OpenRouter | `$X.XX` daily spend (OpenRouter `auth/key` endpoint) |
| always | Context window % — rendered as **progress toward the ~50% compaction point** (`context_tokens / context_length * 200`, not a plain %) |

Key behaviors worth preserving:

- **Provider-adaptive**: explicit provider beats model-name inference (a GPT
  model served via `openai-codex` is *not* treated as OpenRouter).
- **30-second in-memory caches** per provider — no per-turn API hammering.
- **Fields are skipped silently** when data is missing or the provider is
  unknown.
- Secondary fix included: unwraps **ClinePass proxy envelopes** where response
  data is wrapped in `{"data": {...}}` instead of a normal `choices` payload
  (`agent/chat_completion_helpers.py`, `agent/conversation_loop.py`,
  `agent/transports/chat_completions.py`).

## Files in this repo

| File | What it is |
|---|---|
| `footer-mod-backup-2026-09-03.patch` | The full core diff — **11 modified files, +451/−24 lines**. Byte-identical to the live working-tree diff as of 2026-09-07. |
| `footer-mod-to-plugin-plan.md` | The research/design sketch for converting this into a plugin (verbatim copy of the original planning doc). |
| `probe_opencode_limits.py` | Read-only probe script that discovered OpenCode Go's usage API. Reads its key from `~/.hermes/.env` — no secrets embedded. |

## The 11 patched files

| File | Role in the mod |
|---|---|
| `gateway/runtime_footer.py` | Main logic (+206): provider fetchers (`_get_cline_five_hour_percent`, `_get_codex_five_hour_remaining_percent`, `_get_openrouter_daily_spend`), provider detection/labels, context-% math, new footer fields |
| `gateway/run.py` | Call site — passes `provider` into `build_footer_line` |
| `agent/chat_completion_helpers.py` | ClinePass `{"data": ...}` envelope unwrap |
| `agent/conversation_loop.py` | Tolerates envelope-wrapped responses in validation |
| `agent/transports/chat_completions.py` | Same envelope handling at the transport layer |
| `hermes_cli/providers.py` | Provider plumbing |
| `hermes_cli/config_defaults.py`, `gateway/config.py` | Config plumbing |
| `website/docs/user-guide/configuration.md` | Doc line for the new config |
| `tests/gateway/test_runtime_footer.py`, `tests/gateway/test_turn_context.py` | 38 passing targeted tests |

## Why this backup exists

**Core patches are overwritten by `git pull` / `hermes update`.** Every line
here is a committed-line conflict waiting to happen, and the whole point of the
[Next Steps](#next-steps) plan is to eliminate the core diff entirely by moving
the feature into a plugin. Until that happens, this patch is the restore point.

### Restoring after an update clobbers the tree

```bash
cd ~/.hermes/hermes-agent
git diff --stat          # confirm what's gone
git apply path/to/footer-mod-backup-2026-09-03.patch
```

If upstream changed nearby lines, `git apply` may need `--3way`, or the hunk
may need re-porting by hand — check `git diff` afterward and re-run the two
test files under `tests/gateway/`.

## Next Steps

Research completed 2026-09-03 (full sketch in
[`footer-mod-to-plugin-plan.md`](footer-mod-to-plugin-plan.md)). **Nothing has
been implemented yet** — this section documents where the conversion would go.

### Goal

Turn the hand-patched footer into a standalone Hermes **plugin** installed to
`~/.hermes/plugins/`, so `hermes update` / `git pull` stops nuking it, per the
Hermes contribution rubric (plugins must not touch core files; standalone
plugin repos ship in `~/.hermes/plugins/`).

### Extensibility surface (verified against the codebase 2026-09-03)

1. **`transform_llm_output` hook** — fired once per turn in
   `agent/turn_finalizer.py:568-583` after the tool loop, for
   `final_response and not interrupted`. First plugin returning a non-empty
   string wins. Args: `response_text, session_id, model, platform`.
   - ⚠️ **Gap:** the hook does **not** receive `context_tokens`/
     `context_length` or the turn's provider — a plugin needs side channels
     for those (see Design decision below).
2. **Plugin ABC + PluginManager** (`hermes_cli/plugins.py`): manifests
   (`plugin.yaml` — see `plugins/model-providers/opencode-zen/plugin.yaml` as
   the minimal example), discovery from `~/.hermes/plugins/` + bundled
   `plugins/`, enable/disable via config `plugins.enabled`, `PluginContext`
   with state/config namespaces, hooks/middleware/subscriptions,
   `PluginToolOverrideError` permission gate.
3. **Marketplace CLI**: `hermes plugins install/search/update/remove/list/
   enable/disable/capabilities/doctor/pack`, installable from a Git URL or
   `owner/repo`.
4. **Marketplace scan:** searches for `footer`/`usage`/`status`/`widget`/
   `context`/`quota`/`token` returned **no matches** — this niche is open.

### Proposed approach (sketch)

Standalone plugin repo installed to `~/.hermes/plugins/usage-footer/`:

1. `plugin.yaml` manifest + `__init__.py` registering a `transform_llm_output`
   hook that appends the footer line to `response_text`.
2. Move the three provider fetchers + 30s caches into the plugin module nearly
   verbatim (they're self-contained: `urllib` + dict caches).
3. Provider detection stays in the plugin (explicit-provider-first,
   model-name fallback).
4. **Context-% problem (the real design decision)** — `transform_llm_output`
   lacks context-token info. Options in order of preference:
   - a) Track a session-scoped counter via `pre_llm_call`/`post_api_request`
     hooks (they see request payloads) and compute % in the transform hook —
     no core changes. **Needs a spike:** verify those hooks' kwargs actually
     carry token counts (they may only carry model/session IDs).
   - b) Ask upstream (Discord/issue) for `usage`/`context` kwargs on
     `transform_llm_output` — zero local hack, timeline unknown.
   - c) Keep a minimal core patch for plumbing only (rejected: defeats the
     purpose).
5. Config: footer fields/format under the plugin's config namespace.
6. Tests: port the 38 existing tests to plugin context; add an opencode
   branch (mock `/usage` response).
7. After parity: `git -C ~/.hermes/hermes-agent checkout` the 11 files to
   delete the core diff, then `hermes plugins pack` and consider publishing.

### Bonus feature already scoped (NOT built)

OpenCode Go limits: `GET https://opencode.ai/zen/go/v1/usage` (Bearer key)
returns HTTP 200 with `usage.rolling.percent` (≈5h window), `usage.weekly.percent`,
`usage.monthly.percent`, each with `resetsAt`. The data exists server-side; the
opencode-zen provider plugin simply exposes no usage interface, and the current
footer has no opencode branch. A future `opencode` branch in the plugin would
surface `rolling.percent` / `weekly.percent`. Probe script:
[`probe_opencode_limits.py`](probe_opencode_limits.py).

### Risks / open questions

- Hook args gap (above) is the main unknown — option (a) hook-chaining is the
  likely path pending a spike.
- **First-string-wins semantics:** another `transform_llm_output` plugin would
  conflict (only example plugins exist in the index today).
- Interaction with the built-in `runtime_footer`: plugin must disable/duplicate
  gracefully.
- `hermes plugins doctor` should be the acceptance gate for manifest + hooks.
- OpenCode `/usage` percent semantics (rolling = 5h?) worth confirming against
  the billing page before trusting labels.

### Verification plan (when executed)

1. `hermes plugins list` shows `usage-footer` enabled.
2. `hermes plugins doctor usage-footer` passes.
3. Ported test suite passes (≥38 tests).
4. Live Telegram check: footer renders, provider-adaptive (test cline +
   opencode-go), no double-footer.
5. `git -C ~/.hermes/hermes-agent status` clean after `hermes update` — the
   survival test that motivated all of this.
