"""Deterministic dependency closure with complete source chains."""

from __future__ import annotations

from collections import deque
from typing import AbstractSet, Iterable, Mapping

from .errors import ContentPortError
from .model import ResourceKey
from .sources import SourceEdge, SourceGraph


def _format_key(key: ResourceKey) -> str:
    return f"{key.domain}:{key.name}"


def dependency_closure(
    roots: Iterable[ResourceKey],
    dependencies: Mapping[ResourceKey, Iterable[ResourceKey]],
    allowed: AbstractSet[ResourceKey],
) -> tuple[ResourceKey, ...]:
    root_set = set(roots)
    pending = list(sorted(root_set, reverse=True))
    seen: set[ResourceKey] = set()
    parent: dict[ResourceKey, ResourceKey] = {}
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        if current not in allowed:
            chain = [current]
            while chain[-1] in parent:
                chain.append(parent[chain[-1]])
            chain.reverse()
            rendered = " -> ".join(_format_key(item) for item in chain)
            raise ContentPortError(
                f"dependency closure reaches disabled or unowned {_format_key(current)}; chain: {rendered}"
            )
        seen.add(current)
        children = sorted(set(dependencies.get(current, ())) - seen, reverse=True)
        for child in children:
            parent.setdefault(child, current)
        pending.extend(children)
    return tuple(sorted(seen))


def close_source_graph(
    graph: SourceGraph,
    roots: Iterable[ResourceKey],
    allowed: AbstractSet[ResourceKey],
) -> tuple[ResourceKey, ...]:
    """Close a source graph and augment failures with edge provenance."""
    try:
        return dependency_closure(roots, graph.dependencies, allowed)
    except ContentPortError as exc:
        # Find the shortest deterministic route to the first disallowed node.
        by_source: dict[ResourceKey, list[SourceEdge]] = {}
        for edge in graph.edges:
            by_source.setdefault(edge.source, []).append(edge)
        queue = deque((root, ()) for root in sorted(set(roots)))
        visited: set[ResourceKey] = set()
        while queue:
            current, path = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if current not in allowed:
                details = " -> ".join(
                    f"{_format_key(edge.source)} [{edge.provenance}]" for edge in path
                )
                if details:
                    details += f" -> {_format_key(current)}"
                    raise ContentPortError(f"{exc}; source chain: {details}") from exc
                break
            for edge in sorted(by_source.get(current, ())):
                queue.append((edge.target, path + (edge,)))
        raise
