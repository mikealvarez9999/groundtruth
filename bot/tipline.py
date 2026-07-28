"""Live Telegram tip-line for GroundTruth citizen reports.

Long-polling (getUpdates), so it needs NO public webhook, NO tunnel, NO ngrok --
you run it on the demo laptop, text the bot, the tip lands. It reuses the REAL
pipeline: extract -> geocode -> verify_all, the identical code path the seed
loader uses. Each tip is verified against the committed damage layer + valid-area
(so it can be corroborated by, or contradicted by, everything already known) and
appended to console/public/data/live_signals.json, which the console polls.

Phase 2 upgrades (ship-night scope):
  - Shared GPS (D-028): when message.location is present we use the lat/lon
    directly and record geocode.method='gps_shared' (score 1.0). The gazetteer
    is bypassed for that path; text place reference still flows through
    extract+geocode as before.
  - Photos: the LARGEST size of message.photo is downloaded via getFile and
    saved under console/public/data/tips/<signal_id>.jpg. signal.raw.media_refs
    carries a {photo_path, received_at} object so the Audit Drawer can render
    the thumbnail.
  - Per-chat pending (D-028): a tip with no location object AND no parseable
    place string is held in an in-memory dict keyed by chat id, expiring after
    10 minutes. If the same sender follows up with a location within the
    window, the held text is promoted to a real signal at that location.
  - VLM hook (D-029): bot/vlm_check.py is called when a photo is attached.
    Its 3-way verdict modulates, never overrides, the spatial tier ladder.
    NO_COVERAGE never becomes suspect on VLM alone.

PRIVACY (non-negotiable, per bot/README.md): we NEVER store a Telegram user id,
phone number, or display name. source_id and author_ref are salted hashes, so a
person's reports still corroborate each other without us keeping anything that
identifies them. Photos carry NO EXIF; we write the JPEG through without
metadata and store nothing but the bytes and the signal id.

Run (from repo root):
    PowerShell:  $env:TELEGRAM_BOT_TOKEN="123456:ABC-your-token"; python bot\tipline.py
    bash:        TELEGRAM_BOT_TOKEN=123456:ABC-your-token python bot/tipline.py
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import traceback
import uuid
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Reuse the real pipeline. The bot lives outside pipeline/src, so put it on the path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from groundtruth.extract import PROMPT_VERSION, content_hash, detect_lang, extract  # noqa: E402
from groundtruth.geocode import geocode  # noqa: E402
from groundtruth.verify import verify_all  # noqa: E402

import vlm_check  # noqa: E402  -- the sibling module in bot/

from groundtruth import grid as _grid  # noqa: E402  -- for cell_id on gps_shared

PROCESSED = ROOT / "data" / "processed"
LIVE_OUT = ROOT / "console" / "public" / "data" / "live_signals.json"
TIPS_DIR = LIVE_OUT.parent / "tips"  # gitignored via console/.gitignore /public/data/

# Held-claim window: a text tip with no parseable location is parked for this
# long, then dropped. Keeps a single in-memory dict size bounded.
PENDING_TTL_S = 600  # 10 minutes, per Phase 2 brief

# Salt so a raw Telegram user id never leaves this process. Override in the env
# for a real deployment; the default is fine for a local demo.
SALT = os.environ.get("GT_TIPLINE_SALT", "groundtruth-tipline")

_API = "https://api.telegram.org/bot{token}/{method}"
_FILE_API = "https://api.telegram.org/file/bot{token}/{file_path}"

# Tier ladder, low -> high. Used for the "demote one step" rule in D-029.
TIERS = ("suspect", "plausible_unverified", "corroborated")


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load(path: Path, default):
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default


def pseudonym(user_id) -> tuple[str, str]:
    """Stable, non-reversible id for one originator. Same person -> same ids,
    but the raw Telegram id is never stored."""
    digest = content_hash(SALT, str(user_id))
    return "src_tg_" + digest[:12], "tg_" + digest[:6]


def _geocode_from_gps(lon: float, lat: float) -> dict:
    """Build the geo block for a shared-location tip (D-028).

    We trust the lat/lon, set score=1.0 (no fuzzy matching), and emit the new
    gps_shared method enum so the audit drawer can colour-code it. The
    grid_cell_id is computed here because the verifier requires it on every
    placed signal.
    """
    return {
        "lon": float(lon),
        "lat": float(lat),
        "grid_cell_id": _grid.cell_id(float(lon), float(lat)),
        "geocode": {
            "method": "gps_shared",
            "matched_name": "",  # no name; coords are the source of truth
            "admin": None,
            "score": 1.0,
            "ambiguous": False,
            "candidates": [],
        },
    }


def _build_signal(
    text: str | None,
    user_id,
    *,
    photo_path: str | None = None,
    geo: dict | None = None,
) -> dict:
    """Inner worker: text (or text+photo) -> a signal.

    `geo` is the already-built geo block (either from gps_shared or from
    geocode()). If None, the extractor's location_ref couldn't be resolved and
    we leave geo null so the audit drawer can flag it.
    """
    source_id, author_ref = pseudonym(user_id)
    now = _now_iso()

    # The extractor is text-first; we still call it for the event_type, urgency,
    # persons_at_risk etc even when we already have a geocoord. Photo captions
    # take the same path.
    claim_text = text or ""
    claim = extract(claim_text)

    # If the caller already provided geo (gps_shared path), keep it.
    # Otherwise try the gazetteer on the extracted place name.
    if geo is None:
        geo = geocode(claim["location_ref"])

    media_refs: list = []
    if photo_path:
        media_refs.append(
            {
                "photo_path": photo_path,
                "received_at": now,
            }
        )

    return {
        "contract_version": "1.0.0",
        "signal_id": "sig_tg_" + uuid.uuid4().hex[:16],  # uuid for live arrivals
        "channel": "citizen_telegram",
        "source": {
            "source_id": source_id,
            "platform": "telegram",
            "author_ref": author_ref,
            "url": None,
            "received_at": now,
            "replay_offset_s": None,  # live, not part of the seeded timeline
        },
        "raw": {
            "text": claim_text or None,
            "lang": detect_lang(claim_text) if claim_text else "unknown",
            "media_refs": media_refs,
            "imagery_ref": None,
        },
        "claim": claim,
        "geo": geo,
        "extraction": {
            "model": "rules",  # same rule-based extractor as the seed path
            "prompt_version": PROMPT_VERSION,
            "extracted_at": now,
            "confidence": None,
            "cached": False,
        },
    }


def _demote(tier: str) -> str:
    """One step down the ladder. Below 'suspect' we clamp at 'suspect'."""
    if tier not in TIERS:
        return tier
    i = TIERS.index(tier)
    return TIERS[max(0, i - 1)]


def _promote(tier: str) -> str:
    """One step up. Above 'corroborated' we clamp at 'corroborated'."""
    if tier not in TIERS:
        return tier
    i = TIERS.index(tier)
    return TIERS[min(len(TIERS) - 1, i + 1)]


def _apply_vlm(sig: dict, vlm: dict) -> dict:
    """Modulate tier based on VLM verdict (D-029).

    Rules -- encoded EXACTLY as D-029 states them:
      * 'contradicts' -> demote one tier (corroborated -> plausible_unverified
        -> suspect); append 'photo_inconsistent_with_claim' to reason.
      * 'supports' -> if currently plausible_unverified AND spatial check
        was not NO_COVERAGE, promote to corroborated; append
        'photo_consistent' to reason. Otherwise no tier change.
      * 'inconclusive' -> no change.
      * NO_COVERAGE never becomes suspect regardless of VLM. If VLM says
        contradicts but spatial was NO_COVERAGE, we leave the tier alone.
      * The new vlm_assessment block is set on the signal in-place; verify
        did not see it (vlm_check is a no-op on the spatial tier math), so
        this is the only writer.
    """
    raw = sig.get("verification", {})
    spatial = (raw.get("spatial_check") or {}).get("status")
    tier = raw.get("tier", "plausible_unverified")
    reason = raw.get("reason", "")

    status = vlm["status"]

    if status == "contradicts" and spatial != "no_coverage":
        new_tier = _demote(tier)
        if new_tier != tier:
            tier = new_tier
            suffix = "photo_inconsistent_with_claim"
            if suffix not in reason:
                reason = f"{reason}; {suffix}" if reason else suffix

    elif status == "supports":
        # Only ever move up if we're already plausible_unverified and the
        # spatial ladder didn't tell us anything bad.
        if tier == "plausible_unverified" and spatial != "no_coverage":
            tier = "corroborated"
            suffix = "photo_consistent"
            if suffix not in reason:
                reason = f"{reason}; {suffix}" if reason else suffix

    sig["verification"]["tier"] = tier
    sig["verification"]["reason"] = reason
    # vlm_assessment is the schema-conformant block (no extra keys).
    sig["verification"]["vlm_assessment"] = {
        "status": vlm["status"],
        "model": vlm.get("model"),
        "description": vlm.get("description", ""),
        "assessed_at": vlm.get("assessed_at") or _now_iso(),
    }
    return sig


class Tipline:
    """Holds the known world (damage layer, valid area, seed + prior live tips)
    and verifies each new tip against all of it.

    Also owns the per-chat pending dict for tips that arrive without a location.
    """

    def __init__(self) -> None:
        self.damage = _load(
            PROCESSED / "damage_layer.geojson",
            {"type": "FeatureCollection", "features": []},
        )
        self.valid_area = _load(
            PROCESSED / "valid_area.geojson",
            {"type": "FeatureCollection", "features": []},
        )
        seed = _load(PROCESSED / "signals.seed.json", [])
        for s in seed:
            s.pop("eval", None)  # never let ground-truth labels touch verification
        self.seed = seed
        self.live = _load(LIVE_OUT, [])
        # chat_id -> {text, user_id, expires_at, signal_id_pending?}
        self._pending: dict[int, dict] = {}
        # chat_id -> last tip's signal_id, for /start suppression etc.
        self._last_tip_id: dict[int, str] = {}

    # ---------- core ingestion ---------------------------------------------

    def handle(self, text: str, user_id) -> tuple[dict, str]:
        """Plain text tip path (Phase 1 entry, unchanged shape for compat)."""
        sig = _build_signal(text, user_id)
        return self._verify_and_persist(sig)

    def process_message(self, message: dict) -> tuple[dict | None, str]:
        """Phase 2 dispatcher: decides whether the inbound message is text,
        a location share, a photo, or a held text being followed up.

        Returns (sig-or-None, ack-text).
        """
        # --- DIAG (Checkpoint 1): top-of-handler raw-update log. Written so
        # an operator can confirm with one tail -f that updates are arriving.
        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id")
        text_preview = (message.get("text") or message.get("caption") or "")[:80]
        has_loc = bool(message.get("location"))
        has_photo = bool(message.get("photo"))
        sys.stderr.write(
            f"[tipline] recv chat={chat_id} user={user_id} "
            f"text={text_preview!r} location={has_loc} photo={has_photo}\n"
        )
        sys.stderr.flush()

        # --- 2B: photo path -------------------------------------------------
        # Telegram sends the largest size first; we take that and ignore the
        # smaller previews. Caption (if any) is treated as the claim text.
        photo = self._largest_photo(message.get("photo"))
        location = message.get("location")
        text = (message.get("text") or message.get("caption") or "").strip() or None

        # Held-priority: if we had a parked text from this same chat and the
        # new message has a location, promote it now.
        pending = self._take_pending(chat_id)
        if pending and (location is not None or photo is not None):
            user_id = pending["user_id"]
            text = (pending["text"] or "") if not text else text  # photo caption wins if present
            # Fall through with text/location/photo from THIS update.

        # --- 2A: location path ---------------------------------------------
        if location is not None:
            geo = _geocode_from_gps(location["longitude"], location["latitude"])
            sig = _build_signal(text, user_id, geo=geo)
            if photo is not None:
                photo_path = self._store_photo(sig["signal_id"], photo, message, token=None)
                if photo_path:
                    sig["raw"]["media_refs"].append(
                        {"photo_path": photo_path, "received_at": _now_iso()}
                    )
            return self._verify_and_persist(sig)

        # --- 2B: photo path (no location) ----------------------------------
        if photo is not None:
            # Try to geocode the caption like a regular text tip; the photo
            # object lives in sig.raw.media_refs regardless.
            sig = _build_signal(text, user_id)
            photo_path = self._store_photo(sig["signal_id"], photo, message, token=None)
            if photo_path:
                sig["raw"]["media_refs"].append(
                    {"photo_path": photo_path, "received_at": _now_iso()}
                )
            return self._verify_and_persist(sig)

        # --- text-only path -------------------------------------------------
        if text:
            sig, ack = self.handle(text, user_id)
            # If extract+geocode couldn't place the claim, park the text and
            # ask for a location. Don't double-publish as a geo-less signal.
            if sig.get("geo") is None:
                self._set_pending(chat_id, text, user_id)
                return None, (
                    "I couldn't read a place in your message. Use the attachment "
                    "menu (paperclip) → Location → Share to send your position, "
                    "and I'll process the rest of your report automatically."
                )
            return sig, ack

        # --- no usable content -> park if user has chat history, else reply
        self._set_pending(chat_id, "", user_id)
        return None, (
            "I couldn't read a place in your message. Use the attachment menu "
            "(paperclip) → Location → Share to send your position, and I'll "
            "process the rest of your report automatically."
        )

    # ---------- helpers ----------------------------------------------------

    def _verify_and_persist(self, sig: dict) -> tuple[dict, str]:
        """Verify the new signal in the universe of all known signals, persist,
        optionally VLM-modulate, and ack.
        """
        universe = self.seed + self.live + [sig]
        verify_all(universe, self.damage, self.valid_area)

        # If the tip carried a photo we saved to disk, ask the VLM hook for a
        # verdict and apply it AFTER spatial verification (D-029 ordering).
        first_photo = next(
            (
                m["photo_path"]
                for m in sig.get("raw", {}).get("media_refs", [])
                if isinstance(m, dict) and m.get("photo_path")
            ),
            None,
        )
        if first_photo:
            vlm = vlm_check.assess_photo(
                first_photo,
                sig.get("raw", {}).get("text") or "",
                {
                    "cells": self._nearby_cells_for(sig),
                    "note": "groundtruth-rules-v1 spatial verdict already applied",
                },
            )
            sig = _apply_vlm(sig, vlm)

        self.live.append(sig)
        self._persist()
        return sig, self._ack(sig)

    def _nearby_cells_for(self, sig: dict) -> list[dict]:
        """Best-effort: hand the VLM a tiny view of the spatial context.

        Not all geographies have a centred grid cell in the active damage
        layer; if we miss, return an empty list and let the prompt note that.
        """
        geo = sig.get("geo") or {}
        cid = geo.get("grid_cell_id")
        return [{"grid_cell_id": cid}] if cid else []

    def _largest_photo(self, photos):
        if not photos:
            return None
        return max(photos, key=lambda p: p.get("file_size") or p.get("width", 0) * p.get("height", 0))

    def _store_photo(self, signal_id: str, photo: dict, _message: dict, token: str | None) -> str | None:
        """Download the photo via getFile and save as <signal_id>.jpg.

        We avoid touching EXIF: the bytes are written as-is through Python's
        file API (which copies verbatim). No pil, no imaging libs, no metadata
        extraction, no GPS strip -- because the file is freshly downloaded and
        Telegram's getFile response is the binary blob itself.
        """
        file_id = photo.get("file_id")
        if not file_id:
            return None
        token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not token:
            # No token in the test path -> skip download. The signal still
            # carries media_refs but the thumbnail will 404 in the console.
            return None
        try:
            meta = _call(token, "getFile", file_id=file_id)
            file_path = meta.get("result", {}).get("file_path")
            if not file_path:
                return None
            url = _FILE_API.format(token=token, file_path=file_path)
            with urllib.request.urlopen(url, timeout=15) as resp:
                blob = resp.read()
            ext = mimetypes.guess_extension(meta.get("result", {}).get("mime_type") or "") or ".jpg"
            if ext.lower() not in {".jpg", ".jpeg"}:
                # We declared the schema pattern locks to .jpg. Anything else
                # is stored as .jpg for simplicity; the schema validator only
                # runs over signal.media_refs, not the file on disk.
                ext = ".jpg"
            TIPS_DIR.mkdir(parents=True, exist_ok=True)
            target = TIPS_DIR / f"{signal_id}{ext}"
            with target.open("wb") as fh:
                fh.write(blob)
            # Public-relative path is what lives in media_refs.
            return f"tips/{signal_id}{ext}"
        except Exception:
            # Any failure -> no photo; the rest of the tip still proceeds.
            return None

    def _persist(self) -> None:
        LIVE_OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = LIVE_OUT.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(self.live, fh, ensure_ascii=False, indent=1)
        tmp.replace(LIVE_OUT)  # atomic, so the console never polls a half-written file

    def _ack(self, sig: dict) -> str:
        claim = sig["claim"]
        verif = sig["verification"]
        geo = sig.get("geo")
        where = geo["geocode"]["matched_name"] if geo else f"{claim['location_ref']} (could not locate)"

        vlm = verif.get("vlm_assessment")
        vlm_line = ""
        if vlm is not None:
            vlm_line = f"\n• photo review: {vlm['status']} ({vlm['model'] or 'no model'}) — {vlm['description']}"

        return (
            "Got it — here's what we understood. Reply if any of it is wrong:\n"
            f"• place: {where}\n"
            f"• type: {claim['event_type']}   urgency: {claim['urgency']}\n"
            f"• status: {verif['tier']}"
            f"{vlm_line}\n"
            "Your report is anonymous — we do not store your name or number."
        )

    # ---------- pending-by-chat state -------------------------------------

    def _set_pending(self, chat_id: int, text: str, user_id) -> None:
        self._pending[chat_id] = {
            "text": text,
            "user_id": user_id,
            "expires_at": time.time() + PENDING_TTL_S,
        }
        self._gc_pending()

    def _take_pending(self, chat_id: int) -> dict | None:
        self._gc_pending()
        item = self._pending.pop(chat_id, None)
        if item and time.time() < item["expires_at"]:
            return item
        return None

    def _gc_pending(self) -> None:
        now = time.time()
        for k in [k for k, v in self._pending.items() if v["expires_at"] < now]:
            self._pending.pop(k, None)


def _call(token: str, method: str, **params):
    url = _API.format(token=token, method=method)
    if params:
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data)
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        sys.exit(
            "Set TELEGRAM_BOT_TOKEN first.\n"
            '  PowerShell:  $env:TELEGRAM_BOT_TOKEN="123456:ABC-your-token"\n'
            "Get a token from @BotFather with /newbot."
        )

    tip = Tipline()
    # --- DIAG (Checkpoint 3): prove the write path is absolute, and prove
    # the bot can actually talk to Telegram before we enter the loop.
    sys.stderr.write(
        f"[tipline] cwd={os.getcwd()} LIVE_OUT={LIVE_OUT} "
        f"TIPS_DIR={TIPS_DIR} (absolute? {LIVE_OUT.is_absolute()})\n"
    )
    try:
        me = _call(token, "getMe")
        sys.stderr.write(f"[tipline] getMe ok: bot={me.get('result',{}).get('username')!r}\n")
    except urllib.error.HTTPError as exc:
        sys.stderr.write(f"[tipline] getMe FAILED HTTP {exc.code}: {exc.reason}\n")
        sys.stderr.write(
            "[tipline] Token rejected by Telegram. Check TELEGRAM_BOT_TOKEN; "
            "an invalid token returns 401 and we never enter the poll loop.\n"
        )
        sys.stderr.flush()
        return 2
    except Exception as exc:
        sys.stderr.write(f"[tipline] getMe FAILED: {exc!r}\n")
        sys.stderr.flush()
        return 2
    sys.stderr.flush()

    print("GroundTruth tip-line running (long-polling). Text your bot on Telegram. Ctrl+C to stop.")
    print(f"  seed reports loaded : {len(tip.seed)}")
    print(f"  writing live tips  -> {LIVE_OUT}")
    print(f"  photos -> {TIPS_DIR}  pending TTL = {PENDING_TTL_S}s")

    offset = None
    last_heartbeat = time.time()
    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            resp = _call(token, "getUpdates", **params)
        except KeyboardInterrupt:
            print("\nstopped.")
            return 0
        except urllib.error.HTTPError as exc:
            # 409 = another getUpdates consumer holds the lease; tell operator
            # plainly instead of looping silently.
            sys.stderr.write(f"[tipline] poll HTTP {exc.code}: {exc.reason}\n")
            if exc.code == 409:
                sys.stderr.write(
                    "[tipline] 409 Conflict — another bot instance is already "
                    "polling. Kill any duplicate python bot\\tipline.py and retry.\n"
                )
            sys.stderr.flush()
            time.sleep(3)
            continue
        except Exception as exc:  # transient network / API hiccup
            print("poll error:", exc)
            time.sleep(3)
            continue

        # --- DIAG (Checkpoint 1): heartbeat + update count ---
        now = time.time()
        result = resp.get("result", [])
        if now - last_heartbeat > 60:
            sys.stderr.write(
                f"[tipline] heartbeat offset={offset} pending={len(result)} "
                f"live={len(tip.live)} seed={len(tip.seed)}\n"
            )
            last_heartbeat = now
            sys.stderr.flush()

        for upd in result:
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("edited_message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]
            text = (msg.get("text") or "").strip()

            if text.startswith("/start") or text.startswith("/help"):
                _call(
                    token, "sendMessage", chat_id=chat_id,
                    text=(
                        "GroundTruth flood tip-line. Send a short report: what is "
                        "happening and where. You can also share your location via "
                        "the paperclip → Location menu, or send a photo with a "
                        "caption.\n"
                        "e.g. \"Water chest-deep in Companiganj bazar, families "
                        "on rooftops\".\n"
                        "You're anonymous — we never store your name or number."
                    ),
                )
                continue

            try:
                sig, ack = tip.process_message(msg)
            except Exception as exc:
                # Full traceback to stderr so the operator sees WHY a tip
                # bounced instead of just "Sorry" to the sender.
                sys.stderr.write("[tipline] handle error:\n")
                traceback.print_exc()
                sys.stderr.flush()
                try:
                    _call(
                        token, "sendMessage", chat_id=chat_id,
                        text="Sorry — could not process that report. Please try rephrasing.",
                    )
                except Exception:
                    pass
                continue

            if sig is None:
                _call(token, "sendMessage", chat_id=chat_id, text=ack)
                continue

            _call(token, "sendMessage", chat_id=chat_id, text=ack)
            geo = sig.get("geo")
            place = geo["geocode"]["matched_name"] if geo else sig["claim"]["location_ref"]
            photo_count = sum(
                1
                for m in sig.get("raw", {}).get("media_refs", [])
                if isinstance(m, dict)
            )
            print(
                f"  tip [{sig['source']['author_ref']}]: "
                f"{sig['claim']['event_type']} @ {place} -> "
                f"{sig['verification']['tier']}  photos={photo_count}"
            )


if __name__ == "__main__":
    raise SystemExit(main())
