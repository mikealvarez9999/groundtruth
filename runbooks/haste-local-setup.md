# Runbook — Stand up HASTE locally and export a damage layer

**Audience:** the teammate whose laptop runs HASTE (16 GB RAM, Linux, no NVIDIA GPU).
**Goal:** get from a Maxar `bangladesh-flooding22` scene to a per-building damage
GeoPackage, then convert it into our `contracts/damage_layer.schema.json` artifact.

---

## Provenance and trust rules for this runbook

Everything in this file about HASTE's *behaviour* was read out of the cloned source at
`vendor/haste`, pinned at:

| | |
|---|---|
| Repo | `https://github.com/microsoft/haste` |
| Commit | `7d80be7` |
| Commit date | 2026-07-24 |

HASTE is newer than the agent's training data. Every HASTE claim below cites the file it
came from, so you can re-check it. Two rules:

1. **If a claim has a file citation, trust the file over this runbook.** Re-read the cited
   file if something behaves differently.
2. **§10 lists what the HASTE files do NOT answer.** Those are genuinely open and must be
   settled by running the thing — do not let anyone (including an AI) fill them in from
   memory.

Claims about **Maxar Open Data** (bucket names, asset paths) are *not* from the HASTE repo
and are flagged as such wherever they appear.

---

## 0. Read this before you start: your laptop is under the documented minimum

`vendor/haste/docker/README.md` § "Hardware Requirements" states:

> **Minimum (Development / Testing)** — CPU: 8 cores, **RAM: 32 GB**, GPU: None (CPU-only
> mode — training will be slow but functional), **Storage: 100 GB SSD**

You have **16 GB**. That is half the documented minimum. This runbook is still worth
running, because our workflow (Rapid Building Assessment) is the cheap path — but go in
with these expectations:

- **You cannot skip the heavy CUDA image.** `QUICKSTART.md` §4 offers a `--no-deps` shortcut
  to avoid building `haste-training`. **That shortcut does not apply to us.** The
  building-embedding job runs *inside the training image*:
  `vendor/haste/hastelib/src/hastegeo/core/processors/embedding.py` (module docstring) says
  the postprocessor "submits a task to the *training* docker image running
  `embed-buildings`". So budget the disk and the 15–30 min build.
- **Embedding will run on CPU.**
  `vendor/haste/hastelib/src/hastegeo/workflows/embed_buildings.py:597` selects
  `torch.device("cuda" if torch.cuda.is_available() else "cpu")` — there is a real CPU path,
  it is just slow.
- **Keep the AOI small.** A few km² of Sylhet, not the whole district. Fewer footprints =
  less RAM and a shorter embed.
- **Free disk first.** `QUICKSTART.md` §1 says "need ~100 GB for the full image set". Run
  `df -h .` and clear space before you build.

If the embed job gets OOM-killed, that is the expected failure mode at 16 GB — go to §9.

---

## 1. Preflight

```bash
git clone https://github.com/microsoft/haste.git
cd haste

uname -s                       # expect: Linux
uname -m                       # expect: x86_64
docker --version && docker compose version && docker info >/dev/null 2>&1 && echo "docker OK"
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi 2>/dev/null \
  && echo "GPU OK" || echo "NO GPU"
df -h .
```

Source: `QUICKSTART.md` §1.

Per the profile table in `QUICKSTART.md` §1, "Linux host **without** a GPU" → profile `cpu`,
`HASTE_ENABLE_GPU=0`. That is us.

If Docker is missing, `docker/README.md` §"Prerequisites → 1. Docker & Docker Compose" has
the full Ubuntu install script. Use Docker CE, **not** the snap package.

**✅ Gate 1:** `docker info` succeeds and you have written down `cpu` as your profile.

---

## 2. Write `docker/.env`

```bash
HOST_IP=localhost
DOCKER_GID=$(stat -c '%g' /var/run/docker.sock)

cat > docker/.env <<EOF
# --- Required ---
HOST_IP=${HOST_IP}
DOCKER_GID=${DOCKER_GID}

# --- CPU profile (no NVIDIA GPU) ---
HASTE_ENABLE_GPU=0
HASTE_GPU_DEVICES=all

# --- Optional: Azure Maps, only affects the Visualizer swipe map ---
# We do not need this. Our own console renders the map.
VITE_AZURE_MAPS_CLIENT_ID=placeholder

# --- Memory tuning for spawned job containers (see note below) ---
HASTE_DOCKER_SHM_SIZE=4g
HASTE_DOCKER_MEM_LIMIT=12g
EOF

cat docker/.env
```

Sources: `QUICKSTART.md` §2 for the file shape, `HOST_IP`, `DOCKER_GID`, and the GPU flags.

⚠️ **The two memory numbers above are our extrapolation, not HASTE guidance.** The tuning
table in `docker/README.md` § "Memory & Performance Tuning" starts at **32 GB RAM → `8g` /
`28g`** and has no 16 GB row. `4g` / `12g` is us halving the 32 GB row and leaving the host
some headroom. If the embed job dies with "killed by signal", `docker/README.md` says to
*raise* `HASTE_DOCKER_SHM_SIZE` — but on a 16 GB host raising it competes with the host
itself, so also shrink the AOI (§9).

**✅ Gate 2:** `docker/.env` exists, `HOST_IP` non-empty, `DOCKER_GID` is a number.

---

## 3. Build the images

Run every compose command from the **repo root** with `-f docker/docker-compose.yml` — the
build context is the repo root (`context: ..`). Source: `QUICKSTART.md` §3.

```bash
docker compose -f docker/docker-compose.yml build
```

`QUICKSTART.md` §3: "This builds ~9 images including the large CUDA + conda `haste-training`
image. **Expect 15–30 minutes** on a first build."

Do **not** use the "build everything except the heavy training image" variant from
`QUICKSTART.md` §3 — as established in §0, we need `haste-training` for embedding.

If a pull dies mid-layer with `EOF` / `TLS handshake timeout`, `QUICKSTART.md` §9 says to
turn off any VPN and just retry — Docker resumes cached layers, so a retry loop converges.

**✅ Gate 3:** build exits 0; `docker images | grep haste` lists the images, including
`haste-training`.

---

## 4. Start the stack

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f --tail=50
```

`data-init` reaching **`Exited (0)` is correct** — it is a one-shot seeder, not a crash.
`"Container already exists"` lines from it are benign. Source: `QUICKSTART.md` §4.

Boot order (enforced by `depends_on`): `azurite` → `data-init` → `titiler` / `hastefuncapi`
→ `hastefuncqueues` → `api-proxy` → `ui`. Source: `QUICKSTART.md` §4.

`data-init` creates the queues our workflow needs, including the embedding queue —
`vendor/haste/docker/data-init/upload_data.py:42-51` creates `local-image-queue`,
`local-train-queue`, `local-stats-queue`, `local-zip-queue`, `local-inference-queue`,
**`local-embedding-queue`**, and the two poison queues. If the **Embed** button later
appears to do nothing, confirm that queue exists.

**✅ Gate 4:** `azurite`, `api-proxy`, `titiler`, `hastefuncapi`, `hastefuncqueues`, `ui` are
`Up`; `data-init` is `Exited (0)`.

---

## 5. Health checks

```bash
curl -s "http://localhost:10000/devstoreaccount1?comp=list" >/dev/null && echo "azurite OK"
curl -s http://localhost:7071/api/GetAdminSettings | head -c 200 ; echo
curl -s http://localhost:8000/healthz && echo "  <- titiler OK"
curl -s -L -o /dev/null -w "ui HTTP %{http_code}\n" http://localhost:4280
```

Source: `QUICKSTART.md` §5. A bare `curl` of the UI root returning `302` is **correct** — it
redirects to the SWA emulator login portal; with `-L` it should resolve to 200.

Open **http://localhost:4280**. The SWA mock-login form pre-fills **User's roles** with
`administrators`. Enter any User ID and Username, confirm that role is present, click
**Login**. Source: `QUICKSTART.md` §5.

**✅ Gate 5:** all four checks pass and you are logged into the UI.

---

## 6. Load the Maxar `bangladesh-flooding22` scene

### 6a. The URL allowlist — read this before you copy any URL

This is the single most likely thing to waste your afternoon.
`vendor/haste/hastelib/src/hastegeo/core/utils/url_allowlist.py` enforces an **allowlist of
hosts** for imagery URLs:

- `*.blob.core.windows.net` (Azure Blob Storage), or
- `*.amazonaws.com` (AWS S3)

Anything else is a **hard rejection** (`validate_imagery_url`, same file). It is enforced
twice: at submission time in `PutLayer`
(`vendor/haste/api/hastefuncapi/function_app.py:812`, via
`validate_image_layer_imagery_urls`) and again at fetch time.

Consequences:

- ✅ Maxar Open Data lives in an **AWS S3** bucket, so its `https://…amazonaws.com/…` URLs
  satisfy the allowlist. (*The S3-hosting claim is general knowledge, not from the HASTE
  repo — see §10.1 for what you must verify.*)
- ⚠️ **The sample-data URLs in HASTE's own docs will be rejected.**
  `vendor/haste/docs/usage/image-layers.md` § "Sample data to try HASTE" points at
  `https://opendata.aiforgood.ai/…`. That host is not on the allowlist. To use those
  samples, **download the file and upload it** rather than pasting the URL. This is a real
  inconsistency between HASTE's docs and its code; the code is what runs.
- **Custom footprint URLs** are slightly more permissive: same hosts, plus the configured
  local upload host (`validate_footprint_url`, same file) — which is what makes the in-app
  file uploader work. File upload is the reliable route.

Also: only a narrow set of formats can be parsed at all. `vendor/haste/spec/architecture/decisions/0004-gdal-driver-allowlist.md`
restricts GDAL to raster `GTiff`, `COG`, `VRT`, `JPEG`, `PNG`, `MEM` and vector `GPKG`,
`GeoJSON`, `Memory`. Maxar's visual COGs are fine. Anything HDF/netCDF is not.

### 6b. Create the project

1. **New Project** on the dashboard → name (`sylhet-flood-2022`) and description.
2. **Source Type** → **Maxar**. The seeded source types are Maxar, Planet, NASA ISERV,
   OpenArialMap, AWS S3, Azure Blob — see
   `vendor/haste/setup/config_admin_settings.json`.

Source: `docker/README.md` § "Creating a Project".

### 6c. Create the image layer — pick the **Building** workflow

On the **Create Image Layer** form there is a **workflow** selector
(`docs/usage/image-layers.md` § "Choose a workflow"):

- **Standard** — draw labels, train a segmentation model, get a wall-to-wall damage raster.
- **Building** — embed footprints and label them interactively.

**Choose `Building`.** That is the Rapid Building Assessment path: per-building output, no
training job, minutes not hours (`docs/usage/rapid-building-assessment.md`). It is the only
path that fits a 16 GB CPU-only laptop and a 3-day hackathon.

Then:

- **Post-event imagery** — paste one or more Maxar `.tif` URLs (allowlisted host, §6a) or
  upload files. **Only TIFF (`.tif`) is accepted** (`docs/usage/image-layers.md`
  § "Formats"). Multiple files in one section are **merged into a single mosaic**, so all
  files in a section must cover the same AOI (same doc, § "Create a New Image Layer").
- **Pre-event imagery** — optional. `docs/usage/image-layers.md` notes the samples are
  post-event only and "pre-event imagery is optional in both workflows". Add it if you have
  a matching pre-flood Sylhet scene; it makes the labeler's before/after toggle useful.
- **Footprints** — leave **Custom Building Footprints** *off* for the first run.

### 6d. Footprints: prefer the default, and note the format constraint

Our kickoff plan said "Microsoft Global Building Footprints / OSM". **HASTE does not use
either by default.** `docs/usage/image-layers.md` § "Custom building footprints" and
`docs/usage/rapid-building-assessment.md` § "Before you start" both state footprints are
downloaded automatically from **Overture Maps** for the area covered by the post-event
imagery.

Take the Overture default. If you must supply your own, the constraints are exact
(`docs/usage/image-layers.md`, note block):

- **GeoPackage (`.gpkg`) only**, one file per layer, **≤ 500 MB**. Not GeoJSON, not
  shapefile — so an OSM or MS-Footprints extract needs converting first:
  `ogr2ogr -f GPKG footprints.gpkg input.geojson`
- Must carry a CRS (any CRS; HASTE reprojects to EPSG:4326 and clips to the imagery).
- **Polygon / MultiPolygon only** — other geometry types are dropped.
- URL option must be Azure Blob or S3 (§6a); otherwise upload the file.
- **Footprints are set at layer creation and cannot be changed afterward.**

### 6e. Wait for `Processed`

Uploading imagery enqueues `local-image-queue`; `hastefuncqueues` spawns
`haste-imageryprep`, which downloads/validates the imagery, builds COGs, and generates tile
indices (`docker/README.md` § "Uploading Imagery").

```bash
docker compose -f docker/docker-compose.yml logs -f hastefuncqueues
```

**✅ Gate 6:** the layer's status reads **Processed** and an **Embed** button appears on it
(`docs/usage/rapid-building-assessment.md` § "Before you start").

---

## 7. Embed → label → predict

All of §7 follows `vendor/haste/docs/usage/rapid-building-assessment.md`.

### 7a. Embed

Click **Embed**. In the **New Embedding** dialog:

| Field | Options / default | What to pick |
|---|---|---|
| Embedding backbone | **MOSAIKS** (random convolutional features) or **DINOv2** (ViT-S/14, ViT-B/14). "MOSAIKS is the lightweight default." | **MOSAIKS** — see caution below |
| Output dimensions | features per building, MOSAIKS only, default **1024** | leave at 1024 |
| Resize factor | crop upscale around each footprint, default **4** for MOSAIKS | leave at 4 |
| Batch size | buildings per batch; code default **16** (`hastelib/src/hastegeo/core/processors/embedding.py`, `_create_embedding_config`) | lower it to 8 if you hit OOM |

⚠️ **Use MOSAIKS, not DINOv2.** The source is ambiguous about whether DINOv2 weights are
available in the local image. `hastelib/src/hastegeo/workflows/embed_buildings.py` has a
DINOv2 wrapper that loads via `torch.hub` from a pre-baked cache at
`/opt/torch-hub-cache/hub`, but a section comment in the same file reads "DINO path dropped,
no weights in image". I could not resolve that from the files, so do not spend hackathon
time on it — see §10.4.

The job produces, per `hastelib/src/hastegeo/core/config.py:99-102` and
`processors/embedding.py`:

- `building_embeddings_<modelId>.geojson` — footprints + `f_*` feature columns, one row per
  footprint, **in row-index order** (that ordering matters in §8)
- `building_pmtiles_<modelId>.pmtiles` — vector tiles for fast map display (geometry + id)
- `building_features_<modelId>.bin` — binary sidecar, id → feature vector

Watch it:

```bash
docker compose -f docker/docker-compose.yml logs -f hastefuncqueues
docker ps -a --filter ancestor=haste-training:latest
docker logs -f <container_id>
```

**✅ Gate 7a:** an **embedding row** appears with an **Interactive Label** button.

### 7b. Label interactively

Click **Interactive Label**.

- **Left-click** a building to label it with the selected class; **right-click** removes a
  label. **Ctrl+drag** (Cmd+drag on macOS) box-selects and labels many at once.
- Classes: **Intact** (green), **Damaged** (red), **Cloudy** (purple, for obscured
  buildings). Unlabeled is gray.
- Shortcuts: `1`/`2`/`3` pick a class, `T` cycles, `P` toggles Labeled/Predicted view,
  `Space` shows/hides footprints.
- Footprints are only visible at **zoom 15 and closer**.

Once you have labeled **at least 3 buildings across 2+ classes**, an in-browser logistic
regression (WebGPU-accelerated when available) trains automatically and predicts every
building in view. The panel shows holdout **precision / recall / F1 for the Damaged class**.

HASTE's own labeling advice, worth following since our whole damage layer rests on it:

- Label a **diverse** set (varied roofs, colours, damage severity), not many similar ones.
- Use **Cloudy** for cloud-obscured buildings so they are excluded from scoring.
- Watch the Damaged-class F1; if recall is low, add more damaged examples **before**
  running Predict all.

### 7c. Predict all buildings

Three buttons, per the docs:

- **Save labels** — persists manual labels only, no prediction.
- **Predict all buildings** — trains on all labels, scores **every** building, saves a
  predictions layer (GeoPackage). **This is the one that unlocks our export.**
- **Clear labels** — destroys labels including the saved copy. Cannot be undone.

⚠️ Labels and predictions are tied to **a specific embedding**. If you re-embed, you must
re-open the new embedding row; old labels won't apply.

**✅ Gate 7c:** the dialog reports "Predicted N buildings and saved."

### 7d. Validate a sample (do this — it is our accuracy number)

Open **Building Validation** for the layer. It loads a random sample of footprints (**~200
by default**) with pre/post imagery. Label each **Damaged**, **Not Damaged**, or
**Unknown** (`1`/`2`/`3`; arrow keys move Prev/Next). **Save Labels**, and **Download
GeoJSON** to keep the labeled sample.

These human labels are the ground truth the reports score against; **Unknown** is excluded
from metrics.

Then, from the embedding row's **Reports** menu:

- **Validation Report** — overall accuracy, per-class precision/recall/F1, macro-F1,
  confusion matrix.
- **Assessment Report** — total / scored / cloud-excluded counts, count and % predicted
  damaged, and an estimate of **total damaged buildings with a 95% confidence interval**,
  plus a precision–recall curve.

Screenshot both. They are the honest provenance for every number our console displays.

---

## 8. Export and convert to `damage_layer.geojson`

### 8a. Download the artifacts

From the **embedding row → Results** menu:

- **Download Geopackage (`.gpkg`)** — the per-building predictions. Only offered once
  `Predict all buildings` has run (`ui/src/Components/ProjectManagement/EmbeddingModelRow.jsx`
  gates it on `model.gpkgUrl`).

From the image layer's **⋯ (more actions)** menu (`docs/usage/image-layers.md`
§ "Download layer data"):

- **Download Building Footprints** — the footprints actually used.
- **Download Valid Area Mask** — the area actually covered by the imagery. **Take this
  one.** `hastelib/src/hastegeo/workflows/prepare_imagery.py:317` describes it as the AOI
  polygon GeoJSON. It is how our verifier knows "we imaged here and saw nothing", which is
  what makes a SUSPECT ruling defensible instead of a guess.

Drop all of it in `data/raw/haste/` in our repo (gitignored), then commit only the converted
outputs.

### 8b. What is actually inside the predictions GeoPackage

Read from `vendor/haste/api/hastefuncapi/function_app.py`, `PutBuildingPredictions` →
`_build_predictions_gpkg`:

| Column | Type | Meaning |
|---|---|---|
| `id` | int | **Row index into the layer's footprints file**, 0…N-1. The join key. |
| `damaged` | int | **0 or 1.** Hard class, not a probability. |
| `damage_pct_0m` | float | `float(damaged)` — a mirror of the same 0/1, present because the report code expects the column. Carries **no extra information**. |
| `unknown_pct` | float | 1.0 if the building was predicted **Cloudy**, else 0.0. |
| `area` | float | Footprint area in **m²**, computed via `EPSG:6933` (equal-area). |
| `geometry` | Polygon | Copied from the footprints file, which HASTE has already reprojected to **EPSG:4326**. |

Layer name inside the GeoPackage: **`predictions`**. File name:
`building_predictions_<modelId>.gpkg`.

### 8c. ⚠️ The one thing that changes our fusion design

**HASTE does not export a per-building damage probability.** The in-browser model *has*
one — `ui/src/Components/InteractiveLabeler/interactiveModel.js:80` defines `predictProba`
— but the predict-all path thresholds it to a class before saving:
`ui/src/Components/InteractiveLabeler/InteractiveLabeler.jsx` builds the payload as
`damaged: cls === CLASS_DAMAGED ? 1 : 0`, and the endpoint's own docstring says "The
in-browser model predicts `damaged` (0/1) for every building."

So our continuous damage signal **must be built by aggregation** — damaged-building count
and damaged-area fraction per grid cell — not read off individual buildings. See
`DECISIONS.md` D-004. Do not let anyone plumb a fake per-building confidence into the
contract.

### 8d. Convert

`.gpkg` → GeoJSON. Quickest, if you have GDAL:

```bash
ogr2ogr -f GeoJSON -t_srs EPSG:4326 \
  data/raw/haste/predictions.geojson \
  data/raw/haste/building_predictions_<modelId>.gpkg predictions
```

Then map it onto our contract with the pipeline converter. **This exists and is tested**
(round-tripped against a HASTE-shaped input; output validates against the contract):

```bash
cd pipeline
PYTHONPATH=src ./.venv/bin/python -m groundtruth.haste_to_damage_layer \
  --predictions ../data/raw/haste/building_predictions_<modelId>.gpkg \
  --valid-area  ../data/raw/haste/valid_area_mask.geojson \
  --event-id    bangladesh-flooding22 \
  --haste-commit 7d80be7 --backbone mosaiks \
  --imagery-note "Maxar Open Data <collection id>, captured <date>" \
  --labels-total <N> --validation-sample-n 200 \
  --damaged-precision <p> --damaged-recall <r> --damaged-f1 <f1> \
  --out ../data/processed/damage_layer.geojson
```

`.gpkg` input needs geopandas (`./.venv/bin/pip install geopandas`). To skip that heavy
dependency, do the `ogr2ogr` dump above and pass the `.geojson` instead — the stdlib path
handles it and produces identical output.

**If you omit the accuracy flags the layer is marked UNVALIDATED and the console displays
that.** Fill them from the Validation Report (§7d) once you have run Building Validation.
Do not guess them to make the UI look finished.

The converter's job, per `contracts/damage_layer.schema.json`:

1. Read layer `predictions`, assert CRS is EPSG:4326 (reproject if not).
2. Rename `id` → `building_id`, `damaged` → `damage_class` (`0`→`intact`, `1`→`damaged`),
   `unknown_pct` → `obscured` (bool), keep `area_m2`.
3. **Drop `damage_pct_0m`** — it is a duplicate of `damaged` (§8b) and keeping it invites
   someone to mistake it for a confidence score.
4. Stamp provenance on the FeatureCollection: HASTE commit, backbone, label count, the
   Damaged-class F1 from the Validation Report, and the export timestamp.
5. Emit the valid-area polygon alongside as `data/processed/valid_area.geojson` — the
   verifier needs it for spatial-consistency checks.

Do not hand-edit the output. If the shape is wrong, fix the converter.

**✅ Gate 8:** `data/processed/damage_layer.geojson` validates against
`contracts/damage_layer.schema.json`. This validator **does** exist today:

```bash
cd pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m groundtruth.validate_contracts
```

---

## 9. Traps and troubleshooting

The four **critical traps**, verbatim in substance from `QUICKSTART.md` §8 (sourced from
HASTE's `AGENTS.md`):

1. **`data-init` re-seeds on every full `up`** and re-uploads `project_stats.json` with
   empty defaults, wiping the dashboard's project list. When recreating a single service use
   `--no-deps`. If stats were wiped:
   `curl http://localhost:7071/api/GenerateProjectStats`.
2. **nginx caches the `hastefuncapi` upstream IP at startup.** After recreating
   `hastefuncapi`, `/api/*` starts 404-ing — always follow with
   `docker compose -f docker/docker-compose.yml restart api-proxy`.
3. **The docker-socket GID must match the host** or `hastefuncqueues` cannot spawn
   training/imageryprep containers. That is `DOCKER_GID` from §2.
4. **Project/volume/network names are folder-derived** — `docker_default` and
   `docker_azurite-data`, hard-referenced in `HASTE_DOCKER_NETWORK` /
   `HASTE_DOCKER_AZURITE_VOLUME`. If you run compose with `-p <name>` or from a renamed
   folder, update both or spawned jobs cannot reach Azurite.

Symptom table, condensed from `QUICKSTART.md` §9 and `docker/README.md`
§ "Troubleshooting", with our 16 GB additions:

| Symptom | Cause | Fix |
|---|---|---|
| Embed job "killed by signal" / OOM | shared memory or RAM too small | Raise `HASTE_DOCKER_SHM_SIZE` / `HASTE_DOCKER_MEM_LIMIT`; **and** lower the embedding **batch size** to 8 and shrink the AOI. At 16 GB, shrinking the AOI is the lever that actually works. |
| `up -d` unexpectedly builds `haste-training` | `hastefuncqueues depends_on training_image` | Expected for us — we need that image (§0). |
| `/api/*` returns 404 after a recreate | nginx cached old upstream IP | `restart api-proxy` (Trap 2) |
| API 500s | Azurite wasn't ready at startup | `restart hastefuncapi` |
| `/api/GetAdminSettings` refuses connection | `hastefuncapi` down / Azurite not ready | `logs --tail=200 hastefuncapi`, restart it |
| Imagery URL rejected at layer creation | host not on the allowlist | §6a — download and upload the file instead |
| Embed/training job never starts | `DOCKER_GID` mismatch, socket perms | Recompute `DOCKER_GID` (§2), recreate `hastefuncqueues` (Trap 3) |
| Spawned job "no such network/volume" | compose project-name prefix mismatch | Fix `HASTE_DOCKER_NETWORK` / `HASTE_DOCKER_AZURITE_VOLUME` (Trap 4) |
| Dashboard lost its projects | `data-init` re-seeded stats | `curl http://localhost:7071/api/GenerateProjectStats` (Trap 1) |
| TiTiler 502 / tiles blank | proxy stale or titiler down | `ps titiler`; `curl localhost:8000/healthz`; `restart api-proxy` |
| Footprints don't respond to labeling, or look stale | layer needs re-embedding | Re-run **Embed**, open the new embedding row |
| UI stuck in login loop | stale `ui` image | Rebuild and recreate only `ui`; confirm **User's roles** includes `administrators` |
| Visualizer inert / no map | `VITE_AZURE_MAPS_CLIENT_ID` unset | Harmless for us — we do not use HASTE's Visualizer |

Lifecycle commands (`QUICKSTART.md` §7):

```bash
C="docker compose -f docker/docker-compose.yml"
$C up -d
$C down                  # stop, keep data
$C down -v               # stop, WIPE all Azurite data
$C logs -f <service>
$C up -d --no-deps --force-recreate --build hastefuncapi && $C restart api-proxy
```

**Once you have a good export, `$C down` — do not `down -v`.** `-v` wipes Azurite, and your
labels live there.

---

## 10. What the HASTE files do NOT answer

Open questions. Settle them by running the thing, not by asking an AI to recall them.

1. **The exact Maxar `bangladesh-flooding22` asset URLs.** Nothing in `vendor/haste`
   mentions this event; the repo's only Maxar sample is a Lahaina scene hosted on
   `opendata.aiforgood.ai` (which the allowlist rejects, §6a). You must find the real S3
   URLs yourself from Maxar's Open Data STAC catalog, confirm the host ends in
   `.amazonaws.com`, and confirm the assets are COG `.tif`. Verify by `curl -I` on one URL
   before pasting it into HASTE.
2. **Whether 16 GB is actually enough end-to-end.** HASTE documents a 32 GB minimum and no
   16 GB tuning row. Unknown until you run it. Have a fallback: if the embed will not
   complete, shrink the AOI until it does, and say so in the demo.
3. **Overture Maps footprint coverage and quality over Sylhet.** The docs say footprints are
   fetched from Overture automatically; they say nothing about coverage in rural Bangladesh.
   Check the footprint count after preprocessing. If it is implausibly low, that is when the
   custom-`.gpkg` path (§6d) earns its cost.
4. **Whether DINOv2 works in the local image.** The source contradicts itself (§7a). Not
   worth resolving for the MVP — use MOSAIKS.
5. **How long embedding takes for N buildings on CPU.** No benchmark in the repo. Time your
   first run and write the number here.
6. **Whether the Standard workflow's wall-to-wall raster would give us a flood-extent
   polygon.** It produces a continuous damage raster exported as a GeoPackage
   (`docs/usage/damage-mapping.md`), which is *closer* to a flood extent than building points
   — but it needs a training job we cannot afford on this hardware. Out of scope for the
   MVP; noted in `DECISIONS.md` D-005 in case a GPU appears.

When you answer one of these, edit this file. This runbook is the team's shared memory of
what is actually true.
