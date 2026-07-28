/**
 * Server-only helper for the shared tip-line store.
 *
 * The bot writes to Upstash Redis when UPSTASH_REDIS_REST_URL and
 * UPSTASH_REDIS_REST_TOKEN are set; this module reads from the same place.
 * Keys mirror those in bot/tipline.py (REDIS_SIGNALS_KEY, REDIS_PHOTO_PREFIX).
 *
 * If the env vars are not set on the console (local machine demo where the bot
 * writes to a local file), these helpers throw a clear error so the route can
 * fall back to the legacy /data/live_signals.json file path.
 */

import { Redis } from "@upstash/redis";

export const REDIS_SIGNALS_KEY = "gt:signals:live";
export const REDIS_PHOTO_PREFIX = "gt:tip:photo:";

let _client: Redis | null = null;

export function getRedis(): Redis {
  if (_client) return _client;
  const url =
    process.env.UPSTASH_REDIS_REST_URL ?? process.env.UPSTASH_REST_URL ?? "";
  const token =
    process.env.UPSTASH_REDIS_REST_TOKEN ??
    process.env.UPSTASH_REST_TOKEN ??
    "";
  if (!url || !token) {
    throw new Error("UPSTASH_REDIS_REST_URL/_TOKEN not configured");
  }
  _client = new Redis({ url, token });
  return _client;
}

/** True iff Upstash env vars are present. The route uses this to pick the
 *  legacy file-fallback path when running against a local file store. */
export function redisConfigured(): boolean {
  return Boolean(
    (process.env.UPSTASH_REDIS_REST_URL ?? process.env.UPSTASH_REST_URL) &&
      (process.env.UPSTASH_REDIS_REST_TOKEN ??
        process.env.UPSTASH_REST_TOKEN),
  );
}
