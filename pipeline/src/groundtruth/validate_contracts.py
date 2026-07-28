"""Validate our JSON artifacts against the contract schemas in /contracts.

This is contract *tooling*, not pipeline logic -- it deliberately knows nothing
about extraction, geocoding, verification, or fusion. It exists so that "does
this file match the contract?" is a command anyone on the team can run, rather
than an argument.

Run it from the repo root or from /pipeline:

    python -m groundtruth.validate_contracts            # examples + processed data
    python -m groundtruth.validate_contracts --strict   # also fail on warnings

Exit code 0 means every file checked validates. Non-zero means at least one
did not, and the offending path plus the JSON Pointer to the bad value is
printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ModuleNotFoundError:  # pragma: no cover - dependency hint only
    sys.exit(
        "jsonschema is not installed.\n"
        "  cd pipeline && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
    )


def find_repo_root(start: Path) -> Path:
    """Walk up until we find the directory holding /contracts."""
    for candidate in [start, *start.parents]:
        if (candidate / "contracts").is_dir():
            return candidate
    raise SystemExit(f"Could not locate a repo root with a /contracts dir above {start}")


# Which schema governs which artifact. Keyed by schema stem; each entry lists
# glob patterns, relative to the repo root, of files that must satisfy it.
#
# Signals are stored as arrays (a seed file is one JSON array of signals), so
# the signal schema is applied per element. `is_array` says which.
CONTRACTS: dict[str, dict] = {
    "damage_layer": {
        "globs": [
            "contracts/examples/damage_layer.example.json",
            "data/processed/damage_layer.geojson",
        ],
        "is_array": False,
    },
    "signal": {
        "globs": [
            "contracts/examples/signal.*.example.json",
            "data/processed/signals*.json",
        ],
        "is_array": None,  # accept either a single object or an array of them
    },
    "sector_score": {
        "globs": [
            "contracts/examples/sector_score.example.json",
            "data/processed/sector_scores.json",
        ],
        "is_array": False,
    },
}


def load_json(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def describe_error(err) -> str:
    pointer = "/" + "/".join(str(p) for p in err.absolute_path)
    return f"    at {pointer or '/'}: {err.message}"


def validate_file(validator: Draft202012Validator, path: Path, is_array) -> list[str]:
    """Return a list of human-readable problems (empty means valid)."""
    try:
        payload = load_json(path)
    except json.JSONDecodeError as exc:
        return [f"    not valid JSON: {exc}"]

    if is_array is None:
        is_array = isinstance(payload, list)

    documents = payload if is_array else [payload]
    if is_array and not isinstance(payload, list):
        return ["    expected a JSON array of signals"]

    problems: list[str] = []
    for index, document in enumerate(documents):
        prefix = f"[{index}] " if is_array else ""
        for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
            problems.append(f"    {prefix}".rstrip() + describe_error(err).lstrip())
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings (e.g. an expected artifact not yet produced) as failures",
    )
    args = parser.parse_args()

    root = find_repo_root(Path(__file__).resolve())
    failures = 0
    warnings = 0
    checked = 0

    for name, spec in CONTRACTS.items():
        schema_path = root / "contracts" / f"{name}.schema.json"
        if not schema_path.is_file():
            print(f"FAIL {schema_path.relative_to(root)} -- schema missing")
            failures += 1
            continue

        schema = load_json(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)

        matches: list[Path] = []
        for pattern in spec["globs"]:
            matches.extend(sorted(root.glob(pattern)))

        if not matches:
            print(f"WARN {name}: no files matched {spec['globs']}")
            warnings += 1
            continue

        for path in matches:
            rel = path.relative_to(root)
            problems = validate_file(validator, path, spec["is_array"])
            checked += 1
            if problems:
                failures += 1
                print(f"FAIL {rel}  (against {name}.schema.json)")
                for problem in problems:
                    print(problem)
            else:
                print(f"OK   {rel}")

    print(f"\n{checked} file(s) checked, {failures} failure(s), {warnings} warning(s).")
    if failures:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
