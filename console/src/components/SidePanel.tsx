"use client";

/**
 * Left column: layer toggles, legend, and the inspector for whatever is selected.
 *
 * The legend is not decoration. "Obscured / could not see" is a distinct entry
 * from "assessed, no damage" on purpose, because those two states are the ones a
 * responder must never confuse.
 */

import type { LayerVisibility } from "./MapView";
import type { LiveCell } from "@/lib/fusion";
import type { DamageLayer, Signal } from "@/lib/types";
import { Meter, TierBadge, URGENCY_STYLE } from "./ui";

interface Props {
  visibility: LayerVisibility;
  onToggle: (key: keyof LayerVisibility) => void;
  cell: LiveCell | null;
  signal: Signal | null;
  signalsInCell: Signal[];
  onSelectSignal: (signal: Signal) => void;
  onClearSelection: () => void;
  damage: DamageLayer | null;
}

const LAYERS: { key: keyof LayerVisibility; label: string; hint: string }[] = [
  { key: "satellite", label: "Satellite imagery", hint: "Esri World Imagery + reference place-name labels (Google-Earth style)" },
  { key: "flood", label: "SAR floodwater", hint: "Sentinel-1 detected flood extent" },
  { key: "damage", label: "Building damage", hint: "Per-building assessment (optical or SAR)" },
  { key: "sectors", label: "Sector scores", hint: "Fused triage grid, 500 m cells" },
  { key: "signals", label: "Citizen signals", hint: "Verified claims, by tier" },
];

const LEGEND: { color: string; label: string }[] = [
  { color: "bg-[#38bdf8]/60", label: "SAR-detected floodwater" },
  { color: "bg-[#ff3b5c]", label: "Building damaged" },
  { color: "bg-[#1f9d55]", label: "Building assessed, no damage" },
  { color: "bg-[#7c8899]", label: "Cloud-obscured — could not see" },
  { color: "bg-[#22d3ee]", label: "Signal: corroborated" },
  { color: "bg-[#fbbf24]", label: "Signal: single source (recon)" },
  { color: "bg-[#f43f5e]", label: "Signal: suspect (withheld)" },
  { color: "bg-[#475569]", label: "Sector outside imagery footprint" },
];

function ProvRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex gap-1">
      <dt>{label}</dt>
      <dd className="text-slate-300">{value}</dd>
    </div>
  );
}

/**
 * Damage-layer provenance, narrowed on the sensor. HASTE shows backbone + commit;
 * Sentinel-1 SAR shows sensor + classifier + the flood window. The "validated"
 * row is shared — a SAR layer has no ground-truth sample, so it reads UNVALIDATED,
 * which is the honest state, not a bug.
 */
function ProvenanceRows({
  source,
  accuracy,
}: {
  source: DamageLayer["groundtruth"]["source"];
  accuracy: DamageLayer["groundtruth"]["accuracy"];
}) {
  return (
    <dl className="space-y-0.5 text-[9px] text-slate-500">
      {source.tool === "sentinel1_sar" ? (
        <>
          <ProvRow label="sensor" value={source.sensor} />
          <ProvRow label="classifier" value={source.classifier_ref ?? source.classifier} />
          {source.target_window ? (
            <ProvRow
              label="flood window"
              value={`${source.target_window[0]} → ${source.target_window[1]}`}
            />
          ) : null}
          <ProvRow label="footprints" value={source.footprint_source} />
        </>
      ) : (
        <>
          <ProvRow label="backbone" value={source.backbone} />
          <ProvRow label="haste commit" value={source.haste_commit} />
          <ProvRow label="footprints" value={source.footprint_source ?? "—"} />
        </>
      )}
      <div className="flex gap-1">
        <dt>validated</dt>
        <dd className={accuracy ? "text-slate-300" : "text-amber-400"}>
          {accuracy
            ? `damaged F1 ${accuracy.damaged_f1?.toFixed(2) ?? "n/a"}`
            : "NOT VALIDATED — no accuracy measured"}
        </dd>
      </div>
    </dl>
  );
}

export default function SidePanel({
  visibility,
  onToggle,
  cell,
  signal,
  signalsInCell,
  onSelectSignal,
  onClearSelection,
  damage,
}: Props) {
  const accuracy = damage?.groundtruth.accuracy;

  return (
    <div className="flex h-full flex-col gap-2 overflow-hidden">
      {/* layers */}
      <section className="gt-panel gt-bracket shrink-0 px-3 py-2">
        <h2 className="gt-label mb-1.5">Layers</h2>
        <ul className="space-y-1">
          {LAYERS.map((layer) => (
            <li key={layer.key}>
              <button
                onClick={() => onToggle(layer.key)}
                className="group flex w-full cursor-pointer items-center gap-2 text-left"
              >
                <span
                  className={`flex size-3 shrink-0 items-center justify-center border transition-colors ${
                    visibility[layer.key]
                      ? "border-cyan-400 bg-cyan-400/25"
                      : "border-slate-600"
                  }`}
                >
                  {visibility[layer.key] ? (
                    <span className="size-1 bg-cyan-300" />
                  ) : null}
                </span>
                <span
                  className={`text-[11px] transition-colors ${
                    visibility[layer.key] ? "text-slate-100" : "text-slate-500"
                  }`}
                >
                  {layer.label}
                </span>
              </button>
              <p className="ml-5 text-[9px] text-slate-600">{layer.hint}</p>
            </li>
          ))}
        </ul>

        <h2 className="gt-label mt-2.5 mb-1">Legend</h2>
        <ul className="space-y-0.5">
          {LEGEND.map((item) => (
            <li key={item.label} className="flex items-center gap-1.5">
              <span className={`size-2 shrink-0 rounded-full ${item.color}`} />
              <span className="text-[9px] leading-tight text-slate-400">{item.label}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* inspector */}
      <section className="gt-panel gt-bracket flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center gap-2 border-b border-slate-800/90 px-3 py-1.5">
          <h2 className="text-[10px] font-semibold tracking-[0.2em] text-slate-200">
            INSPECTOR
          </h2>
          {cell || signal ? (
            <button
              onClick={onClearSelection}
              className="ml-auto cursor-pointer text-[9px] text-slate-500 hover:text-slate-200"
            >
              clear
            </button>
          ) : null}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2">
          {!cell && !signal ? (
            <div className="space-y-2">
              <p className="text-[10px] leading-relaxed text-slate-500">
                Click a sector on the map or a row in the triage queue to inspect the
                evidence behind its score.
              </p>
              <div className="border-t border-slate-800 pt-2">
                <h3 className="gt-label mb-1">Damage layer provenance</h3>
                {damage ? (
                  <ProvenanceRows
                    source={damage.groundtruth.source}
                    accuracy={accuracy}
                  />
                ) : (
                  <p className="text-[9px] text-slate-600">no layer loaded</p>
                )}
              </div>
            </div>
          ) : null}

          {/* selected signal wins the panel */}
          {signal ? (
            <div className="gt-rise space-y-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <TierBadge tier={signal.verification.tier} />
                <span className={`text-[9px] font-bold ${URGENCY_STYLE[signal.claim.urgency]}`}>
                  {signal.claim.urgency.toUpperCase()}
                </span>
              </div>

              <p className="text-[11px] leading-snug text-slate-100">
                {signal.raw?.text}
              </p>
              {signal.claim.summary_en ? (
                <p className="text-[10px] leading-snug text-slate-500 italic">
                  → {signal.claim.summary_en}{" "}
                  <span className="text-slate-600">
                    (our extractor&apos;s reading, not a translation)
                  </span>
                </p>
              ) : null}

              <dl className="space-y-0.5 text-[9px]">
                {[
                  ["event", signal.claim.event_type.replace(/_/g, " ")],
                  ["claimed place", signal.claim.location_ref || "—"],
                  [
                    "matched",
                    signal.geo
                      ? `${signal.geo.geocode.matched_name} (${signal.geo.geocode.score.toFixed(2)})`
                      : "unresolved",
                  ],
                  [
                    "persons stated",
                    typeof signal.claim.persons_at_risk === "number"
                      ? String(signal.claim.persons_at_risk)
                      : "not stated",
                  ],
                  ["needs", (signal.claim.needs ?? []).join(", ") || "—"],
                  ["sources agreeing", String(signal.verification.distinct_source_count ?? 1)],
                  ["weight", signal.verification.fusion_weight.toFixed(2)],
                  ["extractor", signal.extraction?.model ?? "?"],
                ].map(([k, v]) => (
                  <div key={k} className="flex gap-1.5">
                    <dt className="w-24 shrink-0 text-slate-600">{k}</dt>
                    <dd className="text-slate-300">{v}</dd>
                  </div>
                ))}
              </dl>

              <p className="border-l-2 border-slate-700 pl-2 text-[10px] leading-relaxed text-slate-400">
                {signal.verification.reason}
              </p>
            </div>
          ) : null}

          {/* otherwise the selected cell */}
          {cell && !signal ? (
            <div className="gt-rise space-y-2.5">
              <div>
                <h3 className="text-[13px] leading-tight font-bold text-slate-50">
                  {cell.place_label ?? cell.cell_id}
                </h3>
                <p className="text-[9px] text-slate-500">
                  rank {cell.liveRank} · cell {cell.cell_id} ·{" "}
                  <span
                    className={
                      cell.coverage?.status === "unassessed"
                        ? "text-amber-400"
                        : "text-slate-400"
                    }
                  >
                    {cell.coverage?.status ?? "unknown"}
                  </span>
                </p>
              </div>

              <div className="space-y-1">
                <Meter label="Damage" value={cell.components.damage} color="bg-rose-500" />
                <Meter
                  label="VLM"
                  value={cell.components.vlm}
                  unknown
                  color="bg-violet-500"
                />
                <Meter label="Citizen" value={cell.components.citizen} color="bg-cyan-400" />
              </div>
              <p className="text-[9px] leading-snug text-slate-600">
                VLM is hatched because Channel 2 is not implemented — that is
                &ldquo;no data&rdquo;, not zero.
              </p>

              <ul className="space-y-0.5 border-t border-slate-800 pt-2">
                {(cell.top_reasons ?? []).map((reason) => (
                  <li key={reason} className="text-[10px] leading-snug text-slate-300">
                    · {reason}
                  </li>
                ))}
              </ul>

              {signalsInCell.length > 0 ? (
                <div className="border-t border-slate-800 pt-2">
                  <h4 className="gt-label mb-1">
                    Signals here ({signalsInCell.length})
                  </h4>
                  <ul className="space-y-1">
                    {signalsInCell.map((s) => (
                      <li key={s.signal_id}>
                        <button
                          onClick={() => onSelectSignal(s)}
                          className="w-full cursor-pointer border border-slate-800 px-1.5 py-1 text-left transition-colors hover:border-slate-600"
                        >
                          <div className="flex items-center gap-1">
                            <TierBadge tier={s.verification.tier} small />
                          </div>
                          <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-slate-300">
                            {s.raw?.text}
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}
