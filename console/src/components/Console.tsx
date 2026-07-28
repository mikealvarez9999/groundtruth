"use client";

/**
 * Top-level client component: loads the artifacts, drives the replay clock, and
 * re-scores the grid as signals arrive.
 *
 * The replay is the point. `sector_scores.json` holds the end state with every
 * signal present; during playback we re-run the fusion in the browser over only
 * the signals that have arrived, so the queue genuinely re-ranks as reports land
 * (see lib/fusion.ts, which mirrors pipeline/fuse.py).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type { DamageLayer, SectorScores, Signal, ValidArea } from "@/lib/types";
import { arrivedAt, rescore, replayDuration, summarise } from "@/lib/fusion";
import type { FloodOverlay, LayerVisibility } from "./MapView";
import TopBar from "./TopBar";
import SidePanel from "./SidePanel";
import TriageQueue from "./TriageQueue";
import SignalFeed from "./SignalFeed";
import AuditDrawer from "./AuditDrawer";
import BriefPanel from "./BriefPanel";

// MapLibre and deck.gl both touch `window` on import, so the map must not be
// server-rendered.
const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="absolute inset-0 flex items-center justify-center">
      <span className="text-[11px] tracking-[0.2em] text-slate-600">
        INITIALISING MAP…
      </span>
    </div>
  ),
});

const TICK_MS = 100;

/** One dated SAR pass, built by pipeline's build_epoch. */
interface Epoch {
  slug: string;
  label: string;
}

export default function Console() {
  const [damage, setDamage] = useState<DamageLayer | null>(null);
  const [scores, setScores] = useState<SectorScores | null>(null);
  const [allSignals, setAllSignals] = useState<Signal[]>([]);
  const [validArea, setValidArea] = useState<ValidArea | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Dated SAR passes for the before/after toggle. Empty until
  // /data/epochs/index.json exists (i.e. build_epoch has run at least twice).
  const [epochs, setEpochs] = useState<Epoch[]>([]);
  const [epochSlug, setEpochSlug] = useState<string | null>(null);

  // The epoch's rendered Sentinel-1 flood mask (flood_overlay.py). Optional:
  // an epoch without one just shows no water layer.
  const [floodOverlay, setFloodOverlay] = useState<FloodOverlay | null>(null);

  // Wide national/regional flood context (flood_overlay.py --national). Shown
  // only when its event_id matches the loaded scores, so a Bangladesh backdrop
  // can never appear over, say, a Myanmar earthquake console.
  const [nationalOverlay, setNationalOverlay] = useState<FloodOverlay | null>(null);

  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  // 120x: the seeded corpus spans ~2.2 hours, so this replays in ~70s --
  // long enough to watch the queue re-rank, short enough to demo twice.
  const [speed, setSpeed] = useState(120);

  const [visibility, setVisibility] = useState<LayerVisibility>({
    damage: true,
    sectors: true,
    signals: true,
    flood: true,
    satellite: true,
    national: true,
  });
  const [selectedCellId, setSelectedCellId] = useState<string | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const [briefOpen, setBriefOpen] = useState(false);

  // ---- load artifacts ----------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [d, s, sig, va] = await Promise.all([
          fetch("/data/damage_layer.geojson").then((r) => r.json()),
          fetch("/data/sector_scores.json").then((r) => r.json()),
          fetch("/data/signals.seed.json").then((r) => r.json()),
          fetch("/data/valid_area.geojson").then((r) => r.json()),
        ]);
        if (cancelled) return;
        setDamage(d as DamageLayer);
        setScores(s as SectorScores);
        setAllSignals(sig as Signal[]);
        setValidArea(va as ValidArea);
      } catch (err) {
        if (!cancelled) {
          setLoadError(
            `Could not load /data artifacts (${(err as Error).message}). Run: ` +
              `cd pipeline && PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all`,
          );
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // ---- dated SAR passes (before/after) -----------------------------------
  // The manifest lists epochs built by build_epoch; the LAST-built epoch is the
  // default and matches what the root /data artifacts already hold, so
  // selecting it needs no refetch on first paint.
  useEffect(() => {
    let cancelled = false;
    const loadManifest = async () => {
      try {
        const res = await fetch("/data/epochs/index.json");
        if (!res.ok) return; // no epochs built -- toggle stays hidden
        const manifest = (await res.json()) as { default?: string; epochs?: Epoch[] };
        if (cancelled || !manifest.epochs || manifest.epochs.length < 2) return;
        setEpochs(manifest.epochs);
        setEpochSlug(manifest.default ?? manifest.epochs[manifest.epochs.length - 1].slug);
      } catch {
        /* absent -> single-date console, as before */
      }
    };
    void loadManifest();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSelectEpoch = useCallback(
    async (slug: string) => {
      setEpochSlug(slug);
      try {
        const base = `/data/epochs/${slug}`;
        const [d, s, va] = await Promise.all([
          fetch(`${base}/damage_layer.geojson`).then((r) => r.json()),
          fetch(`${base}/sector_scores.json`).then((r) => r.json()),
          fetch(`${base}/valid_area.geojson`).then((r) => r.json()),
        ]);
        setDamage(d as DamageLayer);
        setScores(s as SectorScores);
        setValidArea(va as ValidArea);
        // Signals are deliberately NOT refetched: the citizen corpus is the same
        // across passes, and refetching would drop live Telegram tips.
      } catch (err) {
        setLoadError(
          `Could not load epoch '${slug}' (${(err as Error).message}). ` +
            "Re-run build_epoch for that date window.",
        );
      }
    },
    [],
  );

  // ---- per-epoch flood overlay -------------------------------------------
  // Bounds come from a sidecar written by flood_overlay.py, so the image drapes
  // by the mask GeoTIFF's real extent. No sidecar -> no overlay, silently.
  useEffect(() => {
    if (!epochSlug) {
      setFloodOverlay(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch(`/data/epochs/${epochSlug}/flood_bounds.json`);
        if (!res.ok) {
          if (!cancelled) setFloodOverlay(null);
          return;
        }
        const sidecar = (await res.json()) as {
          bounds: [number, number, number, number];
        };
        if (!cancelled) {
          setFloodOverlay({
            url: `/data/epochs/${epochSlug}/flood.png`,
            bounds: sidecar.bounds,
          });
        }
      } catch {
        if (!cancelled) setFloodOverlay(null);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [epochSlug]);

  // ---- national flood context overlay ------------------------------------
  // Loaded once, but shown only if its event_id matches the loaded scores, so a
  // country backdrop is never draped over the wrong event's console.
  useEffect(() => {
    if (!scores) return;
    let cancelled = false;
    const load = async () => {
      try {
        const res = await fetch("/data/national_flood.json");
        if (!res.ok) {
          if (!cancelled) setNationalOverlay(null);
          return;
        }
        const sidecar = (await res.json()) as {
          bounds: [number, number, number, number];
          event_id?: string;
        };
        // Honesty gate: wrong event -> no backdrop.
        if (sidecar.event_id && sidecar.event_id !== scores.event_id) {
          if (!cancelled) setNationalOverlay(null);
          return;
        }
        if (!cancelled) {
          setNationalOverlay({ url: "/data/national_flood.png", bounds: sidecar.bounds });
        }
      } catch {
        if (!cancelled) setNationalOverlay(null);
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [scores]);

  // ---- live Telegram tips: poll and merge --------------------------------
  // The tip-line bot (bot/tipline.py) appends verified tips to the shared
  // store -- Upstash Redis when UPSTASH_REDIS_REST_URL/_TOKEN are set (the
  // deployed scenario), or console/public/data/live_signals.json on a local
  // demo. The /api/live-signals route hides the difference; we poll it and
  // merge by signal_id, so a texted report appears on the map and re-ranks
  // the queue within a few seconds. Live tips carry replay_offset_s: null,
  // so arrivedAt() surfaces them at once rather than waiting on the replay
  // clock. A no-op response (bot not running) is fine -- the seeded replay
  // stands alone.
  useEffect(() => {
    let cancelled = false;
    const poll = async () => {
      try {
        const res = await fetch("/api/live-signals", { cache: "no-store" });
        if (!res.ok) return;
        const live = (await res.json()) as Signal[];
        if (cancelled || !Array.isArray(live) || live.length === 0) return;
        setAllSignals((prev) => {
          const byId = new Map(prev.map((s) => [s.signal_id, s]));
          for (const s of live) byId.set(s.signal_id, s); // upsert: retroactive re-tiering wins
          return Array.from(byId.values());
        });
      } catch {
        /* bot not running -> ignore */
      }
    };
    void poll();
    const id = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const duration = useMemo(
    () => (allSignals.length ? replayDuration(allSignals) + 60 : 0),
    [allSignals],
  );

  // ---- replay clock ------------------------------------------------------
  const rafRef = useRef<number | null>(null);
  useEffect(() => {
    if (!playing || duration === 0) return;
    let last = performance.now();
    const tick = () => {
      const now = performance.now();
      const dt = (now - last) / 1000;
      last = now;
      setElapsed((prev) => {
        const next = prev + dt * speed;
        if (next >= duration) {
          setPlaying(false);
          return duration;
        }
        return next;
      });
      rafRef.current = window.setTimeout(tick, TICK_MS) as unknown as number;
    };
    rafRef.current = window.setTimeout(tick, TICK_MS) as unknown as number;
    return () => {
      if (rafRef.current !== null) clearTimeout(rafRef.current);
    };
  }, [playing, speed, duration]);

  // ---- live re-score -----------------------------------------------------
  const arrived = useMemo(
    () => arrivedAt(allSignals, elapsed),
    [allSignals, elapsed],
  );

  const liveCells = useMemo(
    () => (scores ? rescore(scores, arrived) : []),
    [scores, arrived],
  );

  const summary = useMemo(() => summarise(liveCells, arrived), [liveCells, arrived]);

  const selectedCell = useMemo(
    () => liveCells.find((c) => c.cell_id === selectedCellId) ?? null,
    [liveCells, selectedCellId],
  );

  const signalsInCell = useMemo(
    () => (selectedCell ? selectedCell.arrivedSignals : []),
    [selectedCell],
  );

  const rankedCellIds = useMemo(
    () =>
      liveCells
        .filter(
          (c) =>
            c.arrivedSignals.length > 0 ||
            (c.evidence.buildings_damaged ?? 0) > 0,
        )
        .map((c) => c.cell_id),
    [liveCells],
  );

  const damageCounts = useMemo(() => {
    const counts = damage?.groundtruth.counts;
    if (!counts) return undefined;
    return {
      total: counts.buildings_total,
      damaged: counts.buildings_damaged,
      obscured: counts.buildings_obscured,
    };
  }, [damage]);

  const handleSelectCell = useCallback((cellId: string | null) => {
    setSelectedCellId(cellId);
    setSelectedSignal(null);
  }, []);

  const handleSelectSignal = useCallback((signal: Signal) => {
    setSelectedSignal(signal);
    if (signal.geo?.grid_cell_id) setSelectedCellId(signal.geo.grid_cell_id);
  }, []);

  // Keyboard: space toggles playback, A/B open panels, Esc closes.
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const target = ev.target as HTMLElement | null;
      if (target && ["INPUT", "TEXTAREA"].includes(target.tagName)) return;
      if (ev.code === "Space") {
        ev.preventDefault();
        setPlaying((p) => !p);
      } else if (ev.key.toLowerCase() === "a") {
        setAuditOpen((o) => !o);
      } else if (ev.key.toLowerCase() === "b") {
        setBriefOpen((o) => !o);
      } else if (ev.key === "Escape") {
        setAuditOpen(false);
        setBriefOpen(false);
        setSelectedSignal(null);
        setSelectedCellId(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const loading = !damage || !scores;

  return (
    <main className="relative h-screen w-screen overflow-hidden bg-void">
      {/* map underlay */}
      <MapView
        damage={visibility.damage ? damage : damage}
        validArea={validArea}
        floodOverlay={floodOverlay}
        nationalOverlay={nationalOverlay}
        cells={liveCells}
        signals={arrived}
        visibility={visibility}
        selectedCellId={selectedCellId}
        onSelectCell={handleSelectCell}
        onSelectSignal={handleSelectSignal}
      />

      {/* atmospherics */}
      <div className="gt-vignette" />
      <div className="gt-scanline" />

      {/* HUD */}
      <div className="pointer-events-none absolute inset-0 z-20 flex flex-col gap-2 p-3">
        {scores ? (
          <TopBar
            eventId={scores.event_id}
            elapsedSeconds={Math.floor(elapsed)}
            durationSeconds={duration}
            playing={playing}
            speed={speed}
            onTogglePlay={() => setPlaying((p) => !p)}
            onScrub={(s) => {
              setPlaying(false);
              setElapsed(s);
            }}
            onSpeed={setSpeed}
            onReset={() => {
              setPlaying(false);
              setElapsed(0);
            }}
            summary={summary}
            damageCounts={damageCounts}
            top={liveCells.find(
              (c) =>
                c.arrivedSignals.length > 0 ||
                (c.evidence.buildings_damaged ?? 0) > 0,
            )}
            onOpenAudit={() => setAuditOpen((o) => !o)}
            onOpenBrief={() => setBriefOpen(true)}
          />
        ) : null}

        {/* before/after: dated Sentinel-1 passes. Each option is a full pipeline
            run on a real acquisition window -- switching re-fetches that epoch's
            artifacts, nothing is interpolated. */}
        {epochs.length >= 2 ? (
          <div className="pointer-events-auto flex items-center gap-1 self-start border border-slate-700/70 bg-slate-950/85 px-1.5 py-1 backdrop-blur">
            <span className="px-1 text-[8px] font-semibold tracking-[0.25em] text-slate-500">
              SAR PASS
            </span>
            {epochs.map((e) => (
              <button
                key={e.slug}
                onClick={() => void handleSelectEpoch(e.slug)}
                className={`cursor-pointer border px-2 py-0.5 text-[9px] tracking-wider transition-colors ${
                  epochSlug === e.slug
                    ? "border-cyan-500/60 bg-cyan-500/15 text-cyan-300"
                    : "border-transparent text-slate-400 hover:text-slate-200"
                }`}
              >
                {e.label}
              </button>
            ))}
          </div>
        ) : null}

        <div className="flex min-h-0 flex-1 gap-2">
          {/* left column */}
          <div className="pointer-events-auto hidden w-60 shrink-0 flex-col md:flex">
            <SidePanel
              visibility={visibility}
              onToggle={(key) =>
                setVisibility((v) => ({ ...v, [key]: !v[key] }))
              }
              cell={selectedCell}
              signal={selectedSignal}
              signalsInCell={signalsInCell}
              onSelectSignal={handleSelectSignal}
              onClearSelection={() => {
                setSelectedCellId(null);
                setSelectedSignal(null);
              }}
              damage={damage}
            />
          </div>

          <div className="flex-1" />

          {/* right column */}
          <div className="pointer-events-auto hidden w-72 shrink-0 flex-col gap-2 lg:flex">
            <div className="gt-panel gt-bracket min-h-0 flex-[3] overflow-hidden">
              <TriageQueue
                cells={liveCells}
                selectedCellId={selectedCellId}
                onSelect={handleSelectCell}
              />
            </div>
            <div className="gt-panel gt-bracket min-h-0 flex-[2] overflow-hidden">
              <SignalFeed signals={arrived} onSelect={handleSelectSignal} />
            </div>
          </div>
        </div>

        {/* data-provenance ticker: driven by the damage layer's actual source,
            never hardcoded. Honesty cuts both ways — synthetic data must scream
            synthetic, and real SAR data must not be labelled fabricated. */}
        {(() => {
          const src = damage?.groundtruth.source;
          const isSar = src?.tool === "sentinel1_sar";
          const isSynthetic =
            src?.tool === "haste" && src.haste_commit === "0000000";
          const text = isSar
            ? "REAL SATELLITE ASSESSMENT — damage layer from Copernicus Sentinel-1 " +
              "C-band SAR (cloud-penetrating) · damage = flood exposure per building " +
              "· footprints: Google Open Buildings v3 · UNVALIDATED — no ground-truth " +
              "sample measured yet · citizen replay reports are synthetic stand-ins; " +
              "live Telegram tips are real · Channel 2 (VLM) not implemented"
            : isSynthetic
              ? "⚠ SYNTHETIC DEMO DATA — place names are real, all damage labels and " +
                "reports are fabricated · no satellite imagery was assessed · damage " +
                "layer is UNVALIDATED (no accuracy measured) · Channel 2 (VLM) not " +
                "implemented · replace before any external demo ⚠"
              : "HASTE optical assessment — see damage-layer provenance in the side " +
                "panel · citizen replay reports are synthetic stand-ins; live Telegram " +
                "tips are real · Channel 2 (VLM) not implemented";
          const frame = isSar
            ? "border-cyan-700/40 bg-cyan-950/40"
            : "border-amber-600/40 bg-amber-950/40";
          const tone = isSar ? "text-cyan-300/90" : "text-amber-400/90";
          return (
            <div
              className={`gt-ticker pointer-events-auto overflow-hidden border ${frame}`}
            >
              <div className="gt-ticker-track py-0.5">
                {[0, 1].map((copy) => (
                  <span
                    key={copy}
                    className={`px-6 text-[9px] tracking-[0.15em] whitespace-nowrap ${tone}`}
                  >
                    {text}
                  </span>
                ))}
              </div>
            </div>
          );
        })()}
      </div>

      <AuditDrawer
        open={auditOpen}
        onClose={() => setAuditOpen(false)}
        signals={arrived}
      />
      <BriefPanel
        open={briefOpen}
        onClose={() => setBriefOpen(false)}
        cellIds={rankedCellIds}
        elapsedSeconds={Math.floor(elapsed)}
      />

      {/* boot / error overlay */}
      {loading || loadError ? (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-void/85 backdrop-blur">
          <div className="gt-panel gt-bracket max-w-lg px-5 py-4">
            {loadError ? (
              <>
                <h2 className="mb-1.5 text-[12px] font-bold tracking-[0.2em] text-rose-400">
                  DATA UNAVAILABLE
                </h2>
                <p className="text-[11px] leading-relaxed text-slate-300">{loadError}</p>
              </>
            ) : (
              <>
                <h2 className="mb-1.5 flex items-center gap-2 text-[12px] font-bold tracking-[0.2em] text-cyan-300">
                  <span className="inline-block size-2.5 rounded-full border border-cyan-400 border-t-transparent gt-spin" />
                  LOADING ARTIFACTS
                </h2>
                <p className="text-[11px] text-slate-500">
                  damage layer · sector scores · signals · imagery footprint
                </p>
              </>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
}
