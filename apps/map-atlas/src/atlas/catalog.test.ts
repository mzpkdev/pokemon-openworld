import { describe, expect, it } from "vitest";
import { CatalogValidationError, validateCatalog, type CatalogMap, type MapCatalog } from "./catalog";

function fixtureMap(
  name: string,
  id: string,
  connections: CatalogMap["connections"] = [],
): CatalogMap {
  return {
    name,
    id,
    region: "test",
    category: "routes",
    sourceGroup: "test",
    sourceRegion: null,
    mapType: "MAP_TYPE_ROUTE",
    mapSection: null,
    image: {
      path: `maps/test/${name}.png`,
      sha256: "0".repeat(64),
      widthPixels: 64,
      heightPixels: 48,
      overview: {
        path: `overviews/test/${name}.png`,
        sha256: "1".repeat(64),
        widthPixels: 16,
        heightPixels: 12,
      },
    },
    layout: {
      id: `LAYOUT_${name.toUpperCase()}`,
      format: "test",
      widthMetatiles: 4,
      heightMetatiles: 3,
      primaryTileset: "primary",
      secondaryTileset: "secondary",
    },
    world: {
      layer: "surface",
      defaultVisible: true,
      variantGroup: null,
      variant: null,
    },
    presentation: { music: null, weather: null, showMapName: null, requiresFlash: null },
    connections,
    warps: [],
  };
}

function catalogFixture(): MapCatalog {
  const alpha = fixtureMap("Alpha", "MAP_ALPHA", [{
    direction: "right",
    offsetMetatiles: 0,
    destinationMapId: "MAP_BETA",
    destinationMap: "Beta",
  }]);
  const beta = fixtureMap("Beta", "MAP_BETA");
  return {
    $schema: "catalog.schema.json",
    schemaVersion: 2,
    format: "pokemon-openworld-exterior-map-catalog",
    pixelsPerMetatile: 16,
    source: { revision: "fixture", workingTreeDirty: false },
    regions: [{ id: "test", label: "Test", mapCount: 2, maps: ["Alpha", "Beta"] }],
    maps: [alpha, beta],
  };
}

function detailsFor(catalog: MapCatalog): readonly string[] {
  try {
    validateCatalog(catalog);
  } catch (error) {
    expect(error).toBeInstanceOf(CatalogValidationError);
    return (error as CatalogValidationError).details;
  }
  throw new Error("expected semantic validation to fail");
}

describe("validateCatalog", () => {
  it("reports schema failures before the atlas tries to render a catalog", () => {
    expect(() => validateCatalog({})).toThrow(CatalogValidationError);
    expect(() => validateCatalog({})).toThrow(/schema/);
  });

  it("accepts a catalog with matching cross-record metadata", () => {
    expect(() => validateCatalog(catalogFixture())).not.toThrow();
  });

  it("requires an overview asset before the atlas tries to render a catalog", () => {
    const catalog = catalogFixture();
    Reflect.deleteProperty(catalog.maps[0].image, "overview");

    expect(() => validateCatalog(catalog)).toThrow(/overview/);
  });

  it("rejects a schema-valid duplicate map name", () => {
    const catalog = catalogFixture();
    catalog.maps.push({ ...catalog.maps[1], name: "Alpha", id: "MAP_ALPHA_COPY" });
    catalog.regions[0].mapCount = 3;
    catalog.regions[0].maps.push("Alpha");

    expect(detailsFor(catalog)).toContain('maps contains duplicate map name "Alpha".');
  });

  it("reports duplicate identifiers, region membership, and image dimensions", () => {
    const catalog = catalogFixture();
    catalog.maps[1].id = "MAP_ALPHA";
    catalog.maps[0].image.widthPixels = 63;
    catalog.maps[0].image.overview.heightPixels = 11;
    catalog.regions.push({ ...catalog.regions[0] });
    catalog.regions[0].mapCount = 1;
    catalog.regions[0].maps = ["Alpha"];

    const details = detailsFor(catalog);
    expect(details).toContain('maps contains duplicate map id "MAP_ALPHA".');
    expect(details).toContain('regions contains duplicate region id "test".');
    expect(details).toContain('maps[0].image.widthPixels is 63, expected 64 from layout and pixelsPerMetatile.');
    expect(details).toContain('maps[0].image.overview.widthPixels is 16, expected 15.75 as one-quarter of native image width.');
    expect(details).toContain('maps[0].image.overview.heightPixels is 11, expected 12 as one-quarter of native image height.');
    expect(details).toContain('regions[0].maps is missing map "Beta" declared for this region.');
  });

  it("reports connection and warp name or identifier disagreements for catalog maps", () => {
    const catalog = catalogFixture();
    catalog.maps[0].connections[0].destinationMap = "Alpha";
    catalog.maps[0].warps.push({
      warpId: "0",
      xMetatiles: 1,
      yMetatiles: 1,
      elevation: 0,
      destinationWarpId: "0",
      destinationMapId: "MAP_BETA",
      destinationMap: "Alpha",
    });

    const details = detailsFor(catalog);
    expect(details).toContain('maps[0].connections[0].destinationMap "Alpha" resolves to "MAP_ALPHA", not "MAP_BETA".');
    expect(details).toContain('maps[0].warps[0].destinationMapId "MAP_BETA" resolves to "Beta", not "Alpha".');
  });
});
