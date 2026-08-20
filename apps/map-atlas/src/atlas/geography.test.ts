import { describe, expect, it } from "vitest";
import type { CatalogMap } from "./catalog";
import { COMPONENT_GAP_METATILES, placeConnection, solveGeography, toOpenLayersExtent, visibleSurfaceMaps } from "./geography";

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

function intervalGap(leftStart: number, leftSize: number, rightStart: number, rightSize: number): number {
  return Math.max(leftStart - (rightStart + rightSize), rightStart - (leftStart + leftSize));
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
      map("Z", 8, 4),
      map("Y", 8, 4),
      map("X", 8, 4),
    ];
    expect(solveGeography(maps)).toEqual(solveGeography([...maps].reverse()));
  });

  it("packs disconnected components without manual grid positions", () => {
    const result = solveGeography([map("A", 4, 4, [link("right", "B")]), map("B", 2, 4), map("Z", 3, 3)]);
    expect(result.components).toHaveLength(2);
    expect(result.placements.A).toMatchObject({ x: 0, y: 0 });
    expect(result.placements.B).toMatchObject({ x: 4, y: 0 });
    expect(result.placements.Z.y).toBeGreaterThan(result.placements.B.y + result.placements.B.height);
  });

  it("separates every disconnected component bounding box by the fixed gap", () => {
    const result = solveGeography([
      map("A", 8, 4),
      map("B", 5, 7),
      map("C", 6, 3),
      map("D", 4, 9),
      map("E", 7, 5),
    ]);

    for (const [index, component] of result.components.entries()) {
      for (const other of result.components.slice(index + 1)) {
        const horizontalGap = intervalGap(component.bounds.x, component.bounds.width, other.bounds.x, other.bounds.width);
        const verticalGap = intervalGap(component.bounds.y, component.bounds.height, other.bounds.y, other.bounds.height);
        expect(Math.max(horizontalGap, verticalGap)).toBeGreaterThanOrEqual(COMPONENT_GAP_METATILES);
      }
    }
  });

  it("uses multiple shelves to keep representative disconnected components compact", () => {
    const result = solveGeography([
      map("A", 75, 75),
      map("B", 75, 75),
      map("C", 75, 75),
    ]);
    const bounds = result.components.map((component) => component.bounds);
    const packedWidth = Math.max(...bounds.map((component) => component.x + component.width));
    const packedHeight = Math.max(...bounds.map((component) => component.y + component.height));
    const oneDimensionalWidth = 3 * 75 + 2 * COMPONENT_GAP_METATILES;

    expect(new Set(bounds.map((component) => component.y)).size).toBeGreaterThan(1);
    expect(Math.max(packedWidth, packedHeight)).toBeLessThan(oneDimensionalWidth * 0.75);
  });

  it("translates connected placements and residual diagnostics together", () => {
    const result = solveGeography([
      map("A", 4, 4, [link("right", "B")]),
      map("B", 4, 4, [link("right", "A")]),
      map("Large", 50, 20),
    ]);

    expect(result.placements.A).toMatchObject({ x: 0, y: 28 });
    expect(result.placements.B).toMatchObject({ x: 4, y: 28 });
    expect(result.residuals).toEqual([{
      source: "B",
      destination: "A",
      direction: "right",
      offsetMetatiles: 0,
      expected: { x: 8, y: 28, width: 4, height: 4 },
      actual: { x: 0, y: 28, width: 4, height: 4 },
    }]);
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
