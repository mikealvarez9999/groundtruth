# console

Next.js 16 + MapLibre GL JS + deck.gl. Dark command-console UI over the artifacts the
pipeline produces. **No map tokens, no external tiles, no network calls at runtime.**

## Run it

```bash
# 1. produce the artifacts first — the console fetches them from /public/data
cd ../pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all

# 2. then the console
cd ../console
npm install
npm run dev        # http://localhost:3000
```

If the shell loads but you get "DATA UNAVAILABLE", you skipped step 1.

`predev` / `prebuild` run `scripts/sync-maplibre-worker.mjs` automatically. Do not remove
that — see "The blank-map traps" below.

## Controls

| Key | Action |
|---|---|
| `Space` | play / pause the replay |
| `A` | toggle the Audit Drawer |
| `B` | toggle the Brief panel |
| `Esc` | close panels, clear selection |

Speeds are 1× / 30× / 120× / 600×. The seeded corpus spans ~2.2 hours, so 120× replays in
about 70 seconds. Click a triage row or a map sector to inspect it; click a signal pin or a
feed row to inspect that report.

## What is real and what is not

- **The live re-score is real.** `sector_scores.json` holds the end state with every signal
  present. During replay, `lib/fusion.ts` re-runs the fusion in the browser over only the
  signals that have arrived, so the queue genuinely re-ranks as reports land. It **mirrors
  `pipeline/src/groundtruth/fuse.py`** — if you change `SATURATION` or the score formula in
  one, change the other in the same commit or the replay will silently disagree with the
  committed file.
- **There is no basemap.** The MapLibre style has zero sources. The PMTiles basemap of Sylhet
  from the kickoff has not been built, so you are seeing our own layers on a drawn grid. Real
  gap, not a style choice.
- **All the data is synthetic.** Hence the permanent scrolling warning banner. The provenance
  panel reads "NOT VALIDATED — no accuracy measured" because the synthetic layer carries no
  `accuracy` block.
- **Channel 2 (VLM) is not implemented,** so `components.vlm` is null everywhere. The
  inspector renders it as a **hatched** meter, not an empty one — an empty bar reads as zero,
  and zero is not the same as unknown.

## Layout

```
src/app/layout.tsx             shell; no next/font (see below)
src/app/page.tsx               server component, renders <Console/>
src/app/api/brief/route.ts     streaming brief: Gemini if keyed, else deterministic offline
src/components/Console.tsx     loads artifacts, drives the replay clock, owns selection
src/components/MapView.tsx     MapLibre base layers + deck.gl animated overlay
src/components/TopBar.tsx      identity, transport, live counters
src/components/SidePanel.tsx   layer toggles, legend, inspector
src/components/TriageQueue.tsx ranked "go here first" list
src/components/SignalFeed.tsx  arrivals, original text + English gloss
src/components/AuditDrawer.tsx suspect / unverified / unmappable, with stated reasons
src/components/BriefPanel.tsx  streaming brief, names its generator
src/components/ui.tsx          CountUp, TierBadge, Meter, Stat
src/lib/fusion.ts              live re-score; MUST match fuse.py
src/lib/types.ts               hand-written mirrors of /contracts
```

## Design rules that are load-bearing, not cosmetic

1. **An unknown must never look like a safe.** Unassessed sectors are grey-blue, never green;
   cloud-obscured buildings are grey and dimmed; the queue puts an amber `NO IMAGERY` badge on
   any sector outside the imagery footprint.
2. **Original text before our reading.** The feed shows the Bangla/Banglish source first and
   the English gloss second, italicised and marked as our extractor's reading. That is the
   "show both" answer to DECISIONS.md D-013.
3. **Every number is traceable.** Queue cards carry their counts; the inspector shows the
   per-channel components; the Audit Drawer shows the verbatim pipeline reason, the geocode
   with runner-up candidates, and the imagery counts the ruling rests on.
4. **Suspect items are visible, not deleted.** They appear in the drawer with weight 0.00 and
   a stated reason, so a human can overrule us.
5. **`prefers-reduced-motion` is honoured** — every animation collapses and the scanline is
   removed. The console stays fully usable.

## The blank-map traps

Three separate bugs during development each produced *a fully working HUD floating over a
completely blank map*, none of them logging an error. If the map goes blank, check these
first:

1. **The MapLibre worker.** v6 is ESM-only and runs its worker as a separate module.
   `scripts/sync-maplibre-worker.mjs` copies it into `public/maplibre/` and `MapView.tsx`
   calls `setWorkerUrl(...)`. Without it the worker connects but never answers a message:
   `_isUpdatingWorker` sticks at true, `isStyleLoaded()` never becomes true, nothing renders.
2. **`glyphs: undefined` in the style.** Fails style validation ("string expected, undefined
   found"), which aborts the style load — so the `load` handler that adds every layer never
   runs. Omit the key entirely.
3. **CSS import order.** `maplibre-gl.css` must be imported **before** Tailwind in
   `globals.css`. Its `.maplibregl-map { position: relative }` is exactly as specific as
   Tailwind's `.absolute`, so if it loads second the container collapses to height 0.
   `MapView.tsx` also sets the container size inline as a second line of defence.

`window.__gtMap` is a deliberate debugging handle for exactly this:

```js
__gtMap.isStyleLoaded()                                    // false => worker problem
__gtMap.queryRenderedFeatures({layers:["sectors-fill"]})   // 0 => nothing painted
```

## Why no `next/font/google`

It fetches fonts at build time, which breaks an offline build, and Geist has no Bengali
coverage — Sylhet place names would render as tofu boxes. The system monospace stack lets the
OS pick a Bengali-capable font.

## Deploying

Vercel free tier. `/api/brief` is the only dynamic route; everything else is static. Set
`GEMINI_API_KEY` in the Vercel project to switch the brief from the offline generator to the
live model — the panel header says which one ran.
