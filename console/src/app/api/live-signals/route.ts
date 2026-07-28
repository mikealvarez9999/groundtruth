/**
 * GET /api/live-signals
 *
 * Returns the array of live Telegram tips that the bot has written since the
 * console last started. The newer (Upstash) path reads a sorted set; the
 * legacy file path is kept for local-machine dev where the bot writes to
 * console/public/data/live_signals.json.
 *
 * Response is a JSON array of Signal objects (sparse: typically {} on first
 * call, then upserted by signal_id in the console).
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import {
  REDIS_SIGNALS_KEY,
  getRedis,
  hasValidSsoBypass,
  redisConfigured,
} from "@/lib/liveStore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface Signal {
  signal_id: string;
  [k: string]: unknown;
}

async function fromUpstash(): Promise<Signal[] | null> {
  if (!redisConfigured()) return null;
  try {
    const redis = getRedis();
    // ZRANGE 0 -1 returns members in score order = arrival order.
    const raw = (await redis.zrange(REDIS_SIGNALS_KEY, 0, -1)) as unknown;
    const members: string[] = Array.isArray(raw)
      ? (raw as string[])
      : typeof raw === "string"
        ? [raw]
        : [];
    const seen = new Map<string, Signal>();
    for (const m of members) {
      try {
        const s = JSON.parse(m) as Signal;
        if (s && s.signal_id) seen.set(s.signal_id, s);
      } catch {
        /* a half-written entry; skip */
      }
    }
    return Array.from(seen.values());
  } catch {
    return null;
  }
}

async function fromFile(): Promise<Signal[]> {
  const file = path.join(process.cwd(), "public", "data", "live_signals.json");
  try {
    const buf = await readFile(file, "utf8");
    const parsed = JSON.parse(buf) as unknown;
    return Array.isArray(parsed) ? (parsed as Signal[]) : [];
  } catch {
    return [];
  }
}

export async function GET(request: Request) {
  // Vercel Authentication (Deployment Protection) gates every request behind an
  // SSO redirect, including /api/*. The console browser cannot follow the SSO
  // cookie flow on a JSON poll, so we accept a `?secret=...` query string
  // (or the bypass header) that matches the user-configured shared secret in
  // Vercel's dashboard. The route still works unauthenticated on a local
  // dev server where no SSO gate exists.
  const url = new URL(request.url);
  if (!hasValidSsoBypass(url, request.headers)) {
    return new NextResponse(
      "live-signals requires the deployment-protection bypass secret. " +
        "Pass ?secret=<value> as documented in bot/README.md.",
      { status: 401, headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }

  const upstash = await fromUpstash();
  const signals = upstash ?? (await fromFile());
  return NextResponse.json(signals, {
    headers: { "Cache-Control": "no-store" },
  });
}
