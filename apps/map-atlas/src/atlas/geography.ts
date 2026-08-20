import type { CatalogMap } from "./catalog";

export type CardinalDirection = "up" | "down" | "left" | "right";

export interface Placement {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface ResidualConflict {
  readonly source: string;
  readonly destination: string;
  readonly direction: CardinalDirection;
  readonly offsetMetatiles: number;
  readonly expected: Placement;
  readonly actual: Placement;
}

export interface AtlasComponent {
  readonly id: string;
  readonly maps: readonly string[];
  readonly bounds: Placement;
}

export interface Geography {
  readonly placements: Readonly<Record<string, Placement>>;
  readonly components: readonly AtlasComponent[];
  readonly residuals: readonly ResidualConflict[];
}

interface DirectedConnection {
  readonly source: string;
  readonly destination: string;
  readonly direction: CardinalDirection;
  readonly offsetMetatiles: number;
}

interface Neighbor {
  readonly edge: DirectedConnection;
  readonly name: string;
  readonly followsDirection: boolean;
}

const COMPONENT_GAP_METATILES = 8;
const cardinalDirections = new Set<CardinalDirection>(["up", "down", "left", "right"]);

function compareText(left: string, right: string): number {
  return left.localeCompare(right, "en");
}

function mapDimensions(map: CatalogMap): Pick<Placement, "width" | "height"> {
  return {
    width: map.layout.widthMetatiles,
    height: map.layout.heightMetatiles,
  };
}

function edgeKey(edge: DirectedConnection): string {
  return [edge.source, edge.destination, edge.direction, edge.offsetMetatiles].join("\u0000");
}

function compareEdges(left: DirectedConnection, right: DirectedConnection): number {
  return compareText(edgeKey(left), edgeKey(right));
}

function samePlacement(left: Placement, right: Placement): boolean {
  return left.x === right.x && left.y === right.y && left.width === right.width && left.height === right.height;
}

/**
 * Place a cardinal connection in y-down metatile coordinates.
 *
 * right=(sx+sw,sy+offset), left=(sx-dw,sy+offset),
 * down=(sx+offset,sy+sh), up=(sx+offset,sy-dh)
 */
export function placeConnection(
  source: Placement,
  destination: Pick<Placement, "width" | "height">,
  direction: CardinalDirection,
  offsetMetatiles: number,
): Placement {
  switch (direction) {
    case "right":
      return { x: source.x + source.width, y: source.y + offsetMetatiles, width: destination.width, height: destination.height };
    case "left":
      return { x: source.x - destination.width, y: source.y + offsetMetatiles, width: destination.width, height: destination.height };
    case "down":
      return { x: source.x + offsetMetatiles, y: source.y + source.height, width: destination.width, height: destination.height };
    case "up":
      return { x: source.x + offsetMetatiles, y: source.y - destination.height, width: destination.width, height: destination.height };
  }
}

function placeSourceFromDestination(
  destination: Placement,
  source: Pick<Placement, "width" | "height">,
  direction: CardinalDirection,
  offsetMetatiles: number,
): Placement {
  switch (direction) {
    case "right":
      return { x: destination.x - source.width, y: destination.y - offsetMetatiles, ...source };
    case "left":
      return { x: destination.x + destination.width, y: destination.y - offsetMetatiles, ...source };
    case "down":
      return { x: destination.x - offsetMetatiles, y: destination.y - source.height, ...source };
    case "up":
      return { x: destination.x - offsetMetatiles, y: destination.y + destination.height, ...source };
  }
}

function boundsFor(names: readonly string[], placements: Readonly<Record<string, Placement>>): Placement {
  const first = placements[names[0]];
  let minX = first.x;
  let minY = first.y;
  let maxX = first.x + first.width;
  let maxY = first.y + first.height;
  for (const name of names.slice(1)) {
    const placement = placements[name];
    minX = Math.min(minX, placement.x);
    minY = Math.min(minY, placement.y);
    maxX = Math.max(maxX, placement.x + placement.width);
    maxY = Math.max(maxY, placement.y + placement.height);
  }
  return { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
}

function cardinalConnections(maps: readonly CatalogMap[]): readonly DirectedConnection[] {
  const names = new Set(maps.map((map) => map.name));
  return maps
    .flatMap((map) =>
      map.connections.flatMap((connection) => {
        if (!cardinalDirections.has(connection.direction as CardinalDirection)) {
          return [];
        }
        if (!connection.destinationMap || !names.has(connection.destinationMap)) {
          return [];
        }
        return [{
          source: map.name,
          destination: connection.destinationMap,
          direction: connection.direction as CardinalDirection,
          offsetMetatiles: connection.offsetMetatiles,
        }];
      }),
    )
    .sort(compareEdges);
}

function neighborIndex(edges: readonly DirectedConnection[]): ReadonlyMap<string, readonly Neighbor[]> {
  const neighbors = new Map<string, Neighbor[]>();
  for (const edge of edges) {
    const forward = neighbors.get(edge.source) ?? [];
    forward.push({ edge, name: edge.destination, followsDirection: true });
    neighbors.set(edge.source, forward);
    const reverse = neighbors.get(edge.destination) ?? [];
    reverse.push({ edge, name: edge.source, followsDirection: false });
    neighbors.set(edge.destination, reverse);
  }
  for (const entries of neighbors.values()) {
    entries.sort((left, right) => {
      const edgeOrder = compareEdges(left.edge, right.edge);
      if (edgeOrder !== 0) {
        return edgeOrder;
      }
      return Number(right.followsDirection) - Number(left.followsDirection);
    });
  }
  return neighbors;
}

/** Only the default-visible surface of the catalog belongs in the initial atlas. */
export function visibleSurfaceMaps(maps: readonly CatalogMap[]): readonly CatalogMap[] {
  return maps.filter((map) => map.world.layer === "surface" && map.world.defaultVisible);
}

/**
 * Resolve cardinal catalog links into a deterministic spanning forest. Connections are
 * directed records, while their inverse equations allow either endpoint to join the
 * same component. Cycles are retained as residuals instead of invalidating the atlas.
 */
export function solveGeography(maps: readonly CatalogMap[]): Geography {
  const orderedMaps = [...maps].sort((left, right) => compareText(left.name, right.name));
  const mapByName = new Map(orderedMaps.map((map) => [map.name, map]));
  const edges = cardinalConnections(orderedMaps);
  const neighbors = neighborIndex(edges);
  const localPlacements: Record<string, Placement> = {};
  const components: AtlasComponent[] = [];

  for (const root of orderedMaps) {
    if (localPlacements[root.name]) {
      continue;
    }
    localPlacements[root.name] = { x: 0, y: 0, ...mapDimensions(root) };
    const queue = [root.name];
    const memberNames: string[] = [];

    for (let cursor = 0; cursor < queue.length; cursor += 1) {
      const name = queue[cursor];
      memberNames.push(name);
      const current = localPlacements[name];
      for (const neighbor of neighbors.get(name) ?? []) {
        if (localPlacements[neighbor.name]) {
          continue;
        }
        const neighborMap = mapByName.get(neighbor.name);
        if (!neighborMap) {
          continue;
        }
        const placement = neighbor.followsDirection
          ? placeConnection(current, mapDimensions(neighborMap), neighbor.edge.direction, neighbor.edge.offsetMetatiles)
          : placeSourceFromDestination(current, mapDimensions(neighborMap), neighbor.edge.direction, neighbor.edge.offsetMetatiles);
        localPlacements[neighbor.name] = placement;
        queue.push(neighbor.name);
      }
    }

    memberNames.sort(compareText);
    components.push({
      id: memberNames[0],
      maps: memberNames,
      bounds: boundsFor(memberNames, localPlacements),
    });
  }

  const packedPlacements: Record<string, Placement> = {};
  let nextX = 0;
  const packedComponents = components.map((component) => {
    const shiftX = nextX - component.bounds.x;
    const shiftY = -component.bounds.y;
    for (const name of component.maps) {
      const placement = localPlacements[name];
      packedPlacements[name] = { ...placement, x: placement.x + shiftX, y: placement.y + shiftY };
    }
    const packedBounds = boundsFor(component.maps, packedPlacements);
    nextX = packedBounds.x + packedBounds.width + COMPONENT_GAP_METATILES;
    return { ...component, bounds: packedBounds };
  });

  const residuals = edges.flatMap((edge) => {
    const source = packedPlacements[edge.source];
    const destination = packedPlacements[edge.destination];
    if (!source || !destination) {
      return [];
    }
    const expected = placeConnection(source, destination, edge.direction, edge.offsetMetatiles);
    return samePlacement(expected, destination)
      ? []
      : [{ ...edge, expected, actual: destination }];
  });

  return {
    placements: packedPlacements,
    components: packedComponents,
    residuals,
  };
}

/** Convert y-down catalog placement into the y-up extent used by OpenLayers. */
export function toOpenLayersExtent(placement: Placement, pixelsPerMetatile: number): [number, number, number, number] {
  const x = placement.x * pixelsPerMetatile;
  const y = placement.y * pixelsPerMetatile;
  const width = placement.width * pixelsPerMetatile;
  const height = placement.height * pixelsPerMetatile;
  return [x, -(y + height), x + width, -y];
}

export function atlasExtent(
  placements: Readonly<Record<string, Placement>>,
  pixelsPerMetatile: number,
): [number, number, number, number] | null {
  const values = Object.values(placements);
  if (values.length === 0) {
    return null;
  }
  const first = toOpenLayersExtent(values[0], pixelsPerMetatile);
  let minX = first[0];
  let minY = first[1];
  let maxX = first[2];
  let maxY = first[3];
  for (const placement of values.slice(1)) {
    const extent = toOpenLayersExtent(placement, pixelsPerMetatile);
    minX = Math.min(minX, extent[0]);
    minY = Math.min(minY, extent[1]);
    maxX = Math.max(maxX, extent[2]);
    maxY = Math.max(maxY, extent[3]);
  }
  return [minX, minY, maxX, maxY];
}
