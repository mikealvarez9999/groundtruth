/**
 * Copy MapLibre's worker modules into public/maplibre/.
 *
 * WHY THIS EXISTS
 * maplibre-gl v6 is ESM-only and ships its web worker as a SEPARATE module
 * (`maplibre-gl-worker.mjs`), which itself imports `./maplibre-gl-shared.mjs`
 * relatively and is started with `new Worker(url, { type: "module" })`.
 *
 * Bundled through Next/Turbopack, MapLibre's default worker resolution produced a
 * worker that connected but never answered: the actor promise resolved, every
 * `setData` was accepted into `_pendingWorkerUpdate`, `_isUpdatingWorker` stuck at
 * true, `isStyleLoaded()` stayed false forever, and NOTHING rendered -- with no
 * error logged anywhere. The HUD worked perfectly over a blank map, which is the
 * worst kind of bug. Serving the real worker module ourselves and telling MapLibre
 * where it is (setWorkerUrl in MapView.tsx) fixes it.
 *
 * Copying from node_modules at build time (rather than committing the files)
 * guarantees the worker always matches the installed maplibre-gl version. A
 * mismatched worker fails in exactly the same silent way.
 *
 * Wired into `predev` and `prebuild` in package.json. public/maplibre/ is gitignored.
 */

import { copyFile, mkdir, readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";

const require = createRequire(import.meta.url);

// Files the worker needs. The shared chunk is the bulk of the library.
const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

async function main() {
  const pkgJson = require.resolve("maplibre-gl/package.json");
  const dist = path.join(path.dirname(pkgJson), "dist");
  const version = JSON.parse(await readFile(pkgJson, "utf8")).version;

  const outDir = path.join(process.cwd(), "public", "maplibre");
  await mkdir(outDir, { recursive: true });

  for (const file of FILES) {
    await copyFile(path.join(dist, file), path.join(outDir, file));
  }

  console.log(
    `[sync-maplibre-worker] copied ${FILES.length} files from maplibre-gl@${version} -> public/maplibre/`,
  );
}

main().catch((err) => {
  console.error("[sync-maplibre-worker] FAILED:", err.message);
  console.error(
    "The map will render blank without these files. Do not ignore this.",
  );
  process.exit(1);
});
