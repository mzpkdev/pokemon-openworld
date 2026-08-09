"""Normalize expansion-native content into a typed dependency graph."""

from __future__ import annotations

import json
import re
import copy
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol

from .descriptor import PortDescriptor
from .errors import ContentPortError
from .model import ResourceKey


@dataclass(frozen=True, order=True)
class Provenance:
    path: str
    location: str = ""

    def __str__(self) -> str:
        return f"{self.path}{self.location}"


@dataclass(frozen=True)
class SourceRecord:
    value: Mapping[str, Any]
    provenance: Provenance


@dataclass(frozen=True, order=True)
class SourceEdge:
    source: ResourceKey
    target: ResourceKey
    provenance: Provenance
    role: str = field(default="dependency", compare=True)


@dataclass(frozen=True)
class SourceGraph:
    resources: Mapping[ResourceKey, Provenance]
    edges: tuple[SourceEdge, ...]

    @property
    def dependencies(self) -> Mapping[ResourceKey, tuple[ResourceKey, ...]]:
        result: dict[ResourceKey, set[ResourceKey]] = {
            key: set() for key in self.resources
        }
        for edge in self.edges:
            result.setdefault(edge.source, set()).add(edge.target)
        return MappingProxyType(
            {key: tuple(sorted(value)) for key, value in sorted(result.items())}
        )


@dataclass(frozen=True)
class ContractEvidence:
    """Canonical evidence emitted after the real port graph closes."""

    inventory: Mapping[str, int]
    closure: Mapping[str, tuple[str, ...]]
    evidence: Mapping[str, Any]

    def to_report(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "inventory": dict(self.inventory),
                "closure": {key: _thaw(value) for key, value in self.closure.items()},
                "evidence": dict(self.evidence),
            }
        )


@dataclass(frozen=True)
class PortSourceState:
    """Immutable, authority-resolved inputs consumed by renderers."""

    maps: Mapping[str, Mapping[str, Any]]
    layouts: Mapping[str, Mapping[str, Any]]
    map_authorities: Mapping[str, str]
    layout_authorities: Mapping[str, str]
    donor_roots: Mapping[str, Path]
    resources: Mapping[ResourceKey, Provenance]
    inventory: Mapping[str, tuple[str, ...]]


class RecordLoader(Protocol):
    def __call__(self, key: ResourceKey) -> SourceRecord: ...


class SourceContext:
    """Resource loader with deterministic, path-rich failures.

    Tests and descriptors can supply an exact record mapping. Real ports normally
    supply one loader per domain, keeping donor layout knowledge outside the graph.
    """

    def __init__(
        self,
        records: Mapping[ResourceKey, SourceRecord | Mapping[str, Any]] | None = None,
        loaders: Mapping[str, RecordLoader] | None = None,
        aliases: Mapping[ResourceKey, ResourceKey] | None = None,
        active_capabilities: Iterable[str] | None = None,
    ) -> None:
        self._records = dict(records or {})
        self._loaders = dict(loaders or {})
        self._aliases = dict(aliases or {})
        self._active_capabilities = (
            None if active_capabilities is None else frozenset(active_capabilities)
        )

    def canonicalize(self, key: ResourceKey) -> ResourceKey:
        return self._aliases.get(key, key)

    def supports(self, capability: str) -> bool:
        return (
            self._active_capabilities is None or capability in self._active_capabilities
        )

    def load(self, key: ResourceKey) -> SourceRecord:
        key = self.canonicalize(key)
        raw = self._records.get(key)
        if raw is not None:
            if isinstance(raw, SourceRecord):
                return raw
            return SourceRecord(raw, Provenance(f"<{key.domain}:{key.name}>"))
        loader = self._loaders.get(key.domain)
        if loader is None:
            raise ContentPortError(f"no source loader for {key.domain}:{key.name}")
        try:
            return loader(key)
        except ContentPortError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ContentPortError(
                f"cannot load {key.domain}:{key.name}: {exc}"
            ) from exc


class ExpansionSourceContext(SourceContext):
    """Index expansion-native JSON and ASM identities from a donor checkout."""

    def __init__(
        self,
        donor_root: Path | str,
        *,
        capabilities: Mapping[str, Mapping[str, Any]] | None = None,
        persistent_ledger: Path | str | None = None,
        active_capabilities: Iterable[str] = ("spatial",),
    ) -> None:
        root = Path(donor_root)
        records: dict[ResourceKey, SourceRecord] = {}
        aliases: dict[ResourceKey, ResourceKey] = {}

        maps_root = root / "data/maps"
        for path in sorted(maps_root.glob("*/map.json")):
            record = json_record(path)
            name = str(record.value.get("name", path.parent.name))
            canonical = ResourceKey("map", name)
            records[canonical] = record
            map_id = record.value.get("id")
            if isinstance(map_id, str):
                aliases[ResourceKey("map", map_id.removeprefix("MAP_"))] = canonical
                aliases[ResourceKey("map", map_id)] = canonical

            script_path = path.parent / "scripts.inc"
            if script_path.exists():
                for line_number, line in enumerate(
                    script_path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    match = re.match(
                        r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?\s*(?:@.*)?$", line
                    )
                    if match:
                        service = ResourceKey("service", match.group(1))
                        records.setdefault(
                            service,
                            SourceRecord(
                                {},
                                Provenance(script_path.as_posix(), f":{line_number}"),
                            ),
                        )

        script_sources = list((root / "data/scripts").glob("**/*.inc"))
        script_sources.extend((root / "data").glob("*.s"))
        for script_path in sorted(set(script_sources)):
            for line_number, line in enumerate(
                script_path.read_text(encoding="utf-8").splitlines(), 1
            ):
                match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)::?\s*(?:@.*)?$", line)
                if match:
                    service = ResourceKey("service", match.group(1))
                    records.setdefault(
                        service,
                        SourceRecord(
                            {}, Provenance(script_path.as_posix(), f":{line_number}")
                        ),
                    )

        layouts_path = root / "data/layouts/layouts.json"
        if layouts_path.exists():
            document = json.loads(layouts_path.read_text(encoding="utf-8"))
            for index, layout in enumerate(document.get("layouts", [])):
                if not isinstance(layout, Mapping) or not isinstance(
                    layout.get("id"), str
                ):
                    raise ContentPortError(
                        f"{layouts_path}/layouts/{index}: malformed layout"
                    )
                key = ResourceKey("layout", layout["id"])
                records[key] = SourceRecord(
                    layout, Provenance(layouts_path.as_posix(), f"/layouts/{index}")
                )
                for field_name in ("border_filepath", "blockdata_filepath"):
                    asset_name = layout.get(field_name)
                    if isinstance(asset_name, str) and (root / asset_name).is_file():
                        records.setdefault(
                            ResourceKey("asset", asset_name),
                            SourceRecord(
                                {}, Provenance((root / asset_name).as_posix())
                            ),
                        )

        # Assets are semantic leaves here. Renderers own their byte-level source
        # and conversion metadata; the graph still proves every referenced path
        # or tileset symbol exists in the donor checkout.
        for path in (
            sorted((root / "data/tilesets").glob("**/*"))
            if (root / "data/tilesets").exists()
            else ()
        ):
            if path.is_file():
                records.setdefault(
                    ResourceKey("asset", path.relative_to(root).as_posix()),
                    SourceRecord({}, Provenance(path.as_posix())),
                )
        headers = root / "data/tilesets/headers.inc"
        header_sources = [headers, root / "src/data/tilesets/headers.h"]
        for headers in header_sources:
            if headers.exists():
                for line_number, line in enumerate(
                    headers.read_text(encoding="utf-8").splitlines(), 1
                ):
                    match = re.search(r"\b(gTileset_[A-Za-z0-9_]+)\b\s*(?::|=)", line)
                    if not match:
                        continue
                    records[ResourceKey("asset", match.group(1))] = SourceRecord(
                        {}, Provenance(headers.as_posix(), f":{line_number}")
                    )

        if persistent_ledger is not None:
            ledger_path = Path(persistent_ledger)
            document = json.loads(ledger_path.read_text(encoding="utf-8"))
            for index, binding in enumerate(document.get("entries", [])):
                if isinstance(binding, Mapping) and isinstance(
                    binding.get("symbol"), str
                ):
                    records.setdefault(
                        ResourceKey("binding", binding["symbol"]),
                        SourceRecord(
                            binding,
                            Provenance(ledger_path.as_posix(), f"/entries/{index}"),
                        ),
                    )
        for name, capability in sorted((capabilities or {}).items()):
            records[ResourceKey("capability", name)] = SourceRecord(
                capability, Provenance("<descriptor>", f"/capabilities/{name}")
            )
        super().__init__(
            records=records, aliases=aliases, active_capabilities=active_capabilities
        )


def json_record(path: Path, pointer: str = "") -> SourceRecord:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPortError(f"{path}: invalid source JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ContentPortError(f"{path}: source record must be an object")
    return SourceRecord(value, Provenance(path.as_posix(), pointer))


def _key(
    domain: str, value: Any, *, prefixes: tuple[str, ...] = ()
) -> ResourceKey | None:
    if (
        not isinstance(value, str)
        or not value
        or value in {"0", "NULL", "NONE", "MAP_DYNAMIC", "MAP_NONE", "MAP_UNDEFINED"}
    ):
        return None
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    return ResourceKey(domain, value)


def _edge(
    key: ResourceKey,
    domain: str,
    value: Any,
    record: SourceRecord,
    pointer: str,
    *,
    prefixes: tuple[str, ...] = (),
    role: str = "dependency",
) -> SourceEdge | None:
    target = _key(domain, value, prefixes=prefixes)
    if target is None:
        return None
    return SourceEdge(key, target, Provenance(record.provenance.path, pointer), role)


def _array(record: SourceRecord, field_name: str) -> Iterable[Any]:
    value = record.value.get(field_name, ())
    if value is None or value == 0 or value == () or value == []:
        return ()
    if not isinstance(value, list):
        raise ContentPortError(
            f"{record.provenance.path}/{field_name}: must be an array or 0"
        )
    return value


def extract_map_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    value = record.value
    candidates: list[SourceEdge | None] = [
        _edge(key, "layout", value.get("layout"), record, "/layout"),
        _edge(key, "encounter", value.get("encounter"), record, "/encounter")
        if context.supports("encounters")
        else None,
    ]
    for index, connection in enumerate(_array(record, "connections")):
        if isinstance(connection, Mapping):
            candidates.append(
                _edge(
                    key,
                    "map",
                    connection.get("map"),
                    record,
                    f"/connections/{index}/map",
                    prefixes=("MAP_",),
                    role="connection",
                )
            )
    for index, warp in enumerate(_array(record, "warp_events")):
        if isinstance(warp, Mapping):
            candidates.append(
                _edge(
                    key,
                    "map",
                    warp.get("dest_map"),
                    record,
                    f"/warp_events/{index}/dest_map",
                    prefixes=("MAP_",),
                    role="warp",
                )
            )
    if not context.supports("events"):
        return tuple(edge for edge in candidates if edge is not None)
    for collection in ("object_events", "coord_events", "bg_events"):
        for index, event in enumerate(_array(record, collection)):
            if not isinstance(event, Mapping):
                continue
            candidates.append(
                _edge(
                    key,
                    "service",
                    event.get("script"),
                    record,
                    f"/{collection}/{index}/script",
                    role="event",
                )
            )
            candidates.append(
                _edge(
                    key,
                    "trainer",
                    event.get("trainer"),
                    record,
                    f"/{collection}/{index}/trainer",
                    role="trainer",
                )
            )
            for field_name, prefix in (("flag", "FLAG_"), ("var", "VAR_")):
                symbol = event.get(field_name)
                if isinstance(symbol, str) and symbol.startswith(prefix):
                    candidates.append(
                        _edge(
                            key,
                            "binding",
                            symbol,
                            record,
                            f"/{collection}/{index}/{field_name}",
                            role="persistent",
                        )
                    )
    return tuple(edge for edge in candidates if edge is not None)


def extract_layout_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    candidates: list[SourceEdge | None] = []
    for field_name in ("primary_tileset", "secondary_tileset"):
        candidates.append(
            _edge(
                key,
                "asset",
                record.value.get(field_name),
                record,
                f"/{field_name}",
                role="tileset",
            )
        )
    for field_name in ("border_filepath", "blockdata_filepath"):
        candidates.append(
            _edge(
                key,
                "asset",
                record.value.get(field_name),
                record,
                f"/{field_name}",
                role="layout-data",
            )
        )
    return tuple(edge for edge in candidates if edge is not None)


def extract_trainer_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    parties = record.value.get("parties", record.value.get("party"))
    if isinstance(parties, str):
        parties = [parties]
    if isinstance(parties, Iterable) and not isinstance(parties, (str, bytes, Mapping)):
        for index, party in enumerate(parties):
            edge = _edge(key, "party", party, record, f"/parties/{index}", role="party")
            if edge:
                result.append(edge)
    for field_name in ("front_pic", "back_pic", "palette", "encounter_music"):
        edge = _edge(
            key,
            "asset",
            record.value.get(field_name),
            record,
            f"/{field_name}",
            role="presentation",
        )
        if edge:
            result.append(edge)
    return tuple(result)


def extract_party_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    for index, member in enumerate(
        record.value.get("members", record.value.get("pokemon", ()))
    ):
        if not isinstance(member, Mapping):
            continue
        for field_name in ("sprite", "icon", "cry"):
            edge = _edge(
                key,
                "asset",
                member.get(field_name),
                record,
                f"/members/{index}/{field_name}",
                role="presentation",
            )
            if edge:
                result.append(edge)
    return tuple(result)


def extract_encounter_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    result: list[SourceEdge] = []
    maps = record.value.get("maps", ())
    if isinstance(maps, str):
        maps = [maps]
    for index, name in enumerate(maps):
        edge = _edge(
            key,
            "map",
            name,
            record,
            f"/maps/{index}",
            prefixes=("MAP_",),
            role="encounter-map",
        )
        if edge:
            result.append(edge)
    return tuple(result)


def _generic_declared_edges(
    key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    """Read typed native references, never an opaque dependency graph."""
    result: list[SourceEdge] = []
    refs = record.value.get("references", {})
    if not isinstance(refs, Mapping):
        raise ContentPortError(f"{record.provenance}: /references must be an object")
    for domain, names in sorted(refs.items()):
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            raise ContentPortError(
                f"{record.provenance.path}/references/{domain}: must be a list"
            )
        for index, name in enumerate(names):
            edge = _edge(key, domain, name, record, f"/references/{domain}/{index}")
            if edge:
                result.append(edge)
    return tuple(result)


def extract_service_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    return _generic_declared_edges(key, record)


def extract_asset_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    return _generic_declared_edges(key, record)


def extract_capability_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context
    # Capability records name activated resources by domain. A field named
    # "dependencies" is deliberately rejected: that would be a precomputed graph.
    if "dependencies" in record.value:
        raise ContentPortError(
            f"{record.provenance.path}/dependencies: precomputed dependency graphs are forbidden"
        )
    return _generic_declared_edges(key, record)


def extract_binding_edges(
    context: SourceContext, key: ResourceKey, record: SourceRecord
) -> Iterable[SourceEdge]:
    del context, key, record
    return ()


EXTRACTORS: Mapping[
    str, Callable[[SourceContext, ResourceKey, SourceRecord], Iterable[SourceEdge]]
] = {
    "map": extract_map_edges,
    "layout": extract_layout_edges,
    "trainer": extract_trainer_edges,
    "party": extract_party_edges,
    "encounter": extract_encounter_edges,
    "service": extract_service_edges,
    "asset": extract_asset_edges,
    "capability": extract_capability_edges,
    "binding": extract_binding_edges,
}


def build_source_graph(
    context: SourceContext, roots: Iterable[ResourceKey]
) -> SourceGraph:
    resources: dict[ResourceKey, Provenance] = {}
    edges: set[SourceEdge] = set()
    pending = list(sorted({context.canonicalize(key) for key in roots}, reverse=True))
    while pending:
        key = pending.pop()
        if key in resources:
            continue
        extractor = EXTRACTORS.get(key.domain)
        if extractor is None:
            raise ContentPortError(f"unsupported source domain {key.domain}:{key.name}")
        try:
            record = context.load(key)
        except ContentPortError as exc:
            raise ContentPortError(
                f"while loading {key.domain}:{key.name}: {exc}"
            ) from exc
        resources[key] = record.provenance
        for edge in extractor(context, key, record):
            target = context.canonicalize(edge.target)
            canonical_edge = SourceEdge(edge.source, target, edge.provenance, edge.role)
            edges.add(canonical_edge)
            pending.append(target)
    return SourceGraph(
        MappingProxyType(dict(sorted(resources.items()))), tuple(sorted(edges))
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return copy.deepcopy(value)


def _freeze_state(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_state(child) for key, child in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_state(child) for child in value)
    return value


def _path_value(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    for part in path.split("/"):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def _set_path(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split("/")
    current: Any = document
    for part in parts[:-1]:
        current = current[int(part)] if isinstance(current, list) else current[part]
    final = parts[-1]
    if isinstance(current, list):
        current[int(final)] = value
    else:
        current[final] = value


def _canonical_digest(values: Iterable[str]) -> str:
    payload = json.dumps(
        sorted(set(values)), separators=(",", ":"), ensure_ascii=True
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _inventory_digest(values: Iterable[str]) -> str:
    payload = (
        json.dumps(sorted(values), separators=(",", ":"), ensure_ascii=True) + "\n"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def resolve_port_sources(
    descriptor: PortDescriptor, repo: Path | str
) -> tuple[ContractEvidence, PortSourceState]:
    """Close and validate every enabled resource in a loaded ``PortDescriptor``.

    Donor selection and policy live in the descriptor. This generic entry point
    merely applies its exact field decisions, builds the expansion-native graph,
    resolves persistence, and validates the rendered spatial world.
    """
    from .bindings import load_binding_index
    from .closure import close_source_graph
    from .model import CapabilityState
    from .semantics import (
        analyze_entry,
        load_event_policy,
        parse_scripts,
        validate_effects,
    )
    from .world_graph import WorldPolicy, validate_world_graph, world_graph_from_maps

    target_root = Path(repo)
    mechanical_pin = descriptor.donor("mechanical")
    content_pin = descriptor.donor("content")
    mechanical = ExpansionSourceContext(
        mechanical_pin.root, active_capabilities=("spatial",)
    )
    content = ExpansionSourceContext(content_pin.root, active_capabilities=("spatial",))

    adaptations = _thaw(descriptor.adaptations)
    donor_fields = adaptations.get("donorFieldRoles")
    if not isinstance(donor_fields, dict) or set(donor_fields) != {
        "content",
        "mechanical",
    }:
        raise ContentPortError(
            "donorFieldRoles must name content and mechanical policy fields"
        )
    content_field = donor_fields["content"]
    mechanical_field = donor_fields["mechanical"]
    if not all(isinstance(value, str) and value for value in donor_fields.values()):
        raise ContentPortError("donorFieldRoles values must be field names")
    fallback = set(adaptations["contentFallback"]["maps"])
    map_names = tuple(descriptor.map_ownership)
    if fallback - set(map_names):
        raise ContentPortError(
            f"content fallback names unknown map {sorted(fallback - set(map_names))[0]}"
        )

    selected_maps: dict[str, dict[str, Any]] = {}
    map_authorities: dict[str, str] = {}
    source_records: dict[ResourceKey, SourceRecord] = {}
    aliases: dict[ResourceKey, ResourceKey] = {}
    input_evidence: list[str] = []
    for name in map_names:
        authority = mechanical if name in fallback else content
        authority_root = mechanical_pin.root if name in fallback else content_pin.root
        if name in fallback:
            try:
                content.load(ResourceKey("map", name))
            except ContentPortError:
                pass
            else:
                raise ContentPortError(
                    f"fallback map {name} exists in the content donor; mechanical authority is forbidden"
                )
        try:
            record = authority.load(ResourceKey("map", name))
        except ContentPortError as exc:
            role = "mechanical fallback" if name in fallback else "content authority"
            raise ContentPortError(f"{role} map {name}: {exc}") from exc
        document = _thaw(record.value)
        selected_maps[name] = document
        map_authorities[name] = "mechanical" if name in fallback else "content"
        canonical = ResourceKey("map", name)
        source_records[canonical] = SourceRecord(document, record.provenance)
        map_id = document.get("id")
        if isinstance(map_id, str):
            aliases[ResourceKey("map", map_id)] = canonical
            aliases[ResourceKey("map", map_id.removeprefix("MAP_"))] = canonical
        source_path = Path(record.provenance.path)
        if source_path.is_file():
            data = source_path.read_bytes()
            input_evidence.append(
                f"{source_path.relative_to(authority_root).as_posix()}:"
                f"{hashlib.sha256(data).hexdigest()}:{len(data)}"
            )

    # Exact reviewed field substitutions are checked against both donors before
    # the mechanical value becomes desired state.
    for decision in adaptations["adaptations"]:
        name = decision["source"]
        if name not in selected_maps:
            raise ContentPortError(f"adaptation names unknown map {name}")
        content_record = content.load(ResourceKey("map", name))
        mechanical_record = mechanical.load(ResourceKey("map", name))
        path = decision["path"]
        actual_content = _path_value(content_record.value, path)
        actual_mechanical = _path_value(mechanical_record.value, path)
        if actual_content != decision[content_field]:
            raise ContentPortError(f"{name}/{path}: content adaptation preimage drift")
        if actual_mechanical != decision[mechanical_field]:
            raise ContentPortError(
                f"{name}/{path}: mechanical adaptation evidence drift"
            )
        _set_path(selected_maps[name], path, decision[mechanical_field])

    # Validate the authored retained/deferred inventory against the adapted maps
    # before reviewed removals are applied.
    actual_edges: set[tuple[str, str, str, str]] = set()
    for name, document in selected_maps.items():
        for field_name, kind, target_field in (
            ("connections", "connection", "map"),
            ("warp_events", "warp", "dest_map"),
        ):
            for index, edge in enumerate(document.get(field_name, []) or []):
                actual_edges.add(
                    (name, f"{field_name}/{index}", kind, str(edge[target_field]))
                )
    reviewed_retained = {
        (item["source"], item["path"], item["kind"], item["destination"])
        for item in adaptations["retainedEdges"]
    }
    reviewed_deferred = {
        (item["source"], item["path"], item["kind"], item["destination"])
        for item in adaptations["deferredEdges"]
    }
    if actual_edges != reviewed_retained | reviewed_deferred:
        unexpected = sorted(actual_edges - reviewed_retained - reviewed_deferred)
        stale = sorted((reviewed_retained | reviewed_deferred) - actual_edges)
        raise ContentPortError(
            f"reviewed world edge drift: unexpected={unexpected[:1]} stale={stale[:1]}"
        )

    removals_by_map: dict[str, list[int]] = {}
    for removal in adaptations["warpRemovals"]:
        name = removal["source"]
        index = int(removal["path"].split("/")[-1])
        warps = selected_maps[name].get("warp_events", [])
        if index >= len(warps):
            raise ContentPortError(
                f"{name}/{removal['path']}: warp removal is out of bounds"
            )
        warp = warps[index]
        if (
            str(warp.get("dest_map")) != removal["destination"]
            or str(warp.get("dest_warp_id")) != removal["destWarpId"]
        ):
            raise ContentPortError(
                f"{name}/{removal['path']}: warp removal preimage drift"
            )
        removals_by_map.setdefault(name, []).append(index)
    for name, indexes in removals_by_map.items():
        for index in sorted(indexes, reverse=True):
            if (
                not str(selected_maps[name]["warp_events"][index]["dest_warp_id"])
                .lstrip("-")
                .isdigit()
            ):
                # Dynamic warps have no static destination dependency. Keep the
                # authored slot so incoming return-warp indices remain valid and
                # require its separate dynamic/deferred policy below.
                continue
            del selected_maps[name]["warp_events"][index]
    deferred_removals: dict[tuple[str, str], list[int]] = {}
    explicit_removals = {
        (item["source"], item["path"]) for item in adaptations["warpRemovals"]
    }
    for item in adaptations["deferredEdges"]:
        if (item["source"], item["path"]) in explicit_removals:
            continue
        field_name, raw_index = item["path"].split("/")
        deferred_removals.setdefault((item["source"], field_name), []).append(
            int(raw_index)
        )
    for (name, field_name), indexes in deferred_removals.items():
        for index in sorted(indexes, reverse=True):
            del selected_maps[name][field_name][index]

    # Resolve every allocated map/layout and build the mixed-authority layout set.
    selected_layouts: dict[str, SourceRecord] = {}
    layout_authorities: dict[str, str] = {}
    for name, document in selected_maps.items():
        descriptor.allocation_index.map_slot(name)
        layout_id = str(document["layout"])
        descriptor.allocation_index.layout_slot(layout_id)
        for authority_role, authority in (
            ("content", content),
            ("mechanical", mechanical),
        ):
            try:
                record = authority.load(ResourceKey("layout", layout_id))
                selected_layouts.setdefault(layout_id, record)
                layout_authorities.setdefault(layout_id, authority_role)
                break
            except ContentPortError:
                continue
        else:
            raise ContentPortError(
                f"{name}: layout {layout_id} is absent from both donors"
            )
    # The lock contains one alternate layout not selected by a map header.
    for layout_id in descriptor.allocation_index.layouts:
        if layout_id in selected_layouts:
            continue
        for authority_role, authority in (
            ("content", content),
            ("mechanical", mechanical),
        ):
            try:
                selected_layouts[layout_id] = authority.load(
                    ResourceKey("layout", layout_id)
                )
                layout_authorities[layout_id] = authority_role
                break
            except ContentPortError:
                continue
        else:
            raise ContentPortError(
                f"allocated layout {layout_id} is absent from both donors"
            )

    for layout_id, record in list(selected_layouts.items()):
        selected_layouts[layout_id] = SourceRecord(
            _thaw(record.value), record.provenance
        )
    for decision in adaptations["layoutHeaderDecisions"]:
        layout_id, field_name = decision["layout"], decision["field"]
        content_value = content.load(ResourceKey("layout", layout_id)).value[field_name]
        mechanical_value = mechanical.load(ResourceKey("layout", layout_id)).value[
            field_name
        ]
        if (
            content_value != decision[content_field]
            or mechanical_value != decision[mechanical_field]
        ):
            raise ContentPortError(
                f"{layout_id}/{field_name}: layout authority evidence drift"
            )
        selected_layouts[layout_id].value[field_name] = (
            decision[content_field]
            if decision["authority"] == "content"
            else decision[mechanical_field]
        )
    for decision in adaptations["layoutTilesetRemaps"]:
        layout_id, field_name = decision["layout"], decision["field"]
        if selected_layouts[layout_id].value[field_name] != decision["source"]:
            raise ContentPortError(
                f"{layout_id}/{field_name}: tileset remap preimage drift"
            )
        # The graph identity remains the authenticated donor asset. The target
        # renderer binding is validated below without replacing source authority.

    source_records.update(
        {ResourceKey("layout", key): value for key, value in selected_layouts.items()}
    )
    for authority in (content, mechanical):
        source_records.update(
            {
                key: record
                for key, record in authority._records.items()
                if key.domain == "asset"
            }
        )
    # Renderer bindings are authored policy. Installed generated headers are
    # outputs and must never become authority for their own desired state.
    policy_tilesets = {
        f"gTileset_{item.get('targetSymbol', item['symbol'])}"
        for item in adaptations["tilesetAdaptations"]
    }
    for decision in adaptations["layoutTilesetRemaps"]:
        if decision["target"] not in policy_tilesets:
            raise ContentPortError(
                f"{decision['layout']}: target tileset binding {decision['target']} "
                "is missing from typed policy"
            )

    enabled = tuple(
        decision
        for decision in descriptor.capabilities
        if decision.state == CapabilityState.ENABLED
    )
    ledger_path = target_root / "src/data/persistence/persistent_ids.json"
    ledger = load_binding_index(ledger_path)
    explicit_dependencies = {
        dependency for decision in enabled for dependency in decision.dependencies
    }
    for dependency in sorted(explicit_dependencies):
        if dependency.domain != "binding":
            continue
        binding_domain = (
            "flags"
            if dependency.name.startswith("FLAG_")
            else "vars"
            if dependency.name.startswith("VAR_")
            else None
        )
        ledger.resolve(dependency.name, domain=binding_domain)
        source_records[dependency] = SourceRecord(
            {}, Provenance(ledger_path.as_posix(), f"/{dependency.name}")
        )
    capability_roots: list[ResourceKey] = []
    for decision in enabled:
        key = ResourceKey("capability", f"{decision.map_name}/{decision.capability}")
        references: dict[str, list[str]] = {"map": [decision.map_name]}
        for dependency in decision.dependencies:
            references.setdefault(dependency.domain, []).append(dependency.name)
        source_records[key] = SourceRecord(
            {"references": references},
            Provenance(
                descriptor.path.as_posix(),
                f"/capabilities/{decision.map_name}/{decision.capability}",
            ),
        )
        capability_roots.append(key)
    context = SourceContext(
        source_records, aliases=aliases, active_capabilities=("spatial",)
    )
    graph = build_source_graph(context, capability_roots)
    enabled_spatial_maps = {
        decision.map_name for decision in enabled if decision.capability == "spatial"
    }
    allowed: set[ResourceKey] = set(capability_roots) | explicit_dependencies
    allowed.update(ResourceKey("map", name) for name in enabled_spatial_maps)
    for name in enabled_spatial_maps:
        layout_key = ResourceKey("layout", str(selected_maps[name]["layout"]))
        allowed.add(layout_key)
        layout = selected_layouts[layout_key.name]
        for field_name in (
            "primary_tileset",
            "secondary_tileset",
            "border_filepath",
            "blockdata_filepath",
        ):
            asset = _key("asset", layout.value.get(field_name))
            if asset is not None:
                allowed.add(asset)
    closure = close_source_graph(graph, capability_roots, frozenset(allowed))

    rendered_graph = world_graph_from_maps(selected_maps)
    world_policy = adaptations.get("worldPolicy")
    if not isinstance(world_policy, dict) or set(world_policy) != {
        "roots",
        "unreachableShells",
    }:
        raise ContentPortError(
            "worldPolicy requires exact roots and unreachableShells arrays"
        )
    if not all(isinstance(item, str) and item for item in world_policy["roots"]):
        raise ContentPortError("worldPolicy.roots must contain map names")
    if not all(
        isinstance(item, str) and item for item in world_policy["unreachableShells"]
    ):
        raise ContentPortError("worldPolicy.unreachableShells must contain map names")
    deferred_dynamic = frozenset(
        edge.key
        for edge in rendered_graph.edges
        if edge.kind == "warp"
        and not isinstance(edge.target_warp, int)
        and any(
            item["source"] == edge.source
            and item["path"] == f"warp_events/{edge.index}"
            for item in adaptations["deferredEdges"]
        )
    )
    reviewed_one_way = frozenset(
        edge.key
        for edge in rendered_graph.edges
        if edge.kind == "connection"
        and edge.target in rendered_graph.maps
        and not rendered_graph.has_reciprocal(edge)
        and (
            edge.source,
            f"connections/{edge.index}",
            "connection",
            f"MAP_{edge.target}",
        )
        in reviewed_retained
    )
    dynamic_warps = {
        edge.key: str(edge.target_warp)
        for edge in rendered_graph.edges
        if edge.kind == "warp" and not isinstance(edge.target_warp, int)
    }
    validate_world_graph(
        rendered_graph,
        WorldPolicy(
            reviewed_one_way=reviewed_one_way,
            deferred_exits=deferred_dynamic,
            dynamic_warps=dynamic_warps,
            roots=frozenset(world_policy["roots"]),
            unreachable_shells=frozenset(world_policy["unreachableShells"]),
        ),
    )

    entries, effect_policy = load_event_policy(descriptor.path.parent / "events.json")
    enabled_capabilities = {decision.capability for decision in enabled}
    for entry in sorted(entries.values(), key=lambda item: item.name):
        if entry.capability not in enabled_capabilities:
            continue
        scripts = [
            path
            for path in (content_pin.root / "data/maps").glob("*/scripts.inc")
            if entry.name in path.read_text(encoding="utf-8", errors="replace")
        ]
        if not scripts:
            raise ContentPortError(
                f"enabled event entry {entry.name} has no donor script source"
            )
        program = parse_scripts(scripts, root=content_pin.root)
        effects = analyze_entry(program, entry.name)
        validate_effects(entry, effects, effect_policy)
        for effect in effects:
            if (
                effect.kind not in {"state-read", "state-write"}
                or effect.operand is None
            ):
                continue
            binding_domain = (
                "flags"
                if effect.operand.startswith("FLAG_")
                else "vars"
                if effect.operand.startswith("VAR_")
                else None
            )
            ledger.resolve(effect.operand, domain=binding_domain)

    maps_in_closure = tuple(
        name for name in map_names if ResourceKey("map", name) in closure
    )
    layouts_in_closure = tuple(descriptor.allocation_index.layouts)
    tilesets = tuple(
        sorted(
            {
                str(record.value[field_name])
                for record in selected_layouts.values()
                for field_name in ("primary_tileset", "secondary_tileset")
            }
        )
    )
    inventory = MappingProxyType(
        {
            "maps": len(maps_in_closure),
            "layouts": len(layouts_in_closure),
            "groups": len(descriptor.allocation_index.groups),
            "sections": len(descriptor.allocation_index.sections),
            "tilesets": len(tilesets),
        }
    )
    inventory_values: Mapping[str, tuple[str, ...]] = {
        "maps": tuple(maps_in_closure),
        "layouts": tuple(layouts_in_closure),
        "groups": tuple(descriptor.allocation_index.groups),
        "sections": tuple(descriptor.allocation_index.sections),
        "tilesets": tilesets,
    }
    for domain, expected in descriptor.expected_inventory.items():
        if inventory[domain] != expected["count"]:
            raise ContentPortError(
                f"{domain} inventory count {inventory[domain]} != reviewed {expected['count']}"
            )
        actual_digest = _inventory_digest(inventory_values[domain])
        if actual_digest != expected["digest"]:
            raise ContentPortError(
                f"{domain} inventory digest {actual_digest} != reviewed {expected['digest']}"
            )
    closure_report = MappingProxyType(
        {
            "maps": maps_in_closure,
            "layouts": layouts_in_closure,
            "groups": tuple(sorted(descriptor.allocation_index.groups)),
            "sections": tuple(sorted(descriptor.allocation_index.sections)),
            "tilesets": tilesets,
            "deferred_edges": tuple(
                sorted(
                    (item["source"], item["kind"], item["destination"])
                    for item in adaptations["deferredEdges"]
                )
            ),
            "resources": tuple(str(key) for key in closure),
        }
    )
    legacy = descriptor.legacy_report
    legacy_inventory = legacy.get("inventory")
    legacy_closure = legacy.get("closure")
    if not isinstance(legacy_inventory, Mapping) or not isinstance(
        legacy_closure, Mapping
    ):
        raise ContentPortError("required legacy baseline lacks inventory or closure")
    if dict(inventory) != dict(legacy_inventory):
        raise ContentPortError(
            "current inventory differs from required legacy baseline"
        )
    for field_name in (
        "maps",
        "layouts",
        "groups",
        "sections",
        "tilesets",
        "deferred_edges",
    ):
        if _thaw(closure_report[field_name]) != _thaw(legacy_closure.get(field_name)):
            raise ContentPortError(
                f"current closure field {field_name} differs from required legacy baseline"
            )
    provenance_roots = (
        ("content", content_pin.root.resolve()),
        ("mechanical", mechanical_pin.root.resolve()),
        ("target", target_root.resolve()),
    )

    def stable_provenance(value: Provenance) -> str:
        if value.path.startswith("<"):
            return str(value)
        path = Path(value.path).resolve()
        for role, root in provenance_roots:
            try:
                return f"{role}:{path.relative_to(root).as_posix()}{value.location}"
            except ValueError:
                continue
        return f"external:{path.name}{value.location}"

    evidence = MappingProxyType(
        {
            "graphDigest": _canonical_digest(
                f"{edge.source}->{edge.target}@{stable_provenance(edge.provenance)}"
                for edge in graph.edges
            ),
            "resourceDigest": _canonical_digest(str(key) for key in closure),
            "inputDigest": _canonical_digest(input_evidence),
            "resourceCount": len(closure),
            "edgeCount": len(graph.edges),
            "enabledCapabilityCount": len(enabled),
        }
    )
    contract = ContractEvidence(inventory, closure_report, evidence)
    state = PortSourceState(
        maps=_freeze_state(selected_maps),
        layouts=_freeze_state(
            {name: record.value for name, record in selected_layouts.items()}
        ),
        map_authorities=MappingProxyType(dict(map_authorities)),
        layout_authorities=MappingProxyType(dict(layout_authorities)),
        donor_roots=MappingProxyType(
            {"mechanical": mechanical_pin.root, "content": content_pin.root}
        ),
        resources=graph.resources,
        inventory=MappingProxyType(dict(inventory_values)),
    )
    return contract, state


def validate_port_sources(
    descriptor: PortDescriptor, repo: Path | str
) -> ContractEvidence:
    """Validate a port and return its deterministic contract evidence."""
    return resolve_port_sources(descriptor, repo)[0]
