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
