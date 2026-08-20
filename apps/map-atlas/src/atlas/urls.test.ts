import { describe, expect, it } from "vitest";
import { atlasUrl, atlasUrlWithState, catalogUrl, mapImageUrl, parseAtlasUrlState } from "./urls";

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

  it("round-trips region, selection, and camera state while preserving the deployment path", () => {
    const state = parseAtlasUrlState("/tools/map-atlas/?region=hoenn&map=Route101&x=120.125&y=-4&zoom=2.5");

    expect(state).toEqual({ region: "hoenn", selectedMap: "Route101", view: { center: [120.125, -4], zoom: 2.5 } });
    expect(atlasUrlWithState("/tools/map-atlas/?theme=forest#map", state)).toBe(
      "/tools/map-atlas/?theme=forest&region=hoenn&map=Route101&x=120.13&y=-4&zoom=2.5#map",
    );
  });

  it("drops incomplete or invalid camera values without discarding a valid selection", () => {
    expect(parseAtlasUrlState("/?region=johto&map=NewBarkTown&x=1&y=nope&zoom=2")).toEqual({
      region: "johto",
      selectedMap: "NewBarkTown",
      view: null,
    });
  });
});
