"""Fail-closed geometry and object-capacity checks for trainer placements."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from .errors import ContentPortError


Coordinate = tuple[int, int]

STATIC_OBJECT_LIMIT = 64
ACTIVE_OBJECT_LIMIT = 16
RESERVED_ACTIVE_OBJECTS = 2
SPAWN_WINDOW_WIDTH = 20
SPAWN_WINDOW_HEIGHT = 17


class Direction(StrEnum):
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    UP = "up"


class SightMode(StrEnum):
    FIXED = "fixed"
    LOOK_AROUND = "look-around"
    SEE_ALL = "see-all"


_DIRECTION_VECTORS: dict[Direction, Coordinate] = {
    Direction.DOWN: (0, 1),
    Direction.LEFT: (-1, 0),
    Direction.RIGHT: (1, 0),
    Direction.UP: (0, -1),
}
_ALL_DIRECTIONS = frozenset(Direction)


@dataclass(frozen=True, order=True)
class SightGeometry:
    """Every direction a movement/trainer type can face while active."""

    mode: SightMode
    directions: frozenset[Direction]
    sight_range: int


@dataclass(frozen=True, order=True)
class ReviewedCoordinateAdaptation:
    """An exact authenticated state resolution from donor to target geometry."""

    key: str
    source: Coordinate
    target: Coordinate


@dataclass(frozen=True, order=True)
class ConnectionTransform:
    """An authenticated affine projection into one connected map."""

    source_map: str
    target_map: str
    delta_x: int
    delta_y: int
    target_width: int
    target_height: int

    def project(self, target: Coordinate) -> Coordinate:
        return target[0] + self.delta_x, target[1] + self.delta_y


@dataclass(frozen=True, order=True)
class PreservedObjectGeometry:
    """One non-trainer object in the complete ordered target output stream."""

    local_id: int
    x: int
    y: int
    movement_envelope: frozenset[Coordinate]

    @property
    def coordinate(self) -> Coordinate:
        return self.x, self.y


@dataclass(frozen=True, order=True)
class OrdinaryTrainerGeometry:
    """One ordinary in-layout trainer placement."""

    placement: str
    object_index: int
    local_id: int
    source_x: int
    source_y: int
    x: int
    y: int
    movement_envelope: frozenset[Coordinate]
    sight: SightGeometry
    adaptation: str | None = None

    @property
    def source_coordinate(self) -> Coordinate:
        return self.source_x, self.source_y

    @property
    def coordinate(self) -> Coordinate:
        return self.x, self.y


@dataclass(frozen=True, order=True)
class CrossMapCloneTrainerGeometry:
    """One proven connection clone of an ordinary trainer on a neighbor map."""

    placement: str
    object_index: int
    local_id: int
    x: int
    y: int
    movement_envelope: frozenset[Coordinate]
    target_map: str
    target_local_id: int
    target_placement: str
    target_x: int
    target_y: int
    connection: ConnectionTransform

    @property
    def coordinate(self) -> Coordinate:
        return self.x, self.y

    @property
    def target_coordinate(self) -> Coordinate:
        return self.target_x, self.target_y


MapObjectGeometry = (
    PreservedObjectGeometry | OrdinaryTrainerGeometry | CrossMapCloneTrainerGeometry
)
TrainerGeometry = OrdinaryTrainerGeometry | CrossMapCloneTrainerGeometry


@dataclass(frozen=True)
class AuthenticatedMapGeometry:
    """Caller-authenticated output, layout, collision, and entry evidence."""

    name: str
    width: int
    height: int
    objects: tuple[MapObjectGeometry, ...]
    passable_tiles: frozenset[Coordinate]
    entry_components: tuple[frozenset[Coordinate], ...]
    rock_climb_tiles: frozenset[Coordinate] = frozenset()
    reviewed_adaptations: frozenset[ReviewedCoordinateAdaptation] = frozenset()
    connections: frozenset[ConnectionTransform] = frozenset()


@dataclass(frozen=True)
class TrainerGeometryCensus:
    """Capacity and reachability evidence returned after all gates pass."""

    static_objects: int
    peak_active_objects: int
    reachable_tiles: int
    sight_tiles: int
    placements: tuple[str, ...]


def validate_trainer_geometry(
    geometry: AuthenticatedMapGeometry,
) -> TrainerGeometryCensus:
    """Validate one complete map's trainer placement and capacity contract."""

    _validate_layout(geometry)
    _validate_output_order(geometry)
    _validate_adaptation_authority(geometry)
    _validate_objects(geometry)

    if len(geometry.objects) > STATIC_OBJECT_LIMIT:
        raise ContentPortError(
            f"{geometry.name}: {len(geometry.objects)} static objects exceed the "
            f"{STATIC_OBJECT_LIMIT}-object limit"
        )

    ordinary = tuple(
        obj for obj in geometry.objects if isinstance(obj, OrdinaryTrainerGeometry)
    )
    occupied = tuple(obj.coordinate for obj in geometry.objects)
    duplicate_occupancy = _duplicates(occupied)
    if duplicate_occupancy:
        raise ContentPortError(
            f"{geometry.name}: duplicate object occupancy at {duplicate_occupancy[0]}"
        )
    blocked = frozenset(
        obj.coordinate
        for obj in geometry.objects
        if _in_layout(geometry, obj.coordinate)
    )
    traversable = geometry.passable_tiles - geometry.rock_climb_tiles - blocked
    reachable = _reachable_from_entries(geometry, traversable)
    sight_tiles: set[Coordinate] = set()
    for trainer in ordinary:
        sight_tiles.update(
            _validate_interaction_and_sight(geometry, trainer, traversable)
        )

    peak_active = _peak_active_objects(geometry)
    if peak_active > ACTIVE_OBJECT_LIMIT:
        raise ContentPortError(
            f"{geometry.name}: spawn window requires {peak_active} active objects, "
            f"exceeding the {ACTIVE_OBJECT_LIMIT}-object limit including player and "
            "follower"
        )

    placements = tuple(
        obj.placement for obj in geometry.objects if isinstance(obj, TrainerGeometry)
    )
    return TrainerGeometryCensus(
        len(geometry.objects), peak_active, len(reachable), len(sight_tiles), placements
    )


def validate_trainer_geometry_census(
    geometries: Mapping[str, AuthenticatedMapGeometry],
    expected_placements: Iterable[str],
) -> Mapping[str, TrainerGeometryCensus]:
    """Validate an exact-cover multi-map placement census."""

    if tuple(geometries) != tuple(sorted(geometries)):
        raise ContentPortError("geometry census maps must use canonical order")
    expected = tuple(expected_placements)
    if len(expected) != len(set(expected)):
        raise ContentPortError("expected geometry placements must be unique")
    censuses = {
        name: validate_trainer_geometry(geometry)
        for name, geometry in geometries.items()
    }
    for geometry in geometries.values():
        for obj in geometry.objects:
            if not isinstance(obj, CrossMapCloneTrainerGeometry):
                continue
            target_geometry = geometries.get(obj.target_map)
            if target_geometry is None:
                raise ContentPortError(
                    f"{obj.placement}: clone target map is absent from geometry census"
                )
            if obj.target_local_id > len(target_geometry.objects):
                raise ContentPortError(
                    f"{obj.placement}: clone target local ID does not exist"
                )
            target = target_geometry.objects[obj.target_local_id - 1]
            if (
                not isinstance(target, OrdinaryTrainerGeometry)
                or target.placement != obj.target_placement
                or target.coordinate != obj.target_coordinate
            ):
                raise ContentPortError(
                    f"{obj.placement}: clone target does not resolve to its ordinary trainer"
                )
            projected_envelope = frozenset(
                obj.connection.project(coordinate)
                for coordinate in target.movement_envelope
            )
            if obj.movement_envelope != projected_envelope:
                raise ContentPortError(
                    f"{obj.placement}: clone movement envelope differs from target "
                    "trainer projection"
                )
    actual = tuple(
        placement for census in censuses.values() for placement in census.placements
    )
    if actual != expected:
        if len(actual) != len(set(actual)):
            duplicate = next(item for item in actual if actual.count(item) > 1)
            raise ContentPortError(
                f"geometry census has duplicate placement {duplicate!r}"
            )
        missing = next((item for item in expected if item not in actual), None)
        if missing is not None:
            raise ContentPortError(f"geometry census is missing placement {missing!r}")
        extra = next((item for item in actual if item not in expected), None)
        if extra is not None:
            raise ContentPortError(f"geometry census has unknown placement {extra!r}")
        raise ContentPortError("geometry census placements must use canonical order")
    return censuses


def _validate_layout(geometry: AuthenticatedMapGeometry) -> None:
    if not isinstance(geometry.name, str) or not geometry.name.strip():
        raise ContentPortError("map name must be a non-empty string")
    for field, value in (("width", geometry.width), ("height", geometry.height)):
        if type(value) is not int or value <= 0:
            raise ContentPortError(f"{geometry.name}: layout {field} must be positive")
    for domain, coordinates in (
        ("passable tile", geometry.passable_tiles),
        ("Rock Climb tile", geometry.rock_climb_tiles),
    ):
        for coordinate in coordinates:
            _require_coordinate_in_bounds(geometry, coordinate, domain)
    if geometry.rock_climb_tiles - geometry.passable_tiles:
        raise ContentPortError(
            f"{geometry.name}: Rock Climb tiles must belong to the passable collision set"
        )
    for connection in geometry.connections:
        if (
            not isinstance(connection.source_map, str)
            or not connection.source_map
            or not isinstance(connection.target_map, str)
            or not connection.target_map
        ):
            raise ContentPortError(
                f"{geometry.name}: malformed connection map identity"
            )
        if connection.source_map != geometry.name:
            raise ContentPortError(
                f"{geometry.name}: connection authority belongs to another source map"
            )
        for field, value in (
            ("delta_x", connection.delta_x),
            ("delta_y", connection.delta_y),
        ):
            if type(value) is not int:
                raise ContentPortError(
                    f"{geometry.name}: connection {field} must be an integer"
                )
        for field, value in (
            ("target_width", connection.target_width),
            ("target_height", connection.target_height),
        ):
            if type(value) is not int or value <= 0:
                raise ContentPortError(
                    f"{geometry.name}: connection {field} must be positive"
                )
    if not geometry.entry_components:
        raise ContentPortError(
            f"{geometry.name}: at least one entry component is required"
        )
    for index, component in enumerate(geometry.entry_components):
        if not component:
            raise ContentPortError(
                f"{geometry.name}: entry component {index} must not be empty"
            )
        for coordinate in component:
            _require_coordinate_in_bounds(
                geometry, coordinate, f"entry component {index}"
            )
            if coordinate not in geometry.passable_tiles:
                raise ContentPortError(
                    f"{geometry.name}: entry component {index} contains impassable "
                    f"tile {coordinate}"
                )


def _validate_output_order(geometry: AuthenticatedMapGeometry) -> None:
    for expected_local_id, obj in enumerate(geometry.objects, 1):
        if not isinstance(
            obj,
            (
                PreservedObjectGeometry,
                OrdinaryTrainerGeometry,
                CrossMapCloneTrainerGeometry,
            ),
        ):
            raise ContentPortError(
                f"{geometry.name}: output slot {expected_local_id} has unknown object type"
            )
        _require_positive_local_id(obj.local_id, f"{geometry.name}: output object")
        if obj.local_id != expected_local_id:
            raise ContentPortError(
                f"{geometry.name}: output slot {expected_local_id} has local ID "
                f"{obj.local_id}; local IDs must derive from the full object order"
            )
    trainers = tuple(
        obj for obj in geometry.objects if isinstance(obj, TrainerGeometry)
    )
    indices = tuple(obj.object_index for obj in trainers)
    if any(type(index) is not int or index < 0 for index in indices):
        raise ContentPortError("donor object indices must be non-negative integers")
    if len(indices) != len(set(indices)):
        raise ContentPortError(
            f"{geometry.name}: donor trainer object indices must be unique per map"
        )
    if indices != tuple(sorted(indices)):
        raise ContentPortError(
            f"{geometry.name}: trainer objects must use canonical donor object order"
        )
    placements = tuple(obj.placement for obj in trainers)
    if len(placements) != len(set(placements)):
        raise ContentPortError(f"{geometry.name}: trainer placements must be unique")


def _validate_adaptation_authority(geometry: AuthenticatedMapGeometry) -> None:
    for adaptation in geometry.reviewed_adaptations:
        if (
            not isinstance(adaptation.key, str)
            or not adaptation.key
            or adaptation.key.strip() != adaptation.key
        ):
            raise ContentPortError(
                f"{geometry.name}: coordinate adaptation key must be non-empty"
            )
        _require_coordinate(adaptation.source, adaptation.key)
        _require_coordinate(adaptation.target, adaptation.key)
    adaptations = {
        adaptation.key: adaptation for adaptation in geometry.reviewed_adaptations
    }
    if len(adaptations) != len(geometry.reviewed_adaptations):
        raise ContentPortError(f"{geometry.name}: duplicate coordinate adaptation key")
    used: set[str] = set()
    for obj in geometry.objects:
        if not isinstance(obj, OrdinaryTrainerGeometry):
            continue
        if obj.source_coordinate == obj.coordinate:
            if obj.adaptation is not None:
                raise ContentPortError(
                    f"{obj.placement}: unchanged coordinate has a stale adaptation"
                )
            continue
        if obj.adaptation is None or obj.adaptation not in adaptations:
            raise ContentPortError(
                f"{obj.placement}: coordinate change lacks reviewed adaptation"
            )
        authority = adaptations[obj.adaptation]
        if (authority.source, authority.target) != (
            obj.source_coordinate,
            obj.coordinate,
        ):
            raise ContentPortError(
                f"{obj.placement}: coordinate change differs from reviewed adaptation"
            )
        used.add(obj.adaptation)
    stale = sorted(set(adaptations) - used)
    if stale:
        raise ContentPortError(
            f"{geometry.name}: stale coordinate adaptation {stale[0]!r}"
        )


def _validate_objects(geometry: AuthenticatedMapGeometry) -> None:
    connections = set(geometry.connections)
    for obj in geometry.objects:
        pointer = (
            obj.placement
            if isinstance(obj, TrainerGeometry)
            else f"local ID {obj.local_id}"
        )
        if not obj.movement_envelope or obj.coordinate not in obj.movement_envelope:
            raise ContentPortError(
                f"{geometry.name}: {pointer} movement envelope must contain its coordinate"
            )
        if isinstance(obj, CrossMapCloneTrainerGeometry):
            connection = obj.connection
            if connection not in connections or connection.source_map != geometry.name:
                raise ContentPortError(f"{obj.placement}: unproven connection clone")
            if connection.target_map != obj.target_map:
                raise ContentPortError(f"{obj.placement}: clone target map mismatch")
            _require_positive_local_id(obj.target_local_id, obj.placement)
            _require_target_coordinate(connection, obj.target_coordinate, obj.placement)
            if connection.project(obj.target_coordinate) != obj.coordinate:
                raise ContentPortError(
                    f"{obj.placement}: clone coordinate differs from connection transform"
                )
            for coordinate in obj.movement_envelope:
                target = (
                    coordinate[0] - connection.delta_x,
                    coordinate[1] - connection.delta_y,
                )
                _require_target_coordinate(connection, target, obj.placement)
            continue
        _require_coordinate_in_bounds(geometry, obj.coordinate, pointer)
        for coordinate in obj.movement_envelope:
            _require_coordinate_in_bounds(geometry, coordinate, f"{pointer} movement")
        if isinstance(obj, OrdinaryTrainerGeometry):
            _validate_sight(obj)


def _validate_sight(trainer: OrdinaryTrainerGeometry) -> None:
    sight = trainer.sight
    if type(sight.sight_range) is not int or sight.sight_range < 0:
        raise ContentPortError(f"{trainer.placement}: sight range must be non-negative")
    if not isinstance(sight.mode, SightMode):
        raise ContentPortError(f"{trainer.placement}: invalid sight mode")
    directions = sight.directions
    if not directions or any(not isinstance(item, Direction) for item in directions):
        raise ContentPortError(f"{trainer.placement}: invalid sight direction set")
    if sight.mode is SightMode.FIXED and len(directions) != 1:
        raise ContentPortError(
            f"{trainer.placement}: fixed sight requires exactly one direction"
        )
    if sight.mode is SightMode.LOOK_AROUND and not 2 <= len(directions) <= 4:
        raise ContentPortError(
            f"{trainer.placement}: look-around sight requires 2 through 4 directions"
        )
    if sight.mode is SightMode.SEE_ALL and directions != _ALL_DIRECTIONS:
        raise ContentPortError(
            f"{trainer.placement}: see-all sight requires every direction"
        )


def _reachable_from_entries(
    geometry: AuthenticatedMapGeometry, traversable: frozenset[Coordinate]
) -> frozenset[Coordinate]:
    starts = frozenset().union(*geometry.entry_components)
    blocked_starts = sorted(starts - traversable)
    if blocked_starts:
        label = (
            "forbidden Rock Climb"
            if blocked_starts[0] in geometry.rock_climb_tiles
            else "blocked by object occupancy"
        )
        raise ContentPortError(
            f"{geometry.name}: entry tile {blocked_starts[0]} is {label}"
        )
    reachable = set(starts)
    queue = deque(starts)
    while queue:
        x, y = queue.popleft()
        for dx, dy in _DIRECTION_VECTORS.values():
            candidate = x + dx, y + dy
            if candidate in traversable and candidate not in reachable:
                reachable.add(candidate)
                queue.append(candidate)
    return frozenset(reachable)


def _validate_interaction_and_sight(
    geometry: AuthenticatedMapGeometry,
    trainer: OrdinaryTrainerGeometry,
    traversable: frozenset[Coordinate],
) -> frozenset[Coordinate]:
    sight_tiles: set[Coordinate] = set()
    for origin in trainer.movement_envelope:
        if origin not in geometry.passable_tiles:
            raise ContentPortError(
                f"{trainer.placement}: movement envelope occupies an impassable tile"
            )
        if origin in geometry.rock_climb_tiles:
            raise ContentPortError(
                f"{trainer.placement}: movement envelope occupies a forbidden "
                "Rock Climb tile"
            )
        x, y = origin
        state_traversable = (traversable | {trainer.coordinate}) - {origin}
        state_reachable = _reachable_from_entries(geometry, state_traversable)
        interaction_tiles = frozenset(
            (x + dx, y + dy)
            for dx, dy in _DIRECTION_VECTORS.values()
            if (x + dx, y + dy) in state_traversable
        )
        if not interaction_tiles:
            raise ContentPortError(
                f"{trainer.placement}: no passable interaction tile from {origin}"
            )
        if not interaction_tiles & state_reachable:
            suffix = " without Rock Climb" if geometry.rock_climb_tiles else ""
            raise ContentPortError(
                f"{trainer.placement}: interaction from {origin} is unreachable from "
                f"map entries{suffix}"
            )

        for direction in trainer.sight.directions:
            dx, dy = _DIRECTION_VECTORS[direction]
            for distance in range(1, trainer.sight.sight_range + 1):
                candidate = x + dx * distance, y + dy * distance
                if candidate not in state_traversable:
                    break
                sight_tiles.add(candidate)
    return frozenset(sight_tiles)


def _peak_active_objects(geometry: AuthenticatedMapGeometry) -> int:
    peak_static = 0
    for player_y in range(geometry.height):
        for player_x in range(geometry.width):
            count = sum(
                any(
                    player_x - 2 <= x <= player_x + SPAWN_WINDOW_WIDTH - 3
                    and player_y <= y <= player_y + SPAWN_WINDOW_HEIGHT - 1
                    for x, y in obj.movement_envelope
                )
                for obj in geometry.objects
            )
            peak_static = max(peak_static, count)
    return peak_static + RESERVED_ACTIVE_OBJECTS


def _require_coordinate_in_bounds(
    geometry: AuthenticatedMapGeometry, coordinate: Coordinate, pointer: str
) -> None:
    _require_coordinate(coordinate, f"{geometry.name}: {pointer}")
    if not _in_layout(geometry, coordinate):
        raise ContentPortError(
            f"{geometry.name}: {pointer} coordinate {coordinate} is outside the "
            f"{geometry.width}x{geometry.height} layout"
        )


def _require_target_coordinate(
    connection: ConnectionTransform, coordinate: Coordinate, pointer: str
) -> None:
    _require_coordinate(coordinate, pointer)
    x, y = coordinate
    if not (0 <= x < connection.target_width and 0 <= y < connection.target_height):
        raise ContentPortError(
            f"{pointer}: target coordinate {coordinate} is outside connected map"
        )


def _require_coordinate(coordinate: Coordinate, pointer: str) -> None:
    if (
        not isinstance(coordinate, tuple)
        or len(coordinate) != 2
        or any(type(value) is not int for value in coordinate)
    ):
        raise ContentPortError(f"{pointer}: coordinate must contain two integers")


def _require_positive_local_id(local_id: int, pointer: str) -> None:
    if type(local_id) is not int or local_id <= 0:
        raise ContentPortError(f"{pointer}: target local ID must be positive")


def _in_layout(geometry: AuthenticatedMapGeometry, coordinate: Coordinate) -> bool:
    x, y = coordinate
    return 0 <= x < geometry.width and 0 <= y < geometry.height


def _duplicates(coordinates: tuple[Coordinate, ...]) -> list[Coordinate]:
    return sorted(
        coordinate
        for coordinate in set(coordinates)
        if coordinates.count(coordinate) > 1
    )
