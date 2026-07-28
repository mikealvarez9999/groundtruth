"""Render a SAR flood-mask GeoTIFF into the console's per-epoch map overlay.

    PYTHONPATH=src python -m groundtruth.flood_overlay \
        --mask ../data/raw/sentinel1/flood_mask_2022-06-19.tif --slug 2022-06-19

Writes, into BOTH data/processed/epochs/<slug>/ and console/public/data/epochs/<slug>/:

    flood.png          -- RGBA image: detected floodwater in translucent cyan,
                          everything else fully transparent
    flood_bounds.json  -- {"bounds": [west, south, east, north]} taken from the
                          GeoTIFF itself, so the overlay is georeferenced by the
                          raster's real extent, not by whatever bbox we remember

The console drapes flood.png between the basemap and the sector heat, so the
floodwater that drove each building's damage_class is VISIBLE under the dots.
This is the actual classifier output -- the same mask the exposure join sampled
-- not an illustration.

Only dependency beyond the stdlib is rasterio (numpy comes with it). The PNG is
encoded with the stdlib (zlib/struct) so the pipeline gains no imaging library.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

from .build_all import CONSOLE_DATA_SUBDIR, PROCESSED_SUBDIR, repo_root

# Translucent cyan, matched to the console's water/cyan accents.
FLOOD_RGBA = (56, 189, 248, 130)
# Cap the longest PNG edge; the mask is 10 m/px and a browser does not need more.
MAX_DIM = 4096


def write_png(path: Path, rgba: bytes, width: int, height: int) -> None:
    """Minimal stdlib PNG encoder: 8-bit RGBA, no filtering."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    raw = b"".join(
        b"\x00" + rgba[y * stride : (y + 1) * stride] for y in range(height)
    )
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--mask", required=True, type=Path,
                    help="Flood-mask GeoTIFF (band 1: 1 = flood, 0 = not)")
    ap.add_argument("--slug", required=True,
                    help="Epoch slug this overlay belongs to, e.g. 2022-06-19")
    args = ap.parse_args()

    if not args.mask.is_file():
        sys.exit(f"not found: {args.mask}")
    if "/" in args.slug or "\\" in args.slug:
        sys.exit(f"--slug must be a plain directory name, got {args.slug!r}")

    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
    except ModuleNotFoundError:
        sys.exit("rasterio is required:  pip install rasterio")

    with rasterio.open(args.mask) as src:
        scale = max(1, -(-max(src.width, src.height) // MAX_DIM))  # ceil div
        out_w, out_h = src.width // scale, src.height // scale
        band = src.read(
            1, out_shape=(out_h, out_w), resampling=Resampling.nearest
        )
        b = src.bounds
        bounds = [b.left, b.bottom, b.right, b.top]

    flood = band == 1
    rgba = np.zeros((out_h, out_w, 4), dtype=np.uint8)
    rgba[flood] = FLOOD_RGBA

    root = repo_root()
    pct = 100.0 * float(flood.sum()) / flood.size if flood.size else 0.0
    for base in (root / PROCESSED_SUBDIR, root / CONSOLE_DATA_SUBDIR):
        epoch_dir = base / "epochs" / args.slug
        epoch_dir.mkdir(parents=True, exist_ok=True)
        write_png(epoch_dir / "flood.png", rgba.tobytes(), out_w, out_h)
        with (epoch_dir / "flood_bounds.json").open("w", encoding="utf-8") as fh:
            json.dump({"bounds": bounds}, fh)
            fh.write("\n")

    print(
        f"overlay for epoch {args.slug!r}: {out_w}x{out_h} px "
        f"(downsampled {scale}x), {pct:.1f}% flood pixels"
    )
    print(f"  bounds: W {bounds[0]:.4f}  S {bounds[1]:.4f}  E {bounds[2]:.4f}  N {bounds[3]:.4f}")
    print("  wrote flood.png + flood_bounds.json under epochs/ in both trees")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
