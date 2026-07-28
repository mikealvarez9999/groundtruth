"use client";

import type { LiveCell } from "@/lib/fusion";
import { Stat } from "./ui";

interface Props {
  eventId: string;
  elapsedSeconds: number;
  durationSeconds: number;
  playing: boolean;
  speed: number;
  onTogglePlay: () => void;
  onScrub: (seconds: number) => void;
  onSpeed: (speed: number) => void;
  onReset: () => void;
  summary: {
    signals: number;
    corroborated: number;
    plausible: number;
    suspect: number;
    unmappable: number;
    personsAtRisk: number;
    distinctSources: number;
    activeCells: number;
    unassessedWithReports: number;
  };
  damageCounts?: { total: number; damaged: number; obscured: number };
  top: LiveCell | undefined;
  onOpenAudit: () => void;
  onOpenBrief: () => void;
}

const SPEEDS = [1, 30, 120, 600];

function clock(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `T+${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function TopBar({
  eventId,
  elapsedSeconds,
  durationSeconds,
  playing,
  speed,
  onTogglePlay,
  onScrub,
  onSpeed,
  onReset,
  summary,
  damageCounts,
  top,
  onOpenAudit,
  onOpenBrief,
}: Props) {
  const progress = durationSeconds > 0 ? elapsedSeconds / durationSeconds : 0;

  return (
    <header className="gt-panel gt-bracket pointer-events-auto flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-2">
      {/* identity */}
      <div className="flex items-center gap-2.5">
        <div className="relative flex size-6 items-center justify-center text-cyan-400">
          <span className="gt-ring" />
          <span className="gt-ring gt-ring-2" />
          <span className="size-1.5 rounded-full bg-cyan-400" />
        </div>
        <div>
          <h1 className="text-[13px] leading-none font-bold tracking-[0.15em] text-slate-50">
            GROUNDTRUTH
          </h1>
          <p className="mt-0.5 text-[9px] leading-none text-slate-500">
            {eventId} · triage console
          </p>
        </div>
      </div>

      <div className="h-8 w-px bg-slate-800" />

      {/* replay transport */}
      <div className="flex items-center gap-2">
        <button
          onClick={onTogglePlay}
          className={`w-16 cursor-pointer border px-2 py-1 text-[10px] font-bold tracking-wider transition-colors ${
            playing
              ? "border-amber-500/60 bg-amber-500/10 text-amber-300"
              : "border-cyan-500/60 bg-cyan-500/10 text-cyan-300 gt-glow"
          }`}
        >
          {playing ? "❚❚ PAUSE" : "▶ PLAY"}
        </button>
        <button
          onClick={onReset}
          className="cursor-pointer border border-slate-700 px-2 py-1 text-[10px] text-slate-400 transition-colors hover:border-slate-500 hover:text-slate-100"
        >
          ↺
        </button>

        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="gt-tabnum text-[10px] text-cyan-300">
              {clock(elapsedSeconds)}
            </span>
            <div className="flex items-center gap-px">
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  onClick={() => onSpeed(s)}
                  className={`cursor-pointer border px-1 text-[9px] transition-colors ${
                    speed === s
                      ? "border-cyan-500/60 bg-cyan-500/10 text-cyan-300"
                      : "border-slate-700 text-slate-500 hover:text-slate-300"
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>
          </div>
          <input
            type="range"
            min={0}
            max={Math.max(durationSeconds, 1)}
            value={elapsedSeconds}
            onChange={(e) => onScrub(Number(e.target.value))}
            className="h-1 w-44 cursor-pointer appearance-none rounded-full bg-slate-800 accent-cyan-400"
            style={{
              background: `linear-gradient(to right, #22d3ee ${progress * 100}%, #1e293b ${progress * 100}%)`,
            }}
            aria-label="Replay position"
          />
        </div>
      </div>

      <div className="h-8 w-px bg-slate-800" />

      {/* live counters */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Stat label="Signals" value={summary.signals} />
        <Stat label="Sources" value={summary.distinctSources} />
        <Stat label="Corrob" value={summary.corroborated} accent="text-cyan-300" />
        <Stat label="Recon" value={summary.plausible} accent="text-amber-300" />
        <Stat label="Suspect" value={summary.suspect} accent="text-rose-400" />
        {damageCounts ? (
          <>
            <Stat
              label="Bldg damaged"
              value={damageCounts.damaged}
              accent="text-rose-400"
            />
            <Stat
              label="Obscured"
              value={damageCounts.obscured}
              accent="text-slate-400"
            />
          </>
        ) : null}
        <div className="flex flex-col gap-0.5">
          <span className="gt-label">Stated at risk</span>
          <span className="text-lg leading-none font-semibold text-orange-300">
            ≥{summary.personsAtRisk}
          </span>
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        {top ? (
          <div className="hidden text-right xl:block">
            <span className="gt-label">Go here first</span>
            <p className="text-[12px] leading-tight font-bold text-cyan-300">
              {top.place_label ?? top.cell_id}
            </p>
          </div>
        ) : null}
        <button
          onClick={onOpenAudit}
          className={`cursor-pointer border px-2 py-1 text-[10px] tracking-wider transition-colors ${
            summary.suspect > 0
              ? "gt-alarm border-rose-500/60 bg-rose-500/10 text-rose-300"
              : "border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-100"
          }`}
        >
          AUDIT {summary.suspect > 0 ? `(${summary.suspect})` : ""}
        </button>
        <button
          onClick={onOpenBrief}
          className="cursor-pointer border border-cyan-500/60 bg-cyan-500/10 px-2 py-1 text-[10px] font-bold tracking-wider text-cyan-300 transition-colors hover:bg-cyan-500/20"
        >
          BRIEF ▸
        </button>
      </div>
    </header>
  );
}
