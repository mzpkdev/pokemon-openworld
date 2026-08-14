"""Validate the rendered static world graph and reviewed exceptional edges."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .errors import ContentPortError


OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _map_name(value: str) -> str:
    return value[4:] if value.startswith("MAP_") else value


@dataclass(frozen=True, order=True)
class WorldEdge:
    source: str
    target: str
    kind: str
    index: int
    direction: str | None = None
    offset: int | None = None
    target_warp: int | str | None = None
    script_entry: str | None = None
    script_label: str | None = None
    command: str | None = None
    x: int | None = None
    y: int | None = None
    arming_source: str | None = None
    arming_entry: str | None = None
    arming_label: str | None = None
    arming_index: int | None = None
    immediate_target: str | None = None
    immediate_command: str | None = None
    immediate_index: int | None = None
    immediate_x: int | None = None
    immediate_y: int | None = None

    @property
    def key(self) -> str:
        if self.kind == "script-warp":
            return (
                f"{self.source}:{self.kind}:{self.script_entry}:"
                f"{self.script_label}:{self.index}"
            )
        if self.kind == "dynamic-warp":
            return (
                f"{self.source}:{self.kind}:{self.index}:{self.target}:{self.x}:{self.y}:"
                f"{self.arming_source}:{self.arming_entry}:{self.arming_label}:"
                f"{self.arming_index}:{self.immediate_target}:{self.immediate_command}:"
                f"{self.immediate_index}:{self.immediate_x}:{self.immediate_y}"
            )
        return f"{self.source}:{self.kind}:{self.index}"


@dataclass(frozen=True)
class WorldMap:
    name: str
    warp_count: int
    region: str | None = None


@dataclass(frozen=True)
class WorldGraph:
    maps: Mapping[str, WorldMap]
    edges: tuple[WorldEdge, ...]

    def has_reciprocal(self, edge: WorldEdge) -> bool:
        if edge.kind != "connection" or edge.direction not in OPPOSITE:
            return False
        return any(
            candidate.kind == "connection"
            and candidate.source == edge.target
            and candidate.target == edge.source
            and candidate.direction == OPPOSITE[edge.direction]
            and candidate.offset == (-edge.offset if edge.offset is not None else None)
            for candidate in self.edges
        )

    def valid_warp_index(self, edge: WorldEdge) -> bool:
        if edge.kind != "warp" or not isinstance(edge.target_warp, int):
            return True
        destination = self.maps.get(edge.target)
        return (
            destination is not None and 0 <= edge.target_warp < destination.warp_count
        )


@dataclass(frozen=True)
class WorldPolicy:
    reviewed_one_way: frozenset[str] = frozenset()
    deferred_exits: frozenset[str] = frozenset()
    dynamic_warps: Mapping[str, str] = field(default_factory=dict)
    inter_region_gateways: frozenset[str] = frozenset()
    unreachable_shells: frozenset[str] = frozenset()
    roots: frozenset[str] = frozenset()


def world_graph_from_maps(
    maps: Mapping[str, Mapping[str, Any]] | Iterable[Mapping[str, Any]],
) -> WorldGraph:
    supplied_mapping = isinstance(maps, Mapping)
    if not supplied_mapping:
        maps = {_map_name(str(item.get("id", item.get("name")))): item for item in maps}
    id_aliases = {
        _map_name(str(document.get("id", supplied_name))): str(supplied_name)
        for supplied_name, document in maps.items()
    }
    nodes: dict[str, WorldMap] = {}
    edges: list[WorldEdge] = []
    for supplied_name, document in sorted(maps.items()):
        name = (
            str(supplied_name)
            if supplied_mapping
            else _map_name(str(document.get("id", document.get("name", supplied_name))))
        )
        warps = document.get("warp_events", [])
        connections = document.get("connections", [])
        warps = [] if warps in (None, 0) else warps
        connections = [] if connections in (None, 0) else connections
        if not isinstance(warps, list) or not isinstance(connections, list):
            raise ContentPortError(f"{name}: map connections and warps must be arrays")
        nodes[name] = WorldMap(name, len(warps), document.get("region"))
        for index, connection in enumerate(connections):
            try:
                target_symbol = _map_name(str(connection["map"]))
                target = id_aliases.get(target_symbol, target_symbol)
                direction = str(connection["direction"])
                offset = int(connection["offset"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ContentPortError(
                    f"{name}:connection:{index}: malformed connection"
                ) from exc
            if direction not in OPPOSITE:
                raise ContentPortError(
                    f"{name}:connection:{index}: invalid direction {direction}"
                )
            edges.append(
                WorldEdge(name, target, "connection", index, direction, offset)
            )
        for index, warp in enumerate(warps):
            try:
                target_symbol = _map_name(str(warp["dest_map"]))
                target = id_aliases.get(target_symbol, target_symbol)
                raw_index = warp["dest_warp_id"]
                target_warp: int | str = (
                    int(raw_index)
                    if str(raw_index).lstrip("-").isdigit()
                    else str(raw_index)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ContentPortError(f"{name}:warp:{index}: malformed warp") from exc
            edges.append(
                WorldEdge(name, target, "warp", index, target_warp=target_warp)
            )
    return WorldGraph(nodes, tuple(sorted(edges)))


def with_script_warps(graph: WorldGraph, edges: Iterable[WorldEdge]) -> WorldGraph:
    script_edges = tuple(edges)
    if any(edge.kind != "script-warp" for edge in script_edges):
        raise ContentPortError("script-warp evidence contains a non-script edge")
    if any(
        not edge.source
        or not edge.target
        or not edge.script_entry
        or not edge.script_label
        or edge.command not in {"warp", "warpsilent"}
        or type(edge.index) is not int
        or edge.index < 0
        or type(edge.x) is not int
        or edge.x < 0
        or type(edge.y) is not int
        or edge.y < 0
        for edge in script_edges
    ):
        raise ContentPortError("script-warp evidence is incomplete or malformed")
    keys = [edge.key for edge in script_edges]
    if len(keys) != len(set(keys)):
        raise ContentPortError("duplicate script-warp evidence identity")
    return WorldGraph(graph.maps, tuple(sorted((*graph.edges, *script_edges))))


def with_dynamic_warps(graph: WorldGraph, edges: Iterable[WorldEdge]) -> WorldGraph:
    dynamic_edges = tuple(edges)
    if any(edge.kind != "dynamic-warp" for edge in dynamic_edges):
        raise ContentPortError("dynamic-warp evidence contains a non-dynamic edge")
    if any(
        not edge.source
        or not edge.target
        or type(edge.index) is not int
        or edge.index < 0
        or type(edge.x) is not int
        or edge.x < 0
        or type(edge.y) is not int
        or edge.y < 0
        or not edge.arming_source
        or not edge.arming_entry
        or not edge.arming_label
        or type(edge.arming_index) is not int
        or edge.arming_index < 0
        or not edge.immediate_target
        or edge.immediate_command not in {"warp", "warpsilent"}
        or type(edge.immediate_index) is not int
        or edge.immediate_index < 0
        or type(edge.immediate_x) is not int
        or edge.immediate_x < 0
        or type(edge.immediate_y) is not int
        or edge.immediate_y < 0
        for edge in dynamic_edges
    ):
        raise ContentPortError("dynamic-warp evidence is incomplete or malformed")
    keys = [edge.key for edge in dynamic_edges]
    if len(keys) != len(set(keys)):
        raise ContentPortError("duplicate dynamic-warp evidence identity")
    return WorldGraph(graph.maps, tuple(sorted((*graph.edges, *dynamic_edges))))


def validate_world_graph(graph: WorldGraph, policy: WorldPolicy) -> None:
    edge_keys = {edge.key for edge in graph.edges}
    for category, keys in (
        ("reviewed one-way", policy.reviewed_one_way),
        ("deferred exit", policy.deferred_exits),
        ("gateway", policy.inter_region_gateways),
    ):
        stale = sorted(set(keys) - edge_keys)
        if stale:
            raise ContentPortError(f"stale {category} declaration {stale[0]}")
    stale_dynamic = sorted(set(policy.dynamic_warps) - edge_keys)
    if stale_dynamic:
        raise ContentPortError(f"stale dynamic warp declaration {stale_dynamic[0]}")

    for edge in graph.edges:
        if edge.target not in graph.maps:
            if (
                edge.key not in policy.deferred_exits
                and edge.key not in policy.dynamic_warps
            ):
                raise ContentPortError(
                    f"{edge.key}: destination map is outside the closed world graph"
                )
            continue
        if edge.kind == "connection" and not graph.has_reciprocal(edge):
            if edge.key not in policy.reviewed_one_way:
                raise ContentPortError(
                    f"{edge.key}: connection has no reviewed reciprocal edge"
                )
        if edge.kind == "warp":
            dynamic = not isinstance(edge.target_warp, int)
            if dynamic and edge.key not in policy.dynamic_warps:
                raise ContentPortError(
                    f"{edge.key}: dynamic warp lacks reviewed metadata"
                )
            if not dynamic and not graph.valid_warp_index(edge):
                raise ContentPortError(
                    f"{edge.key}: destination warp index is out of bounds"
                )

        source_region = graph.maps[edge.source].region
        target_region = graph.maps[edge.target].region
        crosses_region = (
            source_region is not None
            and target_region is not None
            and source_region != target_region
        )
        if crosses_region and edge.key not in policy.inter_region_gateways:
            raise ContentPortError(
                f"{edge.key}: inter-region edge is not a declared gateway"
            )
        if not crosses_region and edge.key in policy.inter_region_gateways:
            raise ContentPortError(
                f"{edge.key}: declared gateway does not cross regions"
            )

    if graph.maps:
        roots = set(policy.roots) or {min(graph.maps)}
        missing_roots = sorted(roots - set(graph.maps))
        if missing_roots:
            raise ContentPortError(f"world graph root {missing_roots[0]} is missing")
        reachable: set[str] = set()
        queue = deque(sorted(roots))
        adjacency: dict[str, set[str]] = {}
        for edge in graph.edges:
            if edge.target in graph.maps and edge.key not in policy.deferred_exits:
                adjacency.setdefault(edge.source, set()).add(edge.target)
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            queue.extend(sorted(adjacency.get(current, set()) - reachable))
        unreachable = set(graph.maps) - reachable
        unexpected = sorted(unreachable - set(policy.unreachable_shells))
        if unexpected:
            raise ContentPortError(
                f"unreachable map shells are not reviewed: {', '.join(unexpected)}"
            )
        stale_shells = sorted(set(policy.unreachable_shells) - unreachable)
        if stale_shells:
            raise ContentPortError(
                f"{stale_shells[0]}: stale unreachable-shell declaration"
            )
