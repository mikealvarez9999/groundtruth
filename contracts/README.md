# Contracts

Frozen JSON schemas that every artefact on disk must satisfy. Version is
**v1.0.0** — renaming a field is a breaking change and requires project-lead
approval (D-017).

| Schema | What it describes |
|---|---|
| `damage_layer.schema.json` | The SAR damage assessment: one Feature per building, with `damage_class`, `obscured`, `area_m2`, `grid_cell_id`. |
| `signal.schema.json` | A single tip from any citizen channel. Carries `source`, `raw`, `claim`, `geo`, `extraction`, and an optional `vlm_assessment`. |
| `sector_score.schema.json` | One ranked cell: `grid_cell_id`, `score`, contributing signal ids, event-type breakdown. |

Every JSON artefact under `data/processed/` is checked against its schema by
`pipeline/src/groundtruth/validate_contracts.py` before it is written. A bad
build fails loudly.

## Examples

- `examples/damage_layer.example.json` — minimal SAR output (5 buildings, 2
  damaged).
- `examples/signal.corroborated.example.json` — a citizen tip that reached
  the `corroborated` tier.
- `examples/signal.suspect.example.json` — a citizen tip the verifier
  flagged.
- `examples/sector_score.example.json` — one ranked sector.

The examples are **deliberately tiny**. They exist to exercise the schema,
not to look realistic. The synthetic demo in `pipeline/demo_data.py` is what
you read for shape and scale.

## What the schemas refuse to represent

- **`event_count` / `casualty_count` / `people_at_risk`** — there is no
  population model. Anything resembling a headcount is intentionally
  unspeakable; the system corroborates that *something* is happening at a
  place, not how bad it is.
- **Per-signal VLM scores** — only the 3-way verdict (`corroborating`,
  `contradicting`, `inconclusive`) is in-scope. A confidence number invites
  false calibration (D-021).
- **External basemap URLs** — there is no live basemap. A `tiles` field would
  imply a network call that this system does not make.
- **Raw author identifiers** — the Telegram bot pseudonymises at ingestion
  (D-030); the schema enforces a `src_tg_*` shape and rejects bare user IDs.

## Adding a field

1. Open a `D-NNN` entry in `DECISIONS.md` describing the field and the
   downstream change.
2. Bump the schema's `contract_version` only after project-lead review.
3. Add an example in `examples/`.
4. Update every reader (`fuse.ts`, `verify.py`, etc.) in the same PR.

Renaming a field is a breaking change and is not allowed without bumping the
major version.
