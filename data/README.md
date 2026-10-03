# Data

Two trees: `raw/` for inputs, `processed/` for what the pipeline writes.

```
data/
├── raw/
│   └── sentinel1/         # Real SAR inputs — the irreplaceable ones are committed
└── processed/             # committed; the console's source of truth
    ├── damage_layer.geojson
    ├── valid_area.geojson
    ├── signals.seed.json
    ├── sector_scores.json
    └── epochs/
        ├── index.json
        └── <slug>/
            ├── damage_layer.geojson
            ├── valid_area.geojson
            ├── signals.seed.json
            ├── sector_scores.json
            ├── flood.png            # if flood_overlay.py was run
            └── flood_bounds.json
```

## `raw/sentinel1/`

If `damage_layer.geojson` and `valid_area.geojson` are both present,
`build_all.load_real_damage()` uses them and overrides the synthetic demo.
**Both files are required** — a damage layer without its imagery footprint
would let the verifier miscall coverage (D-005).

### What is committed, and what is not (D-036)

`data/raw/` is **not** ignored wholesale any more. The five files the damage
layer is *built from* are committed (18.4 MB), because without them a fresh
clone cannot re-run `sentinel1_to_damage_layer` and `build_all` would
silently fall back to the synthetic demo:

| Committed — irreplaceable inputs | |
|---|---|
| `sylhet_buildings_flood.geojson` | building footprints + flood fraction (peak) |
| `sylhet_buildings_flood_pre.geojson` | same, pre-peak window |
| `flood_mask_2022-06-06.tif` | SAR flood mask, pre-peak |
| `flood_mask_2022-06-19.tif` | SAR flood mask, peak |
| `valid_area.geojson` | the imagery footprint (AOI polygon) |

| Ignored — regenerable outputs | |
|---|---|
| `damage_layer.geojson` | output of `sentinel1_to_damage_layer` |
| `damage_layer_peak.geojson` | " |
| `damage_layer_pre.geojson` | " |

The ignored files are byte-reproducible from the committed inputs (verified:
0/18,292 `damage_class` differences on both epochs), and the same content is
already committed under `processed/`.

Rebuild any of them with:

```powershell
cd pipeline
$env:PYTHONPATH="src"
python -m groundtruth.sentinel1_to_damage_layer `
    --buildings ..\data\raw\sentinel1\sylhet_buildings_flood.geojson `
    --bbox 91.9 25.02 92.12 25.17 `
    --classifier-ref "mitchellthomas1/S1-Flood-Bangladesh@416e8db" `
    --target-window 2022-06-16 2022-06-23 `
    --baseline-window 2021-05-01 2021-10-01 `
    --footprint-confidence-min 0.75 --flood-threshold 0.5 `
    --out ..\data\raw\sentinel1\damage_layer.geojson
```

`--classifier-ref` must name a real pinned commit. A placeholder like
`@<commit>` is rejected outright and no file is written (D-034) — a flood mask
nobody can re-run is not evidence.

## `processed/`

The four artefacts the console reads. Refreshed every time `build_all` (or
`build_epoch.py`) runs. The root snapshot mirrors the most recent epoch
build — `epochs/index.json` records which slug is current.

## `processed/epochs/`

One directory per dated epoch. Each holds its own complete set of artefacts
plus an optional `flood.png` + `flood_bounds.json` from `flood_overlay.py`.

The console's before/after toggle iterates over the entries in
`epochs/index.json`. To add a new epoch:

```powershell
python -m groundtruth.build_epoch --slug <slug> --label "<label>" `
    --damage <path-to-damage.geojson> `
    --valid-area <path-to-valid_area.geojson>
```

Date-like slugs (`YYYY-MM-DD`) sort naturally in the toggle.

## `console/public/data/`

A **copy** of `processed/`, gitignored and kept in sync by
`console/scripts/sync-data.mjs` (`npm run sync:data`). The console cannot read
`data/processed/` directly — it serves everything from its own `public/` tree.

The sync copies the four root artefacts **and** `epochs/` recursively. If
`epochs/` exists in the source but the copy fails, the script exits non-zero
rather than continuing quietly (D-035).

After every pipeline run:

```powershell
cd console
npm run sync:data
```
