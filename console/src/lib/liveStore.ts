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

/**
 * Vercel Deployment-Protection bypass.
 *
 * When the Vercel project has "Vercel Authentication" turned on, every request --
 * including /api/* -- is redirected to vercel.com/sso-api before any of our code
 * runs. Vercel offers a "Protection Bypass for Automation" knob: a single
 * shared secret, sent as `?secret=<value>` (or `x-vercel-protection-bypass`
 * header), that skips the SSO redirect for that one request.
 *
 * We use it because the deployed console polls /api/live-signals every 4s and
 * a JavaScript fetch from the browser cannot follow the SSO cookie flow. The
 * same secret is hard-coded into the browser poll, so it is exposed via
 * DevTools. That is acceptable here because the URL is itself protected by the
 * same SSO gate -- anyone with the URL has the secret; the secret just keeps
 * the JS-poll loop unblocked.
 *
 * The hard-coded value is the user-chosen shared secret. Change both this
 * constant and the matching entry in Vercel's dashboard to rotate it.
 */
export const SSO_BYPASS_SECRET =
  "dhonerprojectkortesijotoshobbaal";

/**
 * Constant-time comparison of a request's `?secret=` (or bypass header) to
 * SSO_BYPASS_SECRET. Returns true iff the caller knows the secret.
 *
 * `URL` is a WHATWG URL object parsed from the request URL; `headers` is the
 * fetch Headers. Both checks match Vercel's documented bypass contract.
 */
export function hasValidSsoBypass(url: URL, headers: Headers): boolean {
  const fromQuery = url.searchParams.get("secret");
  const fromHeader = headers.get("x-vercel-protection-bypass");
  const supplied = fromQuery ?? fromHeader ?? "";
  if (!supplied) return false;
  // Constant-time comparison so a timing-attack probe can't leak the secret.
  if (supplied.length !== SSO_BYPASS_SECRET.length) return false;
  let diff = 0;
  for (let i = 0; i < supplied.length; i++) {
    diff |= supplied.charCodeAt(i) ^ SSO_BYPASS_SECRET.charCodeAt(i);
  }
  return diff === 0;
}
