import { describe, expect, it } from "vitest";
import { atlasUrl, catalogUrl, mapImageUrl } from "./urls";

describe("atlasUrl", () => {
  it("keeps catalog and image requests inside a non-root deployment path", () => {
    expect(catalogUrl("/tools/map-atlas/")).toBe("/tools/map-atlas/map-catalog/catalog.json");
    expect(mapImageUrl("maps/hoenn/routes/Route101.png", "/tools/map-atlas/")).toBe(
      "/tools/map-atlas/map-catalog/maps/hoenn/routes/Route101.png",
    );
  });

  it("also supports Vite's relative build base", () => {
    expect(atlasUrl("/map-catalog/catalog.json", "./")).toBe("./map-catalog/catalog.json");
  });
});
