# Usage Footer Plugin

Live provider usage in the Hermes gateway runtime footer — rendered by core's own
`display.runtime_footer` pipeline, extended at runtime by this plugin (no core files
touched).

## Fields

| Field name | Shows | Source |
|---|---|---|
| `cline_5h` | `Cline 12%` (5h window, % used) | `api.cline.bot/api/v1/users/me/plan/usage-limits` |
| `oc_rolling` | `OC 31%` | `opencode.ai/zen/go/v1/usage` (rolling) |
| `oc_weekly` | `OCw 12%` | same, weekly window |
| `or_today` | `OR $1.23 spent` | `openrouter.ai/api/v1/auth/key` (`usage_daily`) |
| `or_week` | `ORw $4.56 spent` | same, `usage_weekly` |
| `openai_5h` | `GPT 45%` (session window) | core `agent.account_usage` ("openai-codex") |
| `anthropic_5h` | `Claude 8%` (session window) | core `agent.account_usage` ("anthropic", OAuth accounts) |

Credentials come from the environment (`~/.hermes/.env`): `CLINE_API_KEY`,
`OPENCODE_GO_API_KEY`, `OPENROUTER_API_KEY`. OpenAI/Anthropic reuse whatever
credentials Hermes already resolved for those providers.

## Install

```bash
hermes plugins install https://github.com/dolphin-bot-fin/usage-footer-plugin
hermes plugins enable usage-footer
hermes gateway restart
```

Or manually: clone into `~/.hermes/plugins/usage-footer-plugin/` and restart.

## Configure

Footer on + field order (`~/.hermes/config.yaml`):

```yaml
display:
  runtime_footer:
    enabled: true
    fields: [model, context_pct, cwd, cline_5h, oc_rolling, oc_weekly, or_today, openai_5h, anthropic_5h]

plugins:
  entries:
    usage-footer:
      settings:
        enabled: true          # default
        refresh_seconds: 60    # 15-900
        auto_enable_footer: true   # fills in a missing display.runtime_footer.enabled; never overrides explicit false
        fields: [cline_5h, oc_rolling, oc_weekly, or_today, openai_5h, anthropic_5h]  # usage fields this plugin fetches/renders
```

## Status

`/usage-footer` in any session prints installed fields + cached snapshots per provider.

## Plugin market

The Hermes community plugin index (`NousResearch/hermes-plugin-index`, the source
behind `hermes plugins search`) is not publicly available yet — the CLI currently
resolves the seed index bundled with Hermes. A ready-to-submit entry is included at
[`plugin-index-entry.json`](plugin-index-entry.json); open a PR adding it to
`index.json` once the index repo launches.

## Design notes

- **Zero core edits.** The plugin wraps `gateway.runtime_footer.format_runtime_footer`
  at runtime (fail-open, uninstall on plugin unload); core's streaming trailing-footer
  path and `/footer` toggle keep working unchanged.
- **Never blocks a reply.** A daemon refresher thread polls each enabled provider on
  its own interval; the footer reads an in-memory cache only. A provider that fails to
  fetch keeps its last known value; a provider with no credentials is simply absent.
- **Compatibility contract.** Signature-inspected wrap: if upstream changes the footer
  function's contract, the anchor removes itself and the footer degrades to stock —
  no crashes, no mangled replies.
- Tests: `tests/test_usage_footer.py` (`python -m pytest tests/ -q`).

## License

MIT
