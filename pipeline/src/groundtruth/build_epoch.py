"""Build one dated SAR epoch and file it under /data/.../epochs/<slug>/.

The before/after story: run the same pipeline on two Sentinel-1 date windows
(e.g. a pre-peak pass and the 16-22 June peak) and let the console toggle
between them. Each epoch is a full artifact set produced by the REAL pipeline --
nothing is interpolated or invented between dates.

    PYTHONPATH=src python -m groundtruth.build_epoch \
        --slug 2022-06-06 --label "<=10 JUN - PRE-PEAK" \
        --damage ../data/raw/sentinel1/damage_layer_pre.geojson \
        --valid-area ../data/raw/sentinel1/valid_area.geojson

What it does:
 1. stages the given damage layer + valid area into data/raw/sentinel1/
    (the path build_all auto-detects),
 2. runs build_all (extract -> geocode -> verify -> fuse -> validate),
 3. copies the four artifacts into data/processed/epochs/<slug>/ and
    console/public/data/epochs/<slug>/,
 4. updates epochs/index.json; the LAST epoch built becomes the default, and the
    root /data artifacts hold that same epoch -- so build the pre-peak epoch
    first and the peak epoch last.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .build_all import (
    CONSOLE_DATA_SUBDIR,
    PROCESSED_SUBDIR,
    SENTINEL1_SUBDIR,
    main as build_main,
    repo_root,
)

ARTIFACTS = [
    "damage_layer.geojson",
    "valid_area.geojson",
    "signals.seed.json",
    "sector_scores.json",
]


def _stage(src: Path, dest: Path, *, allow_same: bool) -> None:
    """Copy an epoch input into the staging path build_all reads.

    Staging OVERWRITES dest on every epoch build, so dest may hold a previous
    epoch's data. Passing dest itself as the damage source therefore silently
    rebuilds from stale data (this happened; it labelled a pre-peak layer as the
    peak). For --damage that is now a hard error. --valid-area may legitimately
    be the staged copy, since the footprint is identical across passes of one AOI.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest.resolve():
        if allow_same:
            return
        sys.exit(
            f"--damage must not be the staging path itself ({dest}).\n"
            "  Every epoch build overwrites that file, so it may hold a PREVIOUS\n"
            "  epoch's data. Keep each epoch's layer under its own name (e.g.\n"
            "  damage_layer_pre.geojson, damage_layer_peak.geojson) and pass that."
        )
    shutil.copyfile(src, dest)


def _update_index(index_path: Path, slug: str, label: str) -> None:
    index = {"default": None, "epochs": []}
    if index_path.is_file():
        with index_path.open(encoding="utf-8") as fh:
            index = json.load(fh)
    index["epochs"] = [e for e in index.get("epochs", []) if e.get("slug") != slug]
    index["epochs"].append({"slug": slug, "label": label})
    # Last built wins as default: it is what the root /data artifacts now hold.
    index["default"] = slug
    with index_path.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--slug", required=True,
                    help="Directory-safe id, e.g. 2022-06-06. Date-like slugs keep epochs sorted.")
    ap.add_argument("--label", required=True,
                    help='Short UI label, e.g. "<=10 JUN - PRE-PEAK"')
    ap.add_argument("--damage", required=True, type=Path,
                    help="Epoch damage_layer.geojson (from sentinel1_to_damage_layer)")
    ap.add_argument("--valid-area", required=True, type=Path)
    args = ap.parse_args()

    for p in (args.damage, args.valid_area):
        if not p.is_file():
            sys.exit(f"not found: {p}")
    if "/" in args.slug or "\\" in args.slug:
        sys.exit(f"--slug must be a plain directory name, got {args.slug!r}")

    root = repo_root()
    raw = root / SENTINEL1_SUBDIR

    # 1. stage this epoch's inputs where build_all auto-detects them
    _stage(args.damage, raw / "damage_layer.geojson", allow_same=False)
    _stage(args.valid_area, raw / "valid_area.geojson", allow_same=True)

    # Echo what was actually staged, so a wrong-layer mistake is visible before
    # the build output scrolls by.
    with args.damage.open(encoding="utf-8") as fh:
        staged_counts = json.load(fh).get("groundtruth", {}).get("counts", {})
    print(
        f"staging epoch {args.slug!r}: "
        f"{staged_counts.get('buildings_total', '?')} buildings, "
        f"{staged_counts.get('buildings_damaged', '?')} damaged "
        f"(from {args.damage.name})"
    )

    # 2. full pipeline run (build_all parses sys.argv for validate; keep it clean)
    sys.argv = ["build_all"]
    rc = build_main()
    if rc:
        print(f"\nbuild_all failed (rc={rc}); epoch {args.slug!r} NOT filed.")
        return rc

    # 3+4. file the artifacts under epochs/<slug>/ in both output trees
    for base in (root / PROCESSED_SUBDIR, root / CONSOLE_DATA_SUBDIR):
        epoch_dir = base / "epochs" / args.slug
        epoch_dir.mkdir(parents=True, exist_ok=True)
        for name in ARTIFACTS:
            shutil.copyfile(root / PROCESSED_SUBDIR / name, epoch_dir / name)
        _update_index(base / "epochs" / "index.json", args.slug, args.label)

    print("-" * 68)
    print(f"epoch {args.slug!r} ({args.label}) filed under epochs/ in both trees.")
    print("Build order matters: build the PEAK epoch last so it is the default view.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
