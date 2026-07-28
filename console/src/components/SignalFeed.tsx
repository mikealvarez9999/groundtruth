"use client";

/**
 * Bottom-left live feed: signals as they arrive during replay.
 *
 * Shows the ORIGINAL text plus the English gloss, not the gloss alone. For
 * Bangla and Banglish reports the gloss is our extractor's reading, and hiding
 * the source behind a machine translation is how you end up unable to explain a
 * bad call. (D-013 asks whether to keep doing this -- this is the "show both"
 * option, implemented.)
 */

import { useEffect, useRef } from "react";
import type { Signal } from "@/lib/types";
import { firstPhotoPath, PhotoThumb, TierBadge, URGENCY_STYLE } from "./ui";

interface Props {
  signals: Signal[];
  onSelect: (signal: Signal) => void;
  limit?: number;
}

const LANG_LABEL: Record<string, string> = {
  bn: "বাংলা",
  "bn-latn": "Banglish",
  mixed: "mixed",
  en: "EN",
  unknown: "?",
};

export default function SignalFeed({ signals, onSelect, limit = 40 }: Props) {
  // Newest first.
  const recent = [...signals]
    .sort((a, b) => (b.source.replay_offset_s ?? 0) - (a.source.replay_offset_s ?? 0))
    .slice(0, limit);

  const listRef = useRef<HTMLUListElement | null>(null);
  const lastTop = useRef<string | null>(null);

  useEffect(() => {
    const top = recent[0]?.signal_id ?? null;
    if (top && top !== lastTop.current) {
      lastTop.current = top;
      listRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    }
  }, [recent]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex items-center justify-between border-b border-slate-800/90 px-3 py-2">
        <h2 className="flex items-center gap-2 text-[11px] font-semibold tracking-[0.2em] text-slate-200">
          <span className="size-1.5 rounded-full bg-cyan-400 gt-blink" />
          SIGNAL FEED
        </h2>
        <span className="gt-label">{signals.length} received</span>
      </header>

      {recent.length === 0 ? (
        <p className="px-3 py-5 text-[11px] text-slate-500">
          Awaiting signals. Press PLAY to begin the replay.
        </p>
      ) : (
        <ul ref={listRef} className="flex-1 divide-y divide-slate-800/60 overflow-y-auto">
          {recent.map((signal, i) => (
            <li
              key={signal.signal_id}
              style={{ ["--i" as string]: Math.min(i, 8) }}
              className={i === 0 ? "gt-drop-in" : "gt-rise gt-stagger"}
            >
              <button
                onClick={() => onSelect(signal)}
                className="w-full cursor-pointer px-3 py-2 text-left transition-colors hover:bg-slate-800/40"
              >
                <div className="flex items-center gap-1.5">
                  <TierBadge tier={signal.verification.tier} small />
                  <span
                    className={`text-[8px] font-bold tracking-wider ${URGENCY_STYLE[signal.claim.urgency]}`}
                  >
                    {signal.claim.urgency.toUpperCase()}
                  </span>
                  <span className="ml-auto text-[8px] text-slate-600">
                    {LANG_LABEL[signal.raw?.lang ?? "unknown"]}
                  </span>
                </div>

                {/* Original text first. */}
                <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-slate-200">
                  {signal.raw?.text ?? "(no text)"}
                </p>

                {/* Then what we think it means, clearly marked as ours. */}
                {signal.claim.summary_en ? (
                  <p className="mt-0.5 line-clamp-1 text-[10px] leading-snug text-slate-500 italic">
                    → {signal.claim.summary_en}
                  </p>
                ) : null}

                {/* Optional Telegram photo thumbnail. Rendered inline so the
                    reviewer can spot the artefact without opening the drawer. */}
                {(() => {
                  const pp = firstPhotoPath(signal);
                  return pp ? (
                    <div className="mt-1.5">
                      <PhotoThumb photoPath={pp} alt={signal.signal_id} />
                    </div>
                  ) : null;
                })()}

                <div className="mt-1 flex items-center gap-2 text-[9px] text-slate-500">
                  <span className="text-slate-400">
                    {signal.geo?.geocode.matched_name ??
                      `unresolved: "${signal.claim.location_ref || "—"}"`}
                  </span>
                  {signal.geo ? (
                    <span
                      title="Gazetteer fuzzy-match confidence"
                      className={
                        signal.geo.geocode.score < 0.85 ? "text-amber-400" : "text-slate-600"
                      }
                    >
                      m{signal.geo.geocode.score.toFixed(2)}
                    </span>
                  ) : (
                    <span className="text-amber-400">unmappable</span>
                  )}
                  {signal.verification.recon_priority ? (
                    <span className="ml-auto text-amber-400">recon</span>
                  ) : null}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
