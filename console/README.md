# Console

The Next.js command console. Reads the pipeline's JSON artefacts from
`public/data/` and renders the ranked sector map.

```powershell
cd console
npm install
npm run sync-data      # copies fresh artefacts from ../data/processed/
npm run dev            # http://localhost:3000
```

## Stack

- **Next.js 16** (app router, RSC, dynamic import for the map).
- **MapLibre GL JS** + **deck.gl** for the sector layer. No Mapbox, no
  basemap telemetry.
- **Static tile basemap** — the OSM raster bundle in `public/data/`. The
  console does **not** fetch tiles at runtime.
- **MapLibre worker** is checked in under `public/maplibre/` and kept in sync
  with the installed `maplibre-gl` via `npm run sync-maplibre-worker`. If you
  bump `maplibre-gl` in `package.json`, re-run that script.

## What you see on screen

- **Map** — sectors coloured by score. Click a sector for its drawer.
- **Brief panel** — the AI-written situation summary (regenerated server-side
  via `app/api/brief/route.ts`).
- **Triage queue** — signals sorted by priority for a human reviewer.
- **Signal feed** — newest citizen tips, with the VLM verdict inline.
- **Top bar** — epoch toggle (pre-peak / peak / custom), live re-score button,
  eval summary chip.
- **Audit drawer** — opens on cell click. Shows every signal that touched the
  sector: text, source, corroboration chain, demotions, VLM verdict if any.

## Live re-score

The console does **not** re-run `build_all`. When a new citizen tip lands in
`public/data/live_signals.json` (written by `bot/tipline.py`), the client
recomputes sector scores in the browser using the same `fuse.ts` rules the
Python pipeline applies. The Python build is the canonical snapshot; the
client re-score is the live overlay.

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
  `npm run sync-data` from the console dir, or `python -m
  groundtruth.build_all` from the repo root.
- **Worker crashes.** `maplibre-gl` was bumped without re-syncing the worker.
  Run `npm run sync-maplibre-worker`.
- **Epoch toggle shows nothing.** The slug isn't in `public/data/epochs/`.
  Run `build_epoch.py` for that slug and `npm run sync-data`.