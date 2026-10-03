# Bot

The Telegram tipline and the VLM photo check. Lives at the repo root as
`run_bot.py` (long-poll entry point) and in this folder as two modules:
`tipline.py` and `vlm_check.py`.

```powershell
$env:TELEGRAM_BOT_TOKEN = "..."
$env:OPENROUTER_API_KEY = "..."   # optional: enables the photo VLM
python run_bot.py
```

Keys are read from `.env` at the project root by `run_bot.py`, so you usually
don't need to set them in the shell at all.

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
- The salt comes from the `GT_TIPLINE_SALT` env var. **Set it.** `tipline.py`
  falls back to the literal string `"groundtruth-tipline"` when it is absent,
  which is public knowledge in this repo — every pseudonym would be trivially
  reversible. Rotating the salt invalidates every existing pseudonym.

## VLM moderation (D-029)

When a tip carries a photo, `vlm_check.py` asks the configured VLM for a
3-way verdict: `corroborating` / `contradicting` / `inconclusive`. The
verdict **modulates** the signal's tier — it cannot promote or demote across
more than one step on the ladder, and it never overrides a SAR observation.
An `inconclusive` answer is the safe default and is treated as no evidence.

One provider:

1. **OpenRouter `thinkingmachines/inkling:free`** — via `OPENROUTER_API_KEY`.
   Free tier, and verified to accept `image` input. OpenRouter speaks the
   OpenAI wire format, so the call reuses the same `_call_openai_compatible`
   helper that Groq used. The prompt still strips `<think>…</think>` blocks,
   which reasoning models emit in plain text on the wire.

Gemini and Groq-vision were both removed in **D-037**. Groq is still a provider
for the project — it just moved to the *text* brief, where it runs
`openai/gpt-oss-120b`. If no key is set, photos are accepted but get
`status: "inconclusive"` and `model: null`. The tip still lands on the map — it
just has no photo corroboration.

## Diagnostics (D-031, D-032)

There is **no `/diag` command and no `bot/diag.log`**. Diagnostics are stderr
lines, by design — D-032's root cause was "the bot wasn't running", which looks
identical to "the bot crashed" unless you can see proof of polling. What you get:

- `[run_bot] VLM providers: OPENROUTER=set|MISSING` at startup — tells you
  whether the key reached the process at all.
- `[tipline] getMe ok: bot='<name>'` — token is valid. A 401/404 exits with
  code 2 rather than entering the poll loop.
- `[tipline] heartbeat offset=… pending=…` every 60 s — **this is the proof that
  polling is happening.** No heartbeat means no bot.
- `[tipline] recv chat=… text=…` — a message actually arrived.
- `[tipline] poll HTTP 409` — a second bot instance holds the lease. Kill it.
- `[tipline] cwd=… LIVE_OUT=… (absolute? True)` — confirms the write path.

The poll `offset` is **in-memory only**. There is no `bot/.offset` to delete;
restarting simply re-polls from scratch.

## Files written

- `console/public/data/live_signals.json` — the live tip feed the console
  polls. Written atomically (tmp + rename) so the console never reads a
  half-written file. With `PERSIST=upstash` this is skipped and tips go to
  Redis instead.
- `console/public/data/tips/<signal_id>.jpg` — the photo, named by signal id
  only (D-030: no file id, no user id, no caption-derived name in the path).
- `data/processed/signals.seed.json` is **not** written by the bot; it is a
  pipeline output.
