import type { CatalogMap } from "./catalog";
import type { Placement } from "./geography";
import { toOpenLayersExtent } from "./geography";

/**
 * Show exit markers at one source metatile per CSS pixel or closer. The catalog
 * uses 16 source pixels per metatile, so this hides a whole-region overview
 * while preserving markers at the existing map-detail focus scale.
 */
export const EXIT_DETAIL_RESOLUTION_PIXELS = 16;

export type MapImageAssetKind = "overview" | "native";

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

export function shouldShowExitMarkers(showExits: boolean, resolution: number | undefined): boolean {
  return showExits || (resolution ?? Number.POSITIVE_INFINITY) <= EXIT_DETAIL_RESOLUTION_PIXELS;
}

/** Select native terrain only at the same detail boundary used for exit markers. */
export function mapImageAssetKindForResolution(resolution: number | undefined): MapImageAssetKind {
  return (resolution ?? Number.POSITIVE_INFINITY) <= EXIT_DETAIL_RESOLUTION_PIXELS ? "native" : "overview";
}

/** Return a source replacement only when a resolution boundary was crossed. */
export function nextMapImageAssetKind(
  current: MapImageAssetKind,
  resolution: number | undefined,
): MapImageAssetKind | null {
  const next = mapImageAssetKindForResolution(resolution);
  return next === current ? null : next;
}

/** Resolve a catalog map's selected raster without changing its native coordinate extent. */
export function mapImageAssetPath(map: CatalogMap, kind: MapImageAssetKind): string {
  return kind === "native" ? map.image.path : map.image.overview.path;
}

/** Return the rendered exterior's full extent for an explicit camera focus request. */
export function focusExtent(placement: Placement, pixelsPerMetatile: number): [number, number, number, number] {
  return toOpenLayersExtent(placement, pixelsPerMetatile);
}
