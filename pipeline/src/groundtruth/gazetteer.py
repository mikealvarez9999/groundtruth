"""Offline place-name resolution for the Sylhet region.

WHAT THIS IS NOT: the GeoNames Bangladesh dump. That file has not been pulled
yet (DECISIONS.md D-015/D-016 territory). This is a hand-built stand-in of ~30
real Sylhet-region place names with **approximate** coordinates, carrying the
Bangla-script and Banglish spelling variants our seeded corpus actually uses.

It exists so the pipeline runs end to end today. When the real gazetteer lands,
replace ``ENTRIES`` with a loader over the GeoNames TSV and keep
``resolve()`` -- the matching logic is the part worth keeping.

Coordinates are good to roughly a kilometre: fine for a 500 m triage grid used
in a demo, NOT fine for navigating a boat. Do not present them as survey data.

Matching strategy, in order:
  1. exact match on a normalised alias  -> score 1.0, method geonames_exact
  2. fuzzy match on normalised aliases  -> difflib ratio, method geonames_fuzzy

Normalisation is where the Banglish problem actually lives: "Kanaighat",
"Konaighat", "Kanighat" and "কানাইঘাট" must all land on one entry. We fold
case, strip punctuation, collapse the vowel/consonant spellings that vary most
in romanised Bangla, and drop common suffix noise ("upazila", "bazar" when
trailing, "er dike" = "towards").
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

# Fuzzy score below this is treated as "no match" -> signal.geo stays null.
MIN_SCORE = 0.72
# If the runner-up is within this of the winner, flag the match ambiguous.
AMBIGUITY_MARGIN = 0.06


@dataclass(frozen=True)
class Place:
    name: str
    admin: str
    lon: float
    lat: float
    aliases: tuple[str, ...]


# name, admin, lon, lat, aliases (Banglish variants + Bangla script)
ENTRIES: tuple[Place, ...] = (
    Place("Sylhet Sadar", "Sylhet Division / Sylhet District", 91.8687, 24.8949,
          ("sylhet", "silet", "sylhet sadar", "সিলেট", "সিলেট সদর")),
    Place("Zindabazar", "Sylhet Division / Sylhet City", 91.8681, 24.8955,
          ("zindabazar", "jindabazar", "zinda bazar", "জিন্দাবাজার")),
    Place("Ambarkhana", "Sylhet Division / Sylhet City", 91.8712, 24.9042,
          ("ambarkhana", "amborkhana", "আম্বরখানা")),
    Place("Dakshin Surma", "Sylhet Division / Sylhet District", 91.8720, 24.8611,
          ("dakshin surma", "dokkhin surma", "south surma", "দক্ষিণ সুরমা")),
    Place("Kanaighat", "Sylhet Division / Sylhet District", 92.2597, 25.0158,
          ("kanaighat", "konaighat", "kanighat", "kanaighat upazila", "কানাইঘাট")),
    Place("Gowainghat", "Sylhet Division / Sylhet District", 91.7333, 25.0833,
          ("gowainghat", "goainghat", "gowain ghat", "গোয়াইনঘাট")),
    Place("Jaintiapur", "Sylhet Division / Sylhet District", 92.1167, 25.1333,
          ("jaintiapur", "jointapur", "jaintapur", "জৈন্তাপুর")),
    Place("Companiganj", "Sylhet Division / Sylhet District", 91.6500, 25.0500,
          ("companiganj", "kompaniganj", "companyganj", "কোম্পানীগঞ্জ")),
    Place("Zakiganj", "Sylhet Division / Sylhet District", 92.3667, 24.9167,
          ("zakiganj", "jakiganj", "zokiganj", "জকিগঞ্জ")),
    Place("Beanibazar", "Sylhet Division / Sylhet District", 92.1667, 24.8167,
          ("beanibazar", "beani bazar", "bianibazar", "বিয়ানীবাজার")),
    Place("Golapganj", "Sylhet Division / Sylhet District", 92.0000, 24.8333,
          ("golapganj", "gulapganj", "গোলাপগঞ্জ")),
    Place("Fenchuganj", "Sylhet Division / Sylhet District", 91.9333, 24.6833,
          ("fenchuganj", "fenchugonj", "ফেঞ্চুগঞ্জ")),
    Place("Balaganj", "Sylhet Division / Sylhet District", 91.8000, 24.7167,
          ("balaganj", "balagonj", "বালাগঞ্জ")),
    Place("Bishwanath", "Sylhet Division / Sylhet District", 91.7500, 24.7500,
          ("bishwanath", "biswanath", "বিশ্বনাথ")),
    Place("Osmani Nagar", "Sylhet Division / Sylhet District", 91.8500, 24.7500,
          ("osmani nagar", "osmaninagar", "ওসমানীনগর")),
    Place("Jaflong", "Sylhet Division / Gowainghat", 92.0167, 25.1667,
          ("jaflong", "jaflong zero point", "জাফলং")),
    Place("Tamabil", "Sylhet Division / Gowainghat", 92.0000, 25.1833,
          ("tamabil", "tamabil border", "তামাবিল")),
    Place("Chhatak", "Sylhet Division / Sunamganj District", 91.6667, 25.0333,
          ("chhatak", "chatak", "সাতক", "ছাতক")),
    Place("Sunamganj Sadar", "Sylhet Division / Sunamganj District", 91.4000, 25.0667,
          ("sunamganj", "sunamgonj", "সুনামগঞ্জ")),
    Place("Dowarabazar", "Sylhet Division / Sunamganj District", 91.5000, 25.1000,
          ("dowarabazar", "doarabazar", "দোয়ারাবাজার")),
    Place("Jagannathpur", "Sylhet Division / Sunamganj District", 91.5333, 24.7833,
          ("jagannathpur", "joggonnathpur", "জগন্নাথপুর")),
    Place("Derai", "Sylhet Division / Sunamganj District", 91.3167, 24.7167,
          ("derai", "dirai", "দিরাই")),
    Place("Moulvibazar Sadar", "Sylhet Division / Moulvibazar District", 91.7770, 24.4829,
          ("moulvibazar", "maulvibazar", "moulavibazar", "মৌলভীবাজার")),
    Place("Sreemangal", "Sylhet Division / Moulvibazar District", 91.7333, 24.3000,
          ("sreemangal", "srimangal", "sreemongol", "শ্রীমঙ্গল")),
    Place("Kulaura", "Sylhet Division / Moulvibazar District", 92.0333, 24.5333,
          ("kulaura", "kulawra", "কুলাউড়া")),
    Place("Habiganj Sadar", "Sylhet Division / Habiganj District", 91.4167, 24.3745,
          ("habiganj", "hobigonj", "হবিগঞ্জ")),
    Place("Nabiganj", "Sylhet Division / Habiganj District", 91.4000, 24.5333,
          ("nabiganj", "nobigonj", "নবীগঞ্জ")),
    Place("Surma River", "Sylhet Division / Sylhet District", 91.8800, 24.9100,
          ("surma", "surma nodi", "surma river", "সুরমা")),
    Place("Kushiyara River", "Sylhet Division / Sylhet District", 92.0500, 24.7500,
          ("kushiyara", "kushiara", "কুশিয়ারা")),
    Place("Sarighat", "Sylhet Division / Gowainghat", 91.8900, 25.0200,
          ("sarighat", "sari ghat", "সারিঘাট")),
)


# Romanised-Bangla spelling folds. Order matters; longest patterns first.
_FOLDS: tuple[tuple[str, str], ...] = (
    ("gonj", "ganj"),   # Fenchugonj / Fenchuganj
    ("gunj", "ganj"),
    ("jj", "j"),
    ("kk", "k"),
    ("bb", "b"),
    ("nn", "n"),
    ("tt", "t"),
    ("dd", "d"),
    ("ii", "i"),
    ("aa", "a"),
    ("oo", "u"),
    ("ou", "o"),
    ("au", "o"),
    ("ph", "f"),
    ("v", "b"),         # Banglish v/b alternation: Moulvi / Moulbi
    ("z", "j"),         # Zakiganj / Jakiganj, Zindabazar / Jindabazar
    ("w", "o"),         # Gowainghat / Goainghat
    ("y", "i"),
    ("e", "a"),         # Konaighat / Kanaighat
    ("o", "a"),
)

# Trailing noise words that carry no locational information on their own.
_STOP_SUFFIXES = ("upazila", "thana", "sadar", "area", "elaka", "dike", "er")


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def normalise(text: str) -> str:
    """Fold a place string to a comparable key.

    Bangla-script input is left alone apart from case/space handling -- the
    romanisation folds below would corrupt it, and exact alias matching handles
    the script case well enough.
    """
    text = text.strip().lower()
    # Any Bengali codepoint present -> treat as script, only tidy whitespace.
    if any("ঀ" <= ch <= "৿" for ch in text):
        return re.sub(r"\s+", " ", text)

    text = _strip_accents(text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    words = [w for w in text.split() if w]
    while words and words[-1] in _STOP_SUFFIXES:
        words.pop()
    text = "".join(words)  # spaces dropped: "beani bazar" == "beanibazar"
    for a, b in _FOLDS:
        text = text.replace(a, b)
    return text


# Precomputed lookup: normalised alias -> Place
_INDEX: dict[str, Place] = {}
for _p in ENTRIES:
    for _alias in (_p.name, *_p.aliases):
        _INDEX.setdefault(normalise(_alias), _p)


@dataclass
class Match:
    place: Place
    score: float
    method: str
    ambiguous: bool
    candidates: list[tuple[Place, float]]


def resolve(location_ref: str) -> Match | None:
    """Resolve a raw place string. Returns None when nothing scores high enough.

    Returning None is a real outcome, not a failure: the signal is kept with
    ``geo: null`` so it still shows in the Audit Drawer.
    """
    if not location_ref or not location_ref.strip():
        return None

    key = normalise(location_ref)
    if not key:
        return None

    if key in _INDEX:
        place = _INDEX[key]
        return Match(place, 1.0, "geonames_exact", False, [(place, 1.0)])

    # Fuzzy: score every alias, keep the best per place.
    best_per_place: dict[str, tuple[Place, float]] = {}
    for alias_key, place in _INDEX.items():
        score = difflib.SequenceMatcher(None, key, alias_key).ratio()
        prev = best_per_place.get(place.name)
        if prev is None or score > prev[1]:
            best_per_place[place.name] = (place, score)

    ranked = sorted(best_per_place.values(), key=lambda t: -t[1])
    if not ranked or ranked[0][1] < MIN_SCORE:
        return None

    top_place, top_score = ranked[0]
    ambiguous = len(ranked) > 1 and (top_score - ranked[1][1]) < AMBIGUITY_MARGIN
    return Match(
        place=top_place,
        score=round(top_score, 4),
        method="geonames_fuzzy",
        ambiguous=ambiguous,
        candidates=ranked[:4],
    )


def all_aliases() -> list[tuple[str, Place]]:
    """(normalised alias, place) pairs. Used by the extractor to spot place
    names inside free text."""
    return sorted(_INDEX.items(), key=lambda kv: -len(kv[0]))
