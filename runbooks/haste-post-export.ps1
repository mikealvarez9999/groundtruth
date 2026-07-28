# runbooks/haste-post-export.ps1
#
# One-shot post-export pipeline: convert HASTE gpkg/geojson -> our damage layer
# contract, copy the valid-area mask, validate contracts, build_all, sync to the
# console's public/data/. Run from the repo root after you've dropped
#   data\raw\haste\building_predictions_myanmar.gpkg
#   data\raw\haste\valid_area_mask.geojson
# into place and recorded the Validation / Assessment Report numbers.
#
# Usage (edit the $Numbers block before running):
#   powershell -ExecutionPolicy Bypass -File runbooks\haste-post-export.ps1
#
# If fiona/geopandas fail to build on Python 3.14, the script will detect that
# and switch to the GeoJSON path: dump the gpkg with ogr2ogr first, then rerun.

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$Pipeline = Join-Path $RepoRoot "pipeline"
$RawHaste = Join-Path $RepoRoot "data\raw\haste"
$PredictionsGpkg = Join-Path $RawHaste "building_predictions_myanmar.gpkg"
$PredictionsGeo  = Join-Path $RawHaste "predictions.geojson"
$ValidArea       = Join-Path $RawHaste "valid_area_mask.geojson"
$DamageLayer     = Join-Path $RawHaste "damage_layer.geojson"

# ---- EDIT THESE BEFORE RUNNING ----
$Numbers = @{
    event_id        = "earthquake-myanmar-march-2025"
    haste_commit    = "<short commit of your HASTE checkout>"   # e.g. "7d80be7"
    backbone        = "mosaiks"
    imagery_note    = "Maxar Open Data ARD Z47-033111022013, post 2025-03-31 (pre 2025-03-23), Mandalay downtown"
    labels_total    = 0        # total manual labels you placed
    labels_damaged  = 0        # of those, how many were "Damaged"
    val_sample_n    = 200      # HASTE's Building Validation default
    damaged_p       = 0.0      # Damaged-class precision from Validation Report
    damaged_r       = 0.0      # Damaged-class recall    from Validation Report
    damaged_f1      = 0.0      # Damaged-class F1        from Validation Report
    est_damaged     = 0        # estimated total damaged, Assessment Report
    est_ci_lo       = 0        # 95% CI low
    est_ci_hi       = 0        # 95% CI high
}

if (-not (Test-Path $ValidArea)) {
    throw "missing $ValidArea — export the valid-area mask from HASTE first."
}

# Decide input format: prefer .gpkg; fall back to .geojson dump.
$UseGeojson = $false
if (-not (Test-Path $PredictionsGpkg)) {
    if (Test-Path $PredictionsGeo) {
        Write-Host "No gpkg found; using existing $PredictionsGeo (ogr2ogr dump)." -ForegroundColor Yellow
        $UseGeojson = $true
    } else {
        throw "missing $PredictionsGpkg (and no $PredictionsGeo). Export the gpkg first."
    }
}

Push-Location $Pipeline
try {
    $env:PYTHONPATH = "src"

    if (-not $UseGeojson) {
        Write-Host "[1/4] Trying gpkg read via geopandas..." -ForegroundColor Cyan
        $gpkgArgs = @(
            "-m", "groundtruth.haste_to_damage_layer",
            "--predictions", $PredictionsGpkg,
            "--valid-area",  $ValidArea,
            "--event-id",    $Numbers.event_id,
            "--haste-commit", $Numbers.haste_commit,
            "--backbone",    $Numbers.backbone,
            "--imagery-note", $Numbers.imagery_note,
            "--labels-total", $Numbers.labels_total,
            "--labels-damaged", $Numbers.labels_damaged,
            "--validation-sample-n", $Numbers.val_sample_n,
            "--damaged-precision", $Numbers.damaged_p,
            "--damaged-recall", $Numbers.damaged_r,
            "--damaged-f1", $Numbers.damaged_f1,
            "--estimated-damaged-total", $Numbers.est_damaged,
            "--estimated-damaged-ci95", $Numbers.est_ci_lo, $Numbers.est_ci_hi,
            "--out", $DamageLayer
        )
        try {
            & python @gpkgArgs
            Write-Host "[1/4] gpkg read OK." -ForegroundColor Green
        } catch {
            Write-Host "[1/4] gpkg read failed (likely fiona/geopandas won't build on 3.14)." -ForegroundColor Yellow
            Write-Host "       Falling back to ogr2ogr -> GeoJSON path." -ForegroundColor Yellow
            $UseGeojson = $true
        }
    }

    if ($UseGeojson) {
        if (-not (Test-Path $PredictionsGeo)) {
            Write-Host "[1/4] Dumping gpkg to GeoJSON with ogr2ogr..." -ForegroundColor Cyan
            ogr2ogr -f GeoJSON -t_srs EPSG:4326 $PredictionsGeo $PredictionsGpkg predictions
            if ($LASTEXITCODE -ne 0) { throw "ogr2ogr failed." }
        }
        $geoArgs = @(
            "-m", "groundtruth.haste_to_damage_layer",
            "--predictions", $PredictionsGeo,
            "--valid-area",  $ValidArea,
            "--event-id",    $Numbers.event_id,
            "--haste-commit", $Numbers.haste_commit,
            "--backbone",    $Numbers.backbone,
            "--imagery-note", $Numbers.imagery_note,
            "--labels-total", $Numbers.labels_total,
            "--labels-damaged", $Numbers.labels_damaged,
            "--validation-sample-n", $Numbers.val_sample_n,
            "--damaged-precision", $Numbers.damaged_p,
            "--damaged-recall", $Numbers.damaged_r,
            "--damaged-f1", $Numbers.damaged_f1,
            "--estimated-damaged-total", $Numbers.est_damaged,
            "--estimated-damaged-ci95", $Numbers.est_ci_lo, $Numbers.est_ci_hi,
            "--out", $DamageLayer
        )
        & python @geoArgs
        if ($LASTEXITCODE -ne 0) { throw "converter failed (GeoJSON path)." }
    }

    Write-Host ""
    Write-Host "[2/4] Running build_all (auto-detects data/raw/haste/damage_layer.geojson)..." -ForegroundColor Cyan
    & python -m groundtruth.build_all
    if ($LASTEXITCODE -ne 0) { throw "build_all failed." }

    Write-Host ""
    Write-Host "[3/4] Syncing data/processed -> console/public/data ..." -ForegroundColor Cyan
    Push-Location (Join-Path $RepoRoot "console")
    try {
        & node scripts/sync-data.mjs
        if ($LASTEXITCODE -ne 0) { throw "sync-data failed." }
    } finally {
        Pop-Location
    }

    Write-Host ""
    Write-Host "[4/4] Done. Next:  cd console; npm run dev   (camera should land on Mandalay)." -ForegroundColor Green
} finally {
    Pop-Location
}