/**
 * Streaming allocation brief.
 *
 * Two paths, and the response says which one you got:
 *
 *  1. GROQ_API_KEY set  -> streams from Groq (OpenAI-compatible
 *                          chat/completions), given the ranked cells as context.
 *  2. No key / any error  -> streams a DETERMINISTIC brief composed from the same
 *                            ranked cells by code in this file.
 *
 * Gemini was removed (D-037). Groq is the only live-model provider.
 *
 * The fallback is not a canned paragraph. It is generated from the actual
 * sector_scores.json at request time, so it always matches what is on the map.
 * That is what makes it safe to demo with no network: the numbers are real
 * (well -- as real as the synthetic dataset behind them), just not LLM-phrased.
 *
 * Every response ends with a provenance line naming the generator. A brief whose
 * origin is ambiguous is worse than no brief.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import type { SectorScores } from "@/lib/types";

// Needs the Node runtime for fs. The artifacts are static files in /public.
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MODEL = "openai/gpt-oss-120b";
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions";

// D-033: Cloudflare-fronted hosts 403-1010 a default `node`/Python-urllib
// User-Agent. Sending a browser-class UA costs nothing and removes a failure
// mode that otherwise shows up only in production.
const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/127.0 Safari/537.36";

interface BriefRequest {
  /** Cell ids currently ranked, best first. Sent by the client so the brief
   *  reflects the live replay state rather than the full-corpus file. */
  cellIds?: string[];
  elapsedSeconds?: number;
}

async function loadScores(): Promise<SectorScores> {
  const file = path.join(process.cwd(), "public", "data", "sector_scores.json");
  return JSON.parse(await readFile(file, "utf8")) as SectorScores;
}

function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "n/a" : `${Math.round(n * 100)}%`;
}

/** Compact, factual context block. Shared by both paths. */
function buildContext(scores: SectorScores, cellIds: string[] | undefined): string {
  const order = new Map((cellIds ?? []).map((id, i) => [id, i]));
  const cells = [...scores.cells]
    .filter((c) => (cellIds && cellIds.length ? order.has(c.cell_id) : true))
    .sort((a, b) =>
      cellIds && cellIds.length
        ? (order.get(a.cell_id) ?? 1e9) - (order.get(b.cell_id) ?? 1e9)
        : b.score - a.score,
    )
    .slice(0, 8);

  const lines = cells.map((c, i) => {
    const ev = c.evidence;
    return [
      `${i + 1}. ${c.place_label ?? c.cell_id} (cell ${c.cell_id})`,
      `   coverage=${c.coverage?.status ?? "unknown"}`,
      `   buildings assessed=${(ev.buildings_total ?? 0) - (c.coverage?.buildings_obscured ?? 0)}`,
      `   damaged=${ev.buildings_damaged ?? 0} (${pct(ev.damaged_fraction)})`,
      `   obscured=${c.coverage?.buildings_obscured ?? 0}`,
      `   reports: corroborated=${ev.corroborated_count ?? 0} unverified=${ev.plausible_unverified_count ?? 0} suspect=${ev.suspect_count ?? 0} distinct_sources=${ev.distinct_source_count ?? 0}`,
      `   max urgency=${c.urgency_max ?? "n/a"} stated persons at risk=${c.persons_at_risk_est ?? "not stated"}`,
      `   reasons: ${(c.top_reasons ?? []).join(" | ")}`,
    ].join("\n");
  });

  return [
    `EVENT: ${scores.event_id}`,
    `GRID: ${scores.grid.cell_size_m} m cells`,
    `FUSION WEIGHTS: damage=${scores.weights.damage} vlm=${scores.weights.vlm} citizen=${scores.weights.citizen}`,
    "",
    "RANKED SECTORS:",
    ...lines,
  ].join("\n");
}

/**
 * Coarse hazard class from the event id, driving response-capacity wording.
 * Kept deliberately dumb and transparent: the event id names the hazard
 * ("...flooding...", "...earthquake...") and nothing downstream depends on it
 * beyond phrasing -- the numbers all come from the artifacts.
 */
function eventKind(eventId: string): "flood" | "earthquake" | "disaster" {
  if (/flood/i.test(eventId)) return "flood";
  if (/earthquake|quake|seismic/i.test(eventId)) return "earthquake";
  return "disaster";
}

function primaryCapacity(kind: ReturnType<typeof eventKind>): string {
  switch (kind) {
    case "flood":
      return "primary rescue capacity (boats, shallow-draft craft)";
    case "earthquake":
      return "primary urban search-and-rescue capacity (USAR teams, heavy lifting, trauma medical)";
    default:
      return "primary response capacity";
  }
}

const systemRules = (eventId: string) => `You are writing an operational resource-allocation brief for a ${eventKind(eventId)}
response coordinator for event "${eventId}", in the first 72 hours.

Write 4 short sections with these exact headings:
SITUATION
PRIORITY SECTORS
RESOURCE ALLOCATION
GAPS AND CAUTIONS

Hard rules:
- Use ONLY the numbers in the context block. Never invent a figure.
- "unassessed" coverage means NO satellite imagery. Say we cannot see there; never
  imply it is undamaged or safe.
- Cloud-obscured buildings are excluded from damage counts, so damage in those
  sectors is likely UNDERCOUNTED. Say so where it applies.
- Persons-at-risk figures are sums of explicitly stated counts. They are a FLOOR,
  not a population estimate. Label them that way.
- Suspect reports were withheld from scoring. Mention them as withheld, not as facts.
- Be terse and operational. No preamble, no reassurance, no filler.`;

/** The offline brief. Deterministic, derived from the same context. */
function fallbackBrief(scores: SectorScores, cellIds: string[] | undefined): string {
  const order = new Map((cellIds ?? []).map((id, i) => [id, i]));
  const ranked = [...scores.cells]
    .filter((c) => (cellIds && cellIds.length ? order.has(c.cell_id) : true))
    .sort((a, b) =>
      cellIds && cellIds.length
        ? (order.get(a.cell_id) ?? 1e9) - (order.get(b.cell_id) ?? 1e9)
        : b.score - a.score,
    );

  const scored = ranked.filter(
    (c) =>
      (c.evidence.signal_ids?.length ?? 0) > 0 ||
      (c.evidence.buildings_damaged ?? 0) > 0,
  );
  const top = scored.slice(0, 5);

  const totalDamaged = scores.cells.reduce(
    (n, c) => n + (c.evidence.buildings_damaged ?? 0),
    0,
  );
  const totalObscured = scores.cells.reduce(
    (n, c) => n + (c.coverage?.buildings_obscured ?? 0),
    0,
  );
  const suspectTotal = scores.cells.reduce(
    (n, c) => n + (c.evidence.suspect_count ?? 0),
    0,
  );
  const unassessedReported = scored.filter(
    (c) => c.coverage?.status === "unassessed",
  );
  const statedAtRisk = scored.reduce(
    (n, c) => n + (c.persons_at_risk_est ?? 0),
    0,
  );

  const out: string[] = [];

  out.push("SITUATION");
  out.push(
    `${totalDamaged} buildings assessed as damaged across ${scored.length} sectors carrying evidence. ` +
      `${totalObscured} footprints were cloud-obscured and excluded from scoring, so totals are a lower bound. ` +
      `${suspectTotal} report(s) were withheld from scoring as contradicted by imagery.`,
  );
  out.push("");

  out.push("PRIORITY SECTORS");
  top.forEach((c, i) => {
    const assessed =
      (c.evidence.buildings_total ?? 0) - (c.coverage?.buildings_obscured ?? 0);
    const bits: string[] = [];
    if (c.coverage?.status === "unassessed") {
      bits.push("NO IMAGERY COVERAGE - cannot confirm or refute reports here");
    } else {
      bits.push(
        `${c.evidence.buildings_damaged ?? 0}/${assessed} assessed buildings damaged (${pct(c.evidence.damaged_fraction)})`,
      );
    }
    if ((c.evidence.corroborated_count ?? 0) > 0) {
      bits.push(
        `${c.evidence.corroborated_count} corroborated report(s) from ${c.evidence.distinct_source_count ?? 0} distinct sources`,
      );
    }
    if ((c.evidence.plausible_unverified_count ?? 0) > 0) {
      bits.push(`${c.evidence.plausible_unverified_count} single-source report(s), recon priority`);
    }
    if ((c.coverage?.buildings_obscured ?? 0) > 0) {
      bits.push(`${c.coverage?.buildings_obscured} obscured, damage likely undercounted`);
    }
    out.push(
      `${i + 1}. ${c.place_label ?? c.cell_id} [${c.cell_id}] - ${bits.join("; ")}.`,
    );
  });
  out.push("");

  out.push("RESOURCE ALLOCATION");
  const first = top[0];
  const second = top[1];
  const capacity = primaryCapacity(eventKind(scores.event_id));
  if (first) {
    out.push(
      `- Move ${capacity} to ${first.place_label ?? first.cell_id} first: ` +
        `it holds the highest fused score in this run` +
        ((first.evidence.corroborated_count ?? 0) > 0
          ? ` and its reports are corroborated across ${first.evidence.distinct_source_count} independent sources.`
          : `, though its reports are not yet independently corroborated.`),
    );
  }
  if (second) {
    out.push(
      `- Stage secondary capacity for ${second.place_label ?? second.cell_id}; re-task if its score overtakes on new signals.`,
    );
  }
  const reconTargets = scored
    .filter((c) => (c.evidence.plausible_unverified_count ?? 0) > 0)
    .slice(0, 4)
    .map((c) => c.place_label ?? c.cell_id);
  if (reconTargets.length > 0) {
    out.push(
      `- Send recon (not full capacity) to single-source sectors: ${reconTargets.join(", ")}. ` +
        `One report is a lead, not a confirmation.`,
    );
  }
  if (statedAtRisk > 0) {
    out.push(
      `- Plan for at least ${statedAtRisk} named persons at risk. This is a FLOOR from explicitly stated counts only; ` +
        `reports that gave no number contribute nothing to it.`,
    );
  }
  out.push("");

  out.push("GAPS AND CAUTIONS");
  if (unassessedReported.length > 0) {
    out.push(
      `- ${unassessedReported.length} sector(s) with active reports lie OUTSIDE the imagery footprint ` +
        `(${unassessedReported.map((c) => c.place_label ?? c.cell_id).join(", ")}). ` +
        `Their scores are capped because we cannot see them - treat low scores there as ignorance, not safety.`,
    );
  }
  out.push(
    `- Channel 2 (VLM imagery findings) is not implemented in this build, so its ${scores.weights.vlm} weight ` +
      `contributes nothing to any sector.`,
  );
  out.push(
    `- ${totalObscured} cloud-obscured footprints are excluded from damage counts. Absence of damage in those ` +
      `sectors means we could not see, not that they are intact.`,
  );
  if (suspectTotal > 0) {
    out.push(
      `- ${suspectTotal} report(s) contradicted our own imagery and were withheld. They are retained in the ` +
        `Audit Drawer with a stated reason; review before dismissing.`,
    );
  }
  out.push(
    `- Damage labels are binary per building (the sensor pipeline persists a class, not a probability), so sector damage is a ` +
      `fraction of assessed buildings, not a severity measure.`,
  );

  return out.join("\n");
}

function provenance(generator: string): string {
  return `\n\n---\nGenerated by: ${generator}\nSource: sector_scores.json (contract v1.0.0). Figures are from the dataset, not the model.`;
}

async function streamGroq(
  apiKey: string,
  context: string,
  rules: string,
): Promise<ReadableStream<Uint8Array> | null> {
  const res = await fetch(GROQ_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
      "User-Agent": BROWSER_UA,
    },
    body: JSON.stringify({
      model: MODEL,
      temperature: 0.2,
      max_tokens: 1400,
      // gpt-oss is a reasoning model. "low" keeps latency sane for a panel that
      // streams to a human; the reasoning trace is not shown to the responder.
      reasoning_effort: "low",
      messages: [
        { role: "system", content: rules },
        { role: "user", content: context },
      ],
      stream: true,
    }),
  });

  if (!res.ok || !res.body) return null;

  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buffer = "";

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const reader = res.body!.getReader();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload || payload === "[DONE]") continue;
            try {
              const json = JSON.parse(payload);
              // OpenAI-compatible shape: choices[0].delta.content.
              // gpt-oss streams its reasoning trace separately; only `content`
              // is prose meant for the responder, so `reasoning` is ignored.
              const text: string = json?.choices?.[0]?.delta?.content ?? "";
              if (text) controller.enqueue(encoder.encode(text));
            } catch {
              // A partial SSE frame; ignore and wait for the rest.
            }
          }
        }
        controller.enqueue(encoder.encode(provenance(`${MODEL} (live, via Groq)`)));
      } finally {
        controller.close();
        reader.releaseLock();
      }
    },
  });
}

/** Stream a fixed string in word chunks, so the offline path also feels live. */
function streamText(text: string, generator: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  const tokens = text.split(/(\s+)/);
  let i = 0;
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (i >= tokens.length) {
        controller.enqueue(encoder.encode(provenance(generator)));
        controller.close();
        return;
      }
      const chunk = tokens.slice(i, i + 3).join("");
      i += 3;
      controller.enqueue(encoder.encode(chunk));
      await new Promise((r) => setTimeout(r, 16));
    },
  });
}

export async function POST(request: Request) {
  let body: BriefRequest = {};
  try {
    body = (await request.json()) as BriefRequest;
  } catch {
    // No body is fine: fall back to the full-corpus ranking.
  }

  let scores: SectorScores;
  try {
    scores = await loadScores();
  } catch {
    return new Response(
      "BRIEF UNAVAILABLE\n\nsector_scores.json could not be read. Run:\n" +
        "  cd pipeline && PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all\n",
      { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }

  const context = buildContext(scores, body.cellIds);
  const apiKey = process.env.GROQ_API_KEY;

  const headers = {
    "Content-Type": "text/plain; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Brief-Generator": apiKey ? "groq-attempted" : "deterministic-fallback",
  };

  if (apiKey) {
    try {
      const stream = await streamGroq(apiKey, context, systemRules(scores.event_id));
      if (stream) return new Response(stream, { headers });
    } catch {
      // Fall through to the deterministic brief rather than failing the request.
    }
  }

  return new Response(
    streamText(
      fallbackBrief(scores, body.cellIds),
      apiKey
        ? "deterministic fallback (Groq call failed)"
        : "deterministic fallback (no GROQ_API_KEY set)",
    ),
    { headers },
  );
}
