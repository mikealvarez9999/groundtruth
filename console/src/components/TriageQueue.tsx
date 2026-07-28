"use client";

/**
 * The right rail: ranked "go here first" list.
 *
 * Two things this component refuses to do:
 *   - show a score without the counts behind it (every card carries its reasons)
 *   - let an UNASSESSED cell look like a low-priority one. Those get an explicit
 *     amber "NO IMAGERY" marker, because a low score there means "we could not
 *     look", not "it is fine".
 */

import { useEffect, useRef } from "react";
import type { LiveCell } from "@/lib/fusion";
import { CountUp, URGENCY_STYLE } from "./ui";

interface Props {
  cells: LiveCell[];
  selectedCellId: string | null;
  onSelect: (cellId: string) => void;
  limit?: number;
}

function scoreColor(score: number, unassessed: boolean) {
  if (unassessed) return "text-slate-300";
  if (score >= 0.8) return "text-rose-400";
  if (score >= 0.6) return "text-orange-400";
  if (score >= 0.35) return "text-amber-300";
  return "text-cyan-300";
}

export default function TriageQueue({
  cells,
  selectedCellId,
  onSelect,
  limit = 12,
}: Props) {
  // Only cells with something to say. A cell with no reports and no damage
  // sample is noise in a queue that is supposed to direct people.
  const ranked = cells
    .filter(
      (c) =>
        c.arrivedSignals.length > 0 ||
        (c.components.damage !== null && (c.evidence.buildings_damaged ?? 0) > 0),
    )
    .slice(0, limit);

  // `place_label` is the NEAREST gazetteer place, so several adjacent 500 m cells
  // legitimately share one name and the queue showed "Kanaighat" twice with no way
  // to tell them apart. Append a short cell discriminator only where a name repeats.
  const labelCounts = new Map<string, number>();
  for (const cell of ranked) {
    const key = cell.place_label ?? cell.cell_id;
    labelCounts.set(key, (labelCounts.get(key) ?? 0) + 1);
  }
  const discriminator = (cell: LiveCell): string | null => {
    const key = cell.place_label ?? cell.cell_id;
    if ((labelCounts.get(key) ?? 0) < 2) return null;
    const [, ix, iy] = cell.cell_id.split("_");
    return `${ix.slice(-3)}/${iy.slice(-3)}`;
  };

  // Flash a row that climbed the ranking.
  //
  // Done by touching the DOM class directly rather than via state: the queue
  // re-scores up to ten times a second during a fast replay, and a setState per
  // re-score just to drive a 1.2s decoration causes a cascading re-render of the
  // whole list. Adding a class to an existing node is exactly the "synchronise
  // with an external system" case effects are for.
  const prevRanks = useRef<Map<string, number>>(new Map());
  const rowRefs = useRef<Map<string, HTMLLIElement>>(new Map());

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    for (const cell of ranked) {
      const before = prevRanks.current.get(cell.cell_id);
      if (before === undefined || cell.liveRank >= before) continue;
      const el = rowRefs.current.get(cell.cell_id);
      if (!el) continue;
      el.classList.remove("gt-flash-up");
      // Force a reflow so re-adding the class restarts the animation.
      void el.offsetWidth;
      el.classList.add("gt-flash-up");
      timers.push(
        setTimeout(() => el.classList.remove("gt-flash-up"), 1200),
      );
    }
    prevRanks.current = new Map(ranked.map((c) => [c.cell_id, c.liveRank]));
    return () => timers.forEach(clearTimeout);
  }, [ranked]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex items-baseline justify-between border-b border-slate-800/90 px-3 py-2">
        <h2 className="text-[11px] font-semibold tracking-[0.2em] text-slate-200">
          TRIAGE QUEUE
        </h2>
        <span className="gt-label">{ranked.length} sectors</span>
      </header>

      {ranked.length === 0 ? (
        <p className="px-3 py-6 text-[11px] leading-relaxed text-slate-500">
          No sector has evidence yet. Start the replay to stream citizen signals in.
        </p>
      ) : (
        <ol className="flex-1 divide-y divide-slate-800/60 overflow-y-auto">
          {ranked.map((cell, i) => {
            const unassessed = cell.coverage?.status === "unassessed";
            const selected = cell.cell_id === selectedCellId;
            return (
              <li
                key={cell.cell_id}
                ref={(el) => {
                  if (el) rowRefs.current.set(cell.cell_id, el);
                  else rowRefs.current.delete(cell.cell_id);
                }}
                style={{ ["--i" as string]: i }}
                className="gt-rise gt-stagger"
              >
                <button
                  onClick={() => onSelect(cell.cell_id)}
                  className={`group w-full cursor-pointer px-3 py-2.5 text-left transition-colors ${
                    selected ? "bg-cyan-500/10" : "hover:bg-slate-800/40"
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <span
                      className={`mt-px w-5 shrink-0 text-right text-[13px] leading-none font-bold ${
                        cell.liveRank <= 3 ? "text-cyan-300" : "text-slate-500"
                      }`}
                    >
                      {cell.liveRank}
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[12px] font-semibold text-slate-100">
                          {cell.place_label ?? cell.cell_id}
                        </span>
                        {discriminator(cell) ? (
                          <span
                            className="shrink-0 text-[8px] text-slate-600"
                            title={`Cell ${cell.cell_id} — several adjacent cells share the nearest place name`}
                          >
                            {discriminator(cell)}
                          </span>
                        ) : null}
                        {cell.urgency_max ? (
                          <span
                            className={`text-[8px] font-bold tracking-wider ${URGENCY_STYLE[cell.urgency_max]}`}
                          >
                            {cell.urgency_max.toUpperCase()}
                          </span>
                        ) : null}
                      </div>

                      {/* score bar */}
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className={`h-full rounded-full transition-[width] duration-700 ease-out ${
                            unassessed
                              ? "bg-slate-500"
                              : cell.liveScore >= 0.6
                                ? "bg-gradient-to-r from-orange-500 to-rose-500"
                                : "bg-gradient-to-r from-cyan-600 to-cyan-300"
                          }`}
                          style={{ width: `${Math.max(2, cell.liveScore * 100)}%` }}
                        />
                      </div>

                      <ul className="mt-1.5 space-y-0.5">
                        {(cell.top_reasons ?? []).slice(0, 2).map((reason) => (
                          <li
                            key={reason}
                            className="text-[10px] leading-snug text-slate-400"
                          >
                            {reason}
                          </li>
                        ))}
                      </ul>

                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        {unassessed ? (
                          <span className="border border-amber-500/50 bg-amber-500/10 px-1 text-[8px] font-semibold tracking-wider text-amber-300">
                            NO IMAGERY
                          </span>
                        ) : null}
                        {cell.arrivedCorroborated > 0 ? (
                          <span className="border border-cyan-500/40 bg-cyan-500/10 px-1 text-[8px] text-cyan-300">
                            {cell.arrivedCorroborated} corrob
                          </span>
                        ) : null}
                        {cell.arrivedPlausible > 0 ? (
                          <span className="border border-amber-500/40 bg-amber-500/10 px-1 text-[8px] text-amber-300">
                            {cell.arrivedPlausible} recon
                          </span>
                        ) : null}
                        {cell.arrivedSuspect > 0 ? (
                          <span className="gt-blink border border-rose-500/50 bg-rose-500/10 px-1 text-[8px] text-rose-300">
                            {cell.arrivedSuspect} suspect
                          </span>
                        ) : null}
                        {typeof cell.persons_at_risk_est === "number" ? (
                          <span
                            className="border border-slate-600 px-1 text-[8px] text-slate-300"
                            title="Sum of explicitly stated counts only. A floor, not a population estimate."
                          >
                            ≥{cell.persons_at_risk_est} at risk
                          </span>
                        ) : null}
                      </div>
                    </div>

                    <span
                      className={`shrink-0 text-[15px] leading-none font-bold ${scoreColor(
                        cell.liveScore,
                        unassessed,
                      )}`}
                    >
                      <CountUp value={cell.liveScore * 100} decimals={0} />
                    </span>
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
      )}

      <footer className="border-t border-slate-800/90 px-3 py-1.5">
        <p className="text-[9px] leading-snug text-slate-500">
          Score is relative to the highest-ranked sector in this run. Not comparable
          across runs.
        </p>
      </footer>
    </div>
  );
}
