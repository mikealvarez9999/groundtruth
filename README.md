# GroundTruth

A disaster-triage command console for **rapid-onset floods**. Three independent
signal channels — satellite damage assessment, vision-language photo check, and
citizen reports — are fused into a single ranked "go here first" map and an
AI-written brief. The default reference event is the **2022 Sylhet floods**
(`bangladesh-flooding22`).

> Decisions that shaped this codebase live in [`DECISIONS.md`](DECISIONS.md).
> Every load-bearing claim below cites a `D-NNN` entry.

## What it produces

- A ranked sector map (grid cells of ~500 m, see D-019) coloured by the
  posterior "go here first" score.
- An `eval_report` printed at the end of every build: how many planted fakes
  were flagged, how many genuine reports survived.
- A Next.js console for humans — clicking a cell opens its audit drawer
  (every signal, every source, every corroboration, every demotion).
- A Telegram bot that lets people on the ground submit tips in Bangla or
  English from their phone, with optional GPS and photos.

## The three channels

| # | Channel | Status | Module |
|---|---|---|---|
| 1 | **Sentinel-1 SAR damage map** | Live, default | `pipeline/src/groundtruth/sentinel1_to_damage_layer.py` |
| 2 | **VLM photo corroboration** | Live when keyed (OpenRouter) | `bot/vlm_check.py` |
| 3 | **Citizen reports (seeded + Telegram)** | Live | `bot/tipline.py` |

Channel 1 is the only one that produces a **building-level damage class**.
Channels 2 and 3 **modulate** that prior; neither ever overrides a SAR
observation (D-029).

**LLM providers (D-037).** Gemini is gone. Text — the allocation brief — runs on
Groq `openai/gpt-oss-120b` via `GROQ_API_KEY`. Images — the photo VLM — runs on
OpenRouter `thinkingmachines/inkling:free` via `OPENROUTER_API_KEY`. Extraction
stays rule-based (D-021). Both model ids were verified against the providers'
own listings before any code was written.

## Architecture at a glance

```
SAR damage GeoPackage  ─┐
citizen text + GPS     ─┼─►  fuse.py  ──►  ranked sectors + eval report
citizen photo (VLM)    ─┘            │
                                    ▼
                              Next.js console
                              (MapLibre + deck.gl)
```

The pipeline writes four JSON artefacts under `data/processed/`
(`damage_layer.geojson`, `valid_area.geojson`, `sector_scores.json`,
`signals.seed.json`). The console polls for live signals and re-scores on the
fly; the four artefacts are the snapshot.

## Quickstart

```powershell
# 1. Build (synthetic demo if no real damage layer is dropped in).
pip install -r pipeline/requirements.txt
python -m groundtruth.build_all

# 2. Sync to the console.
cd console
npm install
npm run sync:data         # copies JSON artefacts + epochs/ into console/public/data
npm run dev               # http://localhost:3000  (predev re-syncs automatically)

# 3. (Optional) Run the Telegram tipline.
$env:TELEGRAM_BOT_TOKEN = "..."
python run_bot.py
```

To use a real Sentinel-1 assessment instead of the synthetic demo, drop two
files:

- `data/raw/sentinel1/damage_layer.geojson`
- `data/raw/sentinel1/valid_area.geojson`

`build_all.load_real_damage()` auto-detects them and overrides the demo.
**Both must be present** — a damage layer without its imagery footprint would
let the verifier miscall coverage (D-005).

For two dated epochs (the before/after toggle in the console), use
`build_epoch.py`:

```powershell
python -m groundtruth.build_epoch --slug 2022-06-06 --label "<=06 JUN - PRE-PEAK" `
    --damage data\raw\sentinel1\damage_pre.geojson `
    --valid-area data\raw\sentinel1\valid_area.geojson

python -m groundtruth.build_epoch --slug 2022-06-19 --label "19 JUN - PEAK" `
    --damage data\raw\sentinel1\damage_peak.geojson `
    --valid-area data\raw\sentinel1\valid_area.geojson
```

The epoch you build last becomes the root snapshot. Pick a date-like slug so
the toggle sorts naturally.

## What the verifier catches, and what it doesn't

| Planted fake kind | Outcome |
|---|---|
| `contradicts_imagery` | **Flagged SUSPECT** — the case the system is built for |
| `duplicate_astroturf` | **Contained, not flagged** — three posts from one source never reach `corroborated` |
| `exaggerated_scale` | **Not detected** — no population model |
| `impossible_location` | **Not detected as a fake** — it is simply unmappable (`geo: null`) |

The headline number for trust is the **false-positive count**: the seeded eval
ends with 0 genuine reports wrongly marked suspect. Corroboration confirms
that *something* is happening at a place; it cannot bound *how bad*.

## Operating notes

- **No live basemap.** The console renders on the OpenStreetMap raster
  tiles bundled in `console/public/`. There is no Mapbox, no telemetry, no
  external tile API at runtime.
- **Nothing runs Python at deploy time.** The pipeline is run once on a
  machine, and its output is committed under `data/processed/`. Vercel runs
  `npm run sync:data` + `next build` and serves those committed artefacts, so
  the console works from committed data with no Python present (D-035).
- **The SAR inputs are committed; their outputs are not.** The five irreplaceable
  files in `data/raw/sentinel1/` are in git so the damage layer can be rebuilt
  on any machine; the converter's own output stays ignored because it is
  byte-reproducible from them (D-036).
- **Provenance has to be re-runnable.** `--classifier-ref` rejects placeholders
  and writes nothing if given one; `classifier_ref` is required by the schema
  for the SAR branch (D-034). An assessment nobody can re-run is not evidence.
- **Privacy invariant (D-030):** the bot never stores raw Telegram user IDs.
  A salted digest is the only identifier that touches the audit trail.
- **Eval labels are quarantined (D-010):** the synthetic seed carries
  ground-truth labels inside an `eval` block that is stripped before
  corroboration, fusion, or scoring runs. Nothing downstream can read it even
  by accident.
- **Contracts are frozen** at v1.0.0. Renaming a field is a breaking change —
  see `contracts/README.md` for the procedure.

## Repo map

| Path | What's in it |
|---|---|
| `pipeline/` | The Python ground-truth package. Module breakdown in [`pipeline/README.md`](pipeline/README.md). |
| `console/` | The Next.js command console. Run/deploy notes in [`console/README.md`](console/README.md). |
| `bot/` | Telegram tipline + VLM photo check. Privacy and ops in [`bot/README.md`](bot/README.md). |
| `contracts/` | Frozen JSON schemas + fixtures. [`contracts/README.md`](contracts/README.md). |
| `data/` | `raw/` inputs, `processed/` artefacts. [`data/README.md`](data/README.md). |
| `DECISIONS.md` | The design log. Every non-obvious choice has a `D-NNN` entry. |
| `run_bot.py` | Entry point for the long-poll Telegram bot. |
| `maxar_recon.py` | Optional Maxar Open Data recon helper (not on the hot path). |
