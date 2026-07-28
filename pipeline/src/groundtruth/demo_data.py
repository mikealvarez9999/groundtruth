"""Synthetic demo data for the 2022 Sylhet flood scenario.

⚠️  EVERYTHING IN THIS FILE IS SYNTHETIC. ⚠️

The kickoff calls for ~200 real archived posts and a real HASTE damage export.
Neither has been collected. So that the console can be built and demonstrated,
this module fabricates:

  1. a building damage layer (HASTE-shaped, but generated, not assessed)
  2. an imagery valid-area polygon
  3. ~50 citizen reports in Bangla / Banglish / English, 10 of them planted fakes

The place names are real Sylhet-region names and the coordinates are roughly
right. Nothing else is. No building in here was ever looked at by a satellite,
and the damage percentages are invented.

Replace this file with real data before anyone outside the team sees the
console. Every artifact it writes carries a ``notes`` / ``provenance_note``
field saying it is synthetic; do not strip those.

The scenario is designed to exercise every verification path on purpose:
  - Kanaighat / Companiganj : heavy damage + multiple independent reports -> CORROBORATED, top of queue
  - Zindabazar / Ambarkhana : assessed and undamaged -> flood claims here are CONTRADICTED -> SUSPECT
  - Derai / Sunamganj       : outside the imagery footprint -> NO_COVERAGE -> PLAUSIBLE-UNVERIFIED + recon flag
  - Bishwanath              : three near-identical posts from ONE source -> must NOT reach corroborated
  - two exaggerated-scale and one out-of-region fake we openly do NOT catch
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from . import grid

EVENT_ID = "bangladesh-flooding22"

# Demo timeline anchor. The real 2022 Sylhet floods peaked mid-June 2022;
# using a real-ish date makes the replay read correctly on screen.
EVENT_START = datetime(2022, 6, 18, 6, 0, 0, tzinfo=timezone.utc)

# Seeded PRNG: the committed artifacts must be byte-stable across runs.
RNG_SEED = 20220618

# The area our (pretend) Maxar scene covers. Anything outside this polygon is
# NOT assessed, and a claim there can never be called suspect.
VALID_AREA_BBOX = (91.60, 24.65, 92.45, 25.25)  # west, south, east, north


# name, lon, lat, building_count, damaged_fraction
# Urban Sylhet城 sits on higher ground and is deliberately undamaged so the
# planted "city submerged" fakes have something to contradict them.
DAMAGE_CLUSTERS: tuple[tuple[str, float, float, int, float], ...] = (
    ("Kanaighat",     92.2597, 25.0158, 260, 0.62),
    ("Companiganj",   91.6500, 25.0500, 210, 0.55),
    ("Gowainghat",    91.7333, 25.0833, 190, 0.41),
    ("Jaintiapur",    92.1167, 25.1333, 160, 0.36),
    ("Zakiganj",      92.3667, 24.9167, 150, 0.28),
    ("Beanibazar",    92.1667, 24.8167, 140, 0.19),
    ("Golapganj",     92.0000, 24.8333, 130, 0.14),
    ("Sarighat",      91.8900, 25.0200, 110, 0.33),
    ("Fenchuganj",    91.9333, 24.6833, 120, 0.11),
    ("Balaganj",      91.8000, 24.7167, 120, 0.16),
    ("Bishwanath",    91.7500, 24.7500, 115, 0.05),
    ("Osmani Nagar",  91.8500, 24.7500, 100, 0.07),
    ("Dakshin Surma", 91.8720, 24.8611, 150, 0.04),
    ("Zindabazar",    91.8681, 24.8955, 180, 0.00),
    ("Ambarkhana",    91.8712, 24.9042, 160, 0.00),
    ("Sylhet Sadar",  91.8687, 24.8949, 170, 0.01),
)

# Roughly 3% of footprints come back cloud-obscured, as they would in reality.
OBSCURED_RATE = 0.03


# (offset_minutes, source_id, author_ref, text, eval_or_None)
#
# eval is the planted-fake ground truth. It is written into the artifact but
# MUST NOT be read by extract/geocode/verify/fuse (DECISIONS.md D-010) --
# build_all strips it before those stages run.
SEED_POSTS: tuple[tuple[int, str, str, str, dict | None], ...] = (
    # ---- Kanaighat: four independent sources -> CORROBORATED ----
    (12, "src_arch_0091", "reporter_91",
     "Kanaighat er dike pani onek beshi, 3 ta ghor er chal porjonto dube gese. Nouka lagbe.", None),
    (26, "src_arch_0104", "reporter_104",
     "কানাইঘাটে ৭ জন মানুষ ছাদে আটকে আছে, জরুরি উদ্ধার দরকার।", None),
    (41, "src_arch_0117", "reporter_117",
     "Konaighat bazar area te rasta puro bondho, jogajog bichchinno hoye geche.", None),
    (58, "src_arch_0122", "reporter_122",
     "kanighat e nouka pathan, manush atke ache, taratari please.", None),
    (95, "src_arch_0140", "reporter_140",
     "Kanaighat e khabar ar khaowar pani shesh, tran dorkar.", None),

    # ---- Companiganj: three independent sources ----
    (19, "src_arch_0098", "reporter_98",
     "Companiganj e ghor bhenge poresi, bonna pani barche druto.", None),
    (34, "src_arch_0109", "reporter_109",
     "কোম্পানীগঞ্জে অনেক ঘর ডুবে গেছে, পানি বাড়ছে।", None),
    (67, "src_arch_0129", "reporter_129",
     "Kompaniganj e 15 jon atke ache, bachao, ekhuni help lagbe.", None),

    # ---- Gowainghat ----
    (23, "src_arch_0101", "reporter_101",
     "Gowainghat e pani tolie geche, khabar nai amader.", None),
    (52, "src_arch_0119", "reporter_119",
     "গোয়াইনঘাটে সড়ক যোগাযোগ বিচ্ছিন্ন, দ্রুত ব্যবস্থা নিন।", None),
    (88, "src_arch_0136", "reporter_136",
     "Goainghat e bidyut nai, current nai 2 din.", None),

    # ---- Jaintiapur ----
    (31, "src_arch_0107", "reporter_107",
     "Jaintiapur e pani dube geche onek ghor.", None),
    (77, "src_arch_0132", "reporter_132",
     "জৈন্তাপুরে ১২ জন আশ্রয়কেন্দ্রে উঠেছে, খাবার দরকার।", None),

    # ---- Jaflong / Tamabil ----
    (44, "src_arch_0113", "reporter_113",
     "Jaflong zero point e pani onek, rasta bondho.", None),
    (102, "src_arch_0145", "reporter_145",
     "তামাবিলে বন্যার পানি ঢুকেছে।", None),

    # ---- Zakiganj ----
    (37, "src_arch_0111", "reporter_111",
     "Zakiganj e ghor dhose poresi, ahoto manush ache, doctor lagbe.", None),
    (91, "src_arch_0138", "reporter_138",
     "জকিগঞ্জে পানি কমে নামছে এখন।", None),

    # ---- Beanibazar ----
    (48, "src_arch_0115", "reporter_115",
     "Beani Bazar e pani dhukche ghor e, poribar 6 jon.", None),
    (110, "src_arch_0149", "reporter_149",
     "বিয়ানীবাজারে ত্রাণ পৌঁছায়নি এখনো।", None),

    # ---- single-source reports -> PLAUSIBLE-UNVERIFIED, recon priority ----
    (55, "src_arch_0121", "reporter_121",
     "Golapganj e rasta bondho hoye ache gari jaite pare na.", None),
    (63, "src_arch_0126", "reporter_126",
     "Fenchugonj e pani barche, nodi er pani upore.", None),
    (71, "src_arch_0130", "reporter_130",
     "Balagonj e ghor e pani, osud shesh hoye gese.", None),
    (84, "src_arch_0134", "reporter_134",
     "ওসমানীনগরে বিদ্যুৎ নেই, পানি বাড়ছে।", None),
    (99, "src_arch_0142", "reporter_142",
     "Sarighat e nouka lagbe, 9 jon atke ache chal e.", None),
    (116, "src_arch_0151", "reporter_151",
     "Dakshin Surma te rasta te pani, jogajog somossa.", None),
    (121, "src_arch_0153", "reporter_153",
     "Chatak e pani onek barche, ghor dube jacche.", None),
    (128, "src_arch_0156", "reporter_156",
     "ছাতকে ১৮ জন আটকে আছে, নৌকা পাঠান জরুরি।", None),
    (134, "src_arch_0158", "reporter_158",
     "Surma nodi er pani bipod shimar upore.", None),

    # ---- outside the imagery footprint -> NO_COVERAGE, never suspect ----
    (29, "src_arch_0105", "reporter_105",
     "Derai te puro elaka plabito, ghor bari sob pani te.", None),
    (73, "src_arch_0131", "reporter_131",
     "দিরাইয়ে ২২ জন মানুষ আটকে আছে, সাহায্য দরকার।", None),
    (59, "src_arch_0124", "reporter_124",
     "Sunamganj sadar e pani onek, khabar nai.", None),
    (107, "src_arch_0147", "reporter_147",
     "সুনামগঞ্জে রাস্তা ভেঙে গেছে, যোগাযোগ বিচ্ছিন্ন।", None),
    (118, "src_arch_0152", "reporter_152",
     "Doarabazar e bonna, manush ashroy kendro te.", None),
    (125, "src_arch_0155", "reporter_155",
     "Jagannathpur e pani barche druto, nouka dorkar.", None),

    # ---- more inside-coverage volume ----
    (15, "src_arch_0094", "reporter_94",
     "Sylhet e bonna pani rasta te uthe geche kotha kotha.", None),
    (81, "src_arch_0133", "reporter_133",
     "Jaintapur e school e ashroy niyeche onek poribar.", None),
    (93, "src_arch_0139", "reporter_139",
     "Kompaniganj e setu er kaj kora rasta bhenge geche.", None),
    (104, "src_arch_0146", "reporter_146",
     "কানাইঘাটে ঔষধ আর ডাক্তার দরকার, অনেক আহত।", None),
    (112, "src_arch_0150", "reporter_150",
     "Zakiganj e khaowar pani nai, tran lagbe.", None),
    (131, "src_arch_0157", "reporter_157",
     "Gowainghat e 4 ti baccha atke ache, urgent.", None),

    # ================= PLANTED FAKES (10) =================
    # Kind A: contradicts our own imagery. These we DO expect to catch.
    (46, "src_fake_301", "reporter_301",
     "Zindabazar puro dube gese, sob building er chal porjonto pani. Bachao!",
     {"planted_fake": True, "fake_kind": "contradicts_imagery",
      "expected_tier": "suspect",
      "provenance_note": "SYNTHETIC planted fake. Claims total inundation in an assessed, undamaged cell."}),
    (61, "src_fake_302", "reporter_302",
     "জিন্দাবাজারে সব ঘর ডুবে গেছে, কেউ বাঁচেনি।",
     {"planted_fake": True, "fake_kind": "contradicts_imagery",
      "expected_tier": "suspect",
      "provenance_note": "SYNTHETIC. Second DISTINCT source making the same false claim -- tests that spatial contradiction overrides corroboration."}),
    (69, "src_fake_303", "reporter_303",
     "Ambarkhana e pani chal porjonto uthe gese, 200 jon atke.",
     {"planted_fake": True, "fake_kind": "contradicts_imagery",
      "expected_tier": "suspect",
      "provenance_note": "SYNTHETIC. Assessed cell with zero damaged buildings."}),
    (86, "src_fake_304", "reporter_304",
     "Puro Sylhet sadar dube gese, kono building nai ar.",
     {"planted_fake": True, "fake_kind": "contradicts_imagery",
      "expected_tier": "suspect",
      "provenance_note": "SYNTHETIC. Assessed urban cell, ~1% damage."}),

    # Kind B: astroturf. One source, three near-identical posts, in a cell with
    # no other reporting. Tests that corroboration counts DISTINCT sources.
    (50, "src_fake_777", "reporter_777",
     "Bishwanath e voyonkor bonna, sob ghor bhenge gese, urgent help!",
     {"planted_fake": True, "fake_kind": "duplicate_astroturf",
      "expected_tier": "plausible_unverified",
      "provenance_note": "SYNTHETIC astroturf 1/3 from one source. Must NOT be promoted to corroborated."}),
    (53, "src_fake_777", "reporter_777",
     "Bishwanath e voyonkor bonna, sob ghor bhenge gelo, urgent help lagbe!",
     {"planted_fake": True, "fake_kind": "duplicate_astroturf",
      "expected_tier": "plausible_unverified",
      "provenance_note": "SYNTHETIC astroturf 2/3 from the same source_id."}),
    (57, "src_fake_777", "reporter_777",
     "Bishwanath e bonna voyonkor, ghor sob bhenge gese, help urgent!",
     {"planted_fake": True, "fake_kind": "duplicate_astroturf",
      "expected_tier": "plausible_unverified",
      "provenance_note": "SYNTHETIC astroturf 3/3 from the same source_id."}),

    # Kind C: exaggerated scale. We do NOT claim to catch these -- our
    # verifier has no population model. Listed so the gap is measured, not hidden.
    (75, "src_fake_401", "reporter_401",
     "Golapganj e 50000 jon manush atke ache ekhuni bachao.",
     {"planted_fake": True, "fake_kind": "exaggerated_scale",
      "expected_tier": "plausible_unverified",
      "provenance_note": "SYNTHETIC. Implausible count. Our verifier does NOT detect scale exaggeration; the number is dropped only by a sanity ceiling in extract.py."}),
    (97, "src_fake_402", "reporter_402",
     "Beanibazar e 90000 manush pani te atke, sob mara jacche.",
     {"planted_fake": True, "fake_kind": "exaggerated_scale",
      "expected_tier": "corroborated",
      "provenance_note": (
          "SYNTHETIC. A WORSE outcome than fake_401 and the expectation is set to "
          "'corroborated' because that is genuinely what our method produces, not "
          "because we are matching the test to the code. Beanibazar has an "
          "independent genuine report of flooding, so this claim's location and "
          "event group ARE corroborated -- and the exaggerated casualty count rides "
          "along and inherits full fusion weight. Corroboration cannot detect scale "
          "exaggeration; we have no population model. This is the most important "
          "known weakness in the verifier: a wildly inflated claim in a genuinely "
          "affected area is indistinguishable from a truthful one."
      )}),

    # Kind D: out of region entirely -> ungeocodable, cannot be mapped.
    (114, "src_fake_501", "reporter_501",
     "Dhaka Mirpur e bonna pani, sob dube gese, nouka lagbe.",
     {"planted_fake": True, "fake_kind": "impossible_location",
      "expected_tier": "plausible_unverified",
      "provenance_note": "SYNTHETIC. Outside the Sylhet gazetteer, so geo resolves to null and the signal cannot be placed on the map."}),
)


def valid_area_geojson() -> dict:
    """The imagery footprint polygon, HASTE's 'valid area mask' equivalent."""
    w, s, e, n = VALID_AREA_BBOX
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "event_id": EVENT_ID,
                "note": (
                    "SYNTHETIC imagery footprint. Stands in for HASTE's exported "
                    "valid-area mask. Claims outside this polygon are NO_COVERAGE "
                    "and must never be tiered suspect."
                ),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
            },
        }],
    }


def _building_polygon(lon: float, lat: float, size_m: float) -> list:
    """A small axis-aligned rectangle standing in for a footprint."""
    dlat = size_m / 111_320.0
    dlon = size_m / (111_320.0 * 0.9)  # cos(24.9 deg) ~= 0.907
    return [[
        [round(lon - dlon / 2, 7), round(lat - dlat / 2, 7)],
        [round(lon + dlon / 2, 7), round(lat - dlat / 2, 7)],
        [round(lon + dlon / 2, 7), round(lat + dlat / 2, 7)],
        [round(lon - dlon / 2, 7), round(lat + dlat / 2, 7)],
        [round(lon - dlon / 2, 7), round(lat - dlat / 2, 7)],
    ]]


def damage_layer_geojson() -> dict:
    """Generate a HASTE-shaped damage layer. Synthetic; see module docstring."""
    rng = random.Random(RNG_SEED)
    features: list[dict] = []
    bid = 0
    damaged_total = 0
    obscured_total = 0

    for name, clon, clat, count, frac in DAMAGE_CLUSTERS:
        for _ in range(count):
            # Scatter within ~1.6 km of the cluster centre.
            lon = clon + rng.uniform(-0.008, 0.008)
            lat = clat + rng.uniform(-0.0072, 0.0072)
            obscured = rng.random() < OBSCURED_RATE
            # Obscured buildings are excluded from scoring, so they are never
            # labelled damaged -- absence of damage there means "could not see".
            damaged = (not obscured) and (rng.random() < frac)
            size = rng.uniform(6.0, 16.0)
            area = round(size * size * rng.uniform(0.8, 1.3), 1)

            if damaged:
                damaged_total += 1
            if obscured:
                obscured_total += 1

            features.append({
                "type": "Feature",
                "id": bid,
                "geometry": {
                    "type": "Polygon",
                    "coordinates": _building_polygon(lon, lat, size),
                },
                "properties": {
                    "building_id": bid,
                    "damage_class": "damaged" if damaged else "intact",
                    "obscured": obscured,
                    "area_m2": area,
                    "grid_cell_id": grid.cell_id(lon, lat),
                },
            })
            bid += 1

    return {
        "type": "FeatureCollection",
        "groundtruth": {
            "contract_version": "1.0.0",
            "event_id": EVENT_ID,
            "generated_at": EVENT_START.isoformat().replace("+00:00", "Z"),
            "crs": "EPSG:4326",
            "source": {
                "tool": "haste",
                "haste_commit": "0000000",
                "workflow": "building",
                "backbone": "mosaiks",
                "num_features": 1024,
                "resize_factor": 4,
                "footprint_source": "overture",
                "imagery_note": (
                    "SYNTHETIC. No imagery was assessed. haste_commit is zeroed "
                    "deliberately so this can never be mistaken for a real run."
                ),
            },
            "counts": {
                "buildings_total": len(features),
                "buildings_damaged": damaged_total,
                "buildings_obscured": obscured_total,
            },
            "notes": (
                "SYNTHETIC DEMO DATA generated by pipeline/src/groundtruth/demo_data.py. "
                "Place names and approximate coordinates are real; all damage labels are "
                "fabricated. The 'accuracy' block is deliberately ABSENT because nothing "
                "here was validated -- do not add invented accuracy numbers to make the "
                "UI look complete."
            ),
        },
        "features": features,
    }


def seed_posts() -> list[dict]:
    """The raw citizen-report corpus, pre-extraction."""
    out: list[dict] = []
    for offset_min, source_id, author_ref, text, ev in SEED_POSTS:
        received = EVENT_START + timedelta(minutes=offset_min)
        row = {
            "source_id": source_id,
            "author_ref": author_ref,
            "platform": "archived_post",
            "text": text,
            "received_at": received.isoformat().replace("+00:00", "Z"),
            "replay_offset_s": offset_min * 60,
        }
        if ev is not None:
            row["eval"] = dict(ev)
        else:
            row["eval"] = {
                "planted_fake": False,
                "provenance_note": (
                    "SYNTHETIC report written for the demo. Not a real archived post."
                ),
            }
        out.append(row)
    return out
