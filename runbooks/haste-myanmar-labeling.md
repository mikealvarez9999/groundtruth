# Click sheet — second HASTE layer on downtown Mandalay

You said "do it all yourself". I can do everything except click on roofs and run the
embedding CPU job (which is yours). This is the exact list of clicks and shortcuts,
in order, for the second layer on tile `47/033111022013` (downtown Mandalay).
Context: `GROUNDTRUTH_HANDOFF.md` §6/§7/§8, `runbooks/haste-local-setup.md`.

---

## 0. Verify the stack is up

```powershell
docker compose -f docker/docker-compose.yml ps
# Expect: azurite, api-proxy, titiler, hastefuncapi, hastefuncqueues, ui = Up
#         data-init = Exited (0)
curl http://localhost:4280          # should redirect to login (302 is fine)
```

If anything is down, run from the `vendor/haste/` clone (or wherever your compose file lives):
```powershell
docker compose -f docker/docker-compose.yml up -d
```

Log in at `http://localhost:4280` — **User ID** = anything, **User's roles** must
contain `administrators`, click **Login**.

---

## 1. Pick the project

Open the project **`earthquake-myanmar-march-2025`** (already created per the handoff).
The first layer `mandalay_post_2025-03-31` is on tile `…012` (river edge, empty).
You are adding the **downtown** tile `…013`.

## 2. Create the image layer

Click **New Image Layer** on the project page.

| Field | Value |
|---|---|
| Layer name | `mandalay_downtown_post_2025-03-31` |
| Workflow | **Building** (Rapid Building Assessment) |
| Custom Building Footprints | **off** (use Overture defaults — runbook §6d) |
| Post-event imagery | paste **one** URL: |

```
https://maxar-opendata.s3.amazonaws.com/events/Earthquake-Myanmar-March-2025/ard/47/033111022013/2025-03-31/10300101108FC600-visual.tif
```

Verified just now: HEAD 200, 70 MB, 0% cloud, bbox 96.0449..96.0971 E × 21.9465..21.9874 N
(downtown Mandalay). Host is `*.amazonaws.com` → HASTE allowlist passes.

Click **Create**. Status will go `Queued → Processing → Processed`. Expect ~5–10 min
(imagery prep downloads ~70 MB, builds COG, fetches Overture footprints for the bbox).

If status sticks at `Queueing`, `DOCKER_GID` is wrong — see handoff §6.

## 3. Embed — MOSAIKS / 1024 / 4 / batch 8

Click **Embed** on the row. In the dialog:

| Field | Value |
|---|---|
| Embedding backbone | **MOSAIKS** (runbook §7a caution — DINOv2 weights are ambiguous in the local image) |
| Output dimensions | 1024 (default) |
| Resize factor | 4 (default) |
| Batch size | **8** (lowered from default 16 because you're at 16 GB) |

Click **Start**. Watch:
```powershell
docker compose -f docker/docker-compose.yml logs -f hastefuncqueues
```
Expect 30–60 min on CPU for Overture's ~5–15k footprints in this ~5 km² AOI. If you
see `killed by signal`, the embed hit OOM — go to the **What if OOM** note at the
bottom before retrying.

When done, the row shows an **Interactive Label** button.

## 4. Label — what to click

Open **Interactive Label**. Zoom to **level 16+** (footprints only appear at ≥15, and
you need the building edges sharp). Hit **`T`** once or twice to get the **pre/post
flicker** mode — it cycles between the post tile and the **2025-03-23** pre tile so
you can see what changed. **`P`** toggles **Labeled / Predicted** view.

**What to label, in 0.5 m Maxar nadir imagery, for a M7.7 inland quake:**

- **Damaged (2)** — pick roofs that look like:
  - **Pancaked**: flat-topped where neighbours still have ridges/gables; or the whole
    roofline is dropped one storey.
  - **Kinked / sagging rooflines**: a long ridge that bows or breaks where a wall gave.
  - **Rubble texture inside the footprint**: speckled grey/white where it used to be a
    smooth metal roof or tile.
  - **Debris apron in the street** touching the building: bright rubble pile on the
    road, not just a tree shadow.
  - **Bright-blue UNHCR tarps** stretched over the building: emergency shelter, not
    intact roofing.
  - **Fire scars**: large blackened patches adjacent.
- **Intact (1)** — pick **diverse** intact roofs (metal, tile, concrete, painted
  different colours). Do NOT just label green-and-red ones near your Damaged clicks;
  HASTE's training diversifies poorly without variety.
- **Cloudy (3)** — building is occluded by cloud or shadow. Use sparingly; only
  when you genuinely can't tell.
- **Skip** — unlabeled. Don't over-label. The auto-trainer kicks in once you have
  ≥3 across 2 classes.

**Aim:** 60–100 labels total. ~30 Damaged, ~50–70 Intact. Damage prevalence in
Mandalay downtown is single-digit percent so you have to hunt for Damaged — sweep
systematically along the main roads, not in a tight cluster.

**Shortcuts:**
| Key | Action |
|---|---|
| `1` | Intact (green) |
| `2` | Damaged (red) |
| `3` | Cloudy (purple) |
| `T` | cycle imagery (post / pre) |
| `P` | toggle Labeled / Predicted |
| `Space` | show/hide footprints |
| Left-click | label one building |
| Right-click | remove label |
| Ctrl + drag | box-select, label many |

After ~20 labels across both classes, watch the side panel — it auto-trains a
logistic regression in your browser and shows Damaged precision/recall/F1 live.
If recall is low (<0.5), click more **Damaged** examples before Predict.

When you're done: click **Save labels** (mandatory), then **Predict all buildings**.
You should see "Predicted N buildings and saved."

## 5. Validate (~200) — this is where the honest numbers come from

Open **Building Validation** for the layer. HASTE loads ~200 random footprints with
the pre/post flicker; you label each as **Damaged**, **Not Damaged**, or **Unknown**
(`1`/`2`/`3`, arrow keys move next/prev). **Save labels**, then **Download GeoJSON**
(keep this — it's your sample).

Then from the embedding row's **Reports** menu:
- **Validation Report** — overall accuracy, per-class P/R/F1, confusion matrix.
- **Assessment Report** — total / scored / cloud-excluded counts, predicted-damaged
  count + %, **estimated total damaged with 95% CI**, PR curve.

**Write down** these five numbers; they go straight into the converter:
- `labels-total`
- `labels-damaged` (of your ~60–100 manual labels)
- `validation-sample-n` (~200)
- `damaged-precision`, `damaged-recall`, `damaged-f1` (the Damaged row of the Validation Report)
- `estimated-damaged-total`, `estimated-damaged-ci95 LOW HIGH` (from Assessment Report)

If `damaged-f1` looks implausible (e.g. >0.95 from 30 damaged labels), be skeptical.
The console will display whatever you pass; do not guess. No numbers → the layer is
honestly marked UNVALIDATED and the console shows it.

## 6. Export two files

From the **embedding row → Results** menu:
- **Download Geopackage (`.gpkg`)** — the predictions. Save as
  `data\raw\haste\building_predictions_myanmar.gpkg`.

From the image layer's **⋯ (more actions)** menu:
- **Download Valid Area Mask** — save as
  `data\raw\haste\valid_area_mask.geojson`.

Both files are real per-building assessment outputs, not pre-baked visuals. They
ship in the console as live evidence.

## 7. Hand off to the agent

When both files are in `data\raw\haste\`, paste the five numbers you wrote down
and say "convert". The agent runs:

```powershell
$env:PYTHONPATH="src"
python -m groundtruth.haste_to_damage_layer `
  --predictions  ../data/raw/haste/building_predictions_myanmar.gpkg `
  --valid-area   ../data/raw/haste/valid_area_mask.geojson `
  --haste-commit <short commit of your HASTE checkout> `
  --backbone     mosaiks `
  --event-id     earthquake-myanmar-march-2025 `
  --imagery-note "Maxar Open Data ARD Z47-033111022013, post 2025-03-31 (pre 2025-03-23), Mandalay downtown" `
  --labels-total <N> --labels-damaged <N2> --validation-sample-n 200 `
  --damaged-precision <p> --damaged-recall <r> --damaged-f1 <f1> `
  --estimated-damaged-total <est> --estimated-damaged-ci95 <lo> <hi> `
  --out ../data/raw/haste/damage_layer.geojson
```

If `.gpkg` read fails on Python 3.14 (fiona/geopandas may not build), dump it first
with GDAL:
```powershell
ogr2ogr -f GeoJSON -t_srs EPSG:4326 `
  data\raw\haste\predictions.geojson `
  data\raw\haste\building_predictions_myanmar.gpkg predictions
```
…and pass `--predictions data\raw\haste\predictions.geojson` instead. The
converter accepts both formats identically.

After that, `python -m groundtruth.build_all` → console smoke-test.

---

## What if OOM during Embed

Embed job dies with `killed by signal` → it ran out of RAM. The 16 GB host is
already trimmed (`HASTE_DOCKER_MEM_LIMIT=12g`, `HASTE_DOCKER_SHM_SIZE=4g` per
runbook §2); there is no headroom to give back. Levers that actually work:

1. **Drop batch size further**: rerun Embed with batch size **4** instead of 8.
2. **Shrink the AOI**: you can't here — it's set by the tile bbox. Skip this lever.
3. **Fall back to MOSAIKS with resize-factor=2** (smaller crops, less RAM per
   building). Edit the embed dialog; expect slightly weaker features.
4. **Last resort**: split the AOI into a smaller custom footprints GeoPackage covering
   ~half the bbox; embed that; later merge exports before conversion.

For the demo, if you can't get the embed to finish, fall back to keeping just
the `…012` west tile's export (already embedded but no visible damage) and
rebuild Bangladesh's epochs — the SAR data is still on disk and the console
still works end-to-end. Be honest about it; do not guess the numbers.