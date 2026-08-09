"""Strict loading for region policy kept outside the generic engine."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath
from types import MappingProxyType
from typing import Any

from .allocations import AllocationIndex, load_allocation_index
from .errors import ContentPortError
from .model import CapabilityDecision, CapabilityState, DonorPin, ResourceKey


DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PORT_KEYS = {
    "schemaVersion",
    "allocationLock",
    "capabilityPolicy",
    "eventPolicy",
    "adaptations",
    "assetPolicy",
    "legacyReport",
    "donors",
    "expectedInventory",
    "authority",
}
DONOR_KEYS = {
    "name",
    "repository",
    "commit",
    "treeDigest",
    "fileCount",
    "root",
    "migration",
}
INVENTORY_DOMAINS = {"maps", "layouts", "groups", "sections", "tilesets"}
AUTHORITY_KEYS = {"content", "mechanical", "unclassifiedDivergence"}
CAPABILITY_KEYS = {"schemaVersion", "capabilities", "maps"}
MAP_POLICY_KEYS = {"map", "ownership", "capabilities"}
ADAPTATION_KEYS = {
    "schemaVersion",
    "adaptations",
    "layoutHeaderDecisions",
    "mapFieldDecisions",
    "sectionSymbolRemaps",
    "layoutTilesetRemaps",
    "attributeFixtures",
    "preserveSpatialUpdates",
    "contentFallback",
    "retainedEdges",
    "deferredEdges",
    "graphicsAdaptations",
    "musicAdaptations",
    "scriptSubstitutions",
    "tilesetAdaptations",
    "encounterAdaptations",
    "trainerPresentation",
    "warpReindexes",
    "warpRemovals",
    "berryTreeAllocations",
    "materializationProfile",
    "regionAssignment",
    "worldPolicy",
}
MIGRATION_KEYS = {
    "addedPaths",
    "assets",
    "authorityChanges",
    "changedPaths",
    "decision",
    "donor",
    "from",
    "removedPaths",
    "repository",
    "schemaVersion",
    "tests",
    "to",
}
MIGRATION_PIN_KEYS = {"commit", "fileCount", "treeDigest"}
NUMERIC_POLICY_FIELDS = {
    "targetId",
    "targetIndex",
    "targetGroup",
    "targetGroupId",
    "targetMember",
    "targetLayoutIndex",
    "targetSection",
    "groupAllocations",
    "sectionAllocations",
}


class _DuplicateKey(Exception):
    def __init__(self, key: str):
        self.key = key


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise _DuplicateKey(key)
        value[key] = child
    return value


def read_json(path: Path) -> object:
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text, object_pairs_hook=_pairs)
    except _DuplicateKey as error:
        raise ContentPortError(f"{path}: duplicate JSON field {error.key!r}") from error
    except json.JSONDecodeError as error:
        raise ContentPortError(
            f"{path}:{error.lineno}:{error.colno}: invalid JSON: {error.msg}"
        ) from error
    except (OSError, UnicodeError) as error:
        raise ContentPortError(f"cannot read JSON {path}: {error}") from error


def _object(value: object, pointer: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    return value


def _array(value: object, pointer: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContentPortError(f"{pointer}: expected an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], pointer: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")


def _string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def _integer(value: object, pointer: str, *, positive: bool = False) -> int:
    minimum = 1 if positive else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        kind = "positive" if positive else "non-negative"
        raise ContentPortError(f"{pointer}: expected a {kind} integer")
    return value


def _safe_child(root: Path, value: object, pointer: str) -> Path:
    name = _string(value, pointer)
    path = PurePath(name)
    if path.is_absolute() or len(path.parts) != 1 or path.name != name:
        raise ContentPortError(f"{pointer}: expected one local policy filename")
    resolved = root / name
    if resolved.is_symlink():
        raise ContentPortError(f"{pointer}: policy file must not be a symbolic link")
    return resolved


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def forbid_numeric_policy(value: object, pointer: str = "$") -> None:
    """Reject placement fields outside the allocation lock at any depth."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_pointer = f"{pointer}.{key}"
            if key in NUMERIC_POLICY_FIELDS:
                raise ContentPortError(
                    f"{child_pointer}: numeric placement belongs in allocation_lock.json"
                )
            forbid_numeric_policy(child, child_pointer)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbid_numeric_policy(child, f"{pointer}[{index}]")


@dataclass(frozen=True)
class PortDescriptor:
    path: Path
    donors: tuple[DonorPin, ...]
    expected_inventory: Mapping[str, Mapping[str, object]]
    authority: Mapping[str, object]
    allocation_index: AllocationIndex
    capabilities: tuple[CapabilityDecision, ...]
    map_ownership: Mapping[str, str]
    adaptations: Mapping[str, object]
    events: Mapping[str, object]
    assets: Mapping[str, object]
    legacy_report: Mapping[str, object]


def _migration_pin(value: object, pointer: str) -> tuple[str, str, int]:
    item = _object(value, pointer)
    _exact_keys(item, MIGRATION_PIN_KEYS, pointer)
    commit = _string(item["commit"], f"{pointer}.commit")
    digest = _string(item["treeDigest"], f"{pointer}.treeDigest")
    if not COMMIT_RE.fullmatch(commit):
        raise ContentPortError(f"{pointer}.commit: expected 40 lowercase hex")
    if not DIGEST_RE.fullmatch(digest):
        raise ContentPortError(f"{pointer}.treeDigest: expected 64 lowercase hex")
    count = _integer(item["fileCount"], f"{pointer}.fileCount", positive=True)
    return commit, digest, count


def _validate_migration(
    port_dir: Path,
    digest: str,
    *,
    role: str,
    donor: str,
    repository: str,
    commit: str,
    tree_digest: str,
    file_count: int,
) -> None:
    from .update import migration_digest, validate_reviewed_migration

    path = port_dir / "migrations" / f"{digest}.json"
    if path.is_symlink():
        raise ContentPortError(f"{path}: migration record must not be a symbolic link")
    report = _object(read_json(path), f"migration:{digest}")
    _exact_keys(report, MIGRATION_KEYS, f"migration:{digest}")
    if migration_digest(report) != digest:
        raise ContentPortError(f"migration record filename is stale: {path}")
    if report["schemaVersion"] != 1:
        raise ContentPortError(
            f"migration:{digest}.schemaVersion: unsupported migration schema"
        )
    for field in (
        "addedPaths",
        "assets",
        "authorityChanges",
        "changedPaths",
        "removedPaths",
        "tests",
    ):
        _array(report[field], f"migration:{digest}.{field}")
    source_commit, source_digest, source_count = _migration_pin(
        report["from"], f"migration:{digest}.from"
    )
    target_commit, target_digest, target_count = _migration_pin(
        report["to"], f"migration:{digest}.to"
    )
    if source_commit == target_commit:
        raise ContentPortError(
            f"donor {donor}: reviewed migration commit chain is a no-op"
        )
    validate_reviewed_migration(
        report,
        donor=role,
        repository=repository,
        from_commit=source_commit,
        from_tree_digest=source_digest,
        from_file_count=source_count,
        to_commit=commit,
        to_tree_digest=tree_digest,
        to_file_count=file_count,
    )
    if (target_commit, target_digest, target_count) != (
        commit,
        tree_digest,
        file_count,
    ):
        raise ContentPortError(f"donor {donor}: migration target pin is stale")


def _load_donors(
    value: object, donor_root: Path, port_dir: Path, pointer: str
) -> tuple[DonorPin, ...]:
    donors = _object(value, pointer)
    _exact_keys(donors, {"mechanical", "content"}, pointer)
    result: list[DonorPin] = []
    for role in ("mechanical", "content"):
        item_pointer = f"{pointer}.{role}"
        item = _object(donors[role], item_pointer)
        _exact_keys(item, DONOR_KEYS, item_pointer)
        commit = _string(item["commit"], f"{item_pointer}.commit")
        digest = _string(item["treeDigest"], f"{item_pointer}.treeDigest")
        if not COMMIT_RE.fullmatch(commit):
            raise ContentPortError(f"{item_pointer}.commit: expected 40 lowercase hex")
        if not DIGEST_RE.fullmatch(digest):
            raise ContentPortError(
                f"{item_pointer}.treeDigest: expected 64 lowercase hex"
            )
        migration_value = item["migration"]
        if migration_value is not None and (
            not isinstance(migration_value, str)
            or not DIGEST_RE.fullmatch(migration_value)
        ):
            raise ContentPortError(
                f"{item_pointer}.migration: expected null or 64 lowercase hex"
            )
        relative_root = _string(item["root"], f"{item_pointer}.root")
        relative = PurePath(relative_root)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != relative_root
        ):
            raise ContentPortError(f"{item_pointer}.root: unsafe donor checkout path")
        name = _string(item["name"], f"{item_pointer}.name")
        repository = _string(item["repository"], f"{item_pointer}.repository")
        file_count = _integer(
            item["fileCount"], f"{item_pointer}.fileCount", positive=True
        )
        if migration_value is not None:
            _validate_migration(
                port_dir,
                migration_value,
                role=role,
                donor=name,
                repository=repository,
                commit=commit,
                tree_digest=digest,
                file_count=file_count,
            )
        result.append(
            DonorPin(
                name=name,
                repository=repository,
                commit=commit,
                tree_digest=digest,
                file_count=file_count,
                root=donor_root.joinpath(*relative.parts),
                migration=migration_value,
            )
        )
    if len({pin.name for pin in result}) != len(result):
        raise ContentPortError(f"{pointer}: duplicate donor name")
    return tuple(result)


def _load_inventory(value: object, pointer: str) -> Mapping[str, Mapping[str, object]]:
    document = _object(value, pointer)
    _exact_keys(document, INVENTORY_DOMAINS, pointer)
    result: dict[str, Mapping[str, object]] = {}
    for domain in sorted(INVENTORY_DOMAINS):
        item_pointer = f"{pointer}.{domain}"
        item = _object(document[domain], item_pointer)
        _exact_keys(item, {"count", "digest"}, item_pointer)
        count = _integer(item["count"], f"{item_pointer}.count", positive=True)
        digest = _string(item["digest"], f"{item_pointer}.digest")
        if not DIGEST_RE.fullmatch(digest):
            raise ContentPortError(f"{item_pointer}.digest: expected 64 lowercase hex")
        result[domain] = MappingProxyType({"count": count, "digest": digest})
    return MappingProxyType(result)


def _load_authority(value: object, pointer: str) -> Mapping[str, object]:
    document = _object(value, pointer)
    _exact_keys(document, AUTHORITY_KEYS, pointer)
    result: dict[str, object] = {}
    for field in ("content", "mechanical"):
        values = tuple(
            _string(item, f"{pointer}.{field}[{index}]")
            for index, item in enumerate(_array(document[field], f"{pointer}.{field}"))
        )
        if not values or len(values) != len(set(values)):
            raise ContentPortError(
                f"{pointer}.{field}: authority entries must be non-empty and unique"
            )
        result[field] = values
    if document["unclassifiedDivergence"] != "error":
        raise ContentPortError(
            f"{pointer}.unclassifiedDivergence: fail-closed policy must be 'error'"
        )
    result["unclassifiedDivergence"] = "error"
    return MappingProxyType(result)


def _dependency(value: object, pointer: str) -> ResourceKey:
    item = _object(value, pointer)
    _exact_keys(item, {"domain", "name"}, pointer)
    return ResourceKey(
        _string(item["domain"], f"{pointer}.domain"),
        _string(item["name"], f"{pointer}.name"),
    )


def _decision(
    value: object, pointer: str
) -> tuple[CapabilityState, tuple[ResourceKey, ...]]:
    if isinstance(value, str):
        return CapabilityState.parse(value, pointer), ()
    item = _object(value, pointer)
    _exact_keys(item, {"state", "dependencies"}, pointer)
    dependencies = tuple(
        _dependency(child, f"{pointer}.dependencies[{index}]")
        for index, child in enumerate(
            _array(item["dependencies"], f"{pointer}.dependencies")
        )
    )
    if len(dependencies) != len(set(dependencies)):
        raise ContentPortError(f"{pointer}.dependencies: duplicate resource identity")
    return CapabilityState.parse(item["state"], f"{pointer}.state"), dependencies


def _load_capabilities(
    value: object, pointer: str
) -> tuple[tuple[CapabilityDecision, ...], Mapping[str, str]]:
    root = _object(value, pointer)
    _exact_keys(root, CAPABILITY_KEYS, pointer)
    if root["schemaVersion"] != 1:
        raise ContentPortError(
            f"{pointer}.schemaVersion: unsupported capability schema"
        )
    names = tuple(
        _string(item, f"{pointer}.capabilities[{index}]")
        for index, item in enumerate(
            _array(root["capabilities"], f"{pointer}.capabilities")
        )
    )
    if not names or len(names) != len(set(names)):
        raise ContentPortError(
            f"{pointer}.capabilities: names must be non-empty and unique"
        )
    decisions: list[CapabilityDecision] = []
    ownership: dict[str, str] = {}
    for index, raw in enumerate(_array(root["maps"], f"{pointer}.maps")):
        item_pointer = f"{pointer}.maps[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, MAP_POLICY_KEYS, item_pointer)
        map_name = _string(item["map"], f"{item_pointer}.map")
        if map_name in ownership:
            raise ContentPortError(
                f"{item_pointer}.map: duplicate map policy {map_name}"
            )
        mode = _string(item["ownership"], f"{item_pointer}.ownership")
        if mode not in {"preserve", "rendered"}:
            raise ContentPortError(f"{item_pointer}.ownership: unknown ownership mode")
        policy = _object(item["capabilities"], f"{item_pointer}.capabilities")
        _exact_keys(policy, set(names), f"{item_pointer}.capabilities")
        ownership[map_name] = mode
        for capability in names:
            state, dependencies = _decision(
                policy[capability], f"{item_pointer}.capabilities.{capability}"
            )
            decisions.append(
                CapabilityDecision(map_name, capability, state, dependencies)
            )
    return tuple(decisions), MappingProxyType(ownership)


def _load_policy(
    path: Path, expected_keys: set[str] | None, pointer: str
) -> Mapping[str, object]:
    value = _object(read_json(path), pointer)
    if value.get("schemaVersion") != 1:
        raise ContentPortError(f"{pointer}.schemaVersion: unsupported policy schema")
    if expected_keys is not None:
        _exact_keys(value, expected_keys, pointer)
    forbid_numeric_policy(value, pointer)
    return _freeze(dict(value))  # type: ignore[return-value]


def load_port(port_dir: Path, donor_root: Path) -> PortDescriptor:
    port_dir = port_dir.resolve()
    if not port_dir.is_dir():
        raise ContentPortError(f"port descriptor directory does not exist: {port_dir}")
    port_path = port_dir / "port.json"
    root = _object(read_json(port_path), "$")
    _exact_keys(root, PORT_KEYS, "$")
    if root["schemaVersion"] != 1:
        raise ContentPortError("$.schemaVersion: unsupported port schema")
    forbid_numeric_policy(
        {key: value for key, value in root.items() if key != "allocationLock"}
    )

    allocation_path = _safe_child(port_dir, root["allocationLock"], "$.allocationLock")
    allocation_index = load_allocation_index(read_json(allocation_path))
    capability_path = _safe_child(
        port_dir, root["capabilityPolicy"], "$.capabilityPolicy"
    )
    capability_doc = read_json(capability_path)
    forbid_numeric_policy(capability_doc)
    capabilities, ownership = _load_capabilities(capability_doc, "$")
    if set(ownership) != set(allocation_index.maps):
        missing = sorted(set(allocation_index.maps) - set(ownership))
        extra = sorted(set(ownership) - set(allocation_index.maps))
        detail = f"missing={missing[:1]}, extra={extra[:1]}"
        raise ContentPortError(
            f"capability policy does not match allocation maps: {detail}"
        )

    adaptations = _load_policy(
        _safe_child(port_dir, root["adaptations"], "$.adaptations"),
        ADAPTATION_KEYS,
        "$",
    )
    events = _load_policy(
        _safe_child(port_dir, root["eventPolicy"], "$.eventPolicy"), None, "$"
    )
    assets = _load_policy(
        _safe_child(port_dir, root["assetPolicy"], "$.assetPolicy"),
        {"schemaVersion", "assets"},
        "$",
    )
    # Asset policy has domain-specific field and permission validation in the
    # donor-governance module. Blocked entries remain loadable by design.
    from .update import validate_assets

    validate_assets(_thaw(assets), require_redistributable=False)  # type: ignore[arg-type]
    legacy = _load_policy(
        _safe_child(port_dir, root["legacyReport"], "$.legacyReport"), None, "$"
    )
    return PortDescriptor(
        path=port_path,
        donors=_load_donors(root["donors"], donor_root.resolve(), port_dir, "$.donors"),
        expected_inventory=_load_inventory(
            root["expectedInventory"], "$.expectedInventory"
        ),
        authority=_load_authority(root["authority"], "$.authority"),
        allocation_index=allocation_index,
        capabilities=capabilities,
        map_ownership=ownership,
        adaptations=adaptations,
        events=events,
        assets=assets,
        legacy_report=legacy,
    )
