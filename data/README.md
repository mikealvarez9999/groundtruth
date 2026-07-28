# data

Flat files are our entire data layer — no databases, by project constraint.

```
data/raw/         gitignored. Anything downloaded or exported by hand.
data/processed/   committed. Contract-conforming artifacts the app reads.
```

## `raw/` — gitignored

Large, regenerable, or provenance-heavy inputs. Nothing here is committed, so **if it took a
human action to produce it, record how in a runbook**. Expected contents:

- `raw/haste/` — the HASTE exports: `building_predictions_<modelId>.gpkg`, the building
  footprints, and the valid-area mask GeoJSON. See `runbooks/haste-local-setup.md` §8a.
- `raw/imagery/` — Maxar Open Data scenes or crops, if downloaded locally.
- `raw/gazetteer/` — the GeoNames Bangladesh dump used for offline fuzzy geocoding.
- `raw/seed/` — the archived-post source material before extraction.

## `processed/` — committed

Small, contract-validated artifacts the console and pipeline actually read. Every file here
must validate:

```bash
cd pipeline
PYTHONPATH=src ./.venv/bin/python -m groundtruth.validate_contracts
```

Expected filenames, matched by the validator's globs:

| File | Contract |
|---|---|
| `damage_layer.geojson` | `contracts/damage_layer.schema.json` |
| `valid_area.geojson` | plain GeoJSON polygon; the imagery AOI, needed for spatial checks |
| `signals.seed.json` | array of `contracts/signal.schema.json` |
| `sector_scores.json` | `contracts/sector_score.schema.json` |

`.pmtiles`, `.gpkg`, and `.tif` are gitignored even under `processed/` — they are binary and
regenerable. The PMTiles basemap is built once and hosted, not committed.

## Two rules

1. **Never commit a raw file to dodge the gitignore.** If the console needs it, it belongs in
   `processed/` and it needs a contract.
2. **Provenance travels with the data.** `damage_layer.geojson` carries the HASTE commit,
   backbone, and measured accuracy in its `groundtruth` block. A processed file whose origin
   nobody can reconstruct gets deleted, not debugged.
