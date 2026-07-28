"""One command to produce every artifact the console reads.

    PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all

Stages: synthesise demo inputs -> extract -> geocode -> verify -> fuse -> write
-> validate -> print an honest accuracy report against the planted fakes.

Outputs land in BOTH ``data/processed/`` (the committed artifacts) and
``console/public/data/`` (what the browser fetches). Two copies is not elegant,
but the alternative is a Next.js import that reaches outside its own tree, and
this is the boring option.

On the eval report: ``signal.eval`` is stripped before extract/geocode/verify/fuse
ever see a signal (D-010). It is re-attached only here, after the pipeline has
committed to its answers, to score them. That ordering is the whole reason the
catch-rate is meaningful.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from . import demo_data, fuse
from .extract import PROMPT_VERSION, content_hash, detect_lang, extract
from .geocode import geocode
from .verify import verify_all

CONSOLE_DATA_SUBDIR = Path("console") / "public" / "data"
PROCESSED_SUBDIR = Path("data") / "processed"
SEED_SUBDIR = Path("data") / "seed"
HASTE_SUBDIR = Path("data") / "raw" / "haste"
SENTINEL1_SUBDIR = Path("data") / "raw" / "sentinel1"
# Checked in order; first directory holding BOTH files wins. HASTE first: it is
# the primary optical path, the SAR directory is the alternate.
REAL_DAMAGE_SUBDIRS = [HASTE_SUBDIR, SENTINEL1_SUBDIR]


def load_real_damage(root: Path):
    """Return (damage_layer, valid_area) from a committed real assessment, or None.

    A real damage layer plus its valid-area footprint dropped into
    ``data/raw/haste/`` (or ``data/raw/sentinel1/``) take over from the synthetic
    demo inputs. BOTH must be present: a damage layer without its imagery
    footprint would let the verifier miscall coverage and risk tiering
    out-of-coverage claims as suspect.
    """
    for subdir in REAL_DAMAGE_SUBDIRS:
        damage_path = root / subdir / "damage_layer.geojson"
        valid_path = root / subdir / "valid_area.geojson"
        if damage_path.is_file() and valid_path.is_file():
            with damage_path.open(encoding="utf-8") as fh:
                damage_layer = json.load(fh)
            with valid_path.open(encoding="utf-8") as fh:
                valid_area = json.load(fh)
            return damage_layer, valid_area, subdir
    return None


def repo_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / "contracts").is_dir():
            return candidate
    raise SystemExit("Could not locate the repo root (no /contracts dir above this file)")


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")


def build_signals(posts: list[dict]) -> tuple[list[dict], dict[str, dict]]:
    """Raw posts -> signals with claim + geo. Returns (signals, eval_by_id).

    The eval block is split off here and handed back separately, so nothing
    downstream can read it even by accident.
    """
    signals: list[dict] = []
    evals: dict[str, dict] = {}

    for post in posts:
        text = post["text"]
        signal_id = "sig_" + content_hash(post["source_id"], text)

        claim = extract(text)
        geo = geocode(claim["location_ref"])

        signal = {
            "contract_version": "1.0.0",
            "signal_id": signal_id,
            "channel": "citizen_seed",
            "source": {
                "source_id": post["source_id"],
                "platform": post["platform"],
                "author_ref": post["author_ref"],
                "url": None,
                "received_at": post["received_at"],
                "replay_offset_s": post["replay_offset_s"],
            },
            "raw": {
                "text": text,
                "lang": detect_lang(text),
                "media_refs": [],
                "imagery_ref": None,
            },
            "claim": claim,
            "geo": geo,
            "extraction": {
                "model": "rules",  # NOT an LLM -- see extract.py module docstring
                "prompt_version": PROMPT_VERSION,
                "extracted_at": post["received_at"],
                "confidence": None,  # rules do not produce a calibrated score
                "cached": False,
            },
        }
        signals.append(signal)
        if post.get("eval"):
            evals[signal_id] = post["eval"]

    return signals, evals


def eval_report(signals: list[dict], evals: dict[str, dict]) -> str:
    """Score the verifier against the planted fakes. Honest about what it misses."""
    lines: list[str] = []
    planted = [(s, evals[s["signal_id"]]) for s in signals
               if s["signal_id"] in evals and evals[s["signal_id"]].get("planted_fake")]
    genuine = [s for s in signals
               if not evals.get(s["signal_id"], {}).get("planted_fake")]

    by_kind: dict[str, list[tuple[str, str, bool]]] = {}
    for signal, ev in planted:
        kind = ev.get("fake_kind", "unknown")
        actual = signal["verification"]["tier"]
        expected = ev.get("expected_tier", "?")
        by_kind.setdefault(kind, []).append((expected, actual, expected == actual))

    lines.append(f"Planted fakes: {len(planted)}   Genuine reports: {len(genuine)}")
    lines.append("")
    lines.append("By planted-fake kind (expected tier vs actual):")
    for kind, rows in sorted(by_kind.items()):
        ok = sum(1 for _, _, hit in rows if hit)
        lines.append(f"  {kind:22} {ok}/{len(rows)} as expected")
        for expected, actual, hit in rows:
            mark = "ok " if hit else "MISS"
            lines.append(f"      [{mark}] expected={expected:22} actual={actual}")

    caught = sum(1 for s, _ in planted if s["verification"]["tier"] == "suspect")
    lines.append("")
    lines.append(
        f"Flagged SUSPECT: {caught} of {len(planted)} planted fakes. "
        f"This is NOT a 'detection rate' to brag about --"
    )
    lines.append(
        "  only the contradicts_imagery kind is detectable by design. Astroturf is "
        "contained (never promoted"
    )
    lines.append(
        "  to corroborated) rather than flagged, and exaggerated_scale / "
        "impossible_location are openly not detected."
    )

    # Call out the worst failure mode explicitly rather than burying it in a table:
    # an exaggerated claim inside a genuinely affected area gets corroborated by the
    # truthful reports around it and inherits full weight.
    rode_along = [
        s for s, ev in planted
        if ev.get("fake_kind") == "exaggerated_scale"
        and s["verification"]["tier"] == "corroborated"
    ]
    if rode_along:
        lines.append("")
        lines.append(
            f"KNOWN WEAKNESS: {len(rode_along)} exaggerated-scale fake(s) reached "
            f"CORROBORATED by riding on genuine"
        )
        lines.append(
            "  co-located reports. Corroboration confirms that something is happening "
            "at a place; it cannot"
        )
        lines.append(
            "  bound how bad. Do not present a corroborated tier as endorsement of a "
            "claim's numbers."
        )
        for s in rode_along:
            lines.append(f"      {s['signal_id']}  {s['claim']['location_ref']}")

    # False positives are the number that actually matters for trust.
    false_suspect = [s for s in genuine if s["verification"]["tier"] == "suspect"]
    lines.append("")
    lines.append(
        f"Genuine reports wrongly marked suspect: {len(false_suspect)}"
        + (" <-- INVESTIGATE" if false_suspect else " (good)")
    )
    for s in false_suspect:
        lines.append(f"      {s['signal_id']}  {s['claim']['location_ref']}")
    return "\n".join(lines)


def main() -> int:
    root = repo_root()
    print("GroundTruth build")
    print(f"repo root: {root}")
    print("-" * 68)

    # 1. inputs: a real committed damage layer if present, else synthetic demo.
    real = load_real_damage(root)
    if real is not None:
        damage_layer, valid_area, real_dir = real
        src = damage_layer.get("groundtruth", {}).get("source", {})
        tool = src.get("tool", "?")
        detail = f", sensor={src.get('sensor')}" if tool == "sentinel1_sar" else ""
        print(f">> REAL DAMAGE LAYER -- tool={tool}{detail}")
        print(f"   loaded from {real_dir}/ (damage_layer + valid_area)")
    else:
        print("!! SYNTHETIC DEMO DATA -- see pipeline/src/groundtruth/demo_data.py !!")
        damage_layer = demo_data.damage_layer_geojson()
        valid_area = demo_data.valid_area_geojson()

    # The event id comes from the damage layer itself, never from demo constants:
    # the pipeline must work unchanged for any event a real layer declares.
    event_id = damage_layer["groundtruth"]["event_id"]

    # The seeded citizen corpus (and its planted-fake eval) is Sylhet-specific:
    # its texts name Sylhet places and the gazetteer that geocodes them is a
    # Bangladesh extract. For any other event, replaying it would scatter
    # Bangladeshi reports over a foreign AOI as pure NO_COVERAGE noise -- so the
    # citizen channel starts EMPTY there, honestly, until a per-event corpus and
    # gazetteer exist. Live Telegram tips likewise need that gazetteer to geocode.
    if event_id == demo_data.EVENT_ID:
        posts = demo_data.seed_posts()
        if real is not None:
            print("   NOTE: citizen signals are the seeded Sylhet replay (see demo_data.py).")
    else:
        posts = []
        print(f"   NOTE: event {event_id!r} has no citizen corpus -- the seeded replay is")
        print("   Sylhet-only. Citizen channel is EMPTY (damage-only scoring) until a")
        print("   per-event corpus + gazetteer are added.")
    print("-" * 68)

    counts = damage_layer["groundtruth"]["counts"]
    print(f"[1/6] damage layer   : {counts['buildings_total']} buildings, "
          f"{counts['buildings_damaged']} damaged, {counts['buildings_obscured']} obscured")
    print(f"      seed posts     : {len(posts)}")

    # 2+3. extract + geocode
    signals, evals = build_signals(posts)
    placed = sum(1 for s in signals if s.get("geo"))
    print(f"[2/6] extracted      : {len(signals)} claims (rule-based, not LLM)")
    print(f"[3/6] geocoded       : {placed}/{len(signals)} placed, "
          f"{len(signals) - placed} unresolvable")

    # 4. verify
    verify_all(signals, damage_layer, valid_area)
    tiers: dict[str, int] = {}
    for s in signals:
        tiers[s["verification"]["tier"]] = tiers.get(s["verification"]["tier"], 0) + 1
    print(f"[4/6] verified       : " + ", ".join(f"{k}={v}" for k, v in sorted(tiers.items())))

    # 5. fuse
    scores = fuse.fuse(damage_layer, signals, valid_area, event_id)
    print(f"[5/6] fused          : {len(scores['cells'])} cells ranked")
    for cell in scores["cells"][:3]:
        print(f"      #{cell['rank']} {cell['place_label'] or cell['cell_id']:16} "
              f"score={cell['score']:.3f}  {cell['top_reasons'][0] if cell['top_reasons'] else ''}")

    # 6. write, to both locations
    for signal in signals:
        sid = signal["signal_id"]
        if sid in evals:
            signal["eval"] = evals[sid]

    artifacts = {
        "damage_layer.geojson": damage_layer,
        "valid_area.geojson": valid_area,
        "signals.seed.json": signals,
        "sector_scores.json": scores,
    }
    processed = root / PROCESSED_SUBDIR
    console = root / CONSOLE_DATA_SUBDIR
    for name, payload in artifacts.items():
        write_json(processed / name, payload)
    console.mkdir(parents=True, exist_ok=True)
    for name in artifacts:
        shutil.copyfile(processed / name, console / name)
    if posts:
        write_json(root / SEED_SUBDIR / "posts.json", posts)
    print(f"[6/6] wrote          : {len(artifacts)} artifacts -> "
          f"{PROCESSED_SUBDIR} and {CONSOLE_DATA_SUBDIR}")

    # validate
    print("-" * 68)
    from .validate_contracts import main as validate_main
    sys.argv = ["validate_contracts"]
    rc = validate_main()

    if posts:
        print("-" * 68)
        print("EVAL REPORT (eval labels read only here, after the pipeline decided)")
        print("-" * 68)
        print(eval_report(signals, evals))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
