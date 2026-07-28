"""One-shot launcher for the GroundTruth Telegram tipline.

Reads TELEGRAM_BOT_TOKEN (and GT_TIPLINE_SALT, optional) from .env at the
project root, then exec's bot/tipline.py. Use this from the project root so
the bot's stdlib-urllib poll loop has nowhere to hide its diagnostics.

    python run_bot.py

Ctrl+C to stop. The bot writes to console/public/data/live_signals.json
atomically; the console dev server picks it up within ~4 s via its 4-second
poll in Console.tsx.

NOTE: this only works if the console dev server is already running on
http://localhost:3000 (npm run dev, in another shell). Without that,
nothing in the browser can see the file even if it is written.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".env"


def _load_env() -> dict[str, str]:
    """Minimal .env loader so we don't need python-dotenv.

    Lines like KEY=value, # comments, blank lines. Surrounding quotes are
    stripped. Existing process env wins (so a $env:TELEGRAM_BOT_TOKEN in
    PowerShell is honoured even if .env is missing).
    """
    out: dict[str, str] = {}
    if not ENV.is_file():
        return out
    for raw in ENV.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v:
            out[k] = v
    return out


def main() -> int:
    env = _load_env()
    # Forward EVERYTHING from .env into the child. Existing process env wins
    # so a $env:TELEGRAM_BOT_TOKEN in PowerShell is honoured even when .env is
    # missing or partial. We do NOT hard-code a list of keys here -- the
    # bot/vlm pipeline can grow new ones (GEMINI_API_KEY, GROQ_API_KEY, future
    # providers) without this launcher needing to know about them.
    forwarded: list[str] = []
    for k, v in env.items():
        if k not in os.environ:
            os.environ[k] = v
            forwarded.append(k)

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        print(
            "ERROR: TELEGRAM_BOT_TOKEN is not set in this shell OR .env.\n"
            f"  Looked in: {ENV}\n"
            "  Set it in PowerShell:\n"
            '    $env:TELEGRAM_BOT_TOKEN="123456:ABC..."\n'
            "  Or fill it in at the bottom of .env, then re-run.",
            file=sys.stderr,
        )
        return 1

    # PYTHONPATH so `bot/tipline.py` can `import groundtruth.*` from pipeline/src.
    os.environ.setdefault("PYTHONPATH", str(ROOT / "pipeline" / "src"))
    # Without this, Python block-buffers stdout when it is redirected to a
    # file (Start-Process -RedirectStandardOutput), so the launcher's banner
    # wouldn't appear in the log until the child exits. With this, every
    # print() flushes line-by-line and the operator sees the diag output live.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")

    bot = ROOT / "bot" / "tipline.py"
    if not bot.is_file():
        print(f"ERROR: {bot} does not exist.", file=sys.stderr)
        return 1

    # Surface provider availability at startup so a missing key is impossible
    # to miss. Without this banner the bot's reply can say "no VLM provider
    # available" with no indication that .env had one and we just dropped it.
    vlm_keys = {k: ("set" if os.environ.get(k) else "MISSING") for k in
                ("GEMINI_API_KEY", "GROQ_API_KEY")}
    print(
        f"[run_bot] launching {bot}  (cwd={os.getcwd()}, "
        f"PYTHONPATH={os.environ['PYTHONPATH']})",
        flush=True,
    )
    print(
        f"[run_bot] VLM providers: GEMINI={vlm_keys['GEMINI_API_KEY']} "
        f"GROQ={vlm_keys['GROQ_API_KEY']}",
        flush=True,
    )
    print(
        f"[run_bot] forwarded {len(forwarded)} key(s) from .env: "
        f"{', '.join(forwarded) if forwarded else '(none -- already in shell env)'}",
        flush=True,
    )
    print(
        "[run_bot] Ctrl+C to stop. Diagnostic lines stream to stderr; "
        "tail this window if tips don't appear.",
        flush=True,
    )
    # Run the bot as a child so spaces in paths work; Ctrl+C / signal forwarding
    # in the parent shell still terminate it cleanly.
    import subprocess
    try:
        rc = subprocess.call([sys.executable, str(bot)], cwd=str(ROOT))
        return rc
    except KeyboardInterrupt:
        # subprocess already got SIGINT; just exit with 0.
        return 0


if __name__ == "__main__":
    raise SystemExit(main())