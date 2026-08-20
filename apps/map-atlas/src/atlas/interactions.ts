import type { CatalogMap } from "./catalog";
import type { Placement } from "./geography";
import { toOpenLayersExtent } from "./geography";

/** Keep exits out of a whole-region overview, where hundreds of pins obscure the maps. */
export const EXIT_ZOOM_THRESHOLD = 2;

export interface WarpSelection {
  readonly sourceMapName: string;
  readonly warpId: string;
}

export type AtlasClickHit =
  | { readonly kind: "map"; readonly mapName: string }
  | { readonly kind: "warp"; readonly selection: WarpSelection };

/**
 * Keep the first polygon as a fallback, but let OpenLayers stop at its first
 * warp marker. `forEachFeatureAtPixel` yields topmost/closest features first.
 */
export function recordAtlasClickHit(
  current: AtlasClickHit | null,
  candidate: AtlasClickHit,
): { readonly hit: AtlasClickHit; readonly stop: boolean } {
  if (candidate.kind === "warp") {
    return { hit: candidate, stop: true };
  }
  return { hit: current ?? candidate, stop: false };
}

function normalizedSearchValue(value: string): string {
  return value.toLocaleLowerCase("en").replace(/[^a-z0-9]+/g, "");
}

/** Search the source map name and the game-facing map-section symbol deterministically. */
export function searchMaps(maps: readonly CatalogMap[], query: string): readonly CatalogMap[] {
  const needle = normalizedSearchValue(query);
  if (!needle) {
    return [];
  }
  return [...maps]
    .filter((map) => [map.name, map.mapSection ?? ""].some((value) => normalizedSearchValue(value).includes(needle)))
    .sort((left, right) => left.name.localeCompare(right.name, "en") || left.id.localeCompare(right.id, "en"));
}

/** Convert a source warp tile to the center-point coordinate used by the OpenLayers pixel projection. */
export function warpCoordinate(
  placement: Placement,
  warp: Pick<CatalogMap["warps"][number], "xMetatiles" | "yMetatiles">,
  pixelsPerMetatile: number,
): [number, number] {
  return [
    (placement.x + warp.xMetatiles + 0.5) * pixelsPerMetatile,
    -(placement.y + warp.yMetatiles + 0.5) * pixelsPerMetatile,
  ];
}

export function shouldShowExitMarkers(showExits: boolean, zoom: number | undefined): boolean {
  return showExits || (zoom ?? Number.NEGATIVE_INFINITY) >= EXIT_ZOOM_THRESHOLD;
}

/** Return the rendered exterior's full extent for an explicit camera focus request. */
export function focusExtent(placement: Placement, pixelsPerMetatile: number): [number, number, number, number] {
  return toOpenLayersExtent(placement, pixelsPerMetatile);
}
