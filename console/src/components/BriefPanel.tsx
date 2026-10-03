"use client";

/**
 * Streaming allocation brief.
 *
 * The panel shows which generator produced the text (live model vs deterministic
 * fallback) because a brief of unknown origin is worse than no brief. The header
 * reads that from the X-Brief-Generator response header.
 */

import { useEffect, useRef, useState } from "react";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Live-ranked cell ids, best first, so the brief matches the current replay. */
  cellIds: string[];
  elapsedSeconds: number;
}

export default function BriefPanel({ open, onClose, cellIds, elapsedSeconds }: Props) {
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [generator, setGenerator] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const generate = async () => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setText("");
    setError(null);
    setStreaming(true);
    setGenerator(null);

    try {
      const res = await fetch("/api/brief", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cellIds: cellIds.slice(0, 8), elapsedSeconds }),
        signal: controller.signal,
      });

      setGenerator(res.headers.get("X-Brief-Generator"));

      if (!res.ok || !res.body) {
        setError(`Brief request failed (HTTP ${res.status}).`);
        setText(await res.text());
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setText((prev) => prev + chunk);
        bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
      }
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError((err as Error).message);
      }
    } finally {
      setStreaming(false);
    }
  };

  // Generate once when first opened; after that it is manual.
  const generatedOnce = useRef(false);
  useEffect(() => {
    if (open && !generatedOnce.current) {
      generatedOnce.current = true;
      void generate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const isFallback = generator?.includes("fallback");

  return (
    <div
      className={`pointer-events-none absolute inset-y-0 right-0 z-30 w-full max-w-md p-3 transition-transform duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
        open ? "translate-x-0" : "translate-x-full"
      }`}
      aria-hidden={!open}
    >
      <div className="gt-panel gt-bracket pointer-events-auto flex h-full flex-col overflow-hidden">
        <header className="border-b border-slate-800/90 px-3 py-2">
          <div className="flex items-center gap-2">
            <h2 className="text-[11px] font-semibold tracking-[0.2em] text-slate-200">
              ALLOCATION BRIEF
            </h2>
            {streaming ? (
              <span className="flex items-center gap-1 text-[9px] text-cyan-300">
                <span className="inline-block size-2 rounded-full border border-cyan-400 border-t-transparent gt-spin" />
                streaming
              </span>
            ) : null}
            <button
              onClick={onClose}
              className="ml-auto cursor-pointer border border-slate-700 px-2 py-0.5 text-[9px] text-slate-400 transition-colors hover:border-slate-500 hover:text-slate-100"
            >
              CLOSE ✕
            </button>
          </div>

          <div className="mt-1.5 flex items-center gap-2">
            <button
              onClick={() => void generate()}
              disabled={streaming}
              className="cursor-pointer border border-cyan-500/50 bg-cyan-500/10 px-2 py-0.5 text-[9px] tracking-wider text-cyan-300 transition-colors hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {text ? "REGENERATE" : "GENERATE"}
            </button>
            {generator ? (
              <span
                className={`text-[9px] ${isFallback ? "text-amber-400" : "text-cyan-400"}`}
                title={
                  isFallback
                    ? "Composed from sector_scores.json by code, not by a model. Figures are exact."
                    : "Streamed from the model, constrained to the dataset's figures."
                }
              >
                {isFallback ? "offline generator" : "live model"}
              </span>
            ) : null}
          </div>
        </header>

        {/* Shimmer bar while streaming. */}
        <div className="h-px w-full bg-slate-800">
          {streaming ? <div className="gt-shimmer h-px w-full" /> : null}
        </div>

        <div ref={bodyRef} className="flex-1 overflow-y-auto px-3 py-2.5">
          {error ? (
            <p className="mb-2 border border-rose-500/50 bg-rose-500/10 px-2 py-1 text-[10px] text-rose-300">
              {error}
            </p>
          ) : null}

          {!text && !streaming ? (
            <p className="text-[11px] leading-relaxed text-slate-500">
              Generates an operational brief from the current sector ranking. Works
              offline: without a Groq key it is composed from the same figures by
              code, and the header says which generator ran.
            </p>
          ) : (
            <pre
              className={`text-[11px] leading-relaxed whitespace-pre-wrap text-slate-200 ${
                streaming ? "gt-caret" : ""
              }`}
            >
              {text}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
