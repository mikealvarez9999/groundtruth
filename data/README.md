# Data

Two trees: `raw/` for inputs, `processed/` for what the pipeline writes.

```
data/
├── raw/
│   └── sentinel1/         # Real SAR inputs (optional; if absent, demo runs)
└── processed/
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

Optional. If `damage_layer.geojson` and `valid_area.geojson` are both
present, `build_all.load_real_damage()` uses them and overrides the
synthetic demo. **Both files are required** — a damage layer without its
imagery footprint would let the verifier miscall coverage (D-005).

Typical sources for these two files:

- `damage_layer.geojson` — output of
  `python -m groundtruth.sentinel1_to_damage_layer` run against your SAR
  assessment.
- `valid_area.geojson` — the imagery footprint (any polygon in EPSG:4326;
  the verifier uses a point-in-polygon test).

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

A **copy** of `processed/`, kept in sync by `console/scripts/sync-data.mjs`.
The console cannot read `data/processed/` directly — it serves everything
from its own `public/` tree. After every pipeline run:

```powershell
cd console
npm run sync-data
```
