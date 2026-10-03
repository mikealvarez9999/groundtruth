"""Convert a Sentinel-1 SAR flood/building join into our damage_layer contract.

This is the SAR sibling of ``haste_to_damage_layer.py``. It exists because the
damage-layer contract is deliberately *sensor-agnostic*: a building's damage
class can come from HASTE optical OR from Sentinel-1 SAR flood analysis, and the
fusion engine downstream never has to know which. Only the provenance block
differs, and this script fills it in honestly -- it never claims HASTE ran.

    PYTHONPATH=src python -m groundtruth.sentinel1_to_damage_layer \
        --buildings ../data/raw/sentinel1/sylhet_buildings_flood.geojson \
        --bbox 91.81 24.85 91.95 24.98 \
        --classifier-ref "mitchellthomas1/S1-Flood-Bangladesh@<commit>" \
        --target-window 2022-06-16 2022-06-23 \
        --baseline-window 2021-05-01 2021-10-01 \
        --footprint-confidence-min 0.75 \
        --flood-threshold 0.5 \
        --out ../data/raw/sentinel1/damage_layer.geojson

INPUT: a GeoJSON FeatureCollection of building footprints (EPSG:4326), each
carrying the fraction of its footprint that fell inside the SAR flood mask. This
is exactly what Earth Engine's ``flood.reduceRegions(buildings, Reducer.mean())``
exports -- the fraction lands in a property named ``mean`` (override with
--flood-prop). Google Open Buildings also ships ``confidence`` and
``area_in_meters``, both of which we carry through.

FIELD MAPPING:
    <enumeration index>        -> properties.building_id
    mean >= --flood-threshold  -> properties.damage_class ("damaged" | "intact")
    (SAR sees through cloud)    -> properties.obscured = false, always
    area_in_meters             -> properties.area_m2  (null if absent)
    geometry                   -> geometry (asserted EPSG:4326, not reprojected)

No `accuracy` block is written: there is no human-validated ground-truth sample
for the SAR flood map, so the layer is honestly marked UNVALIDATED rather than
carrying an invented F1. The console displays that state.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import grid

CONTRACT_VERSION = "1.0.0"


# Placeholders that look like a citation but name nothing reproducible. The
# shipped layer once carried "S1-Flood-Bangladesh@<commit>", which reads like
# provenance and is not: nobody can rebuild the assessment from it. The HASTE
# branch of the schema already REQUIRES a real haste_commit for the same reason;
# this is the SAR-side equivalent, enforced at write time so a placeholder can
# never reach an artifact again.
_REF_PLACEHOLDERS = re.compile(r"<[^>]*>|\b(?:commit|todo|tbd|xxx|fixme|unknown)\b", re.I)


def _check_ref(value: str | None, flag: str) -> None:
    """Fail loudly if a provenance reference is a placeholder, not a citation."""
    if not value:
        return
    if _REF_PLACEHOLDERS.search(value):
        sys.exit(
            f"--{flag} looks like a placeholder, not a real reference:\n"
            f"  {value!r}\n"
            "A damage layer whose classifier cannot be re-run is not evidence (D-009).\n"
            "Pass the real pinned identifier, e.g. owner/repo@<40-char-sha>."
        )


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


def _valid_area(bbox: tuple[float, float, float, float], event_id: str, note: str) -> dict:
    w, s, e, n = bbox
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"event_id": event_id, "note": note},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
            },
        }],
    }


def convert(features: list[dict], args: argparse.Namespace) -> dict:
    out_features: list[dict] = []
    damaged_total = 0
    missing_flood = 0

    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            continue

        # Flooded fraction of this footprint. Absent (sub-pixel building with no
        # covered pixel) is treated as 0.0 -- i.e. not flooded -- and counted so
        # we can report how many defaulted.
        raw = props.get(args.flood_prop)
        if raw is None:
            missing_flood += 1
            flooded_fraction = 0.0
        else:
            try:
                flooded_fraction = float(raw)
            except (TypeError, ValueError):
                missing_flood += 1
                flooded_fraction = 0.0

        damaged = flooded_fraction >= args.flood_threshold
        damage_class = "damaged" if damaged else "intact"
        if damaged:
            damaged_total += 1

        # Open Buildings ships area_in_meters; carry it if present.
        area = props.get("area_in_meters", props.get("area_m2"))
        try:
            area_m2 = round(float(area), 1) if area is not None else None
        except (TypeError, ValueError):
            area_m2 = None

        properties: dict = {
            "building_id": index,
            "damage_class": damage_class,
            # SAR penetrates cloud: there is nothing it "could not see". Always false.
            "obscured": False,
            "area_m2": area_m2,
        }
        centre = _centroid(geometry)
        if centre:
            properties["grid_cell_id"] = grid.cell_id(*centre)

        out_features.append({
            "type": "Feature",
            "id": index,
            "geometry": geometry,
            "properties": properties,
        })

    if missing_flood:
        print(
            f"note: {missing_flood} building(s) had no '{args.flood_prop}' value "
            f"(typically sub-pixel footprints) and were treated as not-flooded."
        )

    source: dict = {
        "tool": "sentinel1_sar",
        "sensor": args.sensor,
        "classifier": args.classifier,
        "footprint_source": args.footprint_source,
        "flood_fraction_threshold": args.flood_threshold,
    }
    if args.classifier_ref:
        source["classifier_ref"] = args.classifier_ref
    if args.baseline_window:
        source["baseline_window"] = list(args.baseline_window)
    if args.target_window:
        source["target_window"] = list(args.target_window)
    if args.footprint_confidence_min is not None:
        source["footprint_confidence_min"] = args.footprint_confidence_min
    if args.imagery_note:
        source["imagery_note"] = args.imagery_note

    groundtruth: dict = {
        "contract_version": CONTRACT_VERSION,
        "event_id": args.event_id,
        "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        "crs": "EPSG:4326",
        "source": source,
        "counts": {
            "buildings_total": len(out_features),
            "buildings_damaged": damaged_total,
            "buildings_obscured": 0,  # SAR: nothing is obscured
        },
    }
    print(
        "NOTE: no ground-truth validation sample exists for the SAR flood map, so\n"
        "  this layer is honestly marked UNVALIDATED (no accuracy block). The console\n"
        "  displays that. It is not an F1 we are hiding; it is one we have not measured."
    )
    if args.notes:
        groundtruth["notes"] = args.notes

    return {
        "type": "FeatureCollection",
        "groundtruth": groundtruth,
        "features": out_features,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--buildings", required=True, type=Path,
                    help="GeoJSON of building footprints, each with a flooded-fraction property")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--event-id", default="bangladesh-flooding22")
    ap.add_argument("--flood-prop", default="mean",
                    help="Property holding the flooded fraction 0..1 (reduceRegions mean). Default: mean")
    ap.add_argument("--flood-threshold", type=float, default=0.5,
                    help="A building is 'damaged' when this fraction of its footprint is flooded")

    prov = ap.add_argument_group("provenance (truthful SAR metadata)")
    prov.add_argument("--sensor", default="Sentinel-1 C-band SAR (GRD, IW mode, VV+VH)")
    prov.add_argument("--classifier",
                      default="VV+VH z-score anomaly vs seasonal baseline + raw-VH threshold, spatially smoothed")
    prov.add_argument("--classifier-ref", default=None,
                      help="repo@commit of the flood classifier, e.g. mitchellthomas1/S1-Flood-Bangladesh@<commit>")
    prov.add_argument("--baseline-window", nargs=2, default=None, metavar=("START", "END"))
    prov.add_argument("--target-window", nargs=2, default=None, metavar=("START", "END"))
    prov.add_argument("--footprint-source", default="google_open_buildings_v3")
    prov.add_argument("--footprint-confidence-min", type=float, default=None)
    prov.add_argument("--imagery-note", default=None)
    prov.add_argument("--notes", default=None)

    va = ap.add_argument_group("valid area (imagery footprint)")
    va.add_argument("--bbox", nargs=4, type=float, default=None,
                    metavar=("W", "S", "E", "N"),
                    help="AOI bbox; writes valid_area.geojson next to --out")
    va.add_argument("--valid-area", type=Path, default=None,
                    help="Existing valid-area GeoJSON to copy next to --out instead of --bbox")

    args = ap.parse_args()

    if not args.buildings.is_file():
        sys.exit(f"not found: {args.buildings}")

    # Refuse to write provenance that names nothing reproducible.
    _check_ref(args.classifier_ref, "classifier-ref")
    _check_ref(args.footprint_source, "footprint-source")

    features = _read_geojson(args.buildings)
    print(f"read {len(features)} building feature(s) from {args.buildings.name}")
    payload = convert(features, args)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")

    counts = payload["groundtruth"]["counts"]
    total = counts["buildings_total"]
    dmg = counts["buildings_damaged"]
    pct = (100.0 * dmg / total) if total else 0.0
    print(f"wrote {args.out}: {total} buildings, {dmg} damaged ({pct:.1f}%), 0 obscured")

    # Valid area: the imagery footprint the verifier uses to tell 'assessed' from
    # 'never looked'. Without it, claims outside coverage risk being called suspect.
    target = args.out.parent / "valid_area.geojson"
    if args.valid_area:
        if not args.valid_area.is_file():
            print(f"WARNING: --valid-area {args.valid_area} not found; valid_area.geojson NOT written.")
        else:
            target.write_text(args.valid_area.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"copied valid-area mask -> {target}")
    elif args.bbox:
        note = (
            "Sentinel-1 SAR assessment footprint (AOI). Claims outside this polygon "
            "are NO_COVERAGE and must never be tiered suspect."
        )
        with target.open("w", encoding="utf-8") as fh:
            json.dump(_valid_area(tuple(args.bbox), args.event_id, note), fh, ensure_ascii=False, indent=1)
            fh.write("\n")
        print(f"wrote valid-area footprint -> {target}")
    else:
        print(
            "WARNING: neither --bbox nor --valid-area supplied. Without the imagery\n"
            "  footprint the verifier cannot tell 'assessed and clear' from 'never\n"
            "  looked', and claims outside coverage risk being called suspect."
        )

    print("\nNow validate:  PYTHONPATH=src python -m groundtruth.validate_contracts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
