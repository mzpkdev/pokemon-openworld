/** Build a public atlas URL without assuming that the site is served at the host root. */
export function atlasUrl(path: string, baseUrl = import.meta.env.BASE_URL): string {
  const normalizedBase = baseUrl ? (baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`) : "./";
  return `${normalizedBase}${path.replace(/^\/+/, "")}`;
}

export function catalogUrl(baseUrl?: string): string {
  return atlasUrl("map-catalog/catalog.json", baseUrl);
}

export function mapImageUrl(imagePath: string, baseUrl?: string): string {
  return atlasUrl(`map-catalog/${imagePath}`, baseUrl);
}

export interface AtlasViewState {
  readonly center: readonly [number, number];
  readonly zoom: number;
}

export interface AtlasUrlState {
  readonly region: string | null;
  readonly selectedMap: string | null;
  readonly view: AtlasViewState | null;
}

function nonEmptySearchParameter(params: URLSearchParams, name: string): string | null {
  const value = params.get(name)?.trim();
  return value || null;
}

function finiteSearchNumber(params: URLSearchParams, name: string): number | null {
  const value = params.get(name);
  if (value === null || value.trim() === "") {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Read shareable atlas controls while retaining unrelated query parameters. */
export function parseAtlasUrlState(url: string): AtlasUrlState {
  const parsed = new URL(url, "https://pokemon-openworld.invalid");
  const x = finiteSearchNumber(parsed.searchParams, "x");
  const y = finiteSearchNumber(parsed.searchParams, "y");
  const zoom = finiteSearchNumber(parsed.searchParams, "zoom");
  return {
    region: nonEmptySearchParameter(parsed.searchParams, "region"),
    selectedMap: nonEmptySearchParameter(parsed.searchParams, "map"),
    view: x === null || y === null || zoom === null ? null : { center: [x, y], zoom },
  };
}

function displayNumber(value: number): string {
  return String(Math.round(value * 100) / 100);
}

/**
 * Update only atlas-owned query parameters. Returning a path keeps browser updates
 * correct when the static app is mounted below a non-root path.
 */
export function atlasUrlWithState(url: string, state: AtlasUrlState): string {
  const parsed = new URL(url, "https://pokemon-openworld.invalid");
  for (const name of ["region", "map", "x", "y", "zoom"]) {
    parsed.searchParams.delete(name);
  }
  if (state.region) {
    parsed.searchParams.set("region", state.region);
  }
  if (state.selectedMap) {
    parsed.searchParams.set("map", state.selectedMap);
  }
  if (state.view) {
    parsed.searchParams.set("x", displayNumber(state.view.center[0]));
    parsed.searchParams.set("y", displayNumber(state.view.center[1]));
    parsed.searchParams.set("zoom", displayNumber(state.view.zoom));
  }
  return `${parsed.pathname}${parsed.search}${parsed.hash}`;
}
