# pipeline

Python side of GroundTruth: extraction → geocoding → verification → fusion, plus the
HASTE converter and contract tooling. **Everything here runs and is exercised by
`build_all`.**

## Setup

```bash
cd pipeline
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

Only dependency is `jsonschema`. Everything else is the standard library — deliberately,
so this builds fast on three different laptops.

## Run the whole thing

```bash
PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all
```

Synthesises the demo inputs, runs every stage, writes the artifacts to **both**
`data/processed/` and `console/public/data/`, validates them against the contracts, and
prints an accuracy report against the planted fakes.

Expected output: 2465 buildings, 50 signals, 49 geocoded, 18 corroborated / 28 recon /
4 suspect, 175 ranked cells, 7 files validated, 0 genuine reports wrongly marked suspect.

## Modules

| Module | What it does |
|---|---|
| `grid.py` | The 500 m cell scheme. **Mirrored in `console/src/lib/grid` logic inside `fusion.ts`** — change both together. |
| `gazetteer.py` | ~30 real Sylhet place names with Bangla/Banglish aliases and fuzzy matching. Stand-in for the GeoNames dump. |
| `extract.py` | Raw report → structured claim. **Rule-based, not an LLM** (see below). |
| `geocode.py` | `location_ref` → lon/lat/cell, with runner-up candidates for the audit trail. |
| `verify.py` | Corroboration + spatial consistency → tier, reason, fusion weight. |
| `fuse.py` | Damage layer + signals → ranked `sector_scores.json`. |
| `demo_data.py` | **Synthetic** damage layer, imagery footprint, and 50 seeded reports. |
| `haste_to_damage_layer.py` | HASTE predictions `.gpkg`/`.geojson` → `damage_layer.geojson`. |
| `build_all.py` | Driver for all of the above. |
| `validate_contracts.py` | Validates artifacts and fixtures against `/contracts`. |

## Three things to know before trusting the output

**1. Extraction is rule-based, not Gemini.** There is no API key in this environment, so
`extract.py` is a deterministic keyword/regex extractor. `LLM_PROMPT` and
`extract_with_llm()` are the seam for the real thing — and `extract_with_llm()` *raises*
rather than silently falling back, because a silent fallback would make
`extraction.model` in the artifact a lie. Costs: unknown phrasings land as
`event_type: "other"`, `summary_en` is assembled rather than translated, and
`claimed_time` is always null so corroboration windows run on `received_at`.

**2. All the data is synthetic.** `demo_data.py` fabricates everything. Place names and
approximate coordinates are real Sylhet; damage labels and reports are invented, and
`haste_commit` is zeroed to `0000000` so it can never be mistaken for a real run. The
synthetic layer has **no** `accuracy` block, so the console honestly shows
"NOT VALIDATED". Do not add invented numbers to fill it.

**3. Eval labels are quarantined.** `build_all.build_signals()` splits `signal.eval` off
before extract/geocode/verify/fuse ever see a signal, and re-attaches it only in
`eval_report()` *after* the pipeline has committed to its answers. That ordering is the
only reason the fake-catch numbers mean anything. It is enforced by structure here, but
nothing stops a future module from reading the field — see DECISIONS.md D-010.

## What the verifier catches, and what it does not

From the last run's eval report:

| Planted fake kind | Count | Outcome |
|---|---|---|
| `contradicts_imagery` | 4 | **All 4 flagged SUSPECT.** This is the kind we are built to catch. |
| `duplicate_astroturf` | 3 | Contained, not flagged — one source posting three times never reaches `corroborated`. |
| `exaggerated_scale` | 2 | **Not detected.** We have no population model. |
| `impossible_location` | 1 | **Not detected** as a fake; it is simply unmappable (`geo: null`). |

**"4 of 10" is not a detection rate to brag about** — only one kind is detectable by
design. The number that actually matters for trust is the other one: **0 genuine reports
were wrongly marked suspect.**

## Converting a real HASTE export

```bash
PYTHONPATH=src ./.venv/bin/python -m groundtruth.haste_to_damage_layer \
  --predictions ../data/raw/haste/building_predictions_<modelId>.gpkg \
  --valid-area  ../data/raw/haste/valid_area_mask.geojson \
  --haste-commit 7d80be7 --backbone mosaiks \
  --damaged-f1 0.77 --validation-sample-n 200 \
  --out ../data/processed/damage_layer.geojson
```

`.gpkg` input needs `geopandas` (`./.venv/bin/pip install geopandas`). To avoid that,
dump to GeoJSON first with `ogr2ogr` and pass the `.geojson` — the stdlib path handles it.
Omit the accuracy flags and the layer is honestly marked unvalidated. Field mapping is
documented in the module docstring and in `runbooks/haste-local-setup.md` §8.

## Conventions

- **Deterministic ids.** `signal_id` is a content hash, so re-running does not churn
  committed JSON.
- **Null is not zero.** `persons_at_risk: null` means unstated. Never sum it as 0 and
  present the result as an estimate — the UI labels the total as a floor (`≥N`).
- **Obscured is not assessed.** Cloud-obscured buildings are excluded from every damage
  denominator. Absence of damage there means we could not see.
