# Pipeline

The Python ground-truth package. Reads SAR damage + citizen reports, writes
four JSON artefacts the console can consume.

```powershell
pip install -r requirements.txt
python -m groundtruth.build_all
```

If `data/raw/sentinel1/` holds a real damage layer + valid-area footprint,
`build_all` picks it up automatically. Otherwise it runs on the synthetic
demo (`demo_data.py`) seeded from the 2022 Sylhet reference event.

## Modules

| Module | Purpose |
|---|---|
| `grid.py` | 500 m grid cells in EPSG:4326. Pure stdlib; no shapely. D-019. |
| `gazetteer.py` | Place-name lookup for the eight Sylhet upazilas in scope. |
| `geocode.py` | Gazetteer → `geo` block on every signal. Honest about ambiguity (`candidates` array). |
| `extract.py` | Rule-based claim extraction (location_ref, event_type, severity). **Not** an LLM — see D-021. |
| `verify.py` | Corroboration (D-005, D-018), spatial consistency, tier assignment. |
| `fuse.py` | Combines channel weights into sector scores (D-009, D-020). |
| `demo_data.py` | Synthetic citizen posts + SAR stand-in for the demo. |
| `sentinel1_to_damage_layer.py` | Real Sentinel-1 SAR → `damage_layer.geojson`. |
| `flood_overlay.py` | Flood-mask GeoTIFF → epoch `flood.png` + `flood_bounds.json`. |
| `build_epoch.py` | Stages a dated epoch (pre-peak / peak / etc.) into the root artefacts. |
| `build_all.py` | Orchestrator. Runs the full chain, prints `eval_report`. |
| `validate_contracts.py` | Schema-check every JSON artefact before writing it. |

## Outputs

After `build_all`:

```
data/processed/
├── damage_layer.geojson     # SAR: every building + damage_class
├── valid_area.geojson       # Imagery footprint: where the SAR saw something
├── signals.seed.json        # Citizen signals (live: tipline writes here too)
└── sector_scores.json       # The ranked map
```

For multi-epoch runs:

```
data/processed/epochs/<slug>/
├── damage_layer.geojson
├── valid_area.geojson
├── signals.seed.json
├── sector_scores.json
├── flood.png                # if flood_overlay was run
└── flood_bounds.json
```

`epochs/index.json` tracks which slugs exist and which one is the root
default (last built wins — that's what the root artefacts mirror).

## Design choices worth knowing

- **Rule-based extraction, not LLM.** D-021. A Gemini key was never required
  for the MVP. The seam is in place — `extract.py` exposes the same interface
  a model-backed extractor would — but the shipped implementation is regex +
  keyword scoring.
- **The eval block is quarantined (D-010).** `build_all.build_signals()`
  splits the `eval` block off the synthetic posts and hands it back to the
  caller as a separate dict. Nothing downstream of that function can see it.
- **Schema validation runs before write.** Every JSON artefact is checked
  against `contracts/*.schema.json` before it hits disk. A bad build fails
  loudly, not silently.
- **No renormalisation across channels (D-020).** If a sector has fewer
  signals than its neighbours, it does **not** get pulled up by the average.
  Lower evidence → lower score, full stop.
- **Provenance must be re-runnable (D-034).** `sentinel1_to_damage_layer`
  refuses a `--classifier-ref` that is a placeholder (`@<commit>`, `todo`, …) and
  writes no file when it sees one. `classifier_ref` is `required` for the
  `sentinel1_sar` branch of the damage-layer schema, so validation catches it
  too. `--notes` is *not* defaulted: pass it if the run needs a method note, and
  check the output actually carries it.

## Known gaps

- **The `--notes` default is not enforced.** `sentinel1_to_damage_layer` only
  writes `notes` when `--notes` is passed, so a rebuild can silently drop the
  sentence defining what `damage_class` means. The committed layers carry it
  ("flood exposure", 30 m); re-runs must pass `--notes` to keep it.
- **`sentinel1_to_damage_layer`'s docstring describes an older method** than the
  data it produced: it documents a raw flood-mask `reduceRegions` mean, while the
  shipped layers use `flood.focalMax(radius=30m)` then the fraction of the
  footprint within, damaged at ≥ 0.5.

## CLI cheatsheet

```powershell
# Build everything from synthetic defaults.
python -m groundtruth.build_all

# Build from a real Sentinel-1 layer + footprint. Note the real flag names:
# --buildings (not --footprints), and --bbox or --valid-area for the footprint.
python -m groundtruth.sentinel1_to_damage_layer `
    --buildings ..\data\raw\sentinel1\sylhet_buildings_flood.geojson `
    --bbox 91.9 25.02 92.12 25.17 `
    --classifier-ref "mitchellthomas1/S1-Flood-Bangladesh@416e8db" `
    --target-window 2022-06-16 2022-06-23 `
    --baseline-window 2021-05-01 2021-10-01 `
    --footprint-confidence-min 0.75 --flood-threshold 0.5 `
    --out ..\data\raw\sentinel1\damage_layer.geojson

# Stage a dated epoch (the last one you build becomes the root snapshot).
python -m groundtruth.build_epoch --slug 2022-06-19 --label "19 JUN - PEAK" `
    --damage data\raw\sentinel1\damage_peak.geojson `
    --valid-area data\raw\sentinel1\valid_area.geojson

# Generate the flood overlay for an epoch (optional, for the map layer).
python -m groundtruth.flood_overlay --mask data\raw\sentinel1\flood_mask.tif --slug 2022-06-19

# Validate every JSON artefact against its schema.
python -m groundtruth.validate_contracts
```
