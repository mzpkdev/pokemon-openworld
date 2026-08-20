import { describe, expect, it } from "vitest";
import type { CatalogMap } from "./catalog";
import {
  EXIT_DETAIL_RESOLUTION_PIXELS,
  focusExtent,
  mapImageAssetKindForResolution,
  mapImageAssetPath,
  nextMapImageAssetKind,
  recordAtlasClickHit,
  searchMaps,
  shouldShowExitMarkers,
  warpCoordinate,
  type AtlasClickHit,
} from "./interactions";

function map(name: string, mapSection: string | null): CatalogMap {
  return {
    name,
    id: `MAP_${name.toUpperCase()}`,
    region: "test",
    category: "routes",
    sourceGroup: "test",
    sourceRegion: null,
    mapType: "MAP_TYPE_ROUTE",
    mapSection,
    image: {
      path: `${name}.png`,
      sha256: "0".repeat(64),
      widthPixels: 64,
      heightPixels: 48,
      overview: {
        path: `overviews/${name}.png`,
        sha256: "1".repeat(64),
        widthPixels: 16,
        heightPixels: 12,
      },
    },
    layout: { id: `LAYOUT_${name.toUpperCase()}`, format: "test", widthMetatiles: 4, heightMetatiles: 3, primaryTileset: "primary", secondaryTileset: "secondary" },
    world: { layer: "surface", defaultVisible: true, variantGroup: null, variant: null },
    presentation: { music: null, weather: null, showMapName: null, requiresFlash: null },
    connections: [],
    warps: [],
  };
}

describe("atlas interactions", () => {
  it("searches source map names and map-section symbols without punctuation sensitivity", () => {
    const maps = [map("Route101", "MAPSEC_OLDALE_TOWN"), map("PetalburgCity", "MAPSEC_PETALBURG_CITY")];

    expect(searchMaps(maps, "route 101").map((candidate) => candidate.name)).toEqual(["Route101"]);
    expect(searchMaps(maps, "oldale town").map((candidate) => candidate.name)).toEqual(["Route101"]);
    expect(searchMaps(maps, "petalburg").map((candidate) => candidate.name)).toEqual(["PetalburgCity"]);
  });

  it("places warp markers at source metatile centers in the y-up pixel projection", () => {
    expect(warpCoordinate(
      { x: 10, y: 20, width: 4, height: 3 },
      { xMetatiles: 3, yMetatiles: 4 },
      16,
    )).toEqual([216, -392]);
  });

  it("hides exits at a whole-region pixel resolution until explicitly toggled", () => {
    expect(shouldShowExitMarkers(false, EXIT_DETAIL_RESOLUTION_PIXELS + 0.01)).toBe(false);
    expect(shouldShowExitMarkers(false, EXIT_DETAIL_RESOLUTION_PIXELS)).toBe(true);
    expect(shouldShowExitMarkers(true, EXIT_DETAIL_RESOLUTION_PIXELS * 8)).toBe(true);
  });

  it("keeps overview sources until detail resolution, then swaps only on boundary crossings", () => {
    const candidate = map("Route101", "MAPSEC_OLDALE_TOWN");

    expect(mapImageAssetKindForResolution(EXIT_DETAIL_RESOLUTION_PIXELS + 0.01)).toBe("overview");
    expect(mapImageAssetKindForResolution(EXIT_DETAIL_RESOLUTION_PIXELS)).toBe("native");
    expect(mapImageAssetPath(candidate, "overview")).toBe("overviews/Route101.png");
    expect(mapImageAssetPath(candidate, "native")).toBe("Route101.png");
    expect(nextMapImageAssetKind("overview", EXIT_DETAIL_RESOLUTION_PIXELS + 1)).toBeNull();
    expect(nextMapImageAssetKind("overview", EXIT_DETAIL_RESOLUTION_PIXELS)).toBe("native");
    expect(nextMapImageAssetKind("native", EXIT_DETAIL_RESOLUTION_PIXELS - 1)).toBeNull();
    expect(nextMapImageAssetKind("native", EXIT_DETAIL_RESOLUTION_PIXELS + 1)).toBe("overview");
  });

  it("focuses the exact rendered map extent", () => {
    expect(focusExtent({ x: 10, y: 20, width: 4, height: 3 }, 16)).toEqual([160, -368, 224, -320]);
  });

  it("retains the first map fallback but stops at the first overlapping warp marker", () => {
    const mapA: AtlasClickHit = { kind: "map", mapName: "Route101" };
    const mapB: AtlasClickHit = { kind: "map", mapName: "OldaleTown" };
    const firstWarp: AtlasClickHit = { kind: "warp", selection: { sourceMapName: "Route101", warpId: "0" } };
    const laterWarp: AtlasClickHit = { kind: "warp", selection: { sourceMapName: "OldaleTown", warpId: "1" } };

    const firstMap = recordAtlasClickHit(null, mapA);
    expect(firstMap).toEqual({ hit: mapA, stop: false });
    expect(recordAtlasClickHit(firstMap.hit, mapB)).toEqual({ hit: mapA, stop: false });

    let selected: AtlasClickHit | null = null;
    for (const candidate of [mapA, mapB, firstWarp, laterWarp]) {
      const outcome = recordAtlasClickHit(selected, candidate);
      selected = outcome.hit;
      if (outcome.stop) {
        break;
      }
    }
    expect(selected).toEqual(firstWarp);
  });
});
