import Ajv2020 from "ajv/dist/2020";
import catalogSchema from "../../../../tools/map_render/catalog.schema.json";
import type { PokemonOpenWorldExteriorMapCatalog } from "../../../../build/map-atlas/types/catalog";
import { catalogUrl } from "./urls";

export type MapCatalog = PokemonOpenWorldExteriorMapCatalog;
export type CatalogMap = MapCatalog["maps"][number];

export class CatalogValidationError extends Error {
  constructor(readonly details: readonly string[], summary: string) {
    super(`${summary} ${details.join(" ")}`);
    this.name = "CatalogValidationError";
  }
}

const validate = new Ajv2020({ allErrors: true, strict: true }).compile(catalogSchema);

export function validateCatalog(value: unknown): MapCatalog {
  if (!validate(value)) {
    const details = (validate.errors ?? []).map((error) => {
      const location = error.instancePath || "catalog";
      return `${location} ${error.message ?? "is invalid"}.`;
    });
    throw new CatalogValidationError(details, "The map catalog does not match its schema.");
  }

  const catalog = value as unknown as MapCatalog;
  const details = semanticCatalogErrors(catalog);
  if (details.length > 0) {
    throw new CatalogValidationError(
      details,
      "The map catalog is structurally valid but semantically inconsistent.",
    );
  }
  return catalog;
}

export async function loadCatalog(signal?: AbortSignal): Promise<MapCatalog> {
  const response = await fetch(catalogUrl(), {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(
      `Could not load the map catalog (${response.status} ${response.statusText}). Run make map-atlas-catalog first.`,
    );
  }
  return validateCatalog(await response.json());
}

function duplicateValues(values: readonly string[]): readonly string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const value of values) {
    if (seen.has(value)) {
      duplicates.add(value);
    }
    seen.add(value);
  }
  return [...duplicates].sort((left, right) => left.localeCompare(right, "en"));
}

function destinationErrors(
  catalog: MapCatalog,
  mapsByName: ReadonlyMap<string, CatalogMap>,
  mapsById: ReadonlyMap<string, CatalogMap>,
): readonly string[] {
  const errors: string[] = [];
  for (const [mapIndex, map] of catalog.maps.entries()) {
    const destinations = [
      ...map.connections.map((connection, connectionIndex) => ({
        location: `maps[${mapIndex}].connections[${connectionIndex}]`,
        name: connection.destinationMap,
        id: connection.destinationMapId,
      })),
      ...map.warps.map((warp, warpIndex) => ({
        location: `maps[${mapIndex}].warps[${warpIndex}]`,
        name: warp.destinationMap,
        id: warp.destinationMapId,
      })),
    ];
    for (const destination of destinations) {
      const resolvedByName = destination.name ? mapsByName.get(destination.name) : undefined;
      const resolvedById = mapsById.get(destination.id);
      if (resolvedByName && destination.id !== resolvedByName.id) {
        errors.push(
          `${destination.location}.destinationMap ${JSON.stringify(destination.name)} resolves to ${JSON.stringify(resolvedByName.id)}, not ${JSON.stringify(destination.id)}.`,
        );
      }
      if (resolvedById && destination.name !== resolvedById.name) {
        errors.push(
          `${destination.location}.destinationMapId ${JSON.stringify(destination.id)} resolves to ${JSON.stringify(resolvedById.name)}, not ${JSON.stringify(destination.name)}.`,
        );
      }
    }
  }
  return errors;
}

/** Validate relationships that JSON Schema cannot express across catalog records. */
export function semanticCatalogErrors(catalog: MapCatalog): readonly string[] {
  const errors: string[] = [];
  for (const name of duplicateValues(catalog.maps.map((map) => map.name))) {
    errors.push(`maps contains duplicate map name ${JSON.stringify(name)}.`);
  }
  for (const id of duplicateValues(catalog.maps.map((map) => map.id))) {
    errors.push(`maps contains duplicate map id ${JSON.stringify(id)}.`);
  }
  for (const id of duplicateValues(catalog.regions.map((region) => region.id))) {
    errors.push(`regions contains duplicate region id ${JSON.stringify(id)}.`);
  }

  const mapsByName = new Map(catalog.maps.map((map) => [map.name, map]));
  const mapsById = new Map(catalog.maps.map((map) => [map.id, map]));
  const regionsById = new Map(catalog.regions.map((region) => [region.id, region]));
  const mapsByRegion = new Map<string, CatalogMap[]>();
  for (const [mapIndex, map] of catalog.maps.entries()) {
    if (!regionsById.has(map.region)) {
      errors.push(`maps[${mapIndex}].region ${JSON.stringify(map.region)} is not declared in regions.`);
    }
    const regionMaps = mapsByRegion.get(map.region) ?? [];
    regionMaps.push(map);
    mapsByRegion.set(map.region, regionMaps);
    const expectedWidth = map.layout.widthMetatiles * catalog.pixelsPerMetatile;
    const expectedHeight = map.layout.heightMetatiles * catalog.pixelsPerMetatile;
    if (map.image.widthPixels !== expectedWidth) {
      errors.push(`maps[${mapIndex}].image.widthPixels is ${map.image.widthPixels}, expected ${expectedWidth} from layout and pixelsPerMetatile.`);
    }
    if (map.image.heightPixels !== expectedHeight) {
      errors.push(`maps[${mapIndex}].image.heightPixels is ${map.image.heightPixels}, expected ${expectedHeight} from layout and pixelsPerMetatile.`);
    }
    const expectedOverviewWidth = map.image.widthPixels / 4;
    const expectedOverviewHeight = map.image.heightPixels / 4;
    if (map.image.overview.widthPixels !== expectedOverviewWidth) {
      errors.push(`maps[${mapIndex}].image.overview.widthPixels is ${map.image.overview.widthPixels}, expected ${expectedOverviewWidth} as one-quarter of native image width.`);
    }
    if (map.image.overview.heightPixels !== expectedOverviewHeight) {
      errors.push(`maps[${mapIndex}].image.overview.heightPixels is ${map.image.overview.heightPixels}, expected ${expectedOverviewHeight} as one-quarter of native image height.`);
    }
  }

  for (const [regionIndex, region] of catalog.regions.entries()) {
    const actualNames = (mapsByRegion.get(region.id) ?? []).map((map) => map.name).sort((left, right) => left.localeCompare(right, "en"));
    const listedNames = [...region.maps].sort((left, right) => left.localeCompare(right, "en"));
    if (region.mapCount !== actualNames.length) {
      errors.push(`regions[${regionIndex}].mapCount is ${region.mapCount}, but ${actualNames.length} maps declare region ${JSON.stringify(region.id)}.`);
    }
    if (region.mapCount !== listedNames.length) {
      errors.push(`regions[${regionIndex}].mapCount is ${region.mapCount}, but its maps list has ${listedNames.length} entries.`);
    }
    for (const name of duplicateValues(listedNames)) {
      errors.push(`regions[${regionIndex}].maps contains duplicate map name ${JSON.stringify(name)}.`);
    }
    const expectedNames = new Set(actualNames);
    const actualListedNames = new Set(listedNames);
    for (const name of actualNames) {
      if (!actualListedNames.has(name)) {
        errors.push(`regions[${regionIndex}].maps is missing map ${JSON.stringify(name)} declared for this region.`);
      }
    }
    for (const name of listedNames) {
      if (!expectedNames.has(name)) {
        errors.push(`regions[${regionIndex}].maps lists ${JSON.stringify(name)}, which is not declared for this region.`);
      }
    }
  }

  return [...errors, ...destinationErrors(catalog, mapsByName, mapsById)];
}
