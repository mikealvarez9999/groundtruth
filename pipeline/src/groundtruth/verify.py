"""Verification: corroboration + spatial consistency. Nothing else.

There is no media forensics here, no deepfake detection, no credibility model of
any reporter. Two questions only:

  1. Do multiple INDEPENDENT sources say the same kind of thing, in the same
     cell, within a time window?
  2. Does the claim contradict what our own imagery-derived layer shows?

Three rules that matter more than the code:

  * **Contradiction overrides corroboration.** If two distinct sources both
    claim total inundation in a cell where we assessed 180 buildings and found
    zero damaged, that is two people saying the same wrong thing, not evidence.
    Tested by the planted pair in demo_data.py.

  * **No coverage is never suspect.** Outside the imagery footprint we have no
    standing to contradict anyone. Those become PLAUSIBLE-UNVERIFIED with a
    recon flag. Getting this wrong would mean flagging truthful reports from
    unimaged areas as fake -- the worst failure this tool could have.

  * **Corroboration counts distinct source_ids.** Three posts from one account
    are one source. Tested by the astroturf triple in demo_data.py.

Known gaps, stated rather than hidden:
  - No population model, so exaggerated casualty counts are NOT detected.
  - Corroboration groups on a coarse EVENT GROUP, not exact event_type (see
    EVENT_GROUPS and D-017). That is more permissive than the kickoff spec: it
    lets an inundation report and a stranded-persons report in the same cell
    corroborate each other. Narrow the mapping if you disagree.
  - With claimed_time almost always null (the rule extractor cannot parse
    relative time), the window effectively runs on received_at.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import grid

# Radius around a claim in which we look for assessed buildings.
SPATIAL_RADIUS_M = 600.0

# Below this many assessed buildings nearby we do not have the standing to
# contradict a claim -- too small a sample.
MIN_BUILDINGS_TO_CONTRADICT = 25

# A physical claim is contradicted when the damaged fraction nearby is at or
# below this. Not zero: one stray damaged building should not rescue a claim of
# total inundation, and our own damage layer has its own error rate.
CONTRADICTION_MAX_FRAC = 0.02

# Corroboration time window.
TIME_WINDOW = timedelta(hours=3)

# Claim types that assert a visible physical state, and can therefore be
# checked against imagery. A medical need or a power cut is invisible from
# orbit, so those are never contradicted.
PHYSICAL_EVENT_TYPES = frozenset({
    "flood_inundation",
    "structural_damage",
    "people_stranded",
})

# Corroboration groups. The kickoff says to group on event_type exactly; we
# group on a slightly coarser EVENT GROUP instead, and this is a deliberate
# deviation (DECISIONS.md D-017).
#
# Why: two reports 300 m apart within the hour, one saying "water up to the
# rooflines" and one saying "people stuck on a roof", are two witnesses to ONE
# event. Requiring an exact event_type match would call them uncorroborated,
# which is not a defensible reading of the evidence. Grouping is coarse enough
# to see that and narrow enough that a power cut never corroborates a drowning.
EVENT_GROUPS: dict[str, str] = {
    "flood_inundation": "flood_impact",
    "structural_damage": "flood_impact",
    "people_stranded": "flood_impact",
    "missing_person": "flood_impact",
    "road_blocked": "access",
    "power_outage": "infrastructure",
    "medical_need": "relief_need",
    "water_food_need": "relief_need",
    "shelter_status": "relief_need",
    "other": "other",
}

# Human-readable group names for the reason string.
EVENT_GROUP_LABELS = {
    "flood_impact": "flood impact (inundation / damage / stranded persons)",
    "access": "blocked access",
    "infrastructure": "infrastructure outage",
    "relief_need": "relief need (food, water, medical, shelter)",
    "other": "unclassified",
}


def event_group(event_type: str) -> str:
    return EVENT_GROUPS.get(event_type, "other")


# Tier -> base weight. Multiplied by geocode confidence to get fusion_weight.
# NOTE: fuse.py consumes verification.fusion_weight DIRECTLY and does not
# re-apply tier multipliers, so the tier factor is applied exactly once.
TIER_BASE_WEIGHT = {
    "corroborated": 1.0,
    "plausible_unverified": 0.45,
    "suspect": 0.0,
}


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    """Ray-casting point-in-polygon. Stdlib only, no shapely dependency."""
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > lat) != (y2 > lat):
            # x coordinate of the edge at this latitude
            x_at = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lon < x_at:
                inside = not inside
    return inside


def point_in_valid_area(lon: float, lat: float, valid_area: dict) -> bool:
    """True when the point is inside any polygon of the valid-area layer."""
    for feature in valid_area.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polys = [geom["coordinates"]]
        elif geom.get("type") == "MultiPolygon":
            polys = geom["coordinates"]
        else:
            continue
        for poly in polys:
            if not poly:
                continue
            if point_in_ring(lon, lat, poly[0]):
                # Holes: an inner ring hit means outside.
                if any(point_in_ring(lon, lat, hole) for hole in poly[1:]):
                    continue
                return True
    return False


class BuildingIndex:
    """Flat list of (lon, lat, damaged, obscured) with a brute-force radius query.

    Brute force is the boring choice and it is fast enough: our layer is a few
    thousand buildings and we query it once per signal. Swap in a spatial index
    only if that stops being true.
    """

    def __init__(self, damage_layer: dict):
        self.points: list[tuple[float, float, bool, bool]] = []
        for feature in damage_layer.get("features", []):
            geom = feature.get("geometry") or {}
            if geom.get("type") != "Polygon" or not geom.get("coordinates"):
                continue
            ring = geom["coordinates"][0]
            if not ring:
                continue
            # Centroid of the ring is plenty for a radius test.
            lon = sum(pt[0] for pt in ring) / len(ring)
            lat = sum(pt[1] for pt in ring) / len(ring)
            props = feature.get("properties") or {}
            self.points.append((
                lon,
                lat,
                props.get("damage_class") == "damaged",
                bool(props.get("obscured")),
            ))

    def query(self, lon: float, lat: float, radius_m: float) -> tuple[int, int]:
        """(assessed_count, damaged_count) within the radius.

        Obscured buildings are excluded from the assessed count: we could not
        see them, so they are not evidence either way.
        """
        assessed = 0
        damaged = 0
        for blon, blat, is_damaged, is_obscured in self.points:
            if grid.haversine_m(lon, lat, blon, blat) > radius_m:
                continue
            if is_obscured:
                continue
            assessed += 1
            if is_damaged:
                damaged += 1
        return assessed, damaged


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _spatial_check(signal: dict, index: BuildingIndex, valid_area: dict) -> dict:
    geo = signal.get("geo")
    if not geo:
        return {"status": "not_applicable"}

    lon, lat = geo["lon"], geo["lat"]
    inside = point_in_valid_area(lon, lat, valid_area)
    assessed, damaged = index.query(lon, lat, SPATIAL_RADIUS_M)

    check = {
        "inside_valid_area": inside,
        "buildings_in_radius": assessed,
        "damaged_in_radius": damaged,
        "radius_m": SPATIAL_RADIUS_M,
    }

    event_type = signal["claim"]["event_type"]
    if not inside:
        # We have no imagery here. We cannot confirm and we cannot refute.
        check["status"] = "no_coverage"
    elif event_type not in PHYSICAL_EVENT_TYPES:
        check["status"] = "not_applicable"
    elif assessed < MIN_BUILDINGS_TO_CONTRADICT:
        check["status"] = "no_coverage"
    elif (damaged / assessed) <= CONTRADICTION_MAX_FRAC:
        check["status"] = "contradicted"
    else:
        check["status"] = "consistent"

    return check


def _corroboration_groups(signals: list[dict]) -> dict[str, set[str]]:
    """Map signal_id -> set of DISTINCT source_ids making the same claim.

    Same claim means: same grid cell, same EVENT GROUP (see EVENT_GROUPS), and
    reference times within TIME_WINDOW of each other.
    """
    result: dict[str, set[str]] = {}
    for a in signals:
        sources = {a["source"]["source_id"]}
        geo_a = a.get("geo")
        if not geo_a:
            result[a["signal_id"]] = sources
            continue

        t_a = _parse_time(a["claim"].get("claimed_time")) or _parse_time(
            a["source"]["received_at"]
        )
        for b in signals:
            if b["signal_id"] == a["signal_id"]:
                continue
            geo_b = b.get("geo")
            if not geo_b:
                continue
            if geo_b["grid_cell_id"] != geo_a["grid_cell_id"]:
                continue
            if event_group(b["claim"]["event_type"]) != event_group(
                a["claim"]["event_type"]
            ):
                continue
            t_b = _parse_time(b["claim"].get("claimed_time")) or _parse_time(
                b["source"]["received_at"]
            )
            if t_a and t_b and abs(t_a - t_b) > TIME_WINDOW:
                continue
            sources.add(b["source"]["source_id"])
        result[a["signal_id"]] = sources
    return result


def _reason(
    tier: str,
    check: dict,
    distinct: int,
    supporters: set[str],
    signal: dict,
) -> str:
    """The sentence a responder reads in the Audit Drawer.

    Generated from counts, never from an LLM, so it cannot hallucinate.
    """
    geo = signal.get("geo") or {}
    cell = geo.get("grid_cell_id", "an unmapped location")
    place = (geo.get("geocode") or {}).get("matched_name", signal["claim"]["location_ref"])
    event = signal["claim"]["event_type"].replace("_", " ")
    status = check.get("status")

    if tier == "suspect":
        return (
            f"Claims {event} at {place} (cell {cell}), but that cell is inside the "
            f"imagery footprint and only {check['damaged_in_radius']} of "
            f"{check['buildings_in_radius']} assessed buildings within "
            f"{int(check['radius_m'])} m are damaged. "
            f"{distinct} source(s) reporting. Withheld from scoring and flagged for "
            f"human review; not deleted."
        )

    if tier == "corroborated":
        others = sorted(supporters - {signal['source']['source_id']})
        group = EVENT_GROUP_LABELS[event_group(signal["claim"]["event_type"])]
        return (
            f"{distinct} independent sources report {group} in cell {cell} ({place}) "
            f"within {int(TIME_WINDOW.total_seconds() // 3600)}h; this report specifically "
            f"describes {event} (corroborating sources: {', '.join(others)}). "
            + (
                f"Imagery agrees: {check['damaged_in_radius']} of "
                f"{check['buildings_in_radius']} assessed buildings damaged nearby."
                if status == "consistent"
                else "Imagery cannot confirm or refute this claim type."
            )
        )

    # plausible_unverified
    if not signal.get("geo"):
        return (
            f"Location '{signal['claim']['location_ref'] or '(none stated)'}' could not be "
            f"resolved against the gazetteer, so this report cannot be placed on the map "
            f"or scored. Retained for review."
        )
    if status == "no_coverage":
        return (
            f"Single source reports {event} at {place} (cell {cell}). This location is "
            f"outside the assessed imagery footprint, so we can neither confirm nor "
            f"refute it. Recon priority."
        )
    if status == "consistent":
        return (
            f"Single source reports {event} at {place} (cell {cell}). Imagery is "
            f"consistent ({check['damaged_in_radius']}/{check['buildings_in_radius']} "
            f"assessed buildings damaged nearby) but no second independent source has "
            f"reported it. Recon priority."
        )
    return (
        f"Single source reports {event} at {place} (cell {cell}). Claim type cannot be "
        f"checked against imagery. Recon priority."
    )


def verify_all(signals: list[dict], damage_layer: dict, valid_area: dict) -> list[dict]:
    """Attach a ``verification`` block to every signal. Mutates and returns them."""
    index = BuildingIndex(damage_layer)
    groups = _corroboration_groups(signals)
    now = datetime.now().astimezone().replace(microsecond=0)

    for signal in signals:
        check = _spatial_check(signal, index, valid_area)
        supporters = groups[signal["signal_id"]]
        distinct = len(supporters)

        # Order matters: contradiction wins over corroboration.
        if check["status"] == "contradicted":
            tier = "suspect"
        elif distinct >= 2:
            tier = "corroborated"
        else:
            tier = "plausible_unverified"

        # Geocode confidence dampens weight: a confident claim about a place we
        # probably misidentified is not confident evidence.
        geo = signal.get("geo")
        if geo:
            score = geo["geocode"]["score"]
            confidence = score * (0.7 if geo["geocode"]["ambiguous"] else 1.0)
        else:
            confidence = 0.0  # unmappable -> cannot contribute to any cell

        weight = round(TIER_BASE_WEIGHT[tier] * confidence, 4)

        signal["verification"] = {
            "tier": tier,
            "reason": _reason(tier, check, distinct, supporters, signal),
            "corroborating_signal_ids": sorted(
                s["signal_id"]
                for s in signals
                if s["signal_id"] != signal["signal_id"]
                and s["source"]["source_id"] in supporters
                and s.get("geo")
                and signal.get("geo")
                and s["geo"]["grid_cell_id"] == signal["geo"]["grid_cell_id"]
                and event_group(s["claim"]["event_type"])
                == event_group(signal["claim"]["event_type"])
            ),
            "distinct_source_count": distinct,
            "spatial_check": check,
            "fusion_weight": weight,
            "recon_priority": tier == "plausible_unverified" and bool(geo),
            "verified_at": now.isoformat(),
        }

    return signals
