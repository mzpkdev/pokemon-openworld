import { describe, expect, it } from "vitest";
import type { CatalogMap } from "./catalog";
import { placeConnection, solveGeography, toOpenLayersExtent, visibleSurfaceMaps } from "./geography";

function map(
  name: string,
  width: number,
  height: number,
  connections: CatalogMap["connections"] = [],
  world: CatalogMap["world"] = { layer: "surface", defaultVisible: true, variantGroup: null, variant: null },
): CatalogMap {
  return {
    name,
    id: `MAP_${name.toUpperCase()}`,
    region: "test",
    category: "routes",
    sourceGroup: "test",
    sourceRegion: null,
    mapType: "MAP_TYPE_ROUTE",
    mapSection: null,
    image: { path: `${name}.png`, sha256: "0".repeat(64), widthPixels: width * 16, heightPixels: height * 16 },
    layout: { id: `LAYOUT_${name.toUpperCase()}`, format: "test", widthMetatiles: width, heightMetatiles: height, primaryTileset: "primary", secondaryTileset: "secondary" },
    world,
    presentation: { music: null, weather: null, showMapName: null, requiresFlash: null },
    connections,
    warps: [],
  };
}

function link(direction: CatalogMap["connections"][number]["direction"], destinationMap: string, offsetMetatiles = 0): CatalogMap["connections"][number] {
  return { direction, offsetMetatiles, destinationMapId: `MAP_${destinationMap.toUpperCase()}`, destinationMap };
}

describe("placeConnection", () => {
  const source = { x: 10, y: 20, width: 7, height: 9 };
  const destination = { width: 5, height: 6 };

  it("uses the catalog cardinal placement formulas", () => {
    expect(placeConnection(source, destination, "right", 3)).toMatchObject({ x: 17, y: 23 });
    expect(placeConnection(source, destination, "left", 3)).toMatchObject({ x: 5, y: 23 });
    expect(placeConnection(source, destination, "down", 3)).toMatchObject({ x: 13, y: 29 });
    expect(placeConnection(source, destination, "up", 3)).toMatchObject({ x: 13, y: 14 });
  });

  it("adapts y-down catalog rectangles to y-up OpenLayers extents", () => {
    expect(toOpenLayersExtent(source, 16)).toEqual([160, -464, 272, -320]);
  });
});

describe("solveGeography", () => {
  it("is independent of catalog input order", () => {
    const maps = [
      map("A", 4, 4, [link("right", "B")]),
      map("B", 5, 3, [link("down", "C", 1)]),
      map("C", 2, 6),
    ];
    expect(solveGeography(maps)).toEqual(solveGeography([...maps].reverse()));
  });

  it("packs disconnected components without manual grid positions", () => {
    const result = solveGeography([map("A", 4, 4, [link("right", "B")]), map("B", 2, 4), map("Z", 3, 3)]);
    expect(result.components).toHaveLength(2);
    expect(result.placements.A).toMatchObject({ x: 0, y: 0 });
    expect(result.placements.B).toMatchObject({ x: 4, y: 0 });
    expect(result.placements.Z.x).toBeGreaterThan(result.placements.B.x + result.placements.B.width);
  });

  it("surfaces contradictory cycles and preserves a deterministic forest", () => {
    const result = solveGeography([
      map("A", 4, 4, [link("right", "B")]),
      map("B", 4, 4, [link("right", "A")]),
    ]);
    expect(result.residuals).toHaveLength(1);
    expect(result.residuals[0]).toMatchObject({ source: "B", destination: "A", direction: "right" });
    expect(result.placements.A).toMatchObject({ x: 0, y: 0 });
    expect(result.placements.B).toMatchObject({ x: 4, y: 0 });
  });
});

describe("visibleSurfaceMaps", () => {
  it("keeps only default-visible surface maps for the initial atlas", () => {
    const maps = [
      map("surface", 1, 1),
      map("hidden", 1, 1, [], { layer: "surface", defaultVisible: false, variantGroup: null, variant: null }),
      map("underwater", 1, 1, [], { layer: "underwater", defaultVisible: true, variantGroup: null, variant: null }),
      map("generated", 1, 1, [], { layer: "generated", defaultVisible: true, variantGroup: null, variant: null }),
    ];
    expect(visibleSurfaceMaps(maps).map((candidate) => candidate.name)).toEqual(["surface"]);
  });
});
