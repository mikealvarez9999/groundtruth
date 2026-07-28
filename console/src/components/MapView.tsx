"use client";

/**
 * The map: MapLibre GL JS for the base layers, deck.gl overlaid for anything
 * that animates.
 *
 * Basemap: two stacked raster sources — ESRI World Imagery satellite tiles
 * (no token, free, used by Google Earth and many of its clones) on top of Carto
 * dark OSM raster. The Carto layer is the fallback: if ESRI is blocked or slow
 * the dark raster still paints a real map under everything else, so the
 * console degrades gracefully instead of rendering the empty hash grid.
 *
 * Flood imagery: the per-epoch Sentinel-1 flood mask (flood.png, produced by
 * pipeline/flood_overlay.py) drapes between the basemap and the sector heat, so
 * the floodwater that drove each building's damage_class is visible under the
 * dots. It is the classifier's actual output raster, not an illustration.
 *
 * Division of labour:
 *   MapLibre  — basemap (dark + satellite), SAR flood overlay, valid-area mask,
 *               sector cells, building damage points
 *   deck.gl   — signal pins and the pulsing priority markers (time-driven)
 *
 * Buildings render as circles rather than polygons on purpose: a 10 m footprint
 * is sub-pixel at district zoom, so polygons would show an empty map. Zoom past
 * 15 and the radius grows toward true scale.
 */

import { useCallback, useEffect, useRef } from "react";
// maplibre-gl v6 has NO default export -- named imports only.
import {
  AttributionControl,
  Map as MLMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type GeoJSONSource,
  type IControl,
  type ImageSource,
  type MapLayerMouseEvent,
  type StyleSpecification,
} from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { DamageLayer, Signal, ValidArea } from "@/lib/types";
import type { LiveCell } from "@/lib/fusion";

export interface LayerVisibility {
  damage: boolean;
  sectors: boolean;
  signals: boolean;
  flood: boolean;
  satellite: boolean;
  national: boolean;
}

/** Georeferenced SAR flood-mask image for the current epoch. */
export interface FloodOverlay {
  url: string;
  /** [west, south, east, north] straight from the mask GeoTIFF. */
  bounds: [number, number, number, number];
}

interface Props {
  damage: DamageLayer | null;
  validArea: ValidArea | null;
  floodOverlay: FloodOverlay | null;
  /**
   * Wide country/regional flood context. Drawn underneath the AOI overlay as
   * a faded backdrop so reviewers can see the national extent of the event
   * without it competing with the per-cell flood mask they're scrutinising.
   */
  nationalOverlay: FloodOverlay | null;
  cells: LiveCell[];
  signals: Signal[];
  visibility: LayerVisibility;
  selectedCellId: string | null;
  onSelectCell: (cellId: string | null) => void;
  onSelectSignal: (signal: Signal) => void;
}

const SYLHET_CENTER: [number, number] = [91.98, 24.95];

/**
 * Point MapLibre at the worker module we serve ourselves.
 *
 * maplibre-gl v6 runs its worker as an ES module loaded from a separate file. Left
 * to the bundler's resolution, the worker started but never answered any message:
 * sources stayed unparsed, `isStyleLoaded()` never became true, and the map
 * rendered nothing at all while logging no error. `scripts/sync-maplibre-worker.mjs`
 * copies the worker (and the shared chunk it imports relatively) into
 * public/maplibre/ at build time so this path is always valid and always matches
 * the installed version.
 *
 * Set once at module scope, before any Map is constructed -- MapLibre reads it when
 * it lazily spins up the shared worker pool.
 */
setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");

const TIER_COLOR: Record<string, [number, number, number]> = {
  corroborated: [34, 211, 238],
  plausible_unverified: [251, 191, 36],
  suspect: [244, 63, 94],
};

/**
 * Base style: dark Carto background + ESRI World Imagery satellite raster.
 *
 * Two raster sources are registered up front and the satellite one is rendered
 * on top of the dark one. The satellite tiles carry real photo-satellite imagery
 * (Esri / Maxar / Earthstar Geographics), so the operator gets a Google-Earth-like
 * view of Sylhet instead of the blank dark canvas. The Carto dark layer stays
 * visible underneath as a fallback: if the satellite tile request fails or the
 * network is down, the dark raster still renders and the user sees a map, just
 * without the photo overlay.
 *
 * The `glyphs` key must be OMITTED, not set to undefined. MapLibre validates the
 * style and rejects `glyphs: undefined` with "string expected, undefined found",
 * which aborts the style load -- and because every layer is added inside the
 * `load` handler, that silently produced a completely blank map with a working
 * HUD on top of it. No glyphs is fine here only because we add no symbol layers;
 * all map text goes through deck.gl's TextLayer, which builds its own font atlas
 * locally.
 *
 * The basemaps are raster sources on purpose: raster tiles need no glyphs, no
 * sprite, and no style JSON fetch, so a failed tile request degrades to the
 * background colour instead of aborting the style.
 */
function baseStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      // Dark OSM-based raster. Acts as the fallback under the satellite layer
      // -- even if ESRI is blocked entirely, the dark Carto tiles paint a real
      // map. When satellite imagery is enabled we hide this so the satellite
      // and its reference labels read as one Google-Earth-style layer; when
      // satellite is off, we re-show this as the only base.
      basemap: {
        type: "raster",
        tiles: [
          "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
          "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
          "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
          "https://d.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        ],
        tileSize: 256,
        attribution: "© OpenStreetMap contributors © CARTO",
      },
      // Satellite imagery raster. ESRI's ArcGIS World_Imagery is the de-facto
      // free public satellite tile service (no token, attribution required) --
      // the same feed Google Earth and a thousand other tools pull from. Tile
      // schema is /tile/{z}/{y}/{x} (note Y BEFORE X). Visibility follows the
      // user's "satellite" toggle in SidePanel.
      satellite: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        // Reach up to two of ESRI's anycast mirrors before giving up on a tile.
        // Without this a single slow node can leave a permanent grey square
        // over part of the map.
        maxzoom: 19,
        // ESRI's terms require attribution to all four data providers plus the
        // GIS community. AttributionControl picks this up and renders it in
        // the bottom-right compact strip.
        attribution:
          "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community",
      },
      // ESRI's pre-rendered reference layer: country / admin boundaries and
      // city / town / village labels composited onto a transparent raster.
      // This is the Google-Earth-style place labeling -- Sylhet, Jaintiapur,
      // Sunamganj, etc. -- drawn by ESRI in their own typeface, in their own
      // zoom-dependent font sizes, on transparent tiles sized to match
      // World_Imagery exactly. Drawn ON TOP of the satellite raster so the
      // labels sit on the photo, not under it. Same host, same schema
      // /tile/{z}/{y}/{x}, so CORS / caching / attribution behave identically.
      reference: {
        type: "raster",
        tiles: [
          "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        ],
        tileSize: 256,
        maxzoom: 19,
        attribution:
          "Labels © Esri, HERE, Garmin, Food and Agriculture Organization of the United Nations, and the GIS User Community",
      },
    },
    layers: [
      { id: "bg", type: "background", paint: { "background-color": "#04060c" } },
      // Carto dark base. Rendered at 0 opacity by default so the satellite +
      // reference pair win the first frame; the visibility effect below
      // restores the dark base to 0.55 when the user toggles satellite off.
      // Driving this with `raster-opacity` (instead of `visibility: none`)
      // keeps MapLibre's tile cache warm and prevents spurious re-requests.
      {
        id: "basemap",
        type: "raster",
        source: "basemap",
        paint: { "raster-opacity": 0, "raster-fade-duration": 150 },
        layout: { visibility: "visible" },
      },
      // ESRI satellite imagery on top of the dark base. Dimmed a touch so our
      // overlays (sector heat, building damage, signals) stay legible on top
      // of busy photo detail.
      {
        id: "satellite",
        type: "raster",
        source: "satellite",
        paint: { "raster-opacity": 0.85, "raster-fade-duration": 150 },
        layout: { visibility: "visible" },
      },
      // Reference place-name labels. Drawn ABOVE the satellite raster so the
      // city / town names sit cleanly on the photo like Google Earth's built-
      // in labels. The reference tiles are transparent everywhere except the
      // actual label glyphs, so this layer does not darken or distort the
      // satellite imagery underneath.
      {
        id: "reference-labels",
        type: "raster",
        source: "reference",
        paint: { "raster-opacity": 1.0, "raster-fade-duration": 150 },
        layout: { visibility: "visible" },
      },
    ],
  } as unknown as StyleSpecification;
}

/** Build a cell-polygon FeatureCollection for the sector heat layer. */
function cellsToGeoJSON(cells: LiveCell[]) {
  return {
    type: "FeatureCollection" as const,
    features: cells.map((c) => {
      const [w, s, e, n] = (c.bbox ?? [0, 0, 0, 0]) as number[];
      return {
        type: "Feature" as const,
        properties: {
          cell_id: c.cell_id,
          score: c.liveScore,
          rank: c.liveRank,
          unassessed: c.coverage?.status === "unassessed" ? 1 : 0,
          suspect: c.arrivedSuspect,
        },
        geometry: {
          type: "Polygon" as const,
          coordinates: [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
        },
      };
    }),
  };
}

/** Buildings as points: centroid + damage state. */
function damageToPoints(damage: DamageLayer) {
  return {
    type: "FeatureCollection" as const,
    features: damage.features.map((f) => {
      const ring = f.geometry.coordinates[0] as unknown as number[][];
      let lon = 0;
      let lat = 0;
      for (const p of ring) {
        lon += p[0];
        lat += p[1];
      }
      return {
        type: "Feature" as const,
        properties: {
          // 0 intact, 1 damaged, 2 obscured. Obscured wins: we could not see it,
          // so it must never be drawn as an assessment either way.
          state: f.properties.obscured
            ? 2
            : f.properties.damage_class === "damaged"
              ? 1
              : 0,
        },
        geometry: {
          type: "Point" as const,
          coordinates: [lon / ring.length, lat / ring.length],
        },
      };
    }),
  };
}

export default function MapView({
  damage,
  validArea,
  floodOverlay,
  nationalOverlay,
  cells,
  signals,
  visibility,
  selectedCellId,
  onSelectCell,
  onSelectSignal,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MLMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const readyRef = useRef(false);
  const timeRef = useRef(0);

  // Latest props, read by the animation loop without re-subscribing it.
  // Assigned in an effect rather than during render: mutating a ref while
  // rendering is not safe under concurrent React, and the loop only needs the
  // values by the next frame anyway.
  const stateRef = useRef({ cells, signals, visibility, onSelectSignal });
  useEffect(() => {
    stateRef.current = { cells, signals, visibility, onSelectSignal };
  }, [cells, signals, visibility, onSelectSignal]);

  //
  // Single flush function driven by refs, called both when data changes and when
  // the map becomes ready. The previous version registered `map.once("load", push)`
  // with `push` closing over the data as it was AT THAT MOMENT -- which was null,
  // because the artifacts arrive after mount. The handler fired once with nothing
  // to push and was then gone forever, so all three sources stayed empty and the
  // map rendered blank under a fully working HUD. Refs + an idempotent flush
  // removes the ordering question entirely.
  const dataRef = useRef({ damage, validArea, cells, floodOverlay, nationalOverlay });
  useEffect(() => {
    dataRef.current = { damage, validArea, cells, floodOverlay, nationalOverlay };
  }, [damage, validArea, cells, floodOverlay, nationalOverlay]);

  // Fit the camera to the imagery footprint once, the first time we have it.
  // A hardcoded zoom was wrong for the data: at z8.6 a 500 m cell is ~1.3 px, so
  // every layer was technically rendering and visually absent. Fitting also means
  // this keeps working when the real Sylhet AOI replaces the synthetic one.
  const fittedRef = useRef(false);

  const flush = useCallback(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const { damage: d, validArea: va, cells: c } = dataRef.current;

    if (va && !fittedRef.current) {
      const ring = va.features?.[0]?.geometry?.coordinates?.[0];
      if (ring && ring.length > 0) {
        let w = Infinity;
        let s = Infinity;
        let e = -Infinity;
        let n = -Infinity;
        for (const [lon, lat] of ring as [number, number][]) {
          if (lon < w) w = lon;
          if (lon > e) e = lon;
          if (lat < s) s = lat;
          if (lat > n) n = lat;
        }
        if (Number.isFinite(w) && Number.isFinite(n)) {
          fittedRef.current = true;
          map.fitBounds(
            [
              [w, s],
              [e, n],
            ],
            { padding: 60, duration: 0, maxZoom: 12 },
          );
        }
      }
    }

    const damageSrc = map.getSource("damage") as GeoJSONSource | undefined;
    if (damageSrc && d) damageSrc.setData(damageToPoints(d) as never);

    const validSrc = map.getSource("valid-area") as GeoJSONSource | undefined;
    if (validSrc && va) validSrc.setData(va as never);

    const sectorSrc = map.getSource("sectors") as GeoJSONSource | undefined;
    if (sectorSrc) sectorSrc.setData(cellsToGeoJSON(c) as never);

    // SAR flood mask: an image source draped by its GeoTIFF bounds. Added on
    // first sight (below the sector heat, above the basemap), then swapped in
    // place when the epoch toggle changes the URL. Absent overlay = layer hidden,
    // never an error -- epochs without a rendered mask still work.
    const fo = dataRef.current.floodOverlay;
    const floodSrc = map.getSource("flood") as ImageSource | undefined;
    if (fo) {
      const [w2, s2, e2, n2] = fo.bounds;
      const coords: [[number, number], [number, number], [number, number], [number, number]] = [
        [w2, n2],
        [e2, n2],
        [e2, s2],
        [w2, s2],
      ];
      if (floodSrc) {
        floodSrc.updateImage({ url: fo.url, coordinates: coords });
        // Respect the user's layer toggle -- flush runs on every re-score and
        // must not resurrect a layer the user hid.
        map.setLayoutProperty(
          "flood-raster",
          "visibility",
          stateRef.current.visibility.flood ? "visible" : "none",
        );
      } else {
        map.addSource("flood", { type: "image", url: fo.url, coordinates: coords });
        map.addLayer(
          {
            id: "flood-raster",
            type: "raster",
            source: "flood",
            paint: { "raster-opacity": 0.85, "raster-fade-duration": 0 },
          },
          "valid-area-fill",
        );
      }
    } else if (map.getLayer("flood-raster")) {
      map.setLayoutProperty("flood-raster", "visibility", "none");
    }

    // National flood backdrop: same source/layout shape as the AOI overlay
    // but rendered faded and *under* the AOI flood so the eye reads it as
    // context, not as foreground. Only drawn when the artifact actually
    // exists -- absence is silently hidden, never an error.
    const no = dataRef.current.nationalOverlay;
    const natSrc = map.getSource("national-flood") as ImageSource | undefined;
    if (no) {
      const [w3, s3, e3, n3] = no.bounds;
      const coordsN: [[number, number], [number, number], [number, number], [number, number]] = [
        [w3, n3],
        [e3, n3],
        [e3, s3],
        [w3, s3],
      ];
      if (natSrc) {
        natSrc.updateImage({ url: no.url, coordinates: coordsN });
        map.setLayoutProperty(
          "national-flood-raster",
          "visibility",
          stateRef.current.visibility.national ? "visible" : "none",
        );
      } else {
        // Insert before "flood-raster" (and therefore before everything on
        // top of it) so the national backdrop genuinely sits below.
        const before = map.getLayer("flood-raster") ? "flood-raster" : "valid-area-fill";
        map.addSource("national-flood", {
          type: "image",
          url: no.url,
          coordinates: coordsN,
        });
        map.addLayer(
          {
            id: "national-flood-raster",
            type: "raster",
            source: "national-flood",
            paint: { "raster-opacity": 0.45, "raster-fade-duration": 0 },
          },
          before,
        );
      }
    } else if (map.getLayer("national-flood-raster")) {
      map.setLayoutProperty("national-flood-raster", "visibility", "none");
    }
  }, []);

  useEffect(() => {
    flush();
  }, [damage, validArea, cells, floodOverlay, nationalOverlay, flush]);

  // ---- one-time map construction ----------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new MLMap({
      container: containerRef.current,
      style: baseStyle(),
      center: SYLHET_CENTER,
      zoom: 8.6,
      minZoom: 6,
      maxZoom: 17,
      attributionControl: false,
      dragRotate: false,
    });
    mapRef.current = map;

    // Debugging handle. Layer problems here are invisible from the outside -- the
    // HUD keeps working over a blank map -- so keep a way to interrogate sources
    // from the browser console: __gtMap.getSource('sectors')
    (window as unknown as { __gtMap?: MLMap }).__gtMap = map;

    map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");
    // Required by the basemap's licence (OSM/CARTO). Compact so it stays quiet.
    map.addControl(new AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      // --- imagery footprint: what we could actually see -------------------
      map.addSource("valid-area", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "valid-area-fill",
        type: "fill",
        source: "valid-area",
        paint: { "fill-color": "#0e7490", "fill-opacity": 0.055 },
      });
      map.addLayer({
        id: "valid-area-line",
        type: "line",
        source: "valid-area",
        paint: {
          "line-color": "#22d3ee",
          "line-width": 1,
          "line-opacity": 0.5,
          "line-dasharray": [3, 3],
        },
      });

      // --- sector cells ---------------------------------------------------
      map.addSource("sectors", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "sectors-fill",
        type: "fill",
        source: "sectors",
        paint: {
          // Unassessed cells are grey-blue, never green: an unknown must not
          // read as a clear.
          "fill-color": [
            "case",
            ["==", ["get", "unassessed"], 1],
            "#475569",
            [
              "interpolate",
              ["linear"],
              ["get", "score"],
              0.0, "#0b2f4a",
              0.35, "#0e7490",
              0.6, "#eab308",
              0.8, "#f97316",
              1.0, "#ff2d55",
            ],
          ],
          "fill-opacity": [
            "interpolate", ["linear"], ["get", "score"],
            0, 0.14,
            1, 0.70,
          ],
        },
      });
      map.addLayer({
        id: "sectors-line",
        type: "line",
        source: "sectors",
        paint: {
          "line-color": [
            "case",
            [">", ["get", "suspect"], 0], "#f43f5e",
            ["<=", ["get", "rank"], 5], "#22d3ee",
            "#1e293b",
          ],
          "line-width": ["case", ["<=", ["get", "rank"], 5], 1.6, 0.4],
          "line-opacity": 0.85,
        },
      });
      map.addLayer({
        id: "sectors-selected",
        type: "line",
        source: "sectors",
        filter: ["==", ["get", "cell_id"], "__none__"],
        paint: { "line-color": "#f8fafc", "line-width": 2.4 },
      });

      // --- building damage ------------------------------------------------
      map.addSource("damage", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "damage-points",
        type: "circle",
        source: "damage",
        paint: {
          "circle-color": [
            "match", ["get", "state"],
            1, "#ff3b5c",
            2, "#7c8899",
            "#1f9d55",
          ],
          // Tuned so ~2500 scattered footprints read as clusters at region zoom
          // and approach true footprint scale past z15.
          "circle-radius": [
            "interpolate", ["exponential", 2], ["zoom"],
            8, 1.1,
            11, 2.6,
            14, 6,
            17, 20,
          ],
          "circle-opacity": [
            "match", ["get", "state"],
            2, 0.5,  // obscured: dimmer, it is not an assessment
            0.85,
          ],
          "circle-stroke-width": 0,
        },
      });

      readyRef.current = true;
      // The artifacts almost certainly arrived while the style was still loading,
      // so push whatever we already have now that the sources exist.
      flush();

      // deck.gl overlay for the animated marks.
      const overlay = new MapboxOverlay({ layers: [], interleaved: false });
      map.addControl(overlay as unknown as IControl);
      overlayRef.current = overlay;

      map.on("click", "sectors-fill", (ev: MapLayerMouseEvent) => {
        const feature = ev.features?.[0];
        if (feature) onSelectCell(String(feature.properties?.cell_id));
      });
      map.on("mouseenter", "sectors-fill", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "sectors-fill", () => {
        map.getCanvas().style.cursor = "";
      });
    });

    return () => {
      readyRef.current = false;
      overlayRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    // Both deps are stable: `flush` is a useCallback([]) and `onSelectCell` is a
    // useCallback in the parent, so this still constructs the map exactly once.
  }, [flush, onSelectCell]);

  // ---- push data into MapLibre sources -----------------------------------

  // ---- layer visibility --------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    const setVis = (id: string, on: boolean) => {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
      }
    };
    const setOpacity = (id: string, opacity: number) => {
      if (map.getLayer(id)) {
        map.setPaintProperty(id, "raster-opacity", opacity);
      }
    };
    setVis("damage-points", visibility.damage);
    setVis("sectors-fill", visibility.sectors);
    setVis("sectors-line", visibility.sectors);
    // Only when an overlay is loaded; a hidden-because-absent layer stays hidden.
    if (dataRef.current.floodOverlay) setVis("flood-raster", visibility.flood);
    if (dataRef.current.nationalOverlay) setVis("national-flood-raster", visibility.national);
    // Satellite toggle drives THREE basemap layers together so the operator
    // gets one coherent Google-Earth-style view: satellite imagery on, dark
    // Carto base off, ESRI reference place-name labels on. Toggling satellite
    // off collapses all three back to the dark OSM-style look.
    //
    // We drive the toggle with `raster-opacity` instead of `visibility` so
    // MapLibre never tears down its tile cache for the hidden layer. With
    // `visibility: none`, MapLibre was re-requesting tiles it already had --
    // producing a one-shot "AJAXError: Failed to fetch" on a tile that is
    // perfectly reachable (verified: 200 / 3621 B / CORS `*`). Driving with
    // opacity keeps the source alive and the cache warm.
    setOpacity("satellite", visibility.satellite ? 0.85 : 0);
    setOpacity("reference-labels", visibility.satellite ? 1.0 : 0);
    setOpacity("basemap", visibility.satellite ? 0 : 0.55);
  }, [visibility]);

  // ---- selection highlight + fly-to -------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    if (map.getLayer("sectors-selected")) {
      map.setFilter("sectors-selected", [
        "==", ["get", "cell_id"], selectedCellId ?? "__none__",
      ]);
    }
    if (!selectedCellId) return;
    const cell = cells.find((c) => c.cell_id === selectedCellId);
    if (cell) {
      map.flyTo({
        center: [cell.centroid.lon, cell.centroid.lat],
        zoom: Math.max(map.getZoom(), 12.5),
        duration: 900,
        essential: true,
      });
    }
    // Intentionally not depending on `cells`: re-flying on every re-score
    // would fight the user for control of the viewport.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedCellId]);

  // ---- animation loop: rebuild deck layers each frame -------------------
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const overlay = overlayRef.current;
      if (!overlay) return;

      timeRef.current += 1 / 60;
      const t = timeRef.current;
      const { cells: liveCells, signals: liveSignals, visibility: vis } = stateRef.current;

      // 0..1 sawtooth, used for the expanding priority rings.
      const phase = (t % 2.2) / 2.2;
      const top = liveCells
        .filter((c) => c.arrivedSignals.length > 0 || (c.components.damage ?? 0) > 0)
        .slice(0, 5);

      const layers: unknown[] = [];

      if (vis.sectors && top.length > 0) {
        // Three staggered expanding rings on the top-priority cells.
        for (let ring = 0; ring < 3; ring++) {
          const p = (phase + ring / 3) % 1;
          layers.push(
            new ScatterplotLayer({
              id: `priority-ring-${ring}`,
              data: top,
              getPosition: (d: LiveCell) => [d.centroid.lon, d.centroid.lat],
              getRadius: (d: LiveCell) =>
                (900 + 2600 * p) * (1.25 - 0.12 * (d.liveRank - 1)),
              radiusUnits: "meters",
              filled: false,
              stroked: true,
              getLineWidth: 90,
              lineWidthUnits: "meters",
              getLineColor: (d: LiveCell) => {
                const alpha = Math.round(200 * (1 - p) * (d.liveRank === 1 ? 1 : 0.55));
                return d.arrivedSuspect > 0
                  ? [244, 63, 94, alpha]
                  : [34, 211, 238, alpha];
              },
              updateTriggers: { getRadius: p, getLineColor: p },
              pickable: false,
            }),
          );
        }

        layers.push(
          new TextLayer({
            id: "priority-labels",
            data: top,
            getPosition: (d: LiveCell) => [d.centroid.lon, d.centroid.lat],
            // Render the rank + gazetteer name (or cell_id fallback) inside a
            // pill so the text stays legible on busy satellite imagery. The
            // text glyphs are white with a thick black outline and a bold
            // sans-serif family -- the same treatment Google Maps applies to
            // its labels over satellite. backgroundColor draws the pill, and
            // the `▌ ` / ` ▐` vertical bars at the edges give it a rounded
            // look without depending on font metrics.
            getText: (d: LiveCell) =>
              `▌ ${d.liveRank}. ${d.place_label ?? d.cell_id} ▐`,
            getSize: 13,
            getColor: [255, 255, 255, 255],
            // Solid dark pill behind the text so a bright satellite tile
            // (white roof, sun-glare) cannot wash the label out.
            background: true,
            getBackgroundColor: [4, 6, 12, 215],
            getBorderColor: [4, 6, 12, 255],
            getBorderWidth: 0.5,
            backgroundPadding: [5, 3],
            getPixelOffset: [0, -28],
            fontFamily: "Inter, system-ui, sans-serif",
            fontWeight: 700,
            characterSet: "auto",
            outlineWidth: 3,
            outlineColor: [4, 6, 12, 255],
            fontSettings: { sdf: true, fontSize: 13 },
            billboard: true,
            pickable: false,
          }),
        );
      }

      if (vis.signals) {
        const placed = liveSignals.filter((s) => s.geo);
        // Breathing halo. Critical claims breathe faster -- motion carries
        // urgency here, not just colour.
        layers.push(
          new ScatterplotLayer({
            id: "signal-halo",
            data: placed,
            getPosition: (d: Signal) => [d.geo!.lon, d.geo!.lat],
            getRadius: (d: Signal) => {
              const speed = d.claim.urgency === "critical" ? 3.2 : 1.6;
              const wave = 0.5 + 0.5 * Math.sin(t * speed);
              return 260 + 220 * wave;
            },
            radiusUnits: "meters",
            radiusMinPixels: 6,
            filled: true,
            stroked: false,
            getFillColor: (d: Signal) => {
              const [r, g, b] = TIER_COLOR[d.verification.tier] ?? [148, 163, 184];
              return [r, g, b, 46];
            },
            updateTriggers: { getRadius: Math.round(t * 20) },
            pickable: false,
          }),
        );
        layers.push(
          new ScatterplotLayer({
            id: "signal-core",
            data: placed,
            getPosition: (d: Signal) => [d.geo!.lon, d.geo!.lat],
            getRadius: 110,
            radiusUnits: "meters",
            radiusMinPixels: 3.5,
            radiusMaxPixels: 11,
            filled: true,
            stroked: true,
            getLineWidth: 1.4,
            lineWidthUnits: "pixels",
            getLineColor: [4, 6, 12, 220],
            getFillColor: (d: Signal) => {
              const [r, g, b] = TIER_COLOR[d.verification.tier] ?? [148, 163, 184];
              return [r, g, b, 245];
            },
            pickable: true,
            onClick: (info: { object?: Signal }) => {
              if (info.object) stateRef.current.onSelectSignal(info.object);
            },
          }),
        );
      }

      overlay.setProps({ layers: layers as never });
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, []);

  return (
    <div className="absolute inset-0">
      {/* Inline styles, not classes: MapLibre's own `.maplibregl-map` rule sets
          position:relative on this element, and an inline style is the only thing
          guaranteed to win regardless of stylesheet order. See globals.css. */}
      <div
        ref={containerRef}
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      />
    </div>
  );
}
