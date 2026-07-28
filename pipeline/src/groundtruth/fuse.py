"""Fusion: damage layer + signals -> ranked grid cells.

The scoring rule, stated plainly because the contract does not pin it
(sector_score.schema.json records the weights but not the formula):

    damage_component  = (damaged + P*base_rate) / (assessed + P)
        i.e. the observed damaged fraction (obscured buildings excluded) shrunk
        toward the layer-wide base rate, or None when the cell holds too few
        assessed buildings to say anything. See the guards below -- this is the
        difference between a ranked queue and a list of rounding artifacts.
        ``evidence.damaged_fraction`` reports the RAW observed fraction; the
        score uses the shrunk one. Both are in the output on purpose.
    citizen_component = 1 - exp(-load / SATURATION)
        where load = sum over the cell's signals of
                     fusion_weight * urgency_multiplier
    vlm_component     = None in this build -- no VLM findings exist yet

    score_raw = sum(weight * component) over the components we HAVE, divided by
                the total of ALL weights. A missing channel contributes zero.
    score     = score_raw / max(score_raw) across cells  -> 0..1

We deliberately do NOT renormalise over the available channels. An earlier
version did, and it rewarded missing data: a cell with two citizen reports and
no imagery scored a perfect 1.0 and outranked a neighbourhood where 66% of 29
assessed buildings were destroyed, purely because it had less evidence. Breadth
of independent evidence should raise confidence, not lower the bar.

The cost of that choice, stated plainly: a cell OUTSIDE the imagery footprint can
never score as highly as one inside it, however many people report from there.
That is a real bias against unimaged areas -- exactly the places most likely to be
cut off. Mitigations: ``coverage.status`` is in every cell, ``recon_priority`` is
on every single-source signal, and the console surfaces unassessed-but-reported
cells as their own category rather than letting the score bury them. If you would
rather weight human reports higher, that is D-012 and it is your call.

Note also that ``vlm`` is null for every cell in this build (Channel 2 is not
implemented), so its 0.20 weight is currently dead. It lowers every cell equally
and therefore cancels out in the normalisation -- harmless, but do not read a
score of 0.8 as "80% of the worst possible".

Two consequences worth saying out loud:

  * ``score`` is normalised per file. It is meaningful only against its
    siblings. Never compare a score across runs or events.
  * ``verification.fusion_weight`` already contains the tier multiplier, so this
    module does NOT re-apply ``weights.tier_multipliers``. Those are written into
    the output as a record of what was used, not as a second multiplication.
    Double-applying them would quietly square the penalty on unverified signals.

The saturation curve exists so that the tenth corroborated report in a cell adds
less than the second. Ten reports means "definitely here", not "ten times worse
than one report".
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from . import grid
from .geocode import nearest_place

CONTRACT_VERSION = "1.0.0"

# Channel weights. Placeholders pending sign-off (DECISIONS.md D-012).
WEIGHTS = {
    "damage": 0.45,
    "vlm": 0.20,
    "citizen": 0.35,
}

TIER_MULTIPLIERS = {
    "corroborated": 1.0,
    "plausible_unverified": 0.45,
    "suspect": 0.0,
}

URGENCY_MULTIPLIERS = {
    "critical": 1.0,
    "high": 0.75,
    "medium": 0.5,
    "low": 0.25,
}

# Citizen load at which the component reaches ~63% of its ceiling.
SATURATION = 1.6

# --- sample-size guards on the damage component -------------------------------
# Without these, a cell holding ONE assessed building that happens to be damaged
# scores a perfect 1.0 and outranks a neighbourhood with 60% of 200 buildings
# destroyed. That is not a hypothetical: it is what the first run of this module
# actually produced, and it would have put a rounding artifact at the top of a
# list telling responders where to go first.
#
# Two guards:
#   1. Fewer than MIN_ASSESSED_FOR_DAMAGE buildings -> no damage component at
#      all (None). We do not have a sample; saying nothing beats guessing.
#   2. Above that, shrink the observed fraction toward the layer-wide base rate
#      with a prior worth SHRINKAGE_PRIOR pseudo-observations. A cell needs real
#      volume to pull away from the average.
MIN_ASSESSED_FOR_DAMAGE = 10
SHRINKAGE_PRIOR = 15.0

# Cells with neither a usable damage sample nor any signal are dropped from the
# output entirely -- they carry no information and would bury the queue in noise.
MIN_ASSESSED_TO_EMIT = 5


def _fmt_pct(n: int, d: int) -> str:
    return f"{round(100.0 * n / d)}%" if d else "n/a"


def fuse(
    damage_layer: dict,
    signals: list[dict],
    valid_area: dict,
    event_id: str,
) -> dict:
    """Produce the sector_score artifact."""
    from .verify import point_in_valid_area

    # ---- aggregate the damage layer per cell -------------------------------
    cells: dict[str, dict] = {}

    def blank(cid: str) -> dict:
        lon, lat = grid.cell_centroid(cid)
        return {
            "cell_id": cid,
            "centroid": {"lon": round(lon, 6), "lat": round(lat, 6)},
            "bbox": [round(v, 6) for v in grid.cell_bbox(cid)],
            "buildings_total": 0,
            "buildings_damaged": 0,
            "buildings_obscured": 0,
            "damaged_area_m2": 0.0,
            "signals": [],
        }

    for feature in damage_layer.get("features", []):
        props = feature.get("properties") or {}
        cid = props.get("grid_cell_id")
        if not cid:
            geom = feature.get("geometry") or {}
            ring = (geom.get("coordinates") or [[]])[0]
            if not ring:
                continue
            lon = sum(p[0] for p in ring) / len(ring)
            lat = sum(p[1] for p in ring) / len(ring)
            cid = grid.cell_id(lon, lat)

        cell = cells.setdefault(cid, blank(cid))
        cell["buildings_total"] += 1
        if props.get("obscured"):
            cell["buildings_obscured"] += 1
        elif props.get("damage_class") == "damaged":
            cell["buildings_damaged"] += 1
            cell["damaged_area_m2"] += float(props.get("area_m2") or 0.0)

    # ---- attach signals ----------------------------------------------------
    for signal in signals:
        geo = signal.get("geo")
        if not geo:
            continue  # unmappable: counted nowhere, still present in signals.json
        cid = geo["grid_cell_id"]
        cells.setdefault(cid, blank(cid))["signals"].append(signal)

    # Layer-wide damaged rate, used as the shrinkage prior. Computed from the
    # aggregated cells so it matches exactly what we scored.
    total_assessed = sum(
        c["buildings_total"] - c["buildings_obscured"] for c in cells.values()
    )
    total_damaged = sum(c["buildings_damaged"] for c in cells.values())
    base_rate = (total_damaged / total_assessed) if total_assessed else 0.0

    # ---- score every cell -------------------------------------------------
    out_cells: list[dict] = []
    for cid, cell in cells.items():
        assessed = cell["buildings_total"] - cell["buildings_obscured"]
        damaged = cell["buildings_damaged"]

        # Observed fraction is reported as-is in evidence; the SCORE uses the
        # shrunk value so small cells cannot spike. See the guards above.
        if assessed >= MIN_ASSESSED_FOR_DAMAGE:
            damage_component = (damaged + SHRINKAGE_PRIOR * base_rate) / (
                assessed + SHRINKAGE_PRIOR
            )
        else:
            damage_component = None

        # Drop no-information cells: too few buildings to say anything AND
        # nobody reported anything here.
        if assessed < MIN_ASSESSED_TO_EMIT and not cell["signals"]:
            continue

        load = 0.0
        corroborated = plausible = suspect = 0
        sources: set[str] = set()
        urgencies: list[str] = []
        persons = 0
        persons_seen = False

        for signal in cell["signals"]:
            tier = signal["verification"]["tier"]
            if tier == "corroborated":
                corroborated += 1
            elif tier == "plausible_unverified":
                plausible += 1
            else:
                suspect += 1

            sources.add(signal["source"]["source_id"])

            weight = signal["verification"]["fusion_weight"]
            urgency = signal["claim"]["urgency"]
            load += weight * URGENCY_MULTIPLIERS[urgency]

            if tier != "suspect":
                urgencies.append(urgency)
                n = signal["claim"].get("persons_at_risk")
                if isinstance(n, int):
                    persons += n
                    persons_seen = True

        citizen_component = (
            round(1.0 - math.exp(-load / SATURATION), 6) if cell["signals"] else None
        )
        vlm_component = None  # Channel 2 not implemented in this build

        parts = [
            (WEIGHTS["damage"], damage_component),
            (WEIGHTS["vlm"], vlm_component),
            (WEIGHTS["citizen"], citizen_component),
        ]
        # Denominator is the total of ALL weights, not just the available ones,
        # so a missing channel costs the cell its share instead of being
        # papered over. See the module docstring.
        all_w = sum(w for w, _ in parts)
        score_raw = (
            sum(w * v for w, v in parts if v is not None) / all_w if all_w > 0 else 0.0
        )

        centroid = cell["centroid"]
        in_valid = point_in_valid_area(centroid["lon"], centroid["lat"], valid_area)
        if not in_valid:
            coverage_status = "unassessed"
        elif cell["buildings_obscured"] > 0.15 * max(cell["buildings_total"], 1):
            coverage_status = "partial"
        elif assessed > 0:
            coverage_status = "assessed"
        else:
            coverage_status = "unassessed"

        # ---- reasons: counts only, no generated prose --------------------
        reasons: list[str] = []
        if assessed >= MIN_ASSESSED_FOR_DAMAGE:
            reasons.append(
                f"{_fmt_pct(damaged, assessed)} of {assessed} assessed buildings damaged"
            )
        elif assessed > 0:
            reasons.append(
                f"Only {assessed} assessed building(s) here - too few to score damage"
            )
        if corroborated:
            reasons.append(
                f"{corroborated} corroborated report(s) from {len(sources)} distinct source(s)"
            )
        if plausible:
            reasons.append(f"{plausible} single-source report(s) - recon priority")
        if suspect:
            reasons.append(f"{suspect} suspect report(s) withheld - see Audit Drawer")
        if cell["buildings_obscured"]:
            reasons.append(
                f"{cell['buildings_obscured']} building(s) cloud-obscured; damage likely undercounted"
            )
        if coverage_status == "unassessed" and cell["signals"]:
            reasons.append(
                "No imagery coverage here - reports cannot be confirmed or refuted, "
                "and this cell's score is capped as a result"
            )

        out_cells.append({
            "cell_id": cid,
            "centroid": centroid,
            "bbox": cell["bbox"],
            "score": round(score_raw, 6),  # renormalised below
            "components": {
                "damage": round(damage_component, 6) if damage_component is not None else None,
                "vlm": vlm_component,
                "citizen": citizen_component,
            },
            "coverage": {
                "in_valid_area": in_valid,
                "buildings_obscured": cell["buildings_obscured"],
                "status": coverage_status,
            },
            "evidence": {
                "buildings_total": cell["buildings_total"],
                "buildings_damaged": damaged,
                "damaged_fraction": round(damaged / assessed, 6) if assessed else None,
                "damaged_area_m2": round(cell["damaged_area_m2"], 1) if assessed else None,
                "signal_ids": [s["signal_id"] for s in cell["signals"]],
                "corroborated_count": corroborated,
                "plausible_unverified_count": plausible,
                "suspect_count": suspect,
                "distinct_source_count": len(sources),
                "vlm_finding_ids": [],
            },
            "urgency_max": (
                min(urgencies, key=lambda u: list(URGENCY_MULTIPLIERS).index(u))
                if urgencies else None
            ),
            "persons_at_risk_est": persons if persons_seen else None,
            "top_reasons": reasons[:4],
            "place_label": nearest_place(centroid["lon"], centroid["lat"]),
            "updated_at": datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
        })

    # ---- normalise to 0..1 and rank ---------------------------------------
    peak = max((c["score"] for c in out_cells), default=0.0)
    if peak > 0:
        for c in out_cells:
            c["score"] = round(c["score"] / peak, 6)

    out_cells.sort(key=lambda c: (-c["score"], c["cell_id"]))
    for i, c in enumerate(out_cells, start=1):
        c["rank"] = i

    return {
        "contract_version": CONTRACT_VERSION,
        "event_id": event_id,
        "generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        "grid": {"cell_size_m": grid.CELL_SIZE_M, "scheme": grid.SCHEME},
        "weights": {
            **WEIGHTS,
            "tier_multipliers": TIER_MULTIPLIERS,
            "urgency_multipliers": URGENCY_MULTIPLIERS,
        },
        "cells": out_cells,
    }
