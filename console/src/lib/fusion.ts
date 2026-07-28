/**
 * Live re-scoring in the browser.
 *
 * The committed `sector_scores.json` is the state of the world with EVERY signal
 * present. During replay we only know about signals that have "arrived" so far,
 * so the queue has to be recomputed as they land -- that live re-rank is the
 * actual product claim, not decoration.
 *
 * ⚠️  THIS MUST MATCH pipeline/src/groundtruth/fuse.py.
 * The damage component is reused verbatim from the artifact (imagery does not
 * change during a replay), so only the citizen component and the final weighted
 * sum are recomputed here. If you change SATURATION or the score formula in
 * fuse.py, change it here in the same commit or the replay will silently
 * disagree with the committed file.
 */

import type { SectorCell, SectorScores, Signal, Urgency } from "./types";

/** Must equal fuse.py SATURATION. */
export const SATURATION = 1.6;

const DEFAULT_URGENCY_MULTIPLIERS: Record<Urgency, number> = {
  critical: 1.0,
  high: 0.75,
  medium: 0.5,
  low: 0.25,
};

export interface LiveCell extends SectorCell {
  /** Rank in the live re-score, 1 = go here first. */
  liveRank: number;
  /** Score from arrived signals only, normalised 0..1 across cells. */
  liveScore: number;
  /** Signals that have arrived in this cell, any tier. */
  arrivedSignals: Signal[];
  arrivedCorroborated: number;
  arrivedPlausible: number;
  arrivedSuspect: number;
  /** True when this cell moved up since the previous re-score. Drives the UI flash. */
  movedUp?: boolean;
}

/**
 * Recompute cell scores using only the signals supplied.
 *
 * Mirrors fuse.py exactly: missing channels contribute ZERO and the denominator
 * is the sum of all weights. We deliberately do not renormalise over available
 * channels -- doing so rewards cells for having less evidence. See fuse.py's
 * module docstring for the full argument.
 */
export function rescore(
  scores: SectorScores,
  arrived: Signal[],
): LiveCell[] {
  const urgencyMult = scores.weights.urgency_multipliers ?? DEFAULT_URGENCY_MULTIPLIERS;
  const w = scores.weights;
  const totalWeight = w.damage + w.vlm + w.citizen;

  // Bucket arrived signals by cell.
  const byCell = new Map<string, Signal[]>();
  for (const signal of arrived) {
    const cellId = signal.geo?.grid_cell_id;
    if (!cellId) continue; // unmappable signals belong to no cell, by contract
    const list = byCell.get(cellId);
    if (list) list.push(signal);
    else byCell.set(cellId, [signal]);
  }

  const raw: { cell: SectorCell; score: number; signals: Signal[] }[] = [];

  for (const cell of scores.cells) {
    const signals = byCell.get(cell.cell_id) ?? [];

    let load = 0;
    for (const signal of signals) {
      const mult = urgencyMult[signal.claim.urgency] ?? 0.5;
      // fusion_weight already includes the tier multiplier and the geocode
      // confidence. Do not multiply by tier again here.
      load += signal.verification.fusion_weight * mult;
    }
    const citizen = signals.length > 0 ? 1 - Math.exp(-load / SATURATION) : null;

    const damage = cell.components.damage;
    const vlm = cell.components.vlm;

    let weighted = 0;
    if (damage !== null) weighted += w.damage * damage;
    if (vlm !== null) weighted += w.vlm * vlm;
    if (citizen !== null) weighted += w.citizen * citizen;

    raw.push({
      cell: { ...cell, components: { ...cell.components, citizen } },
      score: totalWeight > 0 ? weighted / totalWeight : 0,
      signals,
    });
  }

  const peak = raw.reduce((m, r) => (r.score > m ? r.score : m), 0);

  const live: LiveCell[] = raw.map(({ cell, score, signals }) => {
    let corroborated = 0;
    let plausible = 0;
    let suspect = 0;
    for (const s of signals) {
      if (s.verification.tier === "corroborated") corroborated++;
      else if (s.verification.tier === "plausible_unverified") plausible++;
      else suspect++;
    }
    return {
      ...cell,
      liveScore: peak > 0 ? score / peak : 0,
      liveRank: 0,
      arrivedSignals: signals,
      arrivedCorroborated: corroborated,
      arrivedPlausible: plausible,
      arrivedSuspect: suspect,
    };
  });

  live.sort((a, b) =>
    b.liveScore - a.liveScore || a.cell_id.localeCompare(b.cell_id),
  );
  live.forEach((cell, i) => {
    cell.liveRank = i + 1;
  });

  return live;
}

/** Signals whose replay offset has elapsed. */
export function arrivedAt(signals: Signal[], elapsedSeconds: number): Signal[] {
  return signals.filter((s) => (s.source.replay_offset_s ?? 0) <= elapsedSeconds);
}

/** Latest replay offset in the corpus, i.e. when the replay is over. */
export function replayDuration(signals: Signal[]): number {
  return signals.reduce(
    (max, s) => Math.max(max, s.source.replay_offset_s ?? 0),
    0,
  );
}

/**
 * Live headline counts. Kept here so the top bar and the queue cannot drift
 * apart by computing them separately.
 */
export function summarise(cells: LiveCell[], arrived: Signal[]) {
  let corroborated = 0;
  let plausible = 0;
  let suspect = 0;
  let unmappable = 0;
  let personsAtRisk = 0;
  const sources = new Set<string>();

  for (const s of arrived) {
    sources.add(s.source.source_id);
    if (s.verification.tier === "corroborated") corroborated++;
    else if (s.verification.tier === "plausible_unverified") plausible++;
    else suspect++;
    if (!s.geo) unmappable++;
    // Suspect claims contribute nothing to a headline number a responder reads.
    if (s.verification.tier !== "suspect" && typeof s.claim.persons_at_risk === "number") {
      personsAtRisk += s.claim.persons_at_risk;
    }
  }

  const activeCells = cells.filter((c) => c.arrivedSignals.length > 0).length;
  const unassessedWithReports = cells.filter(
    (c) => c.coverage?.status === "unassessed" && c.arrivedSignals.length > 0,
  ).length;

  return {
    signals: arrived.length,
    corroborated,
    plausible,
    suspect,
    unmappable,
    personsAtRisk,
    distinctSources: sources.size,
    activeCells,
    unassessedWithReports,
  };
}
