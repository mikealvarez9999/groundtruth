# Data contracts

Three JSON Schemas (Draft 2020-12). They are the interface between the four parts of
GroundTruth that different people are building in parallel, which is the only reason they
exist: so the console can be written against a shape the pipeline has not produced yet.

| Schema | Governs | Produced by | Consumed by |
|---|---|---|---|
| `damage_layer.schema.json` | Channel 1 — per-building damage, converted from HASTE's predictions GeoPackage | manual HASTE run + converter (`runbooks/haste-local-setup.md` §8) | fusion, map layer |
| `signal.schema.json` | Channels 2 and 3 — one verified claim about one place | VLM batch, seed loader, Telegram bot | fusion, map pins, Audit Drawer |
| `sector_score.schema.json` | Fusion output — ranked grid cells | fusion engine | Triage Queue, map heat layer, brief agent |

**Per the kickoff: once created, these change only with the project lead's explicit
approval.** Bump `contract_version` and note it in `DECISIONS.md` when they do.

## Checking a file against a contract

```bash
cd pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
PYTHONPATH=src ./.venv/bin/python -m groundtruth.validate_contracts
```

It validates everything in `contracts/examples/` plus any real artifacts in
`data/processed/`, and exits non-zero on the first mismatch with a JSON Pointer to the bad
value. Wire it into a pre-commit hook or a CI step once we have real data.

## `contracts/examples/`

Hand-written fixtures, one per schema plus a corroborated/suspect pair for signals. They
serve three purposes: they prove the schemas are satisfiable, they let the console be built
against realistic data today, and they are the regression fixtures for the validator.

**Every fixture is clearly marked as illustrative and carries invented numbers.** They are
not real data about Sylhet and must never reach the demo. Delete or replace them the moment
real artifacts exist.

## Three decisions baked into these schemas that are worth knowing

1. **`damage_class` is binary, and that is HASTE's constraint, not laziness.** HASTE's
   interactive labeler computes a per-building probability in the browser but thresholds it
   to 0/1 before persisting, so there is no per-building confidence to carry. Continuous
   damage intensity therefore lives only in `sector_score` as an aggregate
   (`damaged_fraction`). Do not add a per-building score field — there is nothing truthful to
   put in it. Evidence: `runbooks/haste-local-setup.md` §8c.

2. **One schema covers both VLM findings and citizen reports**, distinguished by `channel`.
   The fusion engine treats them uniformly, and two near-identical schemas would drift apart
   within a day.

3. **`verification.reason` is required for every tier**, not just `suspect`. A corroborated
   claim we cannot justify in one sentence has not been verified either. It is also what the
   Audit Drawer renders verbatim.

## Things the schemas deliberately refuse to represent

- **Any credibility score attached to a person or account.** Verification is corroboration
  and spatial consistency only. No media forensics, no deepfake detection, no trained
  credibility classifier.
- **Silent deletion of suspect signals.** They stay in the data with `fusion_weight: 0` and a
  stated reason, so a human can overrule us.
- **`no_coverage` as evidence of absence.** A claim we cannot check because we have no
  imagery there is `plausible_unverified`, never `suspect`. Encoded in
  `verification.spatial_check.status`.
- **Real identities.** `source.author_ref` is pseudonymous by contract.
