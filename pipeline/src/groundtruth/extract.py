"""Turn a raw report into a structured claim.

IMPORTANT, READ BEFORE TRUSTING THIS: this is a **deterministic rule-based
extractor**, not Gemini. The kickoff specifies LLM extraction, and
``LLM_PROMPT`` below plus ``extract_with_llm()`` is the seam for it -- but no
API key exists in this environment, so the working path is rules.

That is a real downgrade and you should know exactly what it costs:
  - Rules only understand the vocabulary in the tables below. A report phrased
    outside them falls back to event_type "other" with low urgency.
  - No translation. ``summary_en`` for Bangla input is assembled from matched
    keywords, not translated. It reads like a telegram, because it is one.
  - No inference. "the water reached my chest" will not become
    flood_inundation unless a keyword matches.

What rules buy in exchange: zero cost, zero latency, offline, and identical
output on every run -- which is why the committed artifacts are stable and the
demo cannot fail on a rate limit. Swap in the LLM for quality when a key
exists; keep rules as the offline fallback.
"""

from __future__ import annotations

import hashlib
import re

from .gazetteer import all_aliases, normalise

# --------------------------------------------------------------------------
# Keyword tables. Bangla script and Banglish, lowercase.
# Order matters within a category: the FIRST category to match wins, so the
# tables are ordered most-specific-first in EVENT_RULES.
# --------------------------------------------------------------------------

EVENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("people_stranded", (
        "atke", "atka", "stranded", "trapped", "chad e", "chal e uthe", "roof e",
        "cut off", "attoke", "আটকে", "আটকা", "ছাদে",
    )),
    ("missing_person", (
        "nikhoj", "missing", "khuje pacchi na", "hariye", "নিখোঁজ", "হারিয়ে",
    )),
    ("medical_need", (
        "osud", "medicine", "doctor", "hospital", "injured", "ahoto", "asukh",
        "pregnant", "ঔষধ", "ওষুধ", "ডাক্তার", "আহত", "হাসপাতাল",
    )),
    ("water_food_need", (
        "khabar", "khaddo", "food", "khabar pani", "drinking water", "khaowar pani",
        "bhat", "relief", "tran", "খাবার", "ত্রাণ", "খাদ্য",
    )),
    ("road_blocked", (
        "rasta", "road", "shorok", "bondho", "blocked", "jogajog bichchinno",
        "cut off road", "bridge", "setu", "রাস্তা", "সড়ক", "যোগাযোগ বিচ্ছিন্ন", "সেতু",
    )),
    ("power_outage", (
        "bidyut", "current nai", "power", "electricity", "bijli", "load shed",
        "বিদ্যুৎ", "কারেন্ট নাই",
    )),
    ("shelter_status", (
        "ashroy", "shelter", "school e uthe", "cyclone center", "ashroykendro",
        "আশ্রয়", "আশ্রয়কেন্দ্র",
    )),
    ("structural_damage", (
        "ghor bhenge", "bhenge", "collapsed", "damaged", "dhose", "poresi",
        "wall", "deyal", "ভেঙে", "ধসে", "দেয়াল",
    )),
    ("flood_inundation", (
        "pani", "bonna", "flood", "dube", "tolie", "plabito", "water level",
        "জল", "পানি", "বন্যা", "ডুবে", "প্লাবিত",
    )),
)

URGENCY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("critical", (
        "bachao", "help", "urgent", "jodi", "sathe sathe", "emergency", "mara",
        "dying", "drowning", "dube jacche", "immediately", "ekhuni", "roof",
        "chal porjonto", "বাঁচাও", "সাহায্য", "জরুরি", "এখুনি",
    )),
    ("high", (
        "druto", "quickly", "soon", "taratari", "beshi", "onek", "severe",
        "worse", "barche", "দ্রুত", "তাড়াতাড়ি", "অনেক",
    )),
    ("low", (
        "kome", "receding", "namche", "improving", "better", "thik ache",
        "কমে", "নামছে",
    )),
)

NEEDS_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("boat", ("nouka", "noukа", "boat", "trawler", "vessel", "নৌকা")),
    ("rescue", ("uddhar", "rescue", "bachao", "help", "উদ্ধার", "বাঁচাও")),
    ("medical", ("osud", "medicine", "doctor", "hospital", "ঔষধ", "ওষুধ", "ডাক্তার")),
    ("water", ("khaowar pani", "drinking water", "pure water", "খাওয়ার পানি")),
    ("food", ("khabar", "food", "tran", "relief", "খাবার", "ত্রাণ")),
    ("shelter", ("ashroy", "shelter", "আশ্রয়")),
    ("power", ("bidyut", "current", "electricity", "বিদ্যুৎ")),
)

# Bangla-Indic digits -> ASCII, so "৭ জন" parses as 7.
_BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

# "12 jon", "12 people", "১৫ জন", "family of 6"
_PERSON_PATTERNS = (
    re.compile(r"(\d+)\s*(?:jon|jon\b|person|people|manush|জন|মানুষ)"),
    re.compile(r"(?:family of|poribar)\s*(\d+)"),
    re.compile(r"(\d+)\s*(?:ta|ti)?\s*(?:children|baccha|shishu|বাচ্চা|শিশু)"),
)

# The English gloss is assembled, not translated. Templates keep it honest.
_SUMMARY_TEMPLATES = {
    "flood_inundation": "Reports flooding / rising water at {place}.",
    "people_stranded": "Reports people stranded at {place}.",
    "structural_damage": "Reports structural damage at {place}.",
    "road_blocked": "Reports road or link access blocked at {place}.",
    "medical_need": "Reports a medical need at {place}.",
    "water_food_need": "Reports need for food or drinking water at {place}.",
    "power_outage": "Reports power outage at {place}.",
    "shelter_status": "Reports shelter conditions at {place}.",
    "missing_person": "Reports a missing person at {place}.",
    "other": "Unclassified report referencing {place}.",
}

PROMPT_VERSION = "rules-v1"

# Kept so the LLM upgrade is a drop-in rather than a redesign. Unused today.
LLM_PROMPT = """You extract ONE structured claim from a citizen flood report.
The text may be Bangla, romanised Bangla (Banglish), English, or mixed.

Return JSON only, matching this shape:
{
  "location_ref": "<the place name EXACTLY as written in the text, verbatim>",
  "event_type": one of ["flood_inundation","structural_damage","road_blocked",
      "people_stranded","medical_need","water_food_need","power_outage",
      "shelter_status","missing_person","other"],
  "urgency": one of ["critical","high","medium","low"],
  "persons_at_risk": integer or null (null if not stated -- do NOT guess),
  "claimed_time": ISO-8601 or null,
  "needs": subset of ["rescue","boat","medical","water","food","shelter","power","assessment"],
  "summary_en": one short English sentence
}

Rules:
- location_ref must be copied verbatim from the text. Do not normalise or translate it.
- persons_at_risk is null unless a number is explicitly stated. Never estimate.
- If the text asserts nothing locatable, set location_ref to "".
"""


def _find_location(text: str) -> str:
    """Return the place substring as written in the text, or "".

    Scans known aliases longest-first against a normalised copy of the text,
    then maps the hit back to the original casing/spelling so
    ``claim.location_ref`` stays verbatim per the contract.
    """
    # Bangla script: direct substring search, no folding.
    for alias, _ in all_aliases():
        if any("ঀ" <= ch <= "৿" for ch in alias) and alias in text:
            return alias

    words = re.findall(r"[A-Za-z]+", text)
    # Try 2-word then 1-word windows (catches "Beani Bazar").
    for size in (2, 1):
        for i in range(len(words) - size + 1):
            window = words[i:i + size]
            if normalise(" ".join(window)) in dict(all_aliases()):
                return " ".join(window)
    return ""


def _first_match(text: str, rules) -> str | None:
    for label, keywords in rules:
        if any(kw in text for kw in keywords):
            return label
    return None


def _persons_at_risk(text: str) -> int | None:
    t = text.translate(_BN_DIGITS)
    for pattern in _PERSON_PATTERNS:
        m = pattern.search(t)
        if m:
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            # Sanity ceiling: a single report claiming 100k people is a
            # district statistic, not a locatable rescue count.
            if 0 < n <= 5000:
                return n
    return None


def detect_lang(text: str) -> str:
    """Crude script/language tag for raw.lang."""
    has_bn = any("ঀ" <= ch <= "৿" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text)
    if has_bn and has_latin:
        return "mixed"
    if has_bn:
        return "bn"
    if not has_latin:
        return "unknown"
    # Latin script: Banglish if it carries romanised-Bangla markers.
    banglish_markers = (
        "pani", "ghor", "nouka", "bachao", "onek", "ache", "gese", "korte",
        "amader", "manush", "jon", "dike", "rasta", "khabar", "beshi", "dube",
    )
    low = text.lower()
    return "bn-latn" if any(m in low for m in banglish_markers) else "en"


def extract(text: str) -> dict:
    """Rule-based extraction. Always returns a claim dict; never raises."""
    low = text.lower()

    location_ref = _find_location(text)
    event_type = _first_match(low, EVENT_RULES) or "other"
    urgency = _first_match(low, URGENCY_RULES) or "medium"

    needs = [label for label, kws in NEEDS_RULES if any(k in low for k in kws)]
    # A stranded-persons report implies rescue even if unsaid.
    if event_type == "people_stranded" and "rescue" not in needs:
        needs.append("rescue")

    place_for_summary = location_ref or "an unspecified location"
    summary = _SUMMARY_TEMPLATES[event_type].format(place=place_for_summary)

    return {
        "location_ref": location_ref,
        "event_type": event_type,
        "urgency": urgency,
        "persons_at_risk": _persons_at_risk(text),
        "claimed_time": None,  # rules do not parse relative time expressions
        "needs": needs,
        "summary_en": summary,
    }


def extract_with_llm(text: str) -> dict:  # pragma: no cover - no key available
    """Placeholder for an LLM-backed extractor. Intentionally not implemented.

    Raising is the honest behaviour: a silent fallback to rules would make it
    impossible to tell which extractor produced a given artifact, and
    ``extraction.model`` in the contract would be a lie.
    """
    raise NotImplementedError(
        "LLM extraction is not wired up (D-021: rule-based is the shipped path). "
        "Gemini was removed as a provider in D-037; a text model exists for the "
        "brief (Groq openai/gpt-oss-120b) but extraction is deliberately not on it. "
        "Use extract() (rules) or implement this against LLM_PROMPT."
    )


def content_hash(*parts: str) -> str:
    """Deterministic short id, so re-running does not churn committed JSON."""
    h = hashlib.sha256("␟".join(parts).encode("utf-8")).hexdigest()
    return h[:12]
