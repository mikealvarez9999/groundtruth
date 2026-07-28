"""Build the contract's ``geo`` block from a raw location string."""

from __future__ import annotations

from . import grid
from .gazetteer import resolve


def geocode(location_ref: str) -> dict | None:
    """Resolve a place string into the ``signal.geo`` shape, or None.

    None is a legitimate outcome (unresolvable place). The caller must keep the
    signal with ``geo: null`` rather than dropping it -- an unmappable report is
    still evidence that someone reported something.
    """
    match = resolve(location_ref)
    if match is None:
        return None

    place = match.place
    return {
        "lon": place.lon,
        "lat": place.lat,
        "grid_cell_id": grid.cell_id(place.lon, place.lat),
        "geocode": {
            "method": match.method,
            "matched_name": place.name,
            "admin": place.admin,
            "score": match.score,
            "ambiguous": match.ambiguous,
            "candidates": [
                {
                    "name": p.name,
                    "admin": p.admin,
                    "score": round(s, 4),
                    "lon": p.lon,
                    "lat": p.lat,
                }
                for p, s in match.candidates
            ],
        },
    }


def nearest_place(lon: float, lat: float, max_m: float = 6000.0) -> str | None:
    """Human place label for a point, for ``sector_score.cells[].place_label``.

    Responders navigate by name, not by cell id. Returns None rather than a
    misleading far-away name when nothing is close enough.
    """
    from .gazetteer import ENTRIES

    best: tuple[str, float] | None = None
    for p in ENTRIES:
        d = grid.haversine_m(lon, lat, p.lon, p.lat)
        if best is None or d < best[1]:
            best = (p.name, d)
    if best is None or best[1] > max_m:
        return None
    return best[0]
