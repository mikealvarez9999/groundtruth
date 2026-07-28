"""Smoke test for the new PERSIST modes. Not part of the shipped repo.

Imports the bot via runpy with bot/ on sys.path so vlm_check resolves, then
constructs Tipline and prints which store it picked. Uses a fake token to
avoid Telegram contact.
"""
import os, sys, runpy

# Make bot/ importable so the `import vlm_check` inside the module resolves.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "bot"))
# Bot file runs main() at import time when __name__=='__main__' but not when
# loaded via run_module, so we just import the module and use the Tipline class.
import tipline as t  # noqa: E402

inst = t.Tipline()
print(f"store_kind={inst._store_kind}")
print(f"live_count={len(inst.live)}")
print(f"seed_count={len(inst.seed)}")
print(f"_epoch_ms('2024-01-01T00:00:00Z') = {t._epoch_ms('2024-01-01T00:00:00Z')}")
print("OK")