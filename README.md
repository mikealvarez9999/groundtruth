# GroundTruth — Disaster Triage Command Console

A first-72-hours triage console for floods in Bangladesh. It fuses three signal channels into
one ranked "go here first" map, then generates an AI-written resource-allocation brief.

Demo scenario: the **2022 Sylhet floods** (`bangladesh-flooding22`).

> **Status: working end to end on SYNTHETIC data.** The pipeline runs, the console runs, the
> brief streams. What is missing is real data (no Maxar imagery, no HASTE run, no GeoNames
> dump, no real archived posts), Channel 2 (VLM), and the Telegram bot. Every screen says so.
>
> Two decisions still need the project lead: **D-012** (grid size + fusion weights) and
> **D-013** (Bangla display — currently implemented as "show both").

## Layout

```
console/     Next.js app (MapLibre GL JS + deck.gl, no Mapbox tokens)
pipeline/    Python: extraction, geocoding, verification, fusion, VLM batch
bot/         Telegram bot (Bot API)
contracts/   JSON Schemas — the interface between the above. Plus fixtures.
data/        raw/ gitignored, processed/ committed
runbooks/    operational runbooks (HASTE local setup)
vendor/      read-only reference clones, gitignored (see DECISIONS.md D-001)
DECISIONS.md every scope and design choice, with reasons
```

## The three channels

1. **Wide-area damage layer** — Microsoft's [HASTE](https://github.com/microsoft/haste) runs
   locally in Docker on a teammate's laptop against Maxar Open Data imagery. An analyst labels
   a handful of buildings; HASTE's embedding + logistic-regression method scores every
   building. The export is converted to `damage_layer.geojson` and committed as a static
   artifact. Runbook: `runbooks/haste-local-setup.md`.
2. **Fine-grained VLM findings** — a Python batch sends zoomed imagery crops and citizen photos
   to Gemini with a structured JSON schema. Outputs cached as JSON.
3. **Citizen signals** — ~200 real archived posts from past Bangladesh floods (Bangla/Banglish),
   replayed on a timer, plus a live Telegram bot. Both flow through one pipeline: LLM
   extraction → local GeoNames gazetteer fuzzy-match → verification → map pin.

Verification is **corroboration + spatial consistency only** — no media forensics, no deepfake
detection, no credibility classifiers. Signals are tiered CORROBORATED / PLAUSIBLE-UNVERIFIED /
SUSPECT, each with a stated reason. Suspect items are down-weighted to zero and shown in an
Audit Drawer, never deleted.

## Getting started

Order matters: the console fetches artifacts the pipeline writes.

```bash
# 1. pipeline — synthesise data, run every stage, validate, write artifacts
cd pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all

# 2. console
cd ../console
npm install && npm run dev        # http://localhost:3000
```

Step 1 writes to both `data/processed/` and `console/public/data/`, then validates
everything against `/contracts` and prints how the verifier scored against the planted
fakes. Step 2 needs no API keys; the brief falls back to an offline generator.

In the console: `Space` play/pause, `A` audit drawer, `B` brief, `Esc` close.

**HASTE (the teammate with the 16 GB Linux laptop):** follow
`runbooks/haste-local-setup.md` start to finish. Read its §0 first — that laptop is under
HASTE's documented 32 GB minimum.

## Hard constraints

- **$0 cloud budget.** Free tiers only: Gemini AI Studio primary, Groq spare. API keys via
  environment variables, never committed.
- **Precompute and cache everywhere** except the Telegram→pipeline path, consistency checks,
  fusion re-scoring, and the brief. Only the brief route and the Telegram webhook are dynamic
  on Vercel.
- **No databases.** Flat JSON/GeoJSON files are the data layer.
- **Not building, even if it seems helpful:** live social-media scraping, media forensics, a
  mobile app, auth systems, multi-disaster support.
- **MapLibre GL JS + deck.gl, not Mapbox.** Zero tokens. PMTiles offline basemap of Sylhet.
- **Contracts in `/contracts` change only with the project lead's explicit approval.**

## Honesty rules this project holds itself to

These are not decoration — a triage tool that overstates its confidence sends people to the
wrong place.

- **"No damage recorded" ≠ "safe".** Cells outside the imagery valid-area mask are `unassessed`
  and must render differently from assessed-and-clear ones.
- **A claim we cannot check is not a false claim.** No imagery coverage means
  `plausible_unverified` and a recon flag, never `suspect`.
- **Every displayed number is traceable.** The damage layer carries the HASTE commit, backbone,
  label count, and measured Damaged-class F1. Fusion output carries the weights that produced
  it.
- **Cloud-obscured buildings are excluded from scoring and said so.** Absence of damage there
  means we could not see.
- **The fixtures in `contracts/examples/` are fake and labelled fake.** Their invented accuracy
  numbers must never appear in the demo.

## HASTE questions

HASTE is newer than any model's training data. Answer questions about it **only** from the
cloned files in `vendor/haste`, and cite the file. If the files do not answer it, say so —
`runbooks/haste-local-setup.md` §10 tracks the known-unanswered questions.
