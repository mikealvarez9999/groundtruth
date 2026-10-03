/**
 * Copy the committed artifacts from /data/processed into public/data/.
 *
 * Why not just commit them twice: `damage_layer.geojson` alone is ~1.4 MB, and two
 * copies in git would drift the moment someone edits one. `data/processed/` is the
 * single committed source of truth; public/data/ is a build output and is gitignored.
 *
 * This means the console runs from committed data WITHOUT anyone needing Python.
 * `build_all.py` also writes public/data directly, so a full pipeline run and this
 * copy produce the same result.
 *
 * Missing artifacts are a WARNING, not an error: the console renders a "DATA
 * UNAVAILABLE" panel telling you what to run, which is more useful than a failed build.
 */

import { copyFile, cp, mkdir, readdir } from "node:fs/promises";
import path from "node:path";

const WANTED = [
  "damage_layer.geojson",
  "valid_area.geojson",
  "signals.seed.json",
  "sector_scores.json",
];

// Optional single-file artifacts: copied if present, silent if not (never a
// "DATA UNAVAILABLE" warning). The national flood context overlay lives here.
const OPTIONAL = ["national_flood.png", "national_flood.json"];

async function main() {
  const src = path.resolve(process.cwd(), "..", "data", "processed");
  const dest = path.join(process.cwd(), "public", "data");

  let present;
  try {
    present = new Set(await readdir(src));
  } catch {
    console.warn(
      `[sync-data] ${src} not found. Run:\n` +
        "  cd pipeline && PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all",
    );
    return;
  }

  await mkdir(dest, { recursive: true });

  const copied = [];
  const missing = [];
  for (const file of WANTED) {
    if (!present.has(file)) {
      missing.push(file);
      continue;
    }
    await copyFile(path.join(src, file), path.join(dest, file));
    copied.push(file);
  }

  for (const file of OPTIONAL) {
    if (present.has(file)) {
      await copyFile(path.join(src, file), path.join(dest, file));
      console.log(`[sync-data] copied optional ${file}`);
    }
  }

  // Dated SAR epochs (data/processed/epochs/<slug>/) power the console's
  // before/after toggle. Absent until build_epoch has run, which is fine --
  // Console.tsx hides the toggle until /data/epochs/index.json lists 2+ epochs.
  //
  // A copy failure here is deliberately NOT swallowed. The previous version of
  // this script wrapped the whole block in try/catch and logged nothing, which
  // is how the epoch sync went missing in the first place: the comment arrived
  // without the code, the toggle silently stopped rendering, and nobody saw a
  // warning. `epochs` existing in the source is a promise we made to the
  // console, so failing to deliver it must break the build, not hide.
  if (present.has("epochs")) {
    try {
      await cp(path.join(src, "epochs"), path.join(dest, "epochs"), {
        recursive: true,
      });
      console.log("[sync-data] copied epochs/ -> public/data/epochs/");
    } catch (err) {
      console.error(
        `[sync-data] epochs/ exists in ${src} but the copy FAILED: ${err.message}\n` +
          "  The console's before/after toggle will not render. Fix the copy, do not ignore.",
      );
      process.exitCode = 1;
    }
  }

  console.log(`[sync-data] copied ${copied.length}/${WANTED.length} artifacts -> public/data/`);
  if (missing.length) {
    console.warn(
      `[sync-data] MISSING: ${missing.join(", ")}\n` +
        "  The console will show DATA UNAVAILABLE. Run the pipeline:\n" +
        "  cd pipeline && PYTHONPATH=src ./.venv/bin/python -m groundtruth.build_all",
    );
  }
}

main().catch((err) => {
  console.error("[sync-data] FAILED:", err.message);
  process.exit(1);
});
