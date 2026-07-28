/**
 * GET /api/tip-photo/[id]
 *
 * Serves a Telegram citizen tip photo. The id is the signal id (the bot stores
 * the JPEG bytes as base64 in Redis, keyed by signal_id). The [id] route
 * parameter is restricted to one stem; the .jpg extension is appended
 * automatically so AuditDrawer can keep emitting `tips/<id>.jpg` style paths.
 *
 * Upstash mode: GET gt:tip:photo:<id> -> base64-decoded JPEG bytes.
 * File mode  : <cwd>/public/data/tips/<id>.jpg  (legacy local-machine demo).
 *
 * Missing photos return 404 with a tiny placeholder text. We do NOT 500 -- a
 * disappeared photo is exactly the kind of benign thing the audit drawer
 * should render as a broken-image placeholder, not a thrown error.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import {
  REDIS_PHOTO_PREFIX,
  getRedis,
  hasValidSsoBypass,
  redisConfigured,
} from "@/lib/liveStore";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SAFE_ID = /^[A-Za-z0-9_\-]{4,64}$/;

export async function GET(
  request: Request,
  ctx: { params: Promise<{ id: string }> },
) {
  // Same SSO bypass as /api/live-signals. Without it, the deployed console
  // can't fetch JPEG thumbnails either.
  const bypassUrl = new URL(request.url);
  if (!hasValidSsoBypass(bypassUrl, request.headers)) {
    return new NextResponse(
      "tip-photo requires the deployment-protection bypass secret. " +
        "Pass ?secret=<value> as documented in bot/README.md.",
      { status: 401, headers: { "Content-Type": "text/plain; charset=utf-8" } },
    );
  }

  const { id } = await ctx.params;
  if (!SAFE_ID.test(id)) {
    return new NextResponse("invalid id", { status: 400 });
  }

  if (redisConfigured()) {
    try {
      const redis = getRedis();
      const raw = (await redis.get(REDIS_PHOTO_PREFIX + id)) as unknown;
      const b64 = typeof raw === "string" ? raw : null;
      if (!b64) return new NextResponse("not found", { status: 404 });
      const bytes = Buffer.from(b64, "base64");
      return new NextResponse(bytes, {
        headers: {
          "Content-Type": "image/jpeg",
          "Cache-Control": "public, max-age=3600, immutable",
        },
      });
    } catch {
      // fall through to file path
    }
  }

  const file = path.join(process.cwd(), "public", "data", "tips", `${id}.jpg`);
  try {
    const buf = await readFile(file);
    return new NextResponse(buf, {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": "public, max-age=3600, immutable",
      },
    });
  } catch {
    return new NextResponse("not found", { status: 404 });
  }
}
