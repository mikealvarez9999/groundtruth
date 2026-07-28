# bot

Live Telegram intake for citizen reports. Anyone can send a text or photo report; it flows
through the same pipeline as the seeded dataset and appears on the map.

**Not yet implemented** — waiting on Phase 1 go-ahead and contract sign-off.

## Planned shape

- **Telegram Bot API** (free), **webhook** mode — not long polling. The webhook is one of the
  only dynamic routes we deploy (`console/src/app/api/telegram/route.ts`), because Vercel's free
  tier has no always-on process to poll from.
- On receipt: normalise to the same `signal.schema.json` shape as seeded data, with
  `channel: "citizen_telegram"`, then run extraction → geocoding → verification → fusion
  re-score. Identical code path to the seed loader; only the ingress differs.
- `source.author_ref` must be **pseudonymous**. Never store a Telegram user id, phone number,
  or display name — the contract requires this and a disaster-reporting tool leaking reporter
  identities is a real harm, not a hypothetical one.
- Reply to the sender with what we understood (extracted location, event type, urgency) so a
  bad geocode is visible to the person best placed to correct it.

## Secrets

`TELEGRAM_BOT_TOKEN` via environment variable, never committed. See `.env.example` at the repo
root. Set a webhook secret token as well so the endpoint cannot be spoofed by anyone who
guesses the URL.

## Note for the demo

A live bot on stage is a real failure risk: no signal, a rate limit, or a spam message all land
in front of the judges. Have the seeded replay running regardless, so the Telegram path is
a bonus rather than a dependency.
