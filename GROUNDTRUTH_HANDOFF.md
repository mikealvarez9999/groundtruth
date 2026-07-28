# GroundTruth — Full Project Handoff / Context Transfer

You are picking up an in-progress hackathon project ("HackaDhon") from another AI
assistant. This document is the complete context: what the project is, everything
that has been built and why, every pitfall already solved, the exact current
state, and the immediate next steps. Read it fully before acting.

---

## 1. What the project is

**GroundTruth** — a disaster triage console that fuses satellite building-damage
assessment with citizen reports into one ranked "go here first" map, with a
streaming resource-allocation brief. The pitch: disaster management today runs on
static maps + raw social media; GroundTruth gives responders near-real-time,
per-pass satellite assessment fused with verified crowdsourced reports, plus
allocation advice.

**Owner's machine**: Windows, 16 GB RAM, PowerShell. Python 3.14 (system).
Project lives at `F:\HackaDhon Project\groundtruth` (extracted from a zip — NOT a
git clone; changes are delivered as whole files to place manually).
Related checkouts:
- `F:\HackaDhon Project\S1-Flood-Bangladesh` — clone of
  github.com/mitchellthomas1/S1-Flood-Bangladesh (Sentinel-1 flood classifier,
  used in the earlier Bangladesh phase).
- A local clone of Microsoft **HASTE** (optical building-damage tool, runs as a
  ~9-container Docker stack, UI at `localhost:4280`, user `admin`).

**Google Earth Engine project id**: `groundtruth-2432008` (authenticated via
`ee.Authenticate()` / `ee.Initialize(project='groundtruth-2432008')`).

---

## 2. Repository layout (the `groundtruth` project)

```
contracts/
  damage_layer.schema.json   # SENSOR-AGNOSTIC: source is oneOf {haste | sentinel1_sar}
  signal.schema.json         # citizen/VLM signal, channels: citizen_seed|citizen_telegram|vlm_*
  sector_score.schema.json   # ranked 500m cells
  examples/                  # must always keep validating
data/
  processed/                 # committed artifacts (single source of truth)
  raw/haste/                 # real HASTE damage layer staging (checked FIRST by build_all)
  raw/sentinel1/             # real SAR damage layer staging (checked second)
  seed/posts.json            # raw seeded posts
pipeline/  (Python, venv at pipeline/.venv on the remote; user runs system python)
  src/groundtruth/
    demo_data.py             # synthetic Sylhet dataset: 2,465 buildings, 50 posts (10 planted fakes)
    extract.py               # RULE-BASED claim extraction (not LLM), PROMPT_VERSION "rules-v1"
    geocode.py               # Bangladesh GeoNames gazetteer; nearest_place() caps at 6 km (returns None beyond)
    verify.py                # tiers: corroborated / plausible_unverified / suspect; spatial check vs damage+valid_area
    fuse.py                  # 500m grid; weights damage .45 / vlm .20 / citizen .35; MIN_ASSESSED_TO_EMIT=5;
                             # MIN_ASSESSED_FOR_DAMAGE=10 + shrinkage prior; missing channel COSTS its share (D-020)
    grid.py                  # lonlat 500m cells; NOTE: lon step referenced to Bangladesh latitude (REF_LAT);
                             # at other latitudes cells are slightly non-square (cosmetic)
    build_all.py             # EVENT-AGNOSTIC orchestrator (see §5); writes 4 artifacts to BOTH
                             # data/processed/ and console/public/data/
    validate_contracts.py    # jsonschema validation of all artifacts; run after every build
    haste_to_damage_layer.py # HASTE gpkg/geojson -> damage_layer contract (optical path)
    sentinel1_to_damage_layer.py # SAR flood-join geojson -> damage_layer contract (SAR path)
    build_epoch.py           # files a dated pass under data/.../epochs/<slug>/ + index.json;
                             # LAST epoch built = default; REFUSES --damage pointing at its own staging path
    flood_overlay.py         # SAR flood-mask GeoTIFF -> epochs/<slug>/flood.png + flood_bounds.json (rasterio only)
console/  (Next.js; MapLibre GL v6 + deck.gl)
  scripts/sync-data.mjs      # copies data/processed -> public/data (incl. epochs/ recursively)
  scripts/sync-maplibre-worker.mjs # MapLibre v6 worker must be served from public/maplibre (setWorkerUrl)
  src/components/
    Console.tsx              # loads 4 artifacts; polls /data/live_signals.json every 4s (merge by signal_id);
                             # epochs manifest -> SAR PASS toggle; provenance-driven bottom ticker
    MapView.tsx              # Carto dark raster basemap (degrades offline to void); per-epoch flood.png
                             # image overlay; sectors/damage/valid-area layers; deck.gl pulses; camera
                             # fitBounds to valid_area bbox (works for ANY event location)
    SidePanel.tsx            # layer toggles (flood/damage/sectors/signals); provenance panel narrows on source.tool
    TriageQueue.tsx, SignalFeed.tsx, AuditDrawer.tsx, BriefPanel.tsx, TopBar.tsx
  src/app/api/brief/route.ts # streaming brief: Gemini if GEMINI_API_KEY else DETERMINISTIC fallback
                             # (computed from sector_scores at request time — demo-safe offline).
                             # EVENT-AWARE: flood->boats; earthquake->USAR/heavy lifting/trauma medical.
  src/lib/fusion.ts          # client-side re-scoring MIRRORS fuse.py (change both in same commit — D-012)
  src/lib/types.ts           # DamageLayer.source is a discriminated union on tool
bot/
  tipline.py                 # Telegram LONG-POLLING bot (no webhook/tunnel). Reuses real
                             # extract->geocode->verify_all. Appends to console/public/data/live_signals.json
                             # (atomic tmp+rename). PRIVACY: never stores Telegram ids — salted hashes only
                             # (GT_TIPLINE_SALT env). Needs TELEGRAM_BOT_TOKEN env.
runbooks/haste-local-setup.md # detailed HASTE setup §0–§10 (Docker, env, ingest, embed/label/predict, export)
```

**The console reads exactly four static JSON artifacts** from `/data/`:
`damage_layer.geojson`, `valid_area.geojson`, `signals.seed.json`,
`sector_scores.json` (+ optional `live_signals.json`, `epochs/`). No backend at
demo time except `/api/brief` (which has an offline deterministic path).

---

## 3. Non-negotiable project principles (these are load-bearing)

1. **Never present fabricated data as real.** Synthetic stand-ins are allowed
   only when clearly labeled (the ticker/provenance do this automatically).
2. **Provenance travels with the artifact.** The damage layer's `groundtruth.source`
   block must truthfully name the sensor/tool/method. Never stamp HASTE
   provenance on non-HASTE data (schema is a oneOf union for exactly this reason).
3. **Absence of accuracy figures = layer marked UNVALIDATED** (UI displays it).
   Never invent an F1.
4. **NO_COVERAGE is never SUSPECT.** A claim outside the imagery footprint
   cannot be contradicted; only imagery contradiction earns "suspect".
5. **Eval quarantine (D-010)**: `eval` blocks on seeded posts (planted-fake
   labels) are stripped BEFORE extract/geocode/verify/fuse and re-attached only
   for the post-hoc eval report. Never let pipeline code read them.
6. **Verify external resources before instructing the user** (bucket listings,
   dataset ids). An earlier unverified Maxar suggestion wasted the user's time;
   after that, everything (Open Buildings asset id, Maxar tile URLs) was
   verified by listing the actual source first.
7. **Per-epoch damage files get their own filenames** — never pass the staging
   path `data/raw/*/damage_layer.geojson` as an epoch input (build_epoch hard-errors).
8. **Don't force labels to manufacture signal.** If damage isn't visible,
   change tiles, not standards — a noise-trained classifier is worse than a
   smaller honest AOI, and the Validation step will expose it.
9. **User instruction: DO NOT push to git.** All work is delivered as whole
   files the user places into their zip-extracted project.

---

## 4. Project history (why things are the way they are)

**Phase A — synthetic demo (done, still the fallback).** Built end-to-end with
synthetic Sylhet flood data (event `bangladesh-flooding22`): 2,465 fake
buildings, 50 seeded posts incl. 10 planted fakes (4 contradicts_imagery — the
only kind detectable by design; 3 astroturf — contained not flagged; 2
exaggerated_scale; 1 impossible_location). The replay + live re-ranking + audit
drawer + brief all work on this.

**Phase B — real Sentinel-1 SAR for Bangladesh (done, being retired).** Maxar
post-event optical for the 2022 Sylhet flood does not exist publicly (monsoon
cloud), so the damage channel was built from Copernicus Sentinel-1 SAR instead:
- Classifier: S1-Flood-Bangladesh repo's z-score method (VV+VH anomalies vs a
  2021-monsoon baseline + raw-VH threshold, spatially smoothed) on GEE.
  Its bundled soil-moisture baseline picker is broken (deprecated NASA asset +
  wrong GCP project) — bypassed by calling `make_collections`/`classify_image`
  directly with an explicit baseline. All repo files needed
  `ee.Initialize(project='groundtruth-2432008')` patched in.
- Buildings: **Google Open Buildings v3** GEE asset
  `GOOGLE/Research/open-buildings/v3/polygons` (verified; covers Bangladesh),
  confidence ≥ 0.75.
- Key method lesson: buildings are strong radar scatterers — footprint∩water
  undercounts massively (0.6%). Correct measure is **flood exposure**:
  `flood.focalMax(radius=30m)` then fraction of footprint within — a building
  is "damaged" (flood-exposed) at ≥ 0.5.
- Final Bangladesh ROI: NE floodplain core (Companiganj/Gowainghat/Jaintiapur),
  bbox **[91.90, 25.02, 92.12, 25.17]**, 79.2% area flooded, 18,292 buildings.
  Peak epoch (16–22 Jun 2022): 4,279 damaged (23.4%). Pre-peak (1–10 Jun):
  3,087 (16.9%). Both filed as epochs; console toggles between them.
- Telegram tip-line built and verified live (tip typed on phone → geocoded →
  verified vs damage layer → appears on map in ~4 s and re-ranks the queue).

**Phase C — CURRENT: pivot to HASTE + Maxar Open Data, multi-event.** The user
returned to the original optical vision using events that HAVE public pre+post
Maxar imagery:
- `Earthquake-Myanmar-March-2025` (M7.7 Sagaing quake, 2025-03-28) — **first target**
- `Brazil-Flooding-May24` (Rio Grande do Sul floods) — second target
The pipeline was made event-agnostic (see §5). The Bangladesh data stays on disk
until the Myanmar build is green, then delete: `data\raw\sentinel1\`,
`data\processed\epochs\`, `console\public\data\epochs\`,
`console\public\data\live_signals.json`. (Keep the SAR *code* — it costs nothing.)

---

## 5. Event-agnostic pipeline behavior (current build_all)

- Auto-detects a real damage layer: `data/raw/haste/` first, then
  `data/raw/sentinel1/` (both need `damage_layer.geojson` + `valid_area.geojson`).
  Neither present → synthetic Sylhet demo.
- `event_id` is read from the damage layer itself.
- If `event_id != "bangladesh-flooding22"`: the seeded citizen corpus and its
  eval are **skipped** (they are Sylhet-specific; replaying them over a foreign
  AOI would be NO_COVERAGE noise). Such events score **damage-only** until a
  per-event corpus + gazetteer exist. This is printed honestly at build time.
- `nearest_place()` returns None beyond 6 km → foreign cells show cell ids, not
  wrong Bangladeshi names.
- Brief wording adapts: event_id matching /flood/ → boats; /earthquake|quake/ →
  USAR teams, heavy lifting, trauma medical.

---

## 6. HASTE on the user's machine — state + solved pitfalls

- Stack runs; UI at `localhost:4280` (admin). Project created:
  **`earthquake-myanmar-march-2025`** (name doubles as event id — keep exact).
- **Solved: Docker socket permission failure.** Symptom: layer `Imagery: Failed`,
  status message `Error while fetching server API version: ('Connection
  aborted.', PermissionError(13, 'Permission denied'))`, or jobs stuck
  "Queueing" forever. Cause: `hastefuncqueues` spawns workers via
  `/var/run/docker.sock` and DOCKER_GID was unset (the runbook's
  `$(stat -c '%g' ...)` is Linux-only; user is on Windows). Fix applied: get gid
  via `docker run --rm -v /var/run/docker.sock:/var/run/docker.sock alpine stat -c %g /var/run/docker.sock`,
  put `DOCKER_GID=<n>` in an `.env` **next to docker-compose.yml** (there was no
  docker/.env — location matters), `docker-compose down && up -d`. Fallback if
  needed: `docker-compose.override.yml` with `services: hastefuncqueues: user: root`.
  Verify with: `docker-compose exec hastefuncqueues python -c "import docker; print(docker.from_env().version()['Version'])"`.
- **Use imagery URLs, not uploads** (upload path hit errors; URL is the designed
  allowlisted route — `*.amazonaws.com` allowed).
- Layer `mandalay_post_2025-03-31` (tile …012) is **Processed and EMBEDDED**
  (MOSAIKS). But tile …012 is the city's WESTERN edge (river/low-density) —
  the user found no visible damage there. Advice given: add the DOWNTOWN tile
  …013 as a second layer (see §7 URLs), label there with the pre/post flicker
  (`P` key). Label keys: 1=Intact 2=Damaged 3=Cloudy, T cycle, Space footprints,
  right-click remove. Aim 60–100 labels; auto-trains after ≥3 across 2 classes.
- Remaining HASTE steps after labeling: **Predict** (required to unlock export)
  → **Validate ~200 random footprints** (record damaged precision/recall/F1 —
  the only honest accuracy numbers) → **Export** GeoPackage
  (`building_predictions_<modelId>.gpkg`, layer name `predictions`, columns
  id / damaged 0-1 / unknown_pct / area / geometry, EPSG:4326) + **valid-area
  mask** GeoJSON.

---

## 7. VERIFIED Maxar Open Data facts (listed directly from the bucket)

Bucket: `https://maxar-opendata.s3.amazonaws.com/` (public, no signing).
Structure: `events/<event>/ard/<utm_zone>/<quadkey>/<YYYY-MM-DD>/<catid>-visual.tif`
(+ `-ms.tif`, `-pan.tif`, `-data-mask.gpkg`, `<catid>.json` STAC item with bbox,
datetime, clouds%). Quadkeys are Maxar's per-UTM-zone grid (NOT web-mercator).

**Myanmar** (46 tiles have both pre+post):
- Tile `47/033111022012` = WEST Mandalay (bbox 95.996–96.049E, 21.946–21.987N,
  0% cloud, 0.49 m): pre 2025-03-23, post 2025-03-31 & 2025-04-03. (Embedded already.)
- Tile `47/033111022013` = **DOWNTOWN Mandalay** (96.045–96.097E), same dates:
  - POST: `https://maxar-opendata.s3.amazonaws.com/events/Earthquake-Myanmar-March-2025/ard/47/033111022013/2025-03-31/10300101108FC600-visual.tif`
  - PRE:  `https://maxar-opendata.s3.amazonaws.com/events/Earthquake-Myanmar-March-2025/ard/47/033111022013/2025-03-23/103001010FCDBB00-visual.tif`
- Sagaing city (nearest the epicenter): zone 46 quadkey `122000133121`
  (95.952–96.003E, 21.900–21.949N), pre 03-23, post 03-30/03-31/04-03.
- East downtown: `47/033111022102` (96.093–96.145E) pre 2025-02-15, post 03-31/04-03.

**Brazil**: zone `22/`; e.g. quadkey `213131031102` (Santa Cruz do Sul area,
-52.83..-52.81, -29.70..-29.68): pre 2023-02-01 (`1040010080457D00-visual.tif`),
post 2024-05-15 & 2024-05-17.

A recon script pattern exists (S3 list-type=2 REST + per-item STAC json) to map
any event's tiles to bbox+dates — reproduce it rather than guessing tiles.

---

## 8. Exact current position & immediate next steps

**The user is at HASTE §labeling for Myanmar.** Next actions, in order:

1. Create second layer `mandalay_downtown_post_2025-03-31` with tile …013 URLs
   (POST + PRE above), Overture footprints → process → embed (MOSAIKS, batch 8;
   30–60 min CPU on 16 GB).
2. Label with pre/post flicker. Quake-damage signatures at 0.5 m nadir:
   pancaked roof → rubble texture; kinked/sagging rooflines; debris aprons in
   streets; bright-blue tarps; fire scars. Damage prevalence is a few percent —
   sweep systematically, label obvious Intacts along the way.
3. Predict → Validate (~200; record P/R/F1) → Export gpkg + valid-area mask →
   save to `F:\HackaDhon Project\groundtruth\data\raw\haste\` as
   `building_predictions_myanmar.gpkg` + `valid_area_mask.geojson`.
4. Pre-clean stale Bangladesh view state:
   `Remove-Item -Recurse -Force data\processed\epochs, console\public\data\epochs; Remove-Item -Force console\public\data\live_signals.json`
5. Convert (from `pipeline\`, `$env:PYTHONPATH="src"`; note --event-id exact):
   ```
   python -m groundtruth.haste_to_damage_layer `
     --predictions ..\data\raw\haste\building_predictions_myanmar.gpkg `
     --valid-area ..\data\raw\haste\valid_area_mask.geojson `
     --haste-commit <short commit of the HASTE checkout> `
     --backbone mosaiks `
     --event-id earthquake-myanmar-march-2025 `
     --imagery-note "Maxar Open Data ARD Z47-033111022013, post 2025-03-31 (pre 2025-03-23), Mandalay downtown" `
     --damaged-f1 <F1> --damaged-precision <P> --damaged-recall <R> `
     --out ..\data\raw\haste\damage_layer.geojson
   ```
   (Python 3.14 note: fiona does not build; geopandas may read gpkg via pyogrio.
   If gpkg read fails, export the `predictions` layer as GeoJSON from HASTE/QGIS
   and pass that — the converter accepts both.)
6. `python -m groundtruth.build_all` → expect `>> REAL DAMAGE LAYER -- tool=haste`,
   the "no citizen corpus" note (correct), N buildings/D damaged, `0 failure(s)`.
7. `cd ..\console; npm run dev` → camera lands on Mandalay, basemap streets,
   damage dots, ranked queue (cell-id labels), HASTE provenance ticker,
   earthquake-worded BRIEF.
8. **Before/after (the user's core pitch)**: second HASTE layer on the PRE
   image → label (mostly Intact, fast) → predict → validate → export →
   convert to `..\data\raw\haste\damage_layer_pre.geojson` (own filename!) →
   `python -m groundtruth.build_epoch --slug 2025-03-23 --label "PRE-QUAKE (23 MAR)" --damage ..\data\raw\haste\damage_layer_pre.geojson --valid-area ..\data\raw\haste\valid_area.geojson`
   then the POST epoch with slug 2025-03-31 LAST (last built = default view).
   The console's "SAR PASS" toggle then reads PRE-QUAKE/POST-QUAKE.

**Backlog after Myanmar is green:**
- Brazil event (repeat §7/§8 flow with zone 22 tiles).
- Per-event gazetteer (GeoNames extract for Mandalay–Sagaing / Rio Grande do
  Sul) → restores citizen channel + Telegram tip-line + real place labels for
  foreign events. (Bot + geocoder currently Bangladesh-only.)
- Optional: merge multiple tiles' exports into one damage layer (concatenate
  features before/at conversion).
- Demo hygiene: delete `live_signals.json` before presenting; keep seeded
  replay as backdrop if demoing Bangladesh; bot is bonus, never dependency.
- Known cosmetic: `grid.py` lon-step uses Bangladesh REF_LAT (cells ~8% off
  square at Brazil's −30°; fine at Mandalay's 22°).

---

## 9. Honest framing for the pitch (agreed with the user)

- "Real-time" is framed as **near-real-time, per-satellite-pass**: every new
  acquisition → pipeline re-runs → map updates in minutes (vs days of manual
  mapping). Optical (HASTE) needs a human-in-the-loop labeling step (~10–15 min)
  — that IS HASTE's design; everything after export is two commands.
- The before/after toggle demonstrates "new data flows in → assessment updates"
  with two real acquisitions; precomputed artifacts are REAL results served
  statically (deterministic pipeline), which is demo-safe, not fabrication.
- Channel 2 (VLM) is not implemented and is labeled as such in UI + brief.
- Sentinel-1 work remains a strength to mention: the contract is sensor-agnostic
  (optical HASTE or SAR both drop in; SAR sees through cloud at night —
  complementary to Maxar optical).

## 10. Environment / tooling quirks worth remembering

- PowerShell multi-line continuation is the backtick; `$env:PYTHONPATH="src"`
  is per-session; run pipeline commands from `groundtruth\pipeline\`.
- `pip install jsonschema` was needed on the user's Python (validator).
- GEE: `python -m ee.cli.gcloud` does NOT exist in current earthengine-api;
  use `import ee; ee.Authenticate()`.
- MapLibre v6: worker served from `public/maplibre` via `setWorkerUrl`; `glyphs`
  key must be OMITTED entirely; maplibre CSS before Tailwind; map container
  needs inline position styles. Debug handle: `window.__gtMap`.
- Console dev: `npm run dev` in `console\`; artifacts fetched from
  `/data/*`; live tips can be injected without Telegram:
  `python -c "import sys; sys.path.insert(0,'bot'); import tipline; tipline.Tipline().handle('<text>', 999)"`
  (run from project root; a signal appears on the map within ~4 s).
- Telegram bot run: `$env:TELEGRAM_BOT_TOKEN="..."; python bot\tipline.py`
  (long-polling; get token from @BotFather /newbot).
