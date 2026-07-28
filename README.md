# GroundTruth

**A disaster-triage console that fuses satellite damage assessment with verified
citizen reports into one ranked "go here first" map — and is honest about what it
cannot see.**

---

## The problem

When a disaster hits, the people deciding where to send boats, medics, and food
are buried in conflicting, unverifiable information. Satellites give wide
coverage but no ground truth and a lag. Citizens on the ground give real-time
detail, but it is noisy, unverifiable, and sometimes deliberately faked. Almost
nobody fuses the two. Responders end up either trusting a satellite map that
cannot see under a roof, or chasing social-media reports that might be a rumour.

Conventional disaster dashboards run on **static maps plus raw social feeds**.
GroundTruth runs on **near-real-time, per-satellite-pass building assessment
fused with tiered citizen reports**, and turns that into a ranked action list
with a resource-allocation brief.

## What it does

Every 500 m grid cell over the affected area gets a fused priority score from up
to three channels:

| Channel | Source | Status |
|---|---|---|
| **1 — Satellite damage** | Per-building assessment from optical (HASTE) **or** SAR (Sentinel-1) imagery | **Real** |
| **2 — VLM findings** | Vision model over imagery crops | *Not implemented — labelled as such in the UI and brief* |
| **3 — Citizen signals** | Text reports → extraction → geocoding → verification | Pipeline real; seed corpus synthetic; **live Telegram tips real** |

On top of the fused score, every citizen claim is **tiered**:

- **Corroborated** — 2+ independent sources agree on place, event, and time window.
- **Plausible-unverified** — a single source, nothing contradicts it (worth a scout).
- **Suspect** — the claim contradicts our own imagery (asserts damage where the
  satellite shows an assessed, undamaged area). *Only imagery can earn "suspect".*

The output is a live map, a ranked triage queue, an audit drawer showing the
evidence and reason behind every score, and a streaming **resource-allocation
brief** (situation → priority sectors → allocation → gaps & cautions) that adapts
to the hazard (boats for floods; USAR teams and trauma medical for earthquakes).

In the console: `Space` play/pause the replay, `A` audit drawer, `B` brief,
`Esc` close.

## Honesty by design

The distinctive thing about GroundTruth is what it *refuses* to do. These rules
are enforced in code, not just intent — a triage tool that overstates its
confidence sends people to the wrong place:

- **Provenance travels with the data.** The damage layer's `source` block names
  the exact sensor, tool, model/classifier, and dates. The map ticker reads this
  live — synthetic data screams "SYNTHETIC", real Sentinel-1 says "REAL SATELLITE
  ASSESSMENT", and neither can be mislabelled as the other.
- **No accuracy figure → marked UNVALIDATED.** If no human-validated sample
  exists, the layer says so. We never invent an F1.
- **"No damage recorded" ≠ "safe".** Cells outside the imagery footprint render
  as `unassessed`, distinct from assessed-and-clear. NO_COVERAGE is **never**
  SUSPECT — a claim we cannot check is not a false claim.
- **A missing channel costs its share of the score** rather than being papered
  over, so "two reports and no imagery" cannot outrank "imagery + reports agreeing".
- **Fake-detection cannot cheat.** In the demo dataset, ground-truth "planted
  fake" labels are stripped before the pipeline runs and re-attached only to
  score it afterwards — so the catch-rate is measured, not rigged.

## Architecture

```
 imagery ─► damage assessment ─► damage_layer.geojson ┐
 (HASTE optical / Sentinel-1 SAR)                      │
                                                       ├─► build_all.py ─► 4 static JSON artifacts
 citizen text ─► extract ─► geocode ─► verify ─► signals.seed.json ┘        │  (damage_layer, valid_area,
   (seeded corpus, or live Telegram tip-line)                                │   signals, sector_scores)
                                                                             ▼
                                                                    console (Next.js)
                                                                    reads static /data,
                                                                    re-scores in-browser
```

- **Pipeline** (Python) produces four committed JSON artifacts. One command,
  `build_all`, runs extract → geocode → verify → fuse → validate and writes to
  both `data/processed/` and `console/public/data/`.
- **Console** (Next.js + MapLibre GL + deck.gl, no Mapbox tokens) fetches only
  those four static files and re-scores the grid in the browser as reports
  arrive. **No backend at demo time** except an AI-brief endpoint with a
  deterministic offline path.
- **Contracts** (JSON Schema) gate every artifact. The damage-layer contract is
  **sensor-agnostic** — HASTE optical or Sentinel-1 SAR both drop into the same
  pipeline; the fusion engine never has to know which satellite saw the disaster.
- **Bot** (Python) is a long-polling Telegram tip-line that runs live reports
  through the *same* verification path and drops them onto the map in seconds.

`pipeline/fuse.py` and `console/src/lib/fusion.ts` are two implementations of the
same fusion — change both in the same commit.

## Data sources

- **Maxar Open Data** — high-res optical, pre/post-event ARD tiles
  (`s3://maxar-opendata`), CC BY-NC 4.0. Used via HASTE for optical damage
  assessment (e.g. *Earthquake-Myanmar-March-2025*, *Brazil-Flooding-May24*).
- **Copernicus Sentinel-1** — C-band SAR, free/open. Sees through cloud and at
  night — the only sensor that could observe the 2022 Bangladesh monsoon flood.
- **Microsoft [HASTE](https://github.com/microsoft/haste)** — Rapid Building
  Assessment (embedding + in-browser logistic regression) on optical imagery,
  run locally in Docker. Setup: `runbooks/haste-local-setup.md`.
- **[S1-Flood-Bangladesh](https://github.com/mitchellthomas1/S1-Flood-Bangladesh)**
  — published z-score SAR flood classifier, run on Google Earth Engine.
- **Google Open Buildings v3** — building footprints for the SAR path, CC BY-4.0 / ODbL.
- **CARTO dark basemap** (OpenStreetMap data) — geographic context, gracefully
  optional (degrades to a dark background offline). No API token.

## Quickstart (synthetic demo — runs immediately, no imagery needed)

Order matters: the console fetches artifacts the pipeline writes.

```bash
# 1. Pipeline: build the four artifacts from the bundled synthetic dataset
cd pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all

# 2. Console
cd ../console
npm install && npm run dev          # http://localhost:3000
```

The synthetic dataset is a labelled Sylhet flood scenario (2,465 buildings, 50
reports including 10 planted fakes). `build_all` prints how the verifier scored
against those fakes, and the map ticker makes the synthetic origin impossible to
miss. This is the always-available fallback and the fastest way to see the whole
system work. The console needs no API keys — the brief falls back to an offline
generator.

## Running on real imagery

The pipeline auto-detects a real damage layer in `data/raw/haste/` (optical) or
`data/raw/sentinel1/` (SAR); drop in `damage_layer.geojson` + `valid_area.geojson`
and `build_all` uses them instead of the demo. The event id is read from the
layer itself, so **any event just works**. (Place labels and the citizen corpus
are currently Sylhet-specific, so foreign events score damage-only until a
per-event gazetteer is added.)

### Optical path (HASTE + Maxar)

1. Run HASTE locally (`runbooks/haste-local-setup.md`).
2. Create a **Building** layer from a Maxar Open Data `-visual.tif` URL
   (post-event; optionally pre-event for the before/after view), Overture footprints.
3. **Embed → Label → Predict → Validate (~200 samples) → Export** the GeoPackage
   and valid-area mask into `data/raw/haste/`.
4. Convert and build:
   ```bash
   python -m groundtruth.haste_to_damage_layer \
     --predictions ../data/raw/haste/building_predictions_<id>.gpkg \
     --valid-area  ../data/raw/haste/valid_area_mask.geojson \
     --haste-commit <short> --backbone mosaiks --event-id <event-slug> \
     --damaged-f1 <F1> --damaged-precision <P> --damaged-recall <R> \
     --out ../data/raw/haste/damage_layer.geojson
   python -m groundtruth.build_all
   ```

### SAR path (Sentinel-1 + Google Earth Engine)

1. On GEE, run the z-score flood classifier over your AOI/date window and join
   Open Buildings footprints by **flood exposure** — a building counts as affected
   when floodwater reaches within ~30 m, because buildings are radar-bright and
   rarely read as open water themselves.
2. Convert and build:
   ```bash
   python -m groundtruth.sentinel1_to_damage_layer \
     --buildings ../data/raw/sentinel1/buildings_flood.geojson \
     --bbox W S E N --target-window START END --baseline-window START END \
     --footprint-confidence-min 0.75 --flood-threshold 0.5 \
     --out ../data/raw/sentinel1/damage_layer.geojson
   python -m groundtruth.build_all
   ```

### Before/after and flood overlays

- **Dated passes** — `build_epoch.py` files each acquisition under `epochs/<slug>/`;
  the console shows a **PRE/POST toggle** so you can watch damage appear between
  two real acquisitions. Build the later pass last (it becomes the default view).
- **Flood imagery** — `flood_overlay.py` renders a SAR flood mask into a
  georeferenced map overlay: per epoch, or `--national --event-id <slug>` for a
  country-scale context backdrop the AOI assessment sits inside (event-gated, so
  it only shows for its own event).

## Live Telegram tip-line

```bash
export TELEGRAM_BOT_TOKEN=<from @BotFather>
python bot/tipline.py          # long-polling — no webhook or tunnel needed
```

Each tip runs through the *same* extract → geocode → verify path as seeded data,
is verified against the committed damage layer, and appears on the map within
seconds, re-ranking the queue. Reporter identities are never stored — `source_id`
and `author_ref` are salted hashes, so a person's reports still corroborate
without us keeping anything that identifies them. The seeded replay is the safe
backdrop; a live tip is the bonus that proves the pipeline is real.

## Repository layout

```
contracts/   JSON-Schema contracts (damage_layer is sensor-agnostic) + examples
pipeline/    Python: extract, geocode, verify, fuse, converters, build_all, build_epoch, flood_overlay
console/      Next.js console (MapLibre + deck.gl), reads 4 static artifacts
bot/          Telegram tip-line
runbooks/     HASTE local-setup walkthrough
data/         raw/ (real-imagery staging, gitignored), processed/ (committed artifacts)
```

## Current status & honest limitations

- **Working end to end**: synthetic demo; real Sentinel-1 SAR flood assessment
  (Bangladesh); event-agnostic pipeline ready for HASTE/Maxar optical (Myanmar,
  Brazil); live Telegram tips; before/after toggle; national flood context overlay.
- **Damage semantics are honest and sensor-specific**: HASTE optical detects
  structural damage; the SAR path detects **flood exposure**, not structural
  collapse, and says so in its provenance.
- **SAR under-detects water among dense buildings** (radar layover), so urban
  flood exposure is a conservative lower bound.
- **Channel 2 (VLM) is not implemented** and is labelled as such everywhere.
- **Place labels and the citizen corpus/gazetteer are Bangladesh-specific**;
  other events currently score damage-only until a per-event gazetteer is added
  (which also lights up the tip-line for those events).
- Damage layers with no validation sample are shown **UNVALIDATED** — a guess
  with good styling is still a guess.

## Credits

Built on Microsoft HASTE, Copernicus Sentinel-1, Maxar Open Data, Google Open
Buildings, the S1-Flood-Bangladesh classifier, OpenStreetMap/CARTO, MapLibre GL,
and deck.gl. Respect each source's licence when using its data.
