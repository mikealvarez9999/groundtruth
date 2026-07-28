"""The grid. Deliberately trivial arithmetic, mirrored byte-for-byte in
``console/src/lib/grid.ts``.

Why so simple: the pipeline writes cell ids into committed JSON and the browser
recomputes them live when a new signal arrives. If the two implementations
disagree by one cell, signals silently land in the wrong place and nothing
crashes to tell us. So the scheme is floor-division on degrees and nothing
else -- no projections, no libraries, no cleverness.

Caveat named honestly: cells are degree-based, so ``CELL_SIZE_M`` is converted
using a fixed reference latitude. At Sylhet's latitude the east-west error is
about 2%, which is far below our geocoding error. Do not reuse this grid for a
different part of the world without revisiting REF_LAT.
"""

from __future__ import annotations

import math

# Contract: sector_score.schema.json -> grid.cell_size_m / grid.scheme
CELL_SIZE_M = 500.0
SCHEME = "lonlat_floor"

# Metres per degree of latitude (WGS84 mean). Constant enough for our purposes.
_M_PER_DEG_LAT = 111_320.0

# Reference latitude used to size the longitude step. Sylhet sits ~24.9 N.
REF_LAT = 24.9

LAT_STEP = CELL_SIZE_M / _M_PER_DEG_LAT
LON_STEP = CELL_SIZE_M / (_M_PER_DEG_LAT * math.cos(math.radians(REF_LAT)))


def cell_index(lon: float, lat: float) -> tuple[int, int]:
    """Return the integer (ix, iy) grid indices containing a point."""
    return math.floor(lon / LON_STEP), math.floor(lat / LAT_STEP)


def cell_id(lon: float, lat: float) -> str:
    """Stable string id for the cell containing a point."""
    ix, iy = cell_index(lon, lat)
    return f"c_{ix}_{iy}"


def cell_bbox(cid: str) -> list[float]:
    """[west, south, east, north] for a cell id."""
    _, ix_s, iy_s = cid.split("_")
    ix, iy = int(ix_s), int(iy_s)
    west = ix * LON_STEP
    south = iy * LAT_STEP
    return [west, south, west + LON_STEP, south + LAT_STEP]


def cell_centroid(cid: str) -> tuple[float, float]:
    """(lon, lat) centre of a cell id."""
    west, south, east, north = cell_bbox(cid)
    return (west + east) / 2.0, (south + north) / 2.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance in metres. Used for the spatial-consistency radius."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))
