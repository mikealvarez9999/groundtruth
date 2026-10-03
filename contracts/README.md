# Contracts

Frozen JSON schemas that every artefact on disk must satisfy. Version is
**v1.0.0** — renaming a field is a breaking change and requires project-lead
approval (D-017).

| Schema | What it describes |
|---|---|
| `damage_layer.schema.json` | The damage assessment: one Feature per building, with `damage_class`, `obscured`, `area_m2`, `grid_cell_id`. Sensor-agnostic — `groundtruth.source` is a `oneOf` union discriminated on `tool`. |
| `signal.schema.json` | A single tip from any citizen channel. Carries `source`, `raw`, `claim`, `geo`, `extraction`, and an optional `vlm_assessment`. |
| `sector_score.schema.json` | One ranked cell: `grid_cell_id`, `score`, contributing signal ids, event-type breakdown. |

## Provenance must be re-runnable

Both `damage_layer` branches require a real pinned identifier for the tool that
produced them, and both reject placeholders:

| Branch | Required ref | Enforced by |
|---|---|---|
| `haste` | `haste_commit` + `backbone` | schema `required` |
| `sentinel1_sar` | `classifier_ref` | schema `required` + `pattern`, **and** `sentinel1_to_damage_layer.py` exits non-zero without writing a file |

A shipped layer once carried `S1-Flood-Bangladesh@<commit>` — and the schema's
own `examples` value was the placeholder, so copying the documented example
produced it. Both are fixed (D-034). **`examples` in these schemas is not
decoration:** it is the value a reader is most likely to copy.

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
- **Per-signal VLM scores** — only the 3-way verdict (`supports`,
  `contradicts`, `inconclusive`) is in-scope. A confidence number invites
  false calibration (D-021). `vlm_assessment.model` is a free string and simply
  records which model answered — currently `thinkingmachines/inkling:free` on
  OpenRouter (D-037).
- **External basemap URLs** — there is no live basemap. A `tiles` field would
  imply a network call that this system does not make.
- **Raw author identifiers** — the Telegram bot pseudonymises at ingestion
  (D-030); the schema enforces a `src_tg_*` shape and rejects bare user IDs.

## Adding a field

1. Open a `D-NNN` entry in `DECISIONS.md` describing the field and the
   downstream change.
2. Bump the schema's `contract_version` only after project-lead review. Adding a
   field to `required` is **not** a rename and stays at 1.0.0 — but it still gets
   a D-NNN entry (D-034 is the precedent).
3. Add an example in `examples/` — and make sure the example value is a real
   pinned reference, not a placeholder (see above).
4. Update every reader (`fusion.ts`, `verify.py`, etc.) in the same PR.

Renaming a field is a breaking change and is not allowed without bumping the
major version.
