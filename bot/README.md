# Bot

The Telegram tipline and the VLM photo check. Lives at the repo root as
`run_bot.py` (long-poll entry point) and in this folder as two modules:
`tipline.py` and `vlm_check.py`.

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:GEMINI_API_KEY    = "..."   # optional: enables photo VLM via Gemini
$env:GROQ_API_KEY      = "..."   # optional: enables photo VLM via Groq
python run_bot.py
```

Long-poll, not webhook. No public URL needed; runs from a laptop.

## `tipline.py` — what it accepts

| Input | What we record |
|---|---|
| Text in Bangla or English | The claim (rule-extracted), location, event type |
| Shared GPS pin (D-028) | `geo.method = "gps_shared"`, score 1.0, no gazetteer ambiguity |
| Photo | A media ref + a VLM assessment via `vlm_check.py` (D-029) |

A tip with no GPS and no recognisable place name produces `geo: null` and
never reaches `corroborated` — the audit drawer will show it as "unmappable",
not as a fake.

## Privacy invariant (D-030)

- Raw Telegram user IDs are **never** persisted.
- Every tip is pseudonymised at ingestion via a salted digest. The same
  person always produces the same `src_tg_*` and `tg_*` short refs, but the
  link back to their Telegram account does not exist anywhere on disk.
- The salt lives in `tipline.py` as a constant. Rotate it to invalidate every
  existing pseudonym.

## VLM moderation (D-029)

When a tip carries a photo, `vlm_check.py` asks the configured VLM for a
3-way verdict: `corroborating` / `contradicting` / `inconclusive`. The
verdict **modulates** the signal's tier — it cannot promote or demote across
more than one step on the ladder, and it never overrides a SAR observation.
An `inconclusive` answer is the safe default and is treated as no evidence.

Two providers, tried in order, first success wins:

1. **Gemini 2.5 Flash** — via `GEMINI_API_KEY`.
2. **Groq `qwen/qwen3.6-27b`** — via `GROQ_API_KEY`. Replaces the previous
   `llama-3.2-11b-vision-preview`, which Groq decommissioned (D-033). The
   prompt also strips `<think>…</think>` blocks Qwen emits in plain text on
   the wire.

If neither key is set, photos are accepted but get `status: "inconclusive"`
and `model: null`. The tip still lands on the map — it just has no photo
corroboration.

## Diagnostics (D-031, D-032)

If `run_bot.py` exits silently, send the bot the `/diag` command (or check
`bot/diag.log` if configured). It reports: long-poll health, last `getUpdates`
timestamp, last signal written, VLM provider + last call status. The most
common failure mode is a stale `offset` — delete `bot/.offset` and restart.

## Files written

- `data/processed/signals.seed.json` — the live seed the pipeline reads.
  Append-only on a per-tip basis.
- `bot/.offset` — the long-poll cursor. Don't edit by hand.
- `bot/diag.log` — diagnostic ring buffer (optional, configured at startup).
