"""Convert a HASTE building-predictions export into our damage_layer contract.

    # from a GeoPackage (needs geopandas)
    python -m groundtruth.haste_to_damage_layer \
        --predictions ../data/raw/haste/building_predictions_<modelId>.gpkg \
        --valid-area  ../data/raw/haste/valid_area_mask.geojson \
        --haste-commit 7d80be7 --backbone mosaiks \
        --out ../data/processed/damage_layer.geojson

    # from a GeoJSON dump (no extra dependencies)
    ogr2ogr -f GeoJSON -t_srs EPSG:4326 preds.geojson input.gpkg predictions
    python -m groundtruth.haste_to_damage_layer --predictions preds.geojson ...

FIELD MAPPING (source: HASTE's PutBuildingPredictions -> _build_predictions_gpkg,
in api/hastefuncapi/function_app.py at commit 7d80be7):

    id            -> properties.building_id
    damaged 0/1   -> properties.damage_class  ("intact" | "damaged")
    unknown_pct   -> properties.obscured      (bool: 1.0 means Cloudy)
    area          -> properties.area_m2
    damage_pct_0m -> DROPPED. It is a literal copy of `damaged` cast to float, so
                     carrying it invites someone to read it as a confidence score.
                     There is no per-building confidence in HASTE's export.
    geometry      -> geometry (already EPSG:4326; asserted, not reprojected)

This script never invents an `accuracy` block. Fill it from HASTE's Validation and
Assessment Reports with --damaged-f1 etc., or leave it absent -- an absent accuracy
block honestly says "unvalidated", whereas a plausible-looking number does not.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import grid

CONTRACT_VERSION = "1.0.0"
PREDICTIONS_LAYER = "predictions"


def _read_gpkg(path: Path) -> list[dict]:
    """Read the predictions layer via geopandas. Optional dependency."""
    try:
        import geopandas as gpd
    except ModuleNotFoundError:
        sys.exit(
            f"{path.name} is a GeoPackage, which needs geopandas:\n"
            f"  ./.venv/bin/pip install geopandas\n"
            f"Or convert it first and pass the GeoJSON:\n"
            f"  ogr2ogr -f GeoJSON -t_srs EPSG:4326 preds.geojson {path} {PREDICTIONS_LAYER}"
        )

    gdf = gpd.read_file(path, layer=PREDICTIONS_LAYER)
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        print(
            f"note: reprojecting from EPSG:{gdf.crs.to_epsg()} to EPSG:4326 "
            f"(HASTE normally exports 4326 already)"
        )
        gdf = gdf.to_crs(epsg=4326)
    return json.loads(gdf.to_json())["features"]


def _read_geojson(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    if payload.get("type") != "FeatureCollection":
        sys.exit(f"{path} is not a GeoJSON FeatureCollection")
    return payload.get("features") or []


def _centroid(geometry: dict) -> tuple[float, float] | None:
    """Rough centroid of a (Multi)Polygon's first ring. Enough for cell binning."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None
    ring = coords[0][0] if kind == "MultiPolygon" else coords[0]
    if not ring:
        return None
    lon = sum(p[0] for p in ring) / len(ring)
    lat = sum(p[1] for p in ring) / len(ring)
    return lon, lat


def convert(features: list[dict], args: argparse.Namespace) -> dict:
    out_features: list[dict] = []
    damaged_total = 0
    obscured_total = 0
    missing_fields: set[str] = set()

    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue

        # `id` is HASTE's row index. Fall back to enumeration if absent, but say so.
        if "id" in props and props["id"] is not None:
            building_id = int(props["id"])
        else:
            missing_fields.add("id")
            building_id = index

        if "damaged" in props and props["damaged"] is not None:
            damaged = int(props["damaged"]) == 1
        else:
            missing_fields.add("damaged")
            damaged = False

        unknown = props.get("unknown_pct")
        if unknown is None:
            missing_fields.add("unknown_pct")
            obscured = False
        else:
            # HASTE writes 1.0 for Cloudy, 0.0 otherwise.
            obscured = float(unknown) >= 0.5

        area = props.get("area")
        if area is None:
            missing_fields.add("area")
            area_m2 = None
        else:
            try:
                area_m2 = round(float(area), 1)
            except (TypeError, ValueError):
                area_m2 = None

        # Obscured wins: we could not see it, so it is not an assessment either way.
        if obscured:
            damage_class = "intact"
            obscured_total += 1
        else:
            damage_class = "damaged" if damaged else "intact"
            if damaged:
                damaged_total += 1

        properties: dict = {
            "building_id": building_id,
            "damage_class": damage_class,
            "obscured": obscured,
            "area_m2": area_m2,
        }
        centre = _centroid(geometry)
        if centre:
            properties["grid_cell_id"] = grid.cell_id(*centre)

        out_features.append({
            "type": "Feature",
            "id": building_id,
            "geometry": geometry,
            "properties": properties,
        })

    if missing_fields:
        print(
            "WARNING: expected HASTE columns absent: "
            + ", ".join(sorted(missing_fields))
            + "\n  Check you exported the 'predictions' layer of the building-predictions "
              "GeoPackage, not the footprints or the validation sample."
        )

    groundtruth: dict = {
        "contract_version": CONTRACT_VERSION,
        "event_id": args.event_id,
        "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        "crs": "EPSG:4326",
        "source": {
            "tool": "haste",
            "haste_commit": args.haste_commit,
            "workflow": "building",
            "backbone": args.backbone,
            "num_features": args.num_features,
            "resize_factor": args.resize_factor,
            "footprint_source": args.footprint_source,
        },
        "counts": {
            "buildings_total": len(out_features),
            "buildings_damaged": damaged_total,
            "buildings_obscured": obscured_total,
        },
    }
    if args.imagery_note:
        groundtruth["source"]["imagery_note"] = args.imagery_note

    # Only emit `accuracy` if real measurements were supplied.
    accuracy = {
        k: v
        for k, v in {
            "labels_total": args.labels_total,
            "labels_damaged": args.labels_damaged,
            "validation_sample_n": args.validation_sample_n,
            "damaged_precision": args.damaged_precision,
            "damaged_recall": args.damaged_recall,
            "damaged_f1": args.damaged_f1,
            "overall_accuracy": args.overall_accuracy,
            "estimated_damaged_total": args.estimated_damaged_total,
        }.items()
        if v is not None
    }
    if args.estimated_damaged_ci95:
        accuracy["estimated_damaged_ci95"] = list(args.estimated_damaged_ci95)
    if accuracy:
        groundtruth["accuracy"] = accuracy
    else:
        print(
            "NOTE: no accuracy figures supplied, so the layer is marked UNVALIDATED.\n"
            "  The console will display that. Pass --damaged-f1 etc. from HASTE's\n"
            "  Validation Report once you have run Building Validation."
        )

    if args.notes:
        groundtruth["notes"] = args.notes

    return {
        "type": "FeatureCollection",
        "groundtruth": groundtruth,
        "features": out_features,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True, type=Path,
                    help="HASTE building_predictions_<modelId>.gpkg, or a GeoJSON dump of its 'predictions' layer")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--event-id", default="bangladesh-flooding22")
    ap.add_argument("--haste-commit", required=True,
                    help="Short commit of the microsoft/haste checkout that produced the export")
    ap.add_argument("--backbone", default="mosaiks",
                    choices=["mosaiks", "dinov2_vits14", "dinov2_vitb14", "dinov2_vitl14"])
    ap.add_argument("--num-features", type=int, default=1024)
    ap.add_argument("--resize-factor", type=float, default=4)
    ap.add_argument("--footprint-source", default="overture", choices=["overture", "custom_gpkg"])
    ap.add_argument("--imagery-note", default=None,
                    help="Which scene(s) this came from, e.g. Maxar collection id + capture date")
    ap.add_argument("--notes", default=None)
    ap.add_argument("--valid-area", type=Path, default=None,
                    help="HASTE valid-area mask GeoJSON; copied next to --out as valid_area.geojson")

    acc = ap.add_argument_group(
        "accuracy (from HASTE's Validation / Assessment Reports)",
        "Omit these and the layer is honestly marked unvalidated. Do not guess them.",
    )
    acc.add_argument("--labels-total", type=int, default=None)
    acc.add_argument("--labels-damaged", type=int, default=None)
    acc.add_argument("--validation-sample-n", type=int, default=None)
    acc.add_argument("--damaged-precision", type=float, default=None)
    acc.add_argument("--damaged-recall", type=float, default=None)
    acc.add_argument("--damaged-f1", type=float, default=None)
    acc.add_argument("--overall-accuracy", type=float, default=None)
    acc.add_argument("--estimated-damaged-total", type=int, default=None)
    acc.add_argument("--estimated-damaged-ci95", type=int, nargs=2, default=None,
                     metavar=("LOW", "HIGH"))

    args = ap.parse_args()

    if not args.predictions.is_file():
        sys.exit(f"not found: {args.predictions}")

    suffix = args.predictions.suffix.lower()
    if suffix == ".gpkg":
        features = _read_gpkg(args.predictions)
    elif suffix in (".geojson", ".json"):
        features = _read_geojson(args.predictions)
    else:
        sys.exit(f"unsupported input {suffix!r}; expected .gpkg or .geojson")

    print(f"read {len(features)} feature(s) from {args.predictions.name}")
    payload = convert(features, args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    counts = payload["groundtruth"]["counts"]
    print(
        f"wrote {args.out}: {counts['buildings_total']} buildings, "
        f"{counts['buildings_damaged']} damaged, {counts['buildings_obscured']} obscured"
    )

    if args.valid_area:
        if not args.valid_area.is_file():
            print(f"WARNING: --valid-area {args.valid_area} not found; skipped.")
        else:
            target = args.out.parent / "valid_area.geojson"
            target.write_text(args.valid_area.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"copied valid-area mask -> {target}")
    else:
        print(
            "WARNING: no --valid-area supplied. Without the imagery footprint the verifier\n"
            "  cannot tell 'assessed and clear' from 'never looked', and every claim outside\n"
            "  coverage risks being called suspect. Export it from the layer's ... menu."
        )

    print("\nNow validate:  PYTHONPATH=src python -m groundtruth.validate_contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
