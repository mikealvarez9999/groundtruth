# DECISIONS

Running log of every scope or design choice, newest section last. Each entry says what was
decided, why, and what would make us revisit it. If a decision here is wrong, argue with the
entry rather than quietly doing something else.

Status legend: **[settled]** acted on · **[needs your call]** blocked on the project lead ·
**[open]** unknown, must be resolved by running something.

---

## D-001 — HASTE is vendored but not committed **[settled]**

`vendor/haste` is a shallow clone of `microsoft/haste` at commit `7d80be7` (2026-07-24),
**gitignored**, not committed.

- Why: it is a large reference-only tree we never modify, and committing it would bloat the
  repo and make our diffs unreadable. Anyone can reproduce it in one command.
- Reproduce: `git clone --depth 1 https://github.com/microsoft/haste vendor/haste`
- Consequence: the pinned commit is recorded here and in `runbooks/haste-local-setup.md`. Any
  HASTE claim in our docs cites the file it came from, so a future checkout can be re-checked
  against them.
- Revisit if: we ever need to patch HASTE (we should not — reference only).

## D-002 — `/console` package is named `groundtruth-console` **[settled]**

The directory is `/console` as specified, but `package.json` says `groundtruth-console`.

- Why: npm refuses to create a package named `console` — it is a Node core module name.
  `create-next-app` hard-fails on it.
- Consequence: cosmetic only. Directory layout matches the kickoff spec.

## D-003 — Rapid Building Assessment, not the trained-model path **[settled]**

For Channel 1 we use HASTE's **Building** workflow (per-building embeddings + in-browser
logistic regression), not the **Standard** workflow (train a segmentation model for a
wall-to-wall damage raster).

- Why: it matches the kickoff description ("embedding + logistic-regression method"), needs no
  training job, and is the only path with a chance of completing on a 16 GB CPU-only laptop
  inside the hackathon. Source: `vendor/haste/docs/usage/rapid-building-assessment.md`.
- Cost: output is per-building points/polygons, not a continuous flood-extent raster. See
  D-005 for what that costs the verifier.

## D-004 — Damage is binary per building; intensity is an aggregate **[settled]**

`damage_layer.schema.json` carries `damage_class: intact | damaged` with **no per-building
confidence**. Continuous damage intensity exists only in `sector_score.schema.json` as
`damaged_fraction` (damaged buildings / assessed buildings per cell).

- Why: HASTE's in-browser model computes a probability
  (`ui/src/Components/InteractiveLabeler/interactiveModel.js`, `predictProba`) but the
  predict-all path thresholds it to a class before saving
  (`InteractiveLabeler.jsx`: `damaged: cls === CLASS_DAMAGED ? 1 : 0`), and the persisted
  GeoPackage has only `damaged` 0/1 plus `damage_pct_0m`, which is a literal copy of it.
  There is no per-building confidence to carry.
- Consequence: the fusion engine must aggregate. Anyone who adds a per-building `confidence`
  field is inventing a number.
- Revisit if: we ever patch HASTE's UI to persist probabilities. Not worth it in 3 days, and
  it violates "never modify vendor".

## D-005 — Spatial consistency uses the valid-area mask, not a flood polygon **[settled]**

The SUSPECT check is: point is **inside HASTE's exported imagery valid-area mask** AND the
surrounding radius has assessed buildings AND ~none are damaged → `contradicted`. Outside the
mask → `no_coverage`, which can never produce SUSPECT.

- Why: the kickoff describes SUSPECT as "contradicts our own physical layers — e.g. claims
  flooding where imagery shows dry", which needs a *water/flood extent* polygon. The Building
  workflow does not produce one; it produces building footprints with damage flags. The valid
  area mask (an AOI polygon GeoJSON, per
  `vendor/haste/hastelib/src/hastegeo/workflows/prepare_imagery.py:317`, exported via the
  layer's ⋯ menu) is what tells us "we looked here". Combined with damaged-building density it
  gives a defensible contradiction test without pretending to have a flood raster.
- Why this matters ethically: without the mask, "no damage recorded" and "we have no imagery"
  are indistinguishable, and we would flag truthful reports from uncovered areas as suspect.
  That is the worst possible failure mode for this tool.
- Revisit if: a GPU appears and the Standard workflow becomes affordable — its continuous
  damage raster is closer to a flood extent.

## D-006 — One `signal` schema for both VLM findings and citizen reports **[settled]**

Distinguished by a `channel` enum (`citizen_seed`, `citizen_telegram`, `vlm_imagery`,
`vlm_photo`) rather than by separate schemas.

- Why: the fusion engine consumes them through one code path; two near-identical schemas
  would drift within a day.
- Consequence: some fields are channel-specific and nullable (`raw.imagery_ref`,
  `source.replay_offset_s`).

## D-007 — `verification.reason` required for every tier **[settled]**

Not just for `suspect`.

- Why: the kickoff only requires a reason string for suspects, but a CORROBORATED claim we
  cannot justify in one sentence has not been verified either. Cheap to write, and it is what
  makes the Audit Drawer worth opening.
- Cost: slightly more work in the verifier. Accepted.

## D-008 — Suspect signals are down-weighted, never deleted **[settled]**

`fusion_weight: 0` plus a stated reason, still present in the data and listed in the owning
cell's `evidence.suspect_count`.

- Why: a responder must be able to overrule us. Silently dropping a report we judged false is
  the same failure as believing a fake, but invisible.

## D-009 — Fusion weights are embedded in the output file **[settled]**

`sector_score.schema.json` requires a `weights` block describing the weights that produced
that file.

- Why: a ranked "go here first" list nobody can recompute is not evidence. Embedding the
  weights makes any score reproducible and lets a reviewer disagree with our weighting rather
  than with a black box.
- Note: the specific numbers in `contracts/examples/sector_score.example.json`
  (damage 0.45 / vlm 0.20 / citizen 0.35) are **placeholders, not a tuned decision** — see
  D-012.

## D-010 — Eval labels are quarantined from the pipeline **[settled]**

The seeded dataset's ground truth (`eval.planted_fake`, `eval.expected_tier`) lives in the
signal schema but is documented as strictly off-limits to extraction, geocoding, verification,
and fusion; the loader strips it.

- Why: if the verifier can see which rows are planted, our "we caught 10 of 10 fakes" claim is
  a lie. Keeping the labels in the same file is convenient; reading them would be fraud.

## D-011 — Contract fixtures are committed and marked fake **[settled]**

`contracts/examples/*.json` are hand-written, validate against the schemas, and every one
carries an explicit "ILLUSTRATIVE FIXTURE / not real data" note with invented accuracy
numbers.

- Why: unblocks console work before any real artifact exists, and proves the schemas are
  satisfiable. The loud marking is so an invented `damaged_f1` of 0.77 never gets screenshotted
  into a demo as if it were measured.

---

## Open items and things needing your call

## D-012 — Grid cell size and fusion weights **[needs your call]**

The example artifact uses **500 m** square cells and weights **damage 0.45 / vlm 0.20 /
citizen 0.35**, with tier multipliers corroborated 1.0 / plausible 0.35 / suspect 0.0.

These are placeholders chosen to make the fixtures concrete. They encode a real editorial
judgement — how much we trust imagery versus people — and that is your call, not mine.
Two things worth knowing before you decide:

- 500 m is small enough to be operationally actionable ("this neighbourhood") and large
  enough that a fuzzy gazetteer match usually lands in the right cell. Much smaller and
  geocoding error dominates; much larger and the ranking stops being useful.
- Weighting citizen signals at 0.35 means three corroborated critical reports can outrank a
  cell with moderate imagery damage. That is arguably the point of the product, but it is a
  choice.

Tell me the numbers you want, or tell me to keep these.

## D-013 — Bangla/Banglish handling depth **[needs your call]**

The signal schema tags `raw.lang` (`bn` / `en` / `bn-latn` / `mixed`) and carries a
`claim.summary_en` gloss. Not yet decided: whether the UI shows original text alongside the
English gloss (honest, more work, and needs a Bangla-capable font in the console) or English
only (faster, but hides what the reporter actually said behind a translation).

I would show both. Your call.

## D-014 — 16 GB laptop may not complete the embed **[open]**

HASTE documents a **32 GB minimum** (`vendor/haste/docker/README.md`) and gives no 16 GB
tuning row. Our `docker/.env` numbers (shm 4g / mem limit 12g) are an extrapolation, flagged
as such in the runbook.

Unknown until someone runs it. Mitigation ladder is in the runbook §9: shrink the AOI, lower
the embedding batch size to 8. If it cannot complete at all, the fallback is a much smaller
AOI and saying so plainly in the demo. Not a blocker for anything else — Channels 2 and 3 and
the whole console are independent of it.

## D-015 — Real Maxar `bangladesh-flooding22` asset URLs **[open]**

Nothing in the HASTE repo mentions this event, so I cannot supply verified URLs, and I will
not guess them from memory. Two hard constraints discovered from HASTE's code that will
govern the answer:

- Imagery URLs must be on `*.amazonaws.com` or `*.blob.core.windows.net`
  (`vendor/haste/hastelib/src/hastegeo/core/utils/url_allowlist.py`), enforced at layer
  creation. Maxar Open Data on S3 satisfies this; **HASTE's own documented sample URLs on
  `opendata.aiforgood.ai` do not** and must be downloaded and uploaded instead.
- Only `.tif` is accepted, and GDAL is restricted to GTiff/COG/VRT/JPEG/PNG rasters
  (`vendor/haste/spec/architecture/decisions/0004-gdal-driver-allowlist.md`).

Whoever loads the scene: find the real URLs, `curl -I` one to confirm it resolves, then record
them in the runbook.

## D-016 — Overture footprint coverage over Sylhet **[open]**

HASTE pulls footprints from **Overture Maps** automatically, not from Microsoft Global
Building Footprints or OSM as the kickoff assumed
(`vendor/haste/docs/usage/image-layers.md`). Coverage quality in rural Sylhet is unknown.

Check the footprint count after preprocessing. If implausibly low, the custom-footprints path
is available but constrained: GeoPackage only, ≤500 MB, Polygon/MultiPolygon only, set at
layer creation and **not changeable afterward**. An OSM extract would need
`ogr2ogr -f GPKG` conversion first.

---

# Phase 1 — implementation decisions

Everything below was decided while building the working pipeline and console.

## D-017 — Contract files are named `*.schema.json` **[settled]**

The kickoff said `/contracts/damage_layer.geojson`, `signal.json`, `sector_score.json`.
The files are `damage_layer.schema.json`, `signal.schema.json`, `sector_score.schema.json`.

- Why: these are *schemas*, not instances, and `damage_layer.geojson` is the name of the
  real artifact that now lives at `data/processed/damage_layer.geojson`. Giving both the
  same name guarantees confusion.
- I made this call without logging it in the first pass, which was a gap in this log. Say
  the word and I will rename to match the kickoff exactly.

## D-018 — Corroboration groups on a coarse EVENT GROUP, not exact `event_type` **[settled, deviates from the kickoff]**

The kickoff says group by "grid-cell + event-type + time-window". We group by
`verify.EVENT_GROUPS` instead: `flood_impact` (inundation / structural damage / stranded /
missing), `access`, `infrastructure`, `relief_need`.

- Why: two reports 300 m apart within the hour, one saying "water up to the rooflines" and
  one saying "people stuck on a roof", are two witnesses to ONE event. Exact-type matching
  called them uncorroborated, which is not a defensible reading of the evidence. With exact
  types the seeded corpus produced **2** corroborated signals; with event groups it produces
  **18**, and spot-checking the pairs they are all genuinely the same event.
- Cost: it is more permissive, so it will corroborate faster than a strict reading. The
  mapping is deliberately narrow enough that a power cut never corroborates a drowning.
- Revisit: narrow `EVENT_GROUPS` if you disagree. It is one dict.

## D-019 — Damage component is shrunk toward the base rate, with a minimum sample **[settled]**

`fuse.py`: cells with fewer than `MIN_ASSESSED_FOR_DAMAGE = 10` assessed buildings get **no**
damage component; above that the observed fraction is shrunk toward the layer-wide base rate
with a `SHRINKAGE_PRIOR = 15` pseudo-observation prior.

- Why: without it, a cell holding ONE assessed building that happened to be damaged scored a
  perfect 1.0 and outranked a neighbourhood with 66% of 29 buildings destroyed. That is not
  hypothetical — it is what the first run produced, and it would have put a rounding artifact
  at the top of a list telling responders where to go first.
- `evidence.damaged_fraction` still reports the RAW observed fraction. The score uses the
  shrunk value. Both are in the artifact on purpose.

## D-020 — Missing channels cost a cell their weight; no renormalisation **[settled]**

The score denominator is the sum of ALL channel weights, not just the available ones.

- Why: renormalising rewarded missing data. A cell with two citizen reports and no imagery
  scored 1.0 and outranked Kanaighat purely because it had *less* evidence. Breadth of
  independent evidence should raise confidence, not lower the bar.
- **The cost, stated plainly:** a cell outside the imagery footprint can never score as
  highly as one inside it, however many people report from there. That is a real bias against
  unimaged areas — exactly the places most likely to be cut off. Mitigations: `coverage.status`
  on every cell, `recon_priority` on every single-source signal, an explicit amber "NO IMAGERY"
  marker in the queue, and the brief calls it out under GAPS AND CAUTIONS. If you would rather
  weight human reports higher, that is D-012 and it is your call.

## D-021 — Extraction is rule-based, not Gemini **[settled, forced]**

`extract.py` is a deterministic keyword/regex extractor over Bangla, Banglish and English.
`extract_with_llm()` exists and **raises** `NotImplementedError`.

- Why: there is no `GEMINI_API_KEY` in this environment. `LLM_PROMPT` is written and ready.
  - **Superseded in part by D-037:** Gemini no longer exists as a provider, and a
    text model now does (Groq `openai/gpt-oss-120b`, used by `/api/brief`). So
    "no key available" is no longer the reason extraction stays rule-based —
    the reason is editorial. The decision itself stands: rules, and raising
    rather than falling back.
- Why it raises rather than silently falling back: a silent fallback would make
  `extraction.model` in the artifact a lie, and you could not tell which extractor produced
  a given signal.
- What it costs: rules only understand the vocabulary in the tables. Anything phrased outside
  them lands as `event_type: "other"`. `summary_en` is assembled from matched keywords, not
  translated — it reads like a telegram because it is one. No relative-time parsing, so
  `claimed_time` is always null and corroboration windows run on `received_at`.
- What it buys: zero cost, offline, and identical output every run, so committed artifacts are
  stable and the demo cannot fail on a rate limit.

## D-022 — All data is synthetic, and the console says so continuously **[settled]**

`demo_data.py` fabricates the damage layer, the imagery footprint, and 50 citizen reports
(10 planted fakes). Place names and approximate coordinates are real Sylhet; **everything
else is invented**. `haste_commit` is deliberately zeroed to `0000000`.

- The scenario is built to exercise every verification path: Kanaighat/Companiganj heavy damage
  + independent reports (corroborated), Zindabazar/Ambarkhana assessed-and-undamaged (so flood
  claims there are contradicted), Derai/Sunamganj outside the footprint (no_coverage), and a
  three-post astroturf run from one source in Bishwanath.
- The console carries a permanent scrolling warning banner and the damage layer's provenance
  panel reads "NOT VALIDATED — no accuracy measured". The synthetic layer deliberately has **no**
  `accuracy` block; do not add invented numbers to make the UI look finished.

## D-023 — The brief has a deterministic offline generator, and the UI names which ran **[settled]**

`/api/brief` streams from Gemini when `GEMINI_API_KEY` is set, and otherwise streams a brief
composed **from `sector_scores.json` by code in the route**.

- **Updated by D-037:** the live-model key is now `GROQ_API_KEY` (Groq
  `openai/gpt-oss-120b`), and Gemini is gone. Everything else in this entry
  still holds.
- The fallback is not a canned paragraph: it is generated from the same ranked cells at request
  time, so its figures always match the map.
- The response sets `X-Brief-Generator` and the panel displays "live model" or "offline
  generator". A brief whose origin is ambiguous is worse than no brief.

## D-024 — Telegram bot and Channel 2 (VLM) are not implemented **[settled, per instruction]**

Skipped on request. `bot/` is documentation only. `components.vlm` is `null` for every cell and
the UI renders it as a hatched "no data" meter rather than an empty bar — because an empty bar
reads as zero, and zero is not the same as unknown. The brief states that the VLM weight
contributes nothing.

Verification tiering **was** kept, because `fusion_weight` derives from it and `sector_score`
cannot be computed without it. If "skip social media verification" was meant to include the
tiering itself, say so and I will strip it.

## D-025 — MapLibre's worker is served from `/public`, synced at build time **[settled]**

`scripts/sync-maplibre-worker.mjs` copies `maplibre-gl-worker.mjs` + `maplibre-gl-shared.mjs`
into `console/public/maplibre/` (gitignored) on `predev`/`prebuild`, and `MapView.tsx` calls
`setWorkerUrl("/maplibre/maplibre-gl-worker.mjs")`.

- Why: maplibre-gl v6 is ESM-only and runs its worker as a separate module. Through Turbopack,
  the default resolution produced a worker that connected but never answered: `setData` was
  accepted into `_pendingWorkerUpdate`, `_isUpdatingWorker` stuck at true, `isStyleLoaded()`
  never became true, and **nothing rendered, with no error logged anywhere**. The HUD worked
  perfectly over a blank map.
- Copying from `node_modules` rather than committing the files guarantees the worker always
  matches the installed version. A mismatched worker fails the same silent way.
- Two sibling traps fixed at the same time, both of which also produced a blank map with a
  working HUD: `glyphs: undefined` fails MapLibre's style validation (omit the key), and
  `maplibre-gl.css` must be imported BEFORE Tailwind or its `.maplibregl-map { position:
  relative }` beats `.absolute` and the container collapses to height 0.
- `window.__gtMap` is left as a deliberate debugging handle for exactly this class of bug.

## D-026 — The camera fits the imagery footprint instead of a hardcoded zoom **[settled]**

- Why: at the original zoom 8.6 a 500 m cell is ~1.3 px. Every layer was rendering correctly
  and was visually absent. Fitting to the valid-area bbox also means this keeps working when
  the real Sylhet AOI replaces the synthetic one.

---

## Ship-night triage — logbook

### D-027 — Ship-night pivot: revert from Myanmar/HASTE, upgrade the Telegram tipline **[settled]**

Hours from the deadline, the Myanmar/HASTE path was abandoned (needs 3–5 h of CPU labeling we
do not have). Reverted to the verified Bangladesh Sentinel-1 SAR build, then upgraded the live
tipline with shared GPS, photo capture, and a graceful-degrade VLM hook.

- Why: the bangladesh-flooding22 artifacts are real (Sentinel-1 C-SAR, Open Buildings v3 footprints,
  18,292 buildings / 4,279 damaged at peak) and the two epochs (2022-06-06 / 2022-06-19)
  produce the before/after demo that the kickoff's pitch depends on. The Myanmar work is
  preserved in code paths but not shipped.
- Consequence: this session's exact outcome lives in `DECISIONS.md` (history log) and
  `RUNBOOK_DEMO.md` (cold-start commands). See D-028/D-029/D-030 for the phase-level rules
  that govern the tipline upgrade.
- Revisit if: Myanmar completes; the tipline upgrade is a permanent addition, not a stop-gap.

### D-028 — Shared GPS location is the preferred geocode path over gazetteer text **[settled]**

When a Telegram message carries a `location` object, the tipline uses its `(lat, lon)` directly
and tags `geo.geocode.method = "gps_shared"` with `score=1.0, ambiguous=false, candidates=[the
same point only]`. Text place references still go through the Sylhet GeoNames gazetteer.
Neither present → the tipline holds the claim in a per-chat 10-minute pending buffer and asks
the sender to share location via the attachment menu.

- Why: GPS is the only path that cannot be wrong about the place. Promoting it demotes
  misspelled place strings to "best effort fallback" where they honestly belong.
- Consequence: `geocode.method` enum gains `"gps_shared"`. Replaces the prior
  "GeoNames-fuzzy-or-nothing" gate with two clean paths.

### D-029 — VLM never overrides spatial contradiction; it only modulates within the same tier ladder **[settled]**

- `vlm=contradicts` demotes ONE tier only (corroborated→plausible_unverified→suspect) and adds
  reason `photo_inconsistent_with_claim`. If the spatial check returns `no_coverage`, VLM
  cannot push a signal to `suspect` — NO_COVERAGE stays a hard ceiling (principle §3.4, D-005).
- `vlm=supports` can promote `plausible_unverified` → `corroborated` ONLY when the spatial check
  is NOT `no_coverage`; that gate stops VLM from "corroborating" a report in a place the imagery
  cannot reach.
- `vlm=inconclusive` is a no-op.
- Every VLM-touched signal carries `verifivation.vlm_assessment = {model, status, description,
  experimental: true}` so the Audit Drawer and the brief can call it out as experimental.
- Why: VLM is "experimental" not "authoritative" — it is a heuristic running on top of
  opacity. Spatial consistency vs the satellite layer is the load-bearing signal. Letting VLM
  move a signal outside the spatial ladder is exactly the failure mode handoff §3.2 ("provenance
  travels with the artifact; never stamp false provenance") warns against.
- Cost: the extra code path is opt-in (no VLM key present → no VLM call → bot loop identical
  to before). The console renders the assessment as a clearly labeled line; it does not
  change tier promotion visuals or ranking.
- Revisit if: we ever run the VLM against a held-out VLM ground-truth set and produce
  measured precision/recall per tier. Until then, "experimental" is the honest label.

### D-030 — Bot never stores Telegram user ids, phone numbers, or display names (privacy invariant) **[settled]**

Already enforced in the original tipline (`pseudonym` over `GT_TIPLINE_SALT`). The upgrade
keeps this intact: the only field that carries the user is the salted hash. `message.photo`
files are written to `console/public/data/tips/<signal_id>.jpg` with the signal id only —
no file id, no user id, no caption-derived personal name in the path.

- Why: D-013/D-024/bot/README are explicit that identifying information must not survive
  the trip from Telegram's servers to our disk, ever. A disaster-reporting app that leaks
  reporter identities is a real harm scenario, not a hypothetical one.


## D-031 — Telegram tips not landing: diagnosis, not yet root cause **[open]**

User reported: Telegram tip sent to the bot, no pin on the dashboard within ~4 s. Bot was
running with TELEGRAM_BOT_TOKEN and GT_TIPLINE_SALT set.

Per the brief's checkpoint protocol, ran the diagnostic pass first, did NOT rewrite the bot.

**Checkpoint 0 — manual injection (Tipline().handle()):** Green. A "Water rising in
Companiganj, people stranded" tip with user_id=999 returned tier=plausible_unverified and a
fully populated geo block, and wrote console/public/data/live_signals.json correctly. Pipeline
side is healthy.

**Checkpoint 3 — write path:** Already absolute. LIVE_OUT = ROOT/'console'/'public'/'data'/'live_signals.json'
where ROOT = Path(__file__).resolve().parents[1]. CWD-independent. Startup log confirms:
LIVE_OUT=F:\HackaDhon Project\groundtruth\console\public\data\live_signals.json (absolute? True).
**Not the bug.**

**Checkpoint 4 — dev server serving:** live_signals.json does not exist after the manual
injection only because the bot never wrote it. Once a write happens, Next.js serves /data/*
from public/ with no caching. **Not the bug yet — bot never wrote.**

**Checkpoint 5 — polling/merge:** Console.tsx already polls
fetch('/data/live_signals.json', { cache: 'no-store' }) every 4 s and merges by signal_id.
**Not the bug.**

**Checkpoint 1 — receive layer:** Cannot fully diagnose from this shell because the user's
TELEGRAM_BOT_TOKEN was set in their session, not the one this session can see. Added
diagnostic instrumentation (top-of-handler raw-update log on stderr, exception wrapper that
prints full traceback, startup getMe probe that fails loudly on 401/404, 60-second heartbeat,
distinct 409 Conflict message if a second bot instance is polling). A bot launched with
TELEGRAM_BOT_TOKEN=DIAG_ONLY_NO_TOKEN_SET produced exactly the expected behaviour:
getMe FAILED HTTP 404, refused to enter the poll loop, exit code 2.

**Implication:** The most likely failure modes that the new instrumentation will reveal are
1) token mismatch/revocation, 2) a stale bot instance still holding the long-poll lease, or
3) Telegram returns 200 with an empty result (which would mean the test message never reached
the bot — wrong chat id, or @BotFather bot is not the one the user messaged). Operator must
tail stderr on the next bot launch to see which.

**No bot code logic was changed** — diagnostic lines only. The original try/except around
process_message already existed; only the catch-body was enriched to print the traceback.
The poll loop's exception handler was split into urllib.error.HTTPError (with a dedicated
409 Conflict message) and Exception (the previous behaviour).

## D-032 — Bug was "bot wasn't running", not "bot can't talk to Telegram" **[settled]**

D-031 ended with the receive layer as the suspected failure point and instrumentation in place to localize it. With the user's environment (TELEGRAM_BOT_TOKEN in `.env`), the actual answer came out on first run.

**What was actually wrong:** the bot was not running. `tasklist /fi "imagename eq python.exe"` returned nothing. The console dev server on `:3000` (PID 7296, started earlier in the day) was healthy and polling `/data/live_signals.json` every 4 s — and serving `[]` because no bot had ever written anything. So Telegram messages reached the user's bot (@groundtruth_tip_bot, confirmed via getMe) and were simply ignored: nothing was polling.

**Why this was hard to see:** running `python bot/tipline.py` in a shell, Ctrl+C'ing or closing the shell, leaves no Python process. The dev server, by contrast, runs inside a child process tree that survives the shell, so it appeared to be the only thing alive. The "nothing happens" symptom was indistinguishable from "bot crashed during processing".

**Fixes applied:**

1. `bot/tipline.py` — diagnostic instrumentation per D-031 is kept. Top-of-handler raw-update log, full traceback on exception, startup getMe probe with loud 401/404 exit, 60-second heartbeat, distinct 409 Conflict message. No logic changes.

2. `run_bot.py` (NEW, project root) — small launcher that reads `TELEGRAM_BOT_TOKEN` and `GT_TIPLINE_SALT` from `.env`, sets `PYTHONPATH=pipeline/src`, and spawns `bot/tipline.py` as a child via `subprocess.call` (not `os.execv`, which mishandles paths with spaces). Prints a banner so the operator can confirm cwd and PYTHONPATH. The bot stays alive until the launcher is Ctrl+C'd.

3. Operator workflow (the actual fix the user needs):
   - Make sure the console dev server is running: `cd console; npm run dev`
   - In a separate shell: `python run_bot.py`
   - Banner confirms `[run_bot] launching ... [tipline] getMe ok: bot='groundtruth_tip_bot'`
   - Send a Telegram message to that bot. Within ~4 s it appears on the dashboard.
   - To diagnose: `tail -F bot.stderr.log` (the launcher writes stderr there when launched via Start-Process). Heartbeat tick every 60 s proves polling is happening; `[tipline] recv chat=... text=...` proves the message arrived; `[tipline] poll HTTP 409` means a duplicate bot is holding the lease (kill it).

**End-to-end live proof run during diagnosis:** the launcher reached `getMe ok: bot='groundtruth_tip_bot'`, a synthetic signal was injected via `Tipline().handle()` and written to `console/public/data/live_signals.json`, and `Invoke-WebRequest http://localhost:3000/data/live_signals.json` returned the new signal's content with HTTP 200. Browser tab on `:3000` will pick it up on its next 4-second poll.

**Files in this commit:**
- `run_bot.py` — new launcher; handles `.env` lookup and process spawning
- `bot/tipline.py` — diagnostic instrumentation only (D-031)
- `DECISIONS.md` — D-031, D-032 entries

## D-033 — VLM path was failing on two fronts, not "no provider" **[settled]**

User reported the bot's photo ack saying `photo review: inconclusive (no model) — no VLM provider available (set GEMINI_API_KEY or GROQ_API_KEY)` even though `GROQ_API_KEY` is in `.env`. D-032 had identified "bot wasn't running" as the first blocker; once that was fixed the same symptom reappeared on the photo path, so we dug deeper.

**Two distinct bugs were stacked:**

1. **`run_bot.py` was forwarding only two keys from `.env`.** The launcher's first version enumerated `TELEGRAM_BOT_TOKEN` and `GT_TIPLINE_SALT` only, so even though `GROQ_API_KEY` was present in `.env`, it never reached the child Python process. `vlm_check` then fell through to its no-provider branch. Fixed by replacing the explicit list with `for k, v in env.items(): if k not in os.environ: os.environ[k] = v` (shell env still wins). Added a banner line `[run_bot] VLM providers: GEMINI=<set|MISSING> GROQ=<set|MISSING>` so the operator can see at a glance which keys reached the process. Also added `PYTHONUNBUFFERED=1` and `flush=True` on launcher prints — `Start-Process -RedirectStandardOutput` was block-buffering stdout/stderr on Windows, so the banner never appeared in `bot.stdout.log` even when the process was healthy.

2. **`urllib` on Windows + Cloudflare-fronted APIs = 403-1010.** Even with the key forwarded, hitting `https://api.groq.com/openai/v1/chat/completions` from Python on this machine returned Cloudflare error 1010 ("the owner has banned your access based on your browser's signature"). The default `User-Agent: Python-urllib/3.x` is fingerprinted by Cloudflare. Once a Chrome-class `User-Agent` header was added, the request reached the API. The error then surfaced the *real* problem: the model the bot had configured (`llama-3.2-11b-vision-preview`) was **decommissioned on 2026-04-14** in favour of `meta-llama/llama-4-scout-17b-16e-instruct`, which was itself decommissioned 2026-07-17. The current Groq vision model is `qwen/qwen3.6-27b`. Both fixes applied in `bot/vlm_check.py`: `model_id = "qwen/qwen3.6-27b"` and a module-level `_BROWSER_UA` constant sent on both Gemini and Groq `Request` headers.

**Why this was hard to see:** the safe-default `_inconclusive(...)` message in `vlm_check.assess_photo` is identical whether the provider list is empty, every provider raised, or auth failed. The Cloudflare block looked identical to "key missing" until we hit Groq directly and saw `error code: 1010`. The model deprecation looked identical to "key missing" until we hit Groq with the UA fix and saw `model_decommissioned`. **Lesson:** when the inconclusive path is the only signal the operator sees, every distinct failure mode needs a distinct diagnostic surface — direct Groq probe + HTTP code, not just the final user-facing string.

**After the fix, end-to-end smoke** (`_smoke_vlm.py`):
```
=== ACK ===
photo review: inconclusive (qwen/qwen3.6-27b) ...
=== signal verification ===
"vlm_assessment": {
  "status": "inconclusive",
  "model": "qwen/qwen3.6-27b",
  "description": "a satellite imagery analysis tool or GIS map interface, not a photograph of the ground ...",
  "assessed_at": "2026-07-28T16:26:30Z"
}
```
Model is named (not `null`), status is the schema-correct verdict, description is the model's own reasoning (the test photo is a screenshot of a satellite-imagery viewer, which is correctly `inconclusive` for a claim about flooding — exactly the credibility-layer behaviour D-029 specified).

**Files in this commit:**
- `bot/vlm_check.py` — Groq model swap + User-Agent header on both providers
- `run_bot.py` — bulk-forward all `.env` keys; VLM provider banner; `flush=True`
- `DECISIONS.md` — this entry

**Follow-ups (not blocking ship-night):** Qwen3.6 emits `think` blocks in plain text. Status detection already handles them correctly (default `inconclusive` when no JSON verdict appears), but a future revision could strip the think block before JSON parsing to recover the structured verdict when present.

### D-034 — SAR provenance must name a real pinned commit **[settled]**

The committed Bangladesh damage layer carried
`classifier_ref: "mitchellthomas1/S1-Flood-Bangladesh@<commit>"` — a literal
`<commit>` placeholder. It read like provenance and named nothing re-runnable.

- **Why it survived so long:** the schema's `examples` for that field was
  *itself* `"mitchellthomas1/S1-Flood-Bangladesh @ <commit>"`. The placeholder was
  the documented example, so copying the documented example produced it. The
  HASTE branch already required a real `haste_commit`; the SAR branch required
  nothing. Fixed at three levels:
  1. `sentinel1_to_damage_layer.py` refuses `--classifier-ref` /`--footprint-source`
     values matching `<...>`, `commit`, `todo`, `tbd`, `fixme`, `xxx`. It exits
     non-zero **and writes no file** — a bad ref must not reach an artifact.
  2. `damage_layer.schema.json` adds `classifier_ref` to the `sentinel1_sar`
     branch's `required`, plus a negative-lookahead `pattern` so validation
     rejects a placeholder even if the converter is bypassed.
  3. The misleading `examples` value was replaced with a real pinned ref.
- **Contract impact:** adding to `required` is not a rename, so `contract_version`
  stays **1.0.0**. Per `contracts/README.md` this still gets a D-NNN entry, which
  is this one. The HASTE example layer is unaffected (it carries `haste_commit`).
- **Provenance corrected to** `mitchellthomas1/S1-Flood-Bangladesh@416e8db`
  across `data/raw/sentinel1/` (×3), `data/processed/`, and both epochs.
- **Verified non-substantive:** re-running the converter changed *only*
  provenance. 0/18,292 `damage_class` differences, 0 `area_m2`/`grid_cell_id`
  differences, 0/782 sector-score differences, 0/50 signal-tier differences. The
  sole other delta was `generated_at` — which is the determinism D-021 promised.
- Revisit if: we ever cite a classifier by DOI/registry rather than a repo SHA,
  in which case `pattern` needs widening.

### D-035 — The epoch sync must fail loudly, not silently **[settled]**

`console/scripts/sync-data.mjs` shipped for two commits with its epoch-copy code
missing — only the first line of the explanatory comment had been pasted across
from its near-identical twin `syncdata.mjs`, which no npm script ever invoked. The
console's SAR PASS toggle therefore never rendered, locally or on Vercel.

- **Why nobody noticed:** the twin wrapped the whole block in `try { ... } catch {}`
  and logged nothing on failure. A sync step that cannot report its own failure
  is indistinguishable from a sync step that has nothing to do.
- **Fix:** the working block now lives in the invoked script; `syncdata.mjs` is
  deleted. The blanket catch is deliberately **not** reproduced —
  `epochs/` existing in the source is a promise made to the console, so failing to
  deliver it logs an error and sets `process.exitCode = 1` rather than passing
  quietly. Absence of `epochs/` (synthetic demo, nothing built yet) stays silent,
  because that is legitimate.
- **Root cause was duplication, not omission.** Two files with near-identical
  names and divergent contents, one wired up and one not. Keeping a single
  `sync-data.mjs` is the fix; do not reintroduce a second.
- Note `build_epoch.py` also dual-writes epochs into both trees, so the toggle
  has two independent paths to it. Keep both.

### D-036 — Irreplaceable SAR inputs are committed; converter outputs are not **[settled]**

`data/raw/` was gitignored wholesale, so the two building-join GeoJSONs and two
flood-mask GeoTIFFs the damage layer is built from existed only on one machine. A
fresh clone got `data/processed/` but could not rebuild the layer — `build_all`
would silently fall back to the synthetic demo.

- **Now committed (18.4 MB):** `sylhet_buildings_flood.geojson`,
  `sylhet_buildings_flood_pre.geojson`, `flood_mask_2022-06-06.tif`,
  `flood_mask_2022-06-19.tif`, `valid_area.geojson`.
- **Still ignored:** the three `data/raw/sentinel1/damage_layer*.geojson` files.
  They are *outputs* of `sentinel1_to_damage_layer`, byte-reproducible from the
  inputs above (verified: 0/18,292 `damage_class` differences across both epochs),
  and the same content is already committed under `data/processed/`. Committing
  them would add ~36 MB for nothing.
- **Two gitignore traps, both now documented inline in `.gitignore`:**
  1. The rule must be `/data/raw/*`, **not** `/data/raw/` — git cannot re-include
     a file whose parent directory is itself excluded, so the negations would
     never match.
  2. `!/data/raw/sentinel1/` re-includes the whole directory, outputs included.
     Since the last matching pattern wins, an explicit re-ignore of the outputs
     must come *after* the negations.
- Why it matters: this is the same principle as D-004/D-009. An assessment nobody
  can re-run is not evidence, and neither is one nobody can rebuild.

### D-037 — Gemini removed entirely; Groq for text, OpenRouter for images **[settled]**

Provider consolidation. Gemini is gone from the codebase — not deprecated,
not second-choice, absent.

| Job | Provider | Model | Env key |
|---|---|---|---|
| **Text** (the `/api/brief` allocation brief) | Groq | `openai/gpt-oss-120b` | `GROQ_API_KEY` |
| **Image** (Telegram photo VLM, D-029) | OpenRouter | `thinkingmachines/inkling:free` | `OPENROUTER_API_KEY` |

- **Both model ids were verified against the providers' own listings before any
  code was written**, per principle §3.6. `openai/gpt-oss-120b` appears in
  Groq's supported-models table as a *production* model (131,072 ctx,
  $0.15/$0.60 per 1M, ~500 tok/s). `thinkingmachines/inkling:free` appears in
  OpenRouter's public `/api/v1/models` with `image` among its declared **input**
  modalities — which is the thing that actually had to be checked, since a
  text-only model would have made the VLM quietly useless.
- **Text LLM.** `/api/brief` moves from `streamGemini` (Google's native
  `streamGenerateContent` shape) to `streamGroq` (OpenAI-compatible
  `chat/completions`). The SSE frame parser changes accordingly:
  `choices[0].delta.content` instead of `candidates[0].content.parts[]`.
  gpt-oss is a *reasoning* model, so the request sets `reasoning_effort: "low"`
  and the parser reads **only** `delta.content` — the reasoning trace arrives
  separately and is deliberately not shown to a responder. `X-Brief-Generator`
  now reports `groq-attempted`.
- **Image VLM.** `bot/vlm_check.py` loses both previous providers and the
  bespoke `_call_gemini` (which used Google's `inline_data` envelope). What
  remains is a single `_call_openai_compatible` helper, because OpenRouter
  speaks the same OpenAI wire format Groq did. `PROVIDERS` is still a tuple and
  `assess_photo` still loops, so adding a second image provider later is a
  dict entry, not a rewrite.
- **The Cloudflare UA stays (D-033).** D-033 established that a default
  `Python-urllib` / `node` User-Agent gets `403-1010` from these edges. OpenRouter
  is fronted the same way, so `_BROWSER_UA` is retained in Python and a
  `BROWSER_UA` header was added to the Node fetch for the same reason.
- **Contract impact:** `signal.schema.json`'s `vlm_assessment.model`
  description/examples and both committed signal fixtures were updated from
  `gemini-2.5-flash` to `thinkingmachines/inkling:free`. `model` is a free
  string, so this is documentation-only — no validation change, no version bump.
- **D-021 is unaffected and still correct.** Extraction remains rule-based and
  still raises rather than falling back. Its error message no longer blames a
  missing `GEMINI_API_KEY`, because a text model *does* now exist (Groq) and
  pointing at it would invite someone to wire extraction to a brief-writing
  model. The reason extraction is off is editorial, not a missing credential.
- Revisit if: OpenRouter retires the `:free` tier (the VLM would go dark and
  `assess_photo` would return `inconclusive`, which is the safe default), or if
  `gpt-oss-120b` is superseded on Groq — D-033 is the precedent for how to
  handle a model deprecation here: verify against the live listing first.

