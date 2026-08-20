import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { CatalogMap, MapCatalog } from "./catalog";
import { MapViewport } from "./MapViewport";

const catalog = { pixelsPerMetatile: 16 } as MapCatalog;
const maps = [{
  name: "TestMap",
  layout: { widthMetatiles: 4, heightMetatiles: 3 },
  world: { layer: "surface", defaultVisible: true },
  connections: [],
}] as unknown as CatalogMap[];

describe("MapViewport", () => {
  it("renders a focusable map target with associated keyboard instructions", () => {
    const markup = renderToStaticMarkup(<MapViewport catalog={catalog} maps={maps} />);
    const target = markup.match(
      /<div class="atlas-map" tabindex="0" aria-label="Interactive regional map" aria-describedby="([^"]+)"/,
    );

    expect(target).not.toBeNull();
    expect(markup).toContain(`id="${target?.[1]}"`);
    expect(markup).toContain("Keyboard: focus the map, then use arrow keys to pan and plus or minus to zoom.");
  });
});
