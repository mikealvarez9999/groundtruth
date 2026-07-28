# bot

Live Telegram intake for citizen reports. Anyone can send a text or photo report; it flows
through the same pipeline as the seeded dataset and appears on the map.

**Implemented.** Long-polling (no webhook, no tunnel, no ngrok). Run it on **any always-on
host** — your laptop, a $5 VPS, Railway, Fly.io, Render. The bot writes verified tips to a
shared store (Upstash Redis) so a deployed Vercel console sees them in real time.

## How it reaches the deployed console

Vercel is serverless — it has no always-on process, so `bot/tipline.py` cannot be hosted
there. The bot must run somewhere that stays up. The shared store is the bridge:

- **`PERSIST=upstash`** (or `auto` with both env vars set): the bot writes each verified
  signal to **Upstash Redis** (`gt:signals:live` ZSET, score = received_at epoch ms) and
  each photo to a base64 key (`gt:tip:photo:<signal_id>`). A free-tier Upstash database is
  enough; signup at https://console.upstash.com/ and paste the REST URL + token into `.env`.
- **`PERSIST=local`** (default when no Upstash env): the bot writes to
  `console/public/data/live_signals.json` and `console/public/data/tips/<id>.jpg`. Works on
  the demo laptop when the console dev server is running on the same machine. **Nothing on
  the deployed console sees this path.**

The console (`console/src/app/api/live-signals/route.ts` and
`console/src/app/api/tip-photo/[id]/route.ts`) reads from the same store, so the same
console code works in both modes.

## Privacy

- **Pseudonymous.** `source.author_ref` is a salted hash of the Telegram user id. A
  disaster-reporting tool leaking reporter identities is a real harm, not a hypothetical one.
- **Photos carry no EXIF.** Bytes are written through as-is; we never read or strip metadata.
- **No webhook secret needed** in long-poll mode — the bot initiates the HTTPS connection to
  Telegram, so spoofing the receiver is not a concern.

## Run it

```bash
# 1. Create a free Upstash Redis database (console.upstash.com).
# 2. Paste the REST URL + token into .env at the repo root:
#      UPSTASH_REDIS_REST_URL=https://...upstash.io
#      UPSTASH_REDIS_REST_TOKEN=...
# 3. From the repo root:
python run_bot.py
```

Without Upstash env vars set, the bot still runs and writes to local files — useful for
local-machine demos, useless for any deployed console.

## Note for the demo

A live bot on stage is a real failure risk: no signal, a rate limit, or a spam message all
land in front of the judges. Have the seeded replay running regardless, so the Telegram path
is a bonus rather than a dependency.
