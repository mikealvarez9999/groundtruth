# Console

The Next.js command console. Reads the pipeline's JSON artefacts from
`public/data/` and renders the ranked sector map.

```powershell
cd console
npm install
npm run sync:data      # copies fresh artefacts from ../data/processed/ (incl. epochs/)
npm run dev            # http://localhost:3000
```

`predev` and `prebuild` run `sync:maplibre` + `sync:data` automatically, so
`npm run dev` / `npm run build` alone are enough after `npm install`.

## Stack

- **Next.js 16** (app router, RSC, dynamic import for the map).
- **MapLibre GL JS** + **deck.gl** for the sector layer. No Mapbox, no
  basemap telemetry.
- **Static tile basemap** — the OSM raster bundle in `public/data/`. The
  console does **not** fetch tiles at runtime.
- **MapLibre worker** is synced from `node_modules` into `public/maplibre/`
  (gitignored) via `npm run sync:maplibre`. If you bump `maplibre-gl` in
  `package.json`, re-run that script — a mismatched worker fails silently (D-025).

## Scripts

| Script | What it does |
|---|---|
| `npm run sync:data` | Copies `data/processed/` → `public/data/`, **including `epochs/`** |
| `npm run sync:maplibre` | Copies the MapLibre v6 worker out of `node_modules` |
| `npm run dev` / `build` | Both trigger the two syncs via `predev` / `prebuild` |

`public/data/` is gitignored — it is a build output, never a source. The
committed source of truth is `data/processed/`.

There is exactly **one** sync script, `scripts/sync-data.mjs`. A near-identical
twin named `syncdata.mjs` existed, held the only working copy of the epoch-sync
block, and was referenced by nothing — so the before/after toggle silently
never rendered. It has been deleted; see D-035.

## What you see on screen

- **Map** — sectors coloured by score. Click a sector for its drawer.
- **Brief panel** — the AI-written situation summary (regenerated server-side
  via `app/api/brief/route.ts`). Streams from **Groq `openai/gpt-oss-120b`**
  when `GROQ_API_KEY` is set in `console/.env.local`; otherwise it streams a
  deterministic brief computed from `sector_scores.json` at request time. The
  response header `X-Brief-Generator` says which ran, and the panel displays
  it. Gemini was removed as a provider (D-037).
- **Triage queue** — signals sorted by priority for a human reviewer.
- **Signal feed** — newest citizen tips, with the VLM verdict inline.
- **Top bar** — epoch toggle (pre-peak / peak / custom), live re-score button,
  eval summary chip.
- **Audit drawer** — opens on cell click. Shows every signal that touched the
  sector: text, source, corroboration chain, demotions, VLM verdict if any.

## Live re-score

The console does **not** re-run `build_all`. When a new citizen tip lands in
`public/data/live_signals.json` (written by `bot/tipline.py`), the client
recomputes sector scores in the browser using the same rules the Python
pipeline applies. The Python build is the canonical snapshot; the client
re-score is the live overlay.

`src/lib/fusion.ts` does not re-declare the channel weights — it reads them out
of the `weights` block embedded in `sector_scores.json` (D-009), so there is no
second copy to drift. It does re-implement the score formula and `SATURATION`,
so change those in `fuse.py` and `fusion.ts` together.

## Before / after epochs

The top-bar epoch toggle switches between the dated epochs in
`public/data/epochs/<slug>/`. The slug you built last is the default. To
rebuild epochs, run `build_epoch.py` (see `pipeline/README.md`).

## Deploy

There is no deploy script in this repo — the console is plain Next.js and
builds with `npm run build`. The OSM raster basemap is committed under
`public/data/`, so a `next start` against the built output is offline-safe.
For a production deploy, point your host of choice at the `console/`
directory and serve `npm run build` output; the only requirement is that
`public/data/` is reachable.

## Common traps

- **Blank map.** Almost always: `public/data/` is empty. Run
  `npm run sync:data` from the console dir, or `python -m
  groundtruth.build_all` from `pipeline/`.
- **Worker crashes, or a map that renders nothing with a working HUD.**
  `maplibre-gl` was bumped without re-syncing the worker. Run
  `npm run sync:maplibre`. D-025 documents this whole silent-failure class.
- **Epoch toggle shows nothing.** The console hides the toggle until
  `/data/epochs/index.json` lists **2 or more** epochs (`epochs.length >= 2` in
  `Console.tsx`). Either fewer than two epochs exist, or `epochs/` was never
  copied into `public/data/`. Check in this order:
  1. `data/processed/epochs/index.json` exists and lists 2+ slugs? If not, run
     `python -m groundtruth.build_epoch` for each pass.
  2. `public/data/epochs/index.json` exists? If not, `npm run sync:data`.
  Build the PEAK/POST epoch **last** — the last one built becomes the default.