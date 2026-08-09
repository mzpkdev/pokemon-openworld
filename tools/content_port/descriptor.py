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
from .model import (
    CapabilityDecision,
    CapabilityState,
    DonorPin,
    GeneratedSectionPolicy,
    LayoutBinaryAuthority,
    PersistentBindingRef,
    ResourceKey,
    SectionPersistenceCodec,
    SectionMetadataAuthority,
    TargetBindings,
)


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
    "genesis",
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
    "donorFieldRoles",
    "layoutBinaryAuthorities",
    "generatedSections",
    "sectionMetadataAuthorities",
    "targetBindings",
}
MIGRATION_KEYS = {
    "addedPaths",
    "assets",
    "authorityChanges",
    "changedPaths",
    "decision",
    "donor",
    "from",
    "predecessor",
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
RENDER_POLICY_KEYS = {
    "layoutBinaryAuthorities",
    "generatedSections",
    "sectionMetadataAuthorities",
    "targetBindings",
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
    donors_by_role: Mapping[str, DonorPin]
    expected_inventory: Mapping[str, Mapping[str, object]]
    authority: Mapping[str, object]
    allocation_index: AllocationIndex
    capabilities: tuple[CapabilityDecision, ...]
    map_ownership: Mapping[str, str]
    adaptations: Mapping[str, object]
    events: Mapping[str, object]
    assets: Mapping[str, object]
    legacy_report: Mapping[str, object]
    layout_binary_authorities: tuple[LayoutBinaryAuthority, ...]
    generated_sections: tuple[GeneratedSectionPolicy, ...]
    section_metadata_authorities: tuple[SectionMetadataAuthority, ...]
    target_bindings: TargetBindings

    def donor(self, role: str) -> DonorPin:
        try:
            return self.donors_by_role[role]
        except KeyError as error:
            raise ContentPortError(
                f"port descriptor has no donor role {role!r}"
            ) from error


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
    donor_checkout: Path,
    genesis: tuple[str, str, int],
) -> None:
    from .update import migration_digest, validate_reviewed_migration

    def validate_link(
        link: str,
        expected_target: tuple[str, str, int],
        seen: frozenset[str],
    ) -> None:
        if link in seen:
            raise ContentPortError(f"donor {donor}: migration predecessor cycle")
        path = port_dir / "migrations" / f"{link}.json"
        if path.is_symlink():
            raise ContentPortError(
                f"{path}: migration record must not be a symbolic link"
            )
        report = _object(read_json(path), f"migration:{link}")
        _exact_keys(report, MIGRATION_KEYS, f"migration:{link}")
        if migration_digest(report) != link:
            raise ContentPortError(f"migration record filename is stale: {path}")
        if report["schemaVersion"] != 1:
            raise ContentPortError(
                f"migration:{link}.schemaVersion: unsupported migration schema"
            )
        for field in (
            "addedPaths",
            "assets",
            "authorityChanges",
            "changedPaths",
            "removedPaths",
            "tests",
        ):
            _array(report[field], f"migration:{link}.{field}")
        source = _migration_pin(report["from"], f"migration:{link}.from")
        target = _migration_pin(report["to"], f"migration:{link}.to")
        if source[0] == target[0]:
            raise ContentPortError(
                f"donor {donor}: reviewed migration commit chain is a no-op"
            )
        if target != expected_target:
            raise ContentPortError(f"donor {donor}: migration target pin is stale")
        predecessor = report["predecessor"]
        if predecessor is None:
            if source != genesis:
                raise ContentPortError(
                    f"donor {donor}: migration chain does not start at genesis pin"
                )
        elif isinstance(predecessor, str) and DIGEST_RE.fullmatch(predecessor):
            validate_link(predecessor, source, seen | {link})
        else:
            raise ContentPortError(
                f"migration:{link}.predecessor: expected null or 64 lowercase hex"
            )
        validate_reviewed_migration(
            report,
            donor=role,
            repository=repository,
            from_commit=source[0],
            from_tree_digest=source[1],
            from_file_count=source[2],
            to_commit=target[0],
            to_tree_digest=target[1],
            to_file_count=target[2],
            port_dir=port_dir,
            donor_checkout=donor_checkout,
        )

    validate_link(digest, (commit, tree_digest, file_count), frozenset())


def _load_donors(
    value: object, donor_root: Path, port_dir: Path, pointer: str
) -> Mapping[str, DonorPin]:
    donors = _object(value, pointer)
    if not donors:
        raise ContentPortError(f"{pointer}: at least one donor role is required")
    result: dict[str, DonorPin] = {}
    for role, raw in donors.items():
        _string(role, f"{pointer} role")
        item_pointer = f"{pointer}.{role}"
        item = _object(raw, item_pointer)
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
        genesis = _migration_pin(item["genesis"], f"{item_pointer}.genesis")
        checkout = donor_root.joinpath(*relative.parts)
        current = (commit, digest, file_count)
        if migration_value is None:
            if current != genesis:
                raise ContentPortError(
                    f"{item_pointer}: unlinked pin differs from genesis"
                )
        else:
            _validate_migration(
                port_dir,
                migration_value,
                role=role,
                donor=name,
                repository=repository,
                commit=commit,
                tree_digest=digest,
                file_count=file_count,
                donor_checkout=checkout,
                genesis=genesis,
            )
        result[role] = DonorPin(
            name=name,
            repository=repository,
            commit=commit,
            tree_digest=digest,
            file_count=file_count,
            root=checkout,
            migration=migration_value,
        )
    if len({pin.name for pin in result.values()}) != len(result):
        raise ContentPortError(f"{pointer}: duplicate donor name")
    if len({pin.root for pin in result.values()}) != len(result):
        raise ContentPortError(f"{pointer}: duplicate donor checkout")
    return MappingProxyType(result)


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


def _relative_path(value: object, pointer: str) -> str:
    rendered = _string(value, pointer)
    path = PurePath(rendered)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != rendered
        or rendered.endswith("/")
    ):
        raise ContentPortError(f"{pointer}: unsafe repository-relative path")
    return rendered


def _load_renderer_policy(
    value: object,
    allocations: AllocationIndex,
    donor_roles: set[str],
    pointer: str = "$",
) -> tuple[
    tuple[LayoutBinaryAuthority, ...],
    tuple[GeneratedSectionPolicy, ...],
    tuple[SectionMetadataAuthority, ...],
    TargetBindings,
]:
    document = _object(value, pointer)

    layout_records: list[LayoutBinaryAuthority] = []
    for index, raw in enumerate(
        _array(
            document["layoutBinaryAuthorities"], f"{pointer}.layoutBinaryAuthorities"
        )
    ):
        item_pointer = f"{pointer}.layoutBinaryAuthorities[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, {"layout", "source", "sourceRole"}, item_pointer)
        record = LayoutBinaryAuthority(
            layout=_string(item["layout"], f"{item_pointer}.layout"),
            source=_string(item["source"], f"{item_pointer}.source"),
            source_role=_string(item["sourceRole"], f"{item_pointer}.sourceRole"),
        )
        if record.source_role not in donor_roles:
            raise ContentPortError(
                f"{item_pointer}.sourceRole: unknown donor role {record.source_role!r}"
            )
        layout_records.append(record)
    layout_ids = [record.layout for record in layout_records]
    if len(layout_ids) != len(set(layout_ids)):
        raise ContentPortError(f"{pointer}.layoutBinaryAuthorities: duplicate layout")
    if set(layout_ids) != set(allocations.layouts):
        missing = sorted(set(allocations.layouts) - set(layout_ids))
        extra = sorted(set(layout_ids) - set(allocations.layouts))
        raise ContentPortError(
            "$.layoutBinaryAuthorities: must cover every allocated layout; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )

    generated_records: list[GeneratedSectionPolicy] = []
    allowed_symbols = {
        "map-scripts",
        "berry-bindings",
        "flag-bindings",
        "trainer-bindings",
        "var-bindings",
        "tileset-externs",
        "tileset-graphics",
        "tileset-headers",
        "tileset-metatiles",
        "trainer-parties",
    }
    for index, raw in enumerate(
        _array(document["generatedSections"], f"{pointer}.generatedSections")
    ):
        item_pointer = f"{pointer}.generatedSections[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, {"key", "path", "sourceRole", "sourceSymbol"}, item_pointer)
        record = GeneratedSectionPolicy(
            key=_string(item["key"], f"{item_pointer}.key"),
            path=_relative_path(item["path"], f"{item_pointer}.path"),
            source_role=_string(item["sourceRole"], f"{item_pointer}.sourceRole"),
            source_symbol=_string(item["sourceSymbol"], f"{item_pointer}.sourceSymbol"),
        )
        allowed_roles = donor_roles | {"policy", "target-bindings"}
        if record.source_role not in allowed_roles:
            raise ContentPortError(
                f"{item_pointer}.sourceRole: unknown source role {record.source_role!r}"
            )
        if record.source_symbol not in allowed_symbols:
            raise ContentPortError(
                f"{item_pointer}.sourceSymbol: unknown generated source"
            )
        generated_records.append(record)
    for field, values in (
        ("key", [record.key for record in generated_records]),
        (
            "path/sourceSymbol",
            [(record.path, record.source_symbol) for record in generated_records],
        ),
        ("sourceSymbol", [record.source_symbol for record in generated_records]),
    ):
        if len(values) != len(set(values)):
            raise ContentPortError(f"{pointer}.generatedSections: duplicate {field}")
    if set(record.source_symbol for record in generated_records) != allowed_symbols:
        missing = sorted(
            allowed_symbols - {record.source_symbol for record in generated_records}
        )
        raise ContentPortError(
            f"{pointer}.generatedSections: missing renderer source {missing[0]!r}"
        )

    section_records: list[SectionMetadataAuthority] = []
    for index, raw in enumerate(
        _array(
            document["sectionMetadataAuthorities"],
            f"{pointer}.sectionMetadataAuthorities",
        )
    ):
        item_pointer = f"{pointer}.sectionMetadataAuthorities[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, {"section", "sourceRole", "sourceSymbol"}, item_pointer)
        record = SectionMetadataAuthority(
            section=_string(item["section"], f"{item_pointer}.section"),
            source_role=_string(item["sourceRole"], f"{item_pointer}.sourceRole"),
            source_symbol=_string(item["sourceSymbol"], f"{item_pointer}.sourceSymbol"),
        )
        if record.source_role not in donor_roles:
            raise ContentPortError(
                f"{item_pointer}.sourceRole: unknown donor role {record.source_role!r}"
            )
        section_records.append(record)
    section_ids = [record.section for record in section_records]
    if len(section_ids) != len(set(section_ids)):
        raise ContentPortError(
            f"{pointer}.sectionMetadataAuthorities: duplicate section"
        )
    if set(section_ids) != set(allocations.sections):
        missing = sorted(set(allocations.sections) - set(section_ids))
        extra = sorted(set(section_ids) - set(allocations.sections))
        raise ContentPortError(
            "$.sectionMetadataAuthorities: must cover every allocated section; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )

    bindings_pointer = f"{pointer}.targetBindings"
    bindings = _object(document["targetBindings"], bindings_pointer)
    binding_keys = {
        "layoutFormat",
        "sectionKind",
        "region",
        "regionMapType",
        "savedLocationInvalidBinding",
        "metLocationInvalidBinding",
        "berryTreeBinding",
        "tilesetFeatureMacro",
        "timeEncounterLabel",
        "deferredCallLabel",
        "deferredCallText",
        "sectionPersistenceCodecs",
        "flagExports",
        "varExports",
    }
    _exact_keys(bindings, binding_keys, bindings_pointer)

    def binding_ref(value: object, item_pointer: str) -> PersistentBindingRef:
        item = _object(value, item_pointer)
        _exact_keys(item, {"domain", "symbol"}, item_pointer)
        return PersistentBindingRef(
            domain=_string(item["domain"], f"{item_pointer}.domain"),
            symbol=_string(item["symbol"], f"{item_pointer}.symbol"),
        )

    codecs: list[SectionPersistenceCodec] = []
    for index, raw in enumerate(
        _array(
            bindings["sectionPersistenceCodecs"],
            f"{bindings_pointer}.sectionPersistenceCodecs",
        )
    ):
        item_pointer = f"{bindings_pointer}.sectionPersistenceCodecs[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(
            item,
            {
                "section",
                "savedLocation",
                "metLocationBinding",
                "metLocationDisplay",
            },
            item_pointer,
        )
        codecs.append(
            SectionPersistenceCodec(
                section=_string(item["section"], f"{item_pointer}.section"),
                saved_location=_string(
                    item["savedLocation"], f"{item_pointer}.savedLocation"
                ),
                met_location_binding=binding_ref(
                    item["metLocationBinding"],
                    f"{item_pointer}.metLocationBinding",
                ),
                met_location_display=_string(
                    item["metLocationDisplay"],
                    f"{item_pointer}.metLocationDisplay",
                ),
            )
        )
    codec_sections = [codec.section for codec in codecs]
    if len(codec_sections) != len(set(codec_sections)):
        raise ContentPortError(
            f"{bindings_pointer}.sectionPersistenceCodecs: duplicate section"
        )
    unknown_codecs = sorted(set(codec_sections) - set(allocations.sections))
    if unknown_codecs:
        raise ContentPortError(
            f"{bindings_pointer}.sectionPersistenceCodecs: unknown section {unknown_codecs[0]!r}"
        )

    def exports(field: str) -> tuple[str, ...]:
        values = tuple(
            _string(item, f"{bindings_pointer}.{field}[{index}]")
            for index, item in enumerate(
                _array(bindings[field], f"{bindings_pointer}.{field}")
            )
        )
        if len(values) != len(set(values)):
            raise ContentPortError(f"{bindings_pointer}.{field}: duplicate symbol")
        return values

    target_bindings = TargetBindings(
        layout_format=_string(
            bindings["layoutFormat"], f"{bindings_pointer}.layoutFormat"
        ),
        section_kind=_string(
            bindings["sectionKind"], f"{bindings_pointer}.sectionKind"
        ),
        region=_string(bindings["region"], f"{bindings_pointer}.region"),
        region_map_type=_string(
            bindings["regionMapType"], f"{bindings_pointer}.regionMapType"
        ),
        saved_location_invalid_binding=binding_ref(
            bindings["savedLocationInvalidBinding"],
            f"{bindings_pointer}.savedLocationInvalidBinding",
        ),
        met_location_invalid_binding=binding_ref(
            bindings["metLocationInvalidBinding"],
            f"{bindings_pointer}.metLocationInvalidBinding",
        ),
        berry_tree_binding=binding_ref(
            bindings["berryTreeBinding"], f"{bindings_pointer}.berryTreeBinding"
        ),
        tileset_feature_macro=_string(
            bindings["tilesetFeatureMacro"],
            f"{bindings_pointer}.tilesetFeatureMacro",
        ),
        time_encounter_label=_string(
            bindings["timeEncounterLabel"],
            f"{bindings_pointer}.timeEncounterLabel",
        ),
        deferred_call_label=_string(
            bindings["deferredCallLabel"],
            f"{bindings_pointer}.deferredCallLabel",
        ),
        deferred_call_text=_string(
            bindings["deferredCallText"],
            f"{bindings_pointer}.deferredCallText",
        ),
        section_persistence_codecs=tuple(sorted(codecs)),
        flag_exports=exports("flagExports"),
        var_exports=exports("varExports"),
    )
    return (
        tuple(sorted(layout_records)),
        tuple(sorted(generated_records)),
        tuple(sorted(section_records)),
        target_bindings,
    )


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
    path: Path,
    expected_keys: set[str] | None,
    pointer: str,
) -> Mapping[str, object]:
    value = _object(read_json(path), pointer)
    if value.get("schemaVersion") != 1:
        raise ContentPortError(f"{pointer}.schemaVersion: unsupported policy schema")
    if expected_keys is not None:
        unknown = sorted(set(value) - expected_keys)
        missing = sorted(expected_keys - set(value))
        if unknown:
            raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
        if missing:
            raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")
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
    donors_by_role = _load_donors(
        root["donors"], donor_root.resolve(), port_dir, "$.donors"
    )
    required_roles = {"content", "mechanical"}
    if not required_roles.issubset(donors_by_role):
        missing = sorted(required_roles - set(donors_by_role))
        raise ContentPortError(f"$.donors: missing authority donor role {missing[0]!r}")
    (
        layout_binary_authorities,
        generated_sections,
        section_metadata_authorities,
        target_bindings,
    ) = _load_renderer_policy(_thaw(adaptations), allocation_index, set(donors_by_role))
    return PortDescriptor(
        path=port_path,
        donors=tuple(donors_by_role.values()),
        donors_by_role=donors_by_role,
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
        layout_binary_authorities=layout_binary_authorities,
        generated_sections=generated_sections,
        section_metadata_authorities=section_metadata_authorities,
        target_bindings=target_bindings,
    )
