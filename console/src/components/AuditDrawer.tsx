"use client";

/**
 * The Audit Drawer.
 *
 * This is the most important panel in the product and the least flashy on
 * purpose. It exists so a human can overrule us. Every entry shows:
 *   - the original text, unedited
 *   - the stated reason for the ruling, verbatim from the pipeline
 *   - the geocode that placed it, including runner-up candidates
 *   - the imagery counts the ruling was based on
 *
 * Suspect signals are NEVER deleted from the data (DECISIONS.md D-008). They are
 * weighted to zero and listed here. Silently dropping a report we judged false is
 * the same failure as believing a fake, just invisible.
 */

import { useState } from "react";
import type { Signal, Tier } from "@/lib/types";
import { firstPhotoPath, PhotoThumb, TierBadge, VlmPill } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
  signals: Signal[];
}

type Filter = "suspect" | "plausible_unverified" | "unmappable" | "all";

const FILTERS: { key: Filter; label: string }[] = [
  { key: "suspect", label: "Suspect" },
  { key: "plausible_unverified", label: "Unverified" },
  { key: "unmappable", label: "Unmappable" },
  { key: "all", label: "All" },
];

function matches(signal: Signal, filter: Filter): boolean {
  if (filter === "all") return true;
  if (filter === "unmappable") return !signal.geo;
  return signal.verification.tier === (filter as Tier);
}

export default function AuditDrawer({ open, onClose, signals }: Props) {
  const [filter, setFilter] = useState<Filter>("suspect");
  const rows = signals.filter((s) => matches(s, filter));

  const counts = {
    suspect: signals.filter((s) => s.verification.tier === "suspect").length,
    plausible_unverified: signals.filter(
      (s) => s.verification.tier === "plausible_unverified",
    ).length,
    unmappable: signals.filter((s) => !s.geo).length,
    all: signals.length,
  };

  return (
    <div
      className={`pointer-events-none absolute inset-x-0 bottom-0 z-30 transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
        open ? "translate-y-0" : "translate-y-full"
      }`}
      aria-hidden={!open}
    >
      <div className="gt-panel gt-bracket pointer-events-auto mx-3 mb-3 flex max-h-[52vh] flex-col overflow-hidden">
        <header className="flex flex-wrap items-center gap-3 border-b border-slate-800/90 px-3 py-2">
          <h2 className="text-[11px] font-semibold tracking-[0.2em] text-slate-200">
            AUDIT DRAWER
          </h2>

          <div className="flex items-center gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                className={`cursor-pointer border px-2 py-0.5 text-[9px] tracking-wider transition-colors ${
                  filter === f.key
                    ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-300"
                    : "border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200"
                }`}
              >
                {f.label} {counts[f.key]}
              </button>
            ))}
          </div>

          <p className="hidden flex-1 text-[9px] leading-snug text-slate-500 lg:block">
            Nothing here is deleted from the dataset. Suspect items carry zero weight
            and stay on the record so you can overrule the call.
          </p>

          <button
            onClick={onClose}
            className="ml-auto cursor-pointer border border-slate-700 px-2 py-0.5 text-[9px] text-slate-400 transition-colors hover:border-slate-500 hover:text-slate-100"
          >
            CLOSE ▾
          </button>
        </header>

        <div className="overflow-y-auto">
          {rows.length === 0 ? (
            <p className="px-3 py-6 text-[11px] text-slate-500">
              Nothing in this category yet.
            </p>
          ) : (
            <ul className="divide-y divide-slate-800/60">
              {rows.map((signal, i) => {
                const check = signal.verification.spatial_check;
                return (
                  <li
                    key={signal.signal_id}
                    style={{ ["--i" as string]: Math.min(i, 10) }}
                    className="gt-rise gt-stagger px-3 py-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <TierBadge tier={signal.verification.tier} />
                      <span className="text-[9px] text-slate-500">
                        {signal.signal_id}
                      </span>
                      <span className="text-[9px] text-slate-500">
                        src {signal.source.source_id}
                      </span>
                      {check?.status ? (
                        <span
                          className={`text-[9px] ${
                            check.status === "contradicted"
                              ? "text-rose-400"
                              : check.status === "no_coverage"
                                ? "text-amber-400"
                                : "text-slate-500"
                          }`}
                        >
                          spatial: {check.status}
                        </span>
                      ) : null}
                      <span className="ml-auto text-[9px] text-slate-500">
                        weight {signal.verification.fusion_weight.toFixed(2)}
                      </span>
                    </div>

                    <p className="mt-1.5 text-[11px] leading-snug text-slate-200">
                      {signal.raw?.text ?? "(no text)"}
                    </p>

                    {/* Optional Telegram photo + VLM verdict. Both come from
                        the bot: photo_path is stored at tip time,
                        vlm_assessment is filled by bot/vlm_check.py and
                        modulates (never overrides) the spatial tier. */}
                    {(() => {
                      const pp = firstPhotoPath(signal);
                      const va = signal.verification?.vlm_assessment;
                      if (!pp && !va) return null;
                      return (
                        <div className="mt-1.5 flex flex-wrap items-start gap-3">
                          {pp ? <PhotoThumb photoPath={pp} alt={signal.signal_id} /> : null}
                          {va ? <VlmPill vlm={va} /> : null}
                        </div>
                      );
                    })()}

                    {/* The ruling, verbatim from the pipeline. Never LLM-written. */}
                    <p className="mt-1.5 border-l-2 border-slate-700 pl-2 text-[10px] leading-relaxed text-slate-400">
                      {signal.verification.reason}
                    </p>

                    <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[9px] text-slate-500">
                      <span>
                        claimed place:{" "}
                        <span className="text-slate-300">
                          {signal.claim.location_ref || "—"}
                        </span>
                      </span>
                      {signal.geo ? (
                        <>
                          <span>
                            matched:{" "}
                            <span className="text-slate-300">
                              {signal.geo.geocode.matched_name}
                            </span>{" "}
                            ({signal.geo.geocode.method}, {signal.geo.geocode.score.toFixed(2)}
                            {signal.geo.geocode.ambiguous ? ", ambiguous" : ""})
                          </span>
                          <span>cell {signal.geo.grid_cell_id}</span>
                        </>
                      ) : (
                        <span className="text-amber-400">
                          no gazetteer match — cannot be placed or scored
                        </span>
                      )}
                      {check && typeof check.buildings_in_radius === "number" ? (
                        <span>
                          imagery: {check.damaged_in_radius}/{check.buildings_in_radius}{" "}
                          damaged within {Math.round(check.radius_m ?? 0)} m
                        </span>
                      ) : null}
                    </div>

                    {/* Runner-up geocodes: how a wrong placement gets caught. */}
                    {signal.geo?.geocode.candidates &&
                    signal.geo.geocode.candidates.length > 1 ? (
                      <p className="mt-1 text-[9px] text-slate-600">
                        other candidates:{" "}
                        {signal.geo.geocode.candidates
                          .slice(1, 4)
                          .map((c) => `${c.name} ${c.score.toFixed(2)}`)
                          .join(" · ")}
                      </p>
                    ) : null}

                    {/* Teaching aid only. Never read by the pipeline (D-010). */}
                    {signal.eval?.planted_fake ? (
                      <p className="mt-1 inline-block border border-fuchsia-500/40 bg-fuchsia-500/10 px-1.5 py-0.5 text-[9px] text-fuchsia-300">
                        DATASET LABEL: planted fake ({signal.eval.fake_kind}) — shown for
                        review only; the verifier never sees this field
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
