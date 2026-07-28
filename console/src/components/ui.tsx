"use client";

/** Small shared UI atoms. Kept in one file so the theme stays consistent. */

import { useEffect, useRef, useState } from "react";
import type { Signal, Tier, TelegramPhotoRef, Urgency, VlmAssessment, VlmStatus } from "@/lib/types";

export const TIER_STYLE: Record<Tier, { label: string; cls: string; dot: string }> = {
  corroborated: {
    label: "CORROBORATED",
    cls: "text-cyan-300 border-cyan-500/50 bg-cyan-500/10",
    dot: "bg-cyan-400",
  },
  plausible_unverified: {
    label: "UNVERIFIED",
    cls: "text-amber-300 border-amber-500/50 bg-amber-500/10",
    dot: "bg-amber-400",
  },
  suspect: {
    label: "SUSPECT",
    cls: "text-rose-300 border-rose-500/60 bg-rose-500/10",
    dot: "bg-rose-400",
  },
};

export const URGENCY_STYLE: Record<Urgency, string> = {
  critical: "text-rose-400",
  high: "text-orange-400",
  medium: "text-amber-300",
  low: "text-sky-400",
};

/**
 * Number that eases to its target instead of snapping.
 *
 * Deliberately fast (~550ms): this is instrumentation, and a responder should
 * never have to wait for a number to finish being pretty before reading it.
 */
export function CountUp({
  value,
  decimals = 0,
  className = "",
}: {
  value: number;
  decimals?: number;
  className?: string;
}) {
  const [shown, setShown] = useState(value);
  const fromRef = useRef(value);
  const startRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    if (from === value) return;
    let frame = 0;
    startRef.current = performance.now();
    const duration = 550;

    const step = (now: number) => {
      const p = Math.min(1, (now - startRef.current) / duration);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - p, 3);
      setShown(from + (value - from) * eased);
      if (p < 1) frame = requestAnimationFrame(step);
      else fromRef.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return (
    <span className={`gt-tabnum ${className}`}>
      {shown.toFixed(decimals)}
    </span>
  );
}

export function TierBadge({ tier, small = false }: { tier: Tier; small?: boolean }) {
  const s = TIER_STYLE[tier];
  return (
    <span
      className={`inline-flex items-center gap-1 border px-1.5 py-px font-semibold tracking-wider ${s.cls} ${
        small ? "text-[8px]" : "text-[9px]"
      } ${tier === "suspect" ? "gt-blink" : ""}`}
    >
      <span className={`size-1 rounded-full ${s.dot}`} />
      {s.label}
    </span>
  );
}

/** Thin labelled meter. `unknown` renders a hatched bar, never an empty one --
 *  an empty bar reads as zero, and zero is not the same as "we don't know". */
export function Meter({
  label,
  value,
  color = "bg-cyan-400",
  unknown = false,
}: {
  label: string;
  value: number | null;
  color?: string;
  unknown?: boolean;
}) {
  const isUnknown = unknown || value === null;
  return (
    <div className="flex items-center gap-2">
      <span className="gt-label w-14 shrink-0">{label}</span>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800/80">
        {isUnknown ? (
          <div
            className="absolute inset-0 opacity-45"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, #475569 0 3px, transparent 3px 6px)",
            }}
          />
        ) : (
          <div
            className={`absolute inset-y-0 left-0 rounded-full ${color} transition-[width] duration-700 ease-out`}
            style={{ width: `${Math.max(1, Math.round((value ?? 0) * 100))}%` }}
          />
        )}
      </div>
      <span className="gt-tabnum w-9 shrink-0 text-right text-[10px] text-slate-400">
        {isUnknown ? "n/a" : (value ?? 0).toFixed(2)}
      </span>
    </div>
  );
}

export function Stat({
  label,
  value,
  decimals = 0,
  accent = "text-slate-100",
  suffix,
}: {
  label: string;
  value: number;
  decimals?: number;
  accent?: string;
  suffix?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="gt-label">{label}</span>
      <span className={`text-lg leading-none font-semibold ${accent}`}>
        <CountUp value={value} decimals={decimals} />
        {suffix ? <span className="ml-0.5 text-[10px] text-slate-500">{suffix}</span> : null}
      </span>
    </div>
  );
}

/**
 * Pull the first photo_path out of a signal's media_refs.
 * Backward-compatible with the seeded strings (no photo_path -> null).
 * Used by SignalFeed and AuditDrawer to render a thumbnail.
 */
export function firstPhotoPath(signal: Signal): string | null {
  for (const m of signal.raw?.media_refs ?? []) {
    if (typeof m === "object" && m !== null && "photo_path" in m) {
      const p = (m as TelegramPhotoRef).photo_path;
      if (p) return p;
    }
  }
  return null;
}

/**
 * Small thumbnail for an uploaded Telegram photo. Click-through to a
 * same-tab preview (anchored to the same data root as everything else).
 * Missing files render a broken-image placeholder; we never throw -- a
 * malformed path is exactly the kind of thing the audit drawer should show
 * as-is rather than as a silent 404.
 */
export function PhotoThumb({ photoPath, alt }: { photoPath: string; alt: string }) {
  // The bot writes `tips/<signal_id>.jpg` into the signal's media_refs. The
  // /data/ path works on a local-machine demo where the bot writes the file
  // next to the rest of the artifacts. On any Vercel deployment we serve the
  // photo from the shared Upstash store via the /api/tip-photo route.
  // Anything that already starts with '/' or 'http' is used verbatim.
  const src = photoPath.startsWith("tips/")
    ? `/api/tip-photo/${photoPath.slice("tips/".length).replace(/\.jpg$/i, "")}.jpg`
    : photoPath.startsWith("/") || photoPath.startsWith("http")
      ? photoPath
      : `/data/${photoPath}`;
  return (
    <a
      href={src}
      target="_blank"
      rel="noopener noreferrer"
      className="block w-fit border border-slate-700/70 transition-colors hover:border-cyan-500/60"
      title={`Open ${photoPath} in a new tab`}
    >
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="block h-12 w-16 object-cover"
        onError={(ev) => {
          (ev.currentTarget as HTMLImageElement).style.opacity = "0.25";
        }}
      />
    </a>
  );
}

const VLM_PILL: Record<VlmStatus, { label: string; cls: string }> = {
  supports: {
    label: "PHOTO SUPPORTS",
    cls: "text-cyan-300 border-cyan-500/50 bg-cyan-500/10",
  },
  contradicts: {
    label: "PHOTO CONTRADICTS",
    cls: "text-rose-300 border-rose-500/60 bg-rose-500/10",
  },
  inconclusive: {
    label: "PHOTO INCONCLUSIVE",
    cls: "text-slate-400 border-slate-600/60 bg-slate-700/30",
  },
};

/**
 * Compact pill + one-line description of a VLM verdict.
 * The status drives the colour; the description is the model's own sentence
 * (truncated) so the reviewer can audit without leaving the drawer.
 */
export function VlmPill({ vlm }: { vlm: VlmAssessment }) {
  const s = VLM_PILL[vlm.status];
  const modelLabel = vlm.model ?? "no model";
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <span className={`inline-flex items-center gap-1 border px-1.5 py-px text-[8px] font-semibold tracking-wider ${s.cls}`}>
        {s.label}
      </span>
      <span className="text-[9px] text-slate-500">
        model: <span className="text-slate-400">{modelLabel}</span>
      </span>
      <span className="text-[9px] leading-snug text-slate-400">
        “{vlm.description}”
      </span>
    </div>
  );
}
