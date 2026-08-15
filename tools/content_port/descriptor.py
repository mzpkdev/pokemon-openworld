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
from .donor_paths import validated_donor_checkouts
from .donors import validate_excluded_paths
from .errors import ContentPortError
from .model import (
    CapabilityDecision,
    CapabilityState,
    DonorPin,
    GeneratedSectionPolicy,
    LayoutBinaryAuthority,
    LayoutFieldAuthority,
    PersistentBindingRef,
    ResourceKey,
    SectionPersistenceCodec,
    SectionMetadataAuthority,
    TargetBindings,
)
from .semantics import EffectKey, EventEntry


DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TRAINER_DISPLAY_RE = re.compile(r"^[A-Za-z0-9?][A-Za-z0-9 ?.'-]*$")
MATERIALIZATION_STRIP_EVENT_KINDS = (
    "bg_events",
    "coord_events",
    "object_events",
)
MATERIALIZED_CAPABILITIES = frozenset(
    {"spatial", "environment-assets", "trainers", "encounters"}
)
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
    "trainerPolicy",
    "expectedTrainerInventory",
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
    "excludePaths",
}
INVENTORY_DOMAINS = {"maps", "layouts", "groups", "sections", "tilesets"}
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
    "contentFallback",
    "retainedEdges",
    "deferredEdges",
    "graphicsAdaptations",
    "musicAdaptations",
    "tilesetAdaptations",
    "trainerPresentation",
    "warpReindexes",
    "warpRemovals",
    "berryTreeAllocations",
    "materializationProfile",
    "worldPolicy",
    "donorFieldRoles",
    "layoutBinaryAuthorities",
    "layoutFieldAuthorities",
    "generatedSections",
    "sectionMetadataAuthorities",
    "targetBindings",
    "encounterProfiles",
    "encounterTimePolicy",
}
LEGACY_MIGRATION_KEYS = {
    "addedPaths",
    "assets",
    "authorityChanges",
    "changedPaths",
    "decision",
    "donor",
    "from",
    "predecessor",
    "policy",
    "removedPaths",
    "repository",
    "schemaVersion",
    "tests",
    "to",
}
MIGRATION_KEYS = LEGACY_MIGRATION_KEYS | {
    "publicationPolicyDigest",
    "publicationPolicySnapshot",
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
    "layoutFieldAuthorities",
    "generatedSections",
    "sectionMetadataAuthorities",
    "targetBindings",
}
GENERATED_AUTHORITY_CONTRACT = MappingProxyType(
    {
        "map-scripts": ("allocation-lock", "target-contract"),
        "berry-bindings": ("persistence-ledger", "port-policy"),
        "flag-bindings": ("persistence-ledger", "target-contract"),
        "trainer-bindings": ("persistence-ledger", "port-policy"),
        "var-bindings": ("persistence-ledger", "target-contract"),
        "tileset-externs": ("port-policy", "target-contract"),
        "tileset-graphics": ("port-policy", "target-contract"),
        "tileset-headers": ("port-policy", "target-contract"),
        "tileset-metatiles": ("port-policy", "target-contract"),
        "trainer-parties": ("port-policy",),
    }
)


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


def _boolean(value: object, pointer: str) -> bool:
    if not isinstance(value, bool):
        raise ContentPortError(f"{pointer}: expected a boolean")
    return value


def _string_array(value: object, pointer: str) -> tuple[str, ...]:
    return tuple(
        _string(item, f"{pointer}[{index}]")
        for index, item in enumerate(_array(value, pointer))
    )


def _policy_record(
    value: object,
    pointer: str,
    required: set[str],
    optional: set[str] | None = None,
) -> Mapping[str, Any]:
    item = _object(value, pointer)
    allowed = required | (optional or set())
    unknown = sorted(set(item) - allowed)
    missing = sorted(required - set(item))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")
    return item


def _policy_records(
    document: Mapping[str, Any],
    field: str,
    pointer: str,
    required: set[str],
    optional: set[str] | None = None,
) -> tuple[tuple[Mapping[str, Any], str], ...]:
    family_pointer = f"{pointer}.{field}"
    return tuple(
        (
            _policy_record(
                raw,
                f"{family_pointer}[{index}]",
                required,
                optional,
            ),
            f"{family_pointer}[{index}]",
        )
        for index, raw in enumerate(_array(document[field], family_pointer))
    )


def _unique_policy_records(
    document: Mapping[str, Any],
    family: str,
    pointer: str,
    identity_fields: tuple[str, ...],
) -> None:
    seen: dict[tuple[object, ...], str] = {}
    family_pointer = f"{pointer}.{family}"
    for index, raw in enumerate(_array(document[family], family_pointer)):
        item = _object(raw, f"{family_pointer}[{index}]")
        identity = tuple(item[field] for field in identity_fields)
        item_pointer = f"{family_pointer}[{index}]"
        if identity in seen:
            label = "/".join(identity_fields)
            raise ContentPortError(
                f"{item_pointer}.{identity_fields[-1]}: duplicate {label} identity; "
                f"first declared at {seen[identity]}"
            )
        seen[identity] = item_pointer


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


def _validate_adaptation_policy(value: object, pointer: str) -> None:
    document = _object(value, pointer)
    _exact_keys(document, ADAPTATION_KEYS, pointer)
    if _integer(document["schemaVersion"], f"{pointer}.schemaVersion") != 1:
        raise ContentPortError(
            f"{pointer}.schemaVersion: unsupported adaptation schema"
        )

    donor_pointer = f"{pointer}.donorFieldRoles"
    donor_fields = _object(document["donorFieldRoles"], donor_pointer)
    _exact_keys(donor_fields, {"content", "mechanical"}, donor_pointer)
    for role in ("content", "mechanical"):
        _string(donor_fields[role], f"{donor_pointer}.{role}")
    policy_fields = set(donor_fields.values())
    if len(policy_fields) != len(donor_fields):
        raise ContentPortError(
            f"{donor_pointer}: donor policy field names must be unique"
        )
    content_field = donor_fields["content"]

    encounter_profile_fields = {"map", "label", "habitat", "authority", "time"}
    encounter_profiles = _policy_records(
        document,
        "encounterProfiles",
        pointer,
        encounter_profile_fields,
    )
    encounter_identities: set[str] = set()
    for item, item_pointer in encounter_profiles:
        for field in encounter_profile_fields:
            _string(item[field], f"{item_pointer}.{field}")
        if item["authority"] not in donor_fields:
            raise ContentPortError(
                f"{item_pointer}.authority: unknown donor role {item['authority']!r}"
            )
        if item["habitat"] != "land_mons":
            raise ContentPortError(
                f"{item_pointer}.habitat: only land_mons is currently materialized"
            )
        if item["time"] not in {"TIME_DAY", "TIME_NIGHT"}:
            raise ContentPortError(
                f"{item_pointer}.time: expected TIME_DAY or TIME_NIGHT"
            )
        if item["label"] in encounter_identities:
            raise ContentPortError(
                f"{item_pointer}.label: duplicate encounter profile identity"
            )
        encounter_identities.add(item["label"])

    time_records = _policy_records(
        document,
        "encounterTimePolicy",
        pointer,
        {"map", "dayStart", "nightStart", "dayLabel", "nightLabel", "fallbackLabel"},
    )
    if len(time_records) > 1 or bool(encounter_profiles) != bool(time_records):
        raise ContentPortError(
            f"{pointer}.encounterTimePolicy: expected exactly one policy for authored profiles"
        )
    if time_records:
        time_policy, time_pointer = time_records[0]
        for field in time_policy:
            _string(time_policy[field], f"{time_pointer}.{field}")
        if time_policy["dayStart"] != "06:00" or time_policy["nightStart"] != "18:00":
            raise ContentPortError(
                f"{time_pointer}: target policy must select day from 06:00 through 17:59"
            )
        labels_by_time = {
            item["time"]: item["label"]
            for item, _ in encounter_profiles
            if item["map"] == time_policy["map"]
        }
        if (
            labels_by_time
            != {
                "TIME_DAY": time_policy["dayLabel"],
                "TIME_NIGHT": time_policy["nightLabel"],
            }
            or time_policy["fallbackLabel"] != time_policy["dayLabel"]
        ):
            raise ContentPortError(
                f"{time_pointer}: day, night, and fallback labels do not match profiles"
            )

    for item, item_pointer in _policy_records(
        document,
        "adaptations",
        pointer,
        {"source", "path", "reason"} | policy_fields,
    ):
        for field in {"source", "path", "reason"} | policy_fields:
            _string(item[field], f"{item_pointer}.{field}")

    for family, identity_field in (
        ("layoutHeaderDecisions", "layout"),
        ("mapFieldDecisions", "map"),
    ):
        for item, item_pointer in _policy_records(
            document,
            family,
            pointer,
            {identity_field, "field", "authority"} | policy_fields,
        ):
            for field in {identity_field, "field", "authority"} | policy_fields:
                _string(item[field], f"{item_pointer}.{field}")
            if item["authority"] not in donor_fields:
                raise ContentPortError(
                    f"{item_pointer}.authority: unknown donor role "
                    f"{item['authority']!r}"
                )

    string_record_families = {
        "sectionSymbolRemaps": {"source", "target", "reason"},
        "layoutTilesetRemaps": {"layout", "field", "source", "target"},
        "retainedEdges": {"source", "path", "kind", "destination"},
        "deferredEdges": {"source", "path", "kind", "destination"},
        "musicAdaptations": {content_field, "target"},
        "warpRemovals": {
            "source",
            "path",
            "destination",
            "destWarpId",
            "reason",
        },
        "berryTreeAllocations": {"source", "path", content_field, "target"},
    }
    for family, fields in string_record_families.items():
        for item, item_pointer in _policy_records(document, family, pointer, fields):
            for field in fields:
                _string(item[field], f"{item_pointer}.{field}")
            if family in {"retainedEdges", "deferredEdges"} and item["kind"] not in {
                "connection",
                "warp",
            }:
                raise ContentPortError(
                    f"{item_pointer}.kind: expected 'connection' or 'warp'"
                )

    fixture_fields = {
        "representative",
        "layout",
        "role",
        "tileset",
        "metatiles",
        "attributes",
        "metatilesSha256",
        "attributesSha256",
        "format",
        "authority",
    }
    for item, item_pointer in _policy_records(
        document, "attributeFixtures", pointer, fixture_fields
    ):
        for field in fixture_fields:
            _string(item[field], f"{item_pointer}.{field}")
        for field in ("metatilesSha256", "attributesSha256"):
            if not DIGEST_RE.fullmatch(item[field]):
                raise ContentPortError(
                    f"{item_pointer}.{field}: expected 64 lowercase hex"
                )
        if item["role"] not in {"primary", "secondary"}:
            raise ContentPortError(
                f"{item_pointer}.role: expected 'primary' or 'secondary'"
            )
        if item["authority"] not in policy_fields:
            raise ContentPortError(
                f"{item_pointer}.authority: unknown donor policy field "
                f"{item['authority']!r}"
            )

    fallback_pointer = f"{pointer}.contentFallback"
    fallback = _policy_record(
        document["contentFallback"],
        fallback_pointer,
        {"authority", "reason", "maps"},
    )
    _string(fallback["authority"], f"{fallback_pointer}.authority")
    _string(fallback["reason"], f"{fallback_pointer}.reason")
    _string_array(fallback["maps"], f"{fallback_pointer}.maps")

    for item, item_pointer in _policy_records(
        document,
        "graphicsAdaptations",
        pointer,
        {content_field, "target"},
        {"reason"},
    ):
        for field in set(item):
            _string(item[field], f"{item_pointer}.{field}")

    tileset_required = {
        "role",
        "directory",
        "symbol",
        "secondary",
        "paletteCount",
        "authority",
    }
    tileset_aliases = {"targetDirectory", "targetSymbol", "animationCallback"}
    tileset_target_aliases = {"targetDirectory", "targetSymbol"}
    seen_tilesets: dict[str, str] = {}
    for item, item_pointer in _policy_records(
        document,
        "tilesetAdaptations",
        pointer,
        tileset_required,
        tileset_aliases,
    ):
        for field in ("role", "directory", "symbol", "authority"):
            _string(item[field], f"{item_pointer}.{field}")
        present_aliases = set(item) & tileset_aliases
        present_target_aliases = present_aliases & tileset_target_aliases
        if present_target_aliases and present_target_aliases != tileset_target_aliases:
            missing = sorted(tileset_target_aliases - present_target_aliases)
            raise ContentPortError(f"{item_pointer}: missing field {missing[0]!r}")
        for field in present_aliases:
            _string(item[field], f"{item_pointer}.{field}")
        effective_symbol = item.get("targetSymbol", item["symbol"])
        if effective_symbol in seen_tilesets:
            identity_field = "targetSymbol" if "targetSymbol" in item else "symbol"
            raise ContentPortError(
                f"{item_pointer}.{identity_field}: duplicate rendered tileset identity; "
                f"first declared at {seen_tilesets[effective_symbol]}"
            )
        seen_tilesets[effective_symbol] = item_pointer
        secondary = _boolean(item["secondary"], f"{item_pointer}.secondary")
        _integer(item["paletteCount"], f"{item_pointer}.paletteCount", positive=True)
        expected_secondary = item["role"] == "secondary"
        if item["role"] not in {"primary", "secondary"}:
            raise ContentPortError(
                f"{item_pointer}.role: expected 'primary' or 'secondary'"
            )
        if secondary != expected_secondary:
            raise ContentPortError(
                f"{item_pointer}.secondary: must match the tileset role"
            )
        if item["authority"] not in policy_fields:
            raise ContentPortError(
                f"{item_pointer}.authority: unknown donor policy field "
                f"{item['authority']!r}"
            )

    trainer_fields = {
        "id",
        "name",
        "class",
        "pic",
        "gender",
        "music",
        "battleType",
        "species",
        "level",
        "ivs",
    }
    for item, item_pointer in _policy_records(
        document, "trainerPresentation", pointer, trainer_fields
    ):
        for field in trainer_fields - {"level"}:
            _string(item[field], f"{item_pointer}.{field}")
        _integer(item["level"], f"{item_pointer}.level", positive=True)

    for item, item_pointer in _policy_records(
        document, "warpReindexes", pointer, {"source", "path", "to"}
    ):
        _string(item["source"], f"{item_pointer}.source")
        _string(item["path"], f"{item_pointer}.path")
        target = item["to"]
        if isinstance(target, str):
            _string(target, f"{item_pointer}.to")
        else:
            _integer(target, f"{item_pointer}.to")

    profile_pointer = f"{pointer}.materializationProfile"
    profile = _policy_record(
        document["materializationProfile"],
        profile_pointer,
        {"mapScripts", "stripEventKinds"},
    )
    map_scripts = _string(profile["mapScripts"], f"{profile_pointer}.mapScripts")
    if map_scripts not in {"empty", "selected-trainers"}:
        raise ContentPortError(
            f"{profile_pointer}.mapScripts: unsupported map script profile"
        )
    strip_event_kinds = _string_array(
        profile["stripEventKinds"], f"{profile_pointer}.stripEventKinds"
    )
    unknown_event_kinds = sorted(
        set(strip_event_kinds) - set(MATERIALIZATION_STRIP_EVENT_KINDS)
    )
    if unknown_event_kinds:
        raise ContentPortError(
            f"{profile_pointer}.stripEventKinds: unsupported event kind "
            f"{unknown_event_kinds[0]!r}"
        )
    if strip_event_kinds != MATERIALIZATION_STRIP_EVENT_KINDS:
        raise ContentPortError(
            f"{profile_pointer}.stripEventKinds: must exactly strip "
            f"{list(MATERIALIZATION_STRIP_EVENT_KINDS)!r}"
        )

    world_pointer = f"{pointer}.worldPolicy"
    world = _policy_record(
        document["worldPolicy"],
        world_pointer,
        {
            "roots",
            "unreachableShells",
            "gateways",
            "dynamicWarps",
            "scriptWarps",
        },
    )
    _string_array(world["roots"], f"{world_pointer}.roots")
    _string_array(world["unreachableShells"], f"{world_pointer}.unreachableShells")
    gateway_fields = {
        "source",
        "destination",
        "kind",
        "index",
        "sourceRegion",
        "targetRegion",
    }
    for index, raw in enumerate(_array(world["gateways"], f"{world_pointer}.gateways")):
        item_pointer = f"{world_pointer}.gateways[{index}]"
        item = _policy_record(raw, item_pointer, gateway_fields)
        for field in gateway_fields - {"index"}:
            _string(item[field], f"{item_pointer}.{field}")
        if item["kind"] not in {"connection", "warp"}:
            raise ContentPortError(
                f"{item_pointer}.kind: must be 'connection' or 'warp'"
            )
        _integer(item["index"], f"{item_pointer}.index")

    script_warp_fields = {
        "source",
        "destination",
        "script",
        "label",
        "command",
        "index",
        "x",
        "y",
        "sourceRegion",
        "targetRegion",
    }
    script_warp_pointer = f"{world_pointer}.scriptWarps"
    for index, raw in enumerate(_array(world["scriptWarps"], script_warp_pointer)):
        item_pointer = f"{script_warp_pointer}[{index}]"
        item = _policy_record(raw, item_pointer, script_warp_fields)
        for field in script_warp_fields - {"index", "x", "y"}:
            _string(item[field], f"{item_pointer}.{field}")
        if item["command"] not in {"warp", "warpsilent"}:
            raise ContentPortError(
                f"{item_pointer}.command: must be 'warp' or 'warpsilent'"
            )
        for field in ("index", "x", "y"):
            value = _integer(item[field], f"{item_pointer}.{field}")
            if value < 0:
                raise ContentPortError(f"{item_pointer}.{field}: must be non-negative")

    dynamic_warp_pointer = f"{world_pointer}.dynamicWarps"
    for index, raw in enumerate(_array(world["dynamicWarps"], dynamic_warp_pointer)):
        item_pointer = f"{dynamic_warp_pointer}[{index}]"
        item = _policy_record(
            raw,
            item_pointer,
            {"source", "index", "token", "sourceOwnership", "destinations"},
        )
        _string(item["source"], f"{item_pointer}.source")
        _integer(item["index"], f"{item_pointer}.index")
        _string(item["token"], f"{item_pointer}.token")
        _string(item["sourceOwnership"], f"{item_pointer}.sourceOwnership")
        option_fields = {
            "destination",
            "x",
            "y",
            "armingSource",
            "script",
            "label",
            "index",
            "immediateDestination",
            "immediateCommand",
            "immediateIndex",
            "immediateX",
            "immediateY",
            "sourceRegion",
            "targetRegion",
            "armingRegion",
            "destinationOwnership",
            "armingOwnership",
        }
        options = _array(item["destinations"], f"{item_pointer}.destinations")
        if not options:
            raise ContentPortError(
                f"{item_pointer}.destinations: must contain at least one destination"
            )
        seen_options: set[tuple[object, ...]] = set()
        for option_index, raw_option in enumerate(options):
            option_pointer = f"{item_pointer}.destinations[{option_index}]"
            option = _policy_record(raw_option, option_pointer, option_fields)
            for field in option_fields - {
                "x",
                "y",
                "index",
                "immediateIndex",
                "immediateX",
                "immediateY",
            }:
                _string(option[field], f"{option_pointer}.{field}")
            if option["immediateCommand"] not in {"warp", "warpsilent"}:
                raise ContentPortError(
                    f"{option_pointer}.immediateCommand: must be 'warp' or 'warpsilent'"
                )
            for field in (
                "x",
                "y",
                "index",
                "immediateIndex",
                "immediateX",
                "immediateY",
            ):
                if _integer(option[field], f"{option_pointer}.{field}") < 0:
                    raise ContentPortError(
                        f"{option_pointer}.{field}: must be non-negative"
                    )
            identity = tuple(option[field] for field in sorted(option_fields))
            if identity in seen_options:
                raise ContentPortError(
                    f"{option_pointer}.index: duplicate dynamic destination identity"
                )
            seen_options.add(identity)

    unique_families = {
        "adaptations": ("source", "path"),
        "layoutHeaderDecisions": ("layout", "field"),
        "mapFieldDecisions": ("map", "field"),
        "sectionSymbolRemaps": ("source",),
        "layoutTilesetRemaps": ("layout", "field"),
        "attributeFixtures": ("representative",),
        "retainedEdges": ("source", "path"),
        "deferredEdges": ("source", "path"),
        "graphicsAdaptations": (content_field,),
        "musicAdaptations": (content_field,),
        "trainerPresentation": ("id",),
        "warpReindexes": ("source", "path"),
        "warpRemovals": ("source", "path"),
        "berryTreeAllocations": ("source", "path"),
    }
    for family, identity_fields in unique_families.items():
        _unique_policy_records(document, family, pointer, identity_fields)
    classified_edges: dict[tuple[object, object], str] = {}
    for family in ("retainedEdges", "deferredEdges"):
        for index, raw in enumerate(document[family]):
            item = _object(raw, f"{pointer}.{family}[{index}]")
            identity = (item["source"], item["path"])
            item_pointer = f"{pointer}.{family}[{index}]"
            if identity in classified_edges:
                raise ContentPortError(
                    f"{item_pointer}.path: edge is already classified at "
                    f"{classified_edges[identity]}"
                )
            classified_edges[identity] = item_pointer

    transform_paths: dict[tuple[object, object], str] = {}
    for family in (
        "adaptations",
        "warpReindexes",
        "warpRemovals",
        "berryTreeAllocations",
    ):
        for index, raw in enumerate(document[family]):
            item = _object(raw, f"{pointer}.{family}[{index}]")
            identity = (item["source"], item["path"])
            item_pointer = f"{pointer}.{family}[{index}]"
            if identity in transform_paths:
                raise ContentPortError(
                    f"{item_pointer}.path: transform path is already declared at "
                    f"{transform_paths[identity]}"
                )
            transform_paths[identity] = item_pointer

    for family, values, identity_fields in (
        ("gateways", world["gateways"], ("source", "kind", "index")),
        ("dynamicWarps", world["dynamicWarps"], ("source", "index")),
        (
            "scriptWarps",
            world["scriptWarps"],
            ("source", "script", "label", "index"),
        ),
    ):
        seen: dict[tuple[object, ...], str] = {}
        for index, raw in enumerate(values):
            item = _object(raw, f"{world_pointer}.{family}[{index}]")
            identity = tuple(item[field] for field in identity_fields)
            item_pointer = f"{world_pointer}.{family}[{index}]"
            if identity in seen:
                raise ContentPortError(
                    f"{item_pointer}.{identity_fields[-1]}: duplicate world edge "
                    f"identity; first declared at {seen[identity]}"
                )
            seen[identity] = item_pointer


def _validate_encounter_profile_reachability(
    adaptations: Mapping[str, object],
    capabilities: tuple[CapabilityDecision, ...],
    pointer: str = "$",
) -> None:
    profiles = _array(adaptations["encounterProfiles"], f"{pointer}.encounterProfiles")
    profile_labels = {
        _string(
            _object(raw, f"{pointer}.encounterProfiles[{index}]")["label"],
            f"{pointer}.encounterProfiles[{index}].label",
        )
        for index, raw in enumerate(profiles)
    }
    dependency_maps: dict[str, str] = {}
    for decision in capabilities:
        if (
            decision.capability != "encounters"
            or decision.state is not CapabilityState.ENABLED
        ):
            continue
        for dependency in decision.dependencies:
            if dependency.domain != "encounter":
                continue
            previous = dependency_maps.setdefault(dependency.name, decision.map_name)
            if previous != decision.map_name:
                raise ContentPortError(
                    f"{pointer}.encounterProfiles: encounter dependency "
                    f"{dependency.name!r} is reachable from multiple maps"
                )
    dependency_labels = set(dependency_maps)
    policies = _array(
        adaptations["encounterTimePolicy"], f"{pointer}.encounterTimePolicy"
    )
    policy_labels = {
        label
        for index, raw in enumerate(policies)
        for label in (
            _string(
                _object(raw, f"{pointer}.encounterTimePolicy[{index}]")["dayLabel"],
                f"{pointer}.encounterTimePolicy[{index}].dayLabel",
            ),
            _string(
                _object(raw, f"{pointer}.encounterTimePolicy[{index}]")["nightLabel"],
                f"{pointer}.encounterTimePolicy[{index}].nightLabel",
            ),
        )
    }
    if profile_labels != dependency_labels or profile_labels != policy_labels:
        raise ContentPortError(
            f"{pointer}.encounterProfiles: labels must exactly match enabled "
            "encounter dependencies and reviewed time-policy labels"
        )
    for index, raw in enumerate(profiles):
        item = _object(raw, f"{pointer}.encounterProfiles[{index}]")
        label = _string(item["label"], f"{pointer}.encounterProfiles[{index}].label")
        map_name = _string(item["map"], f"{pointer}.encounterProfiles[{index}].map")
        if dependency_maps[label] != map_name:
            raise ContentPortError(
                f"{pointer}.encounterProfiles[{index}].map: does not match enabled "
                "encounter dependency owner"
            )


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
    trainer_policy_path: Path
    expected_trainer_inventory: Mapping[str, object]
    allocation_index: AllocationIndex
    capabilities: tuple[CapabilityDecision, ...]
    map_ownership: Mapping[str, str]
    adaptations: Mapping[str, object]
    events: Mapping[str, object]
    event_entries: Mapping[str, EventEntry]
    effect_policy: Mapping[EffectKey, str]
    event_policy_path: Path
    assets: Mapping[str, object]
    animations: Mapping[str, object]
    legacy_report: Mapping[str, object] | None
    layout_binary_authorities: tuple[LayoutBinaryAuthority, ...]
    layout_field_authorities: tuple[LayoutFieldAuthority, ...]
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
    from .update import (
        _validated_migrations_dir,
        migration_digest,
        validate_reviewed_migration,
    )

    migrations = port_dir / "migrations"
    if migrations.exists() or migrations.is_symlink():
        try:
            migrations = _validated_migrations_dir(port_dir, create=False)
        except ContentPortError as error:
            raise ContentPortError(str(error)) from error

    def validate_link(
        link: str,
        expected_target: tuple[str, str, int],
        seen: frozenset[str],
        *,
        live_policy: bool,
    ) -> None:
        if link in seen:
            raise ContentPortError(f"donor {donor}: migration predecessor cycle")
        path = migrations / f"{link}.json"
        if path.is_symlink():
            raise ContentPortError(
                f"{path}: migration record must not be a symbolic link"
            )
        report = _object(read_json(path), f"migration:{link}")
        schema_version = report.get("schemaVersion")
        if schema_version == 1:
            _exact_keys(report, LEGACY_MIGRATION_KEYS, f"migration:{link}")
        elif schema_version == 2:
            _exact_keys(report, MIGRATION_KEYS, f"migration:{link}")
        else:
            raise ContentPortError(
                f"migration:{link}.schemaVersion: unsupported migration schema"
            )
        if migration_digest(report) != link:
            raise ContentPortError(f"migration record filename is stale: {path}")
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
            validate_link(predecessor, source, seen | {link}, live_policy=False)
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
            validate_live_publication_policy=live_policy,
        )

    validate_link(
        digest, (commit, tree_digest, file_count), frozenset(), live_policy=True
    )


def _load_donors(
    value: object,
    donor_checkouts: Mapping[str, Path],
    port_dir: Path,
    pointer: str,
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
        excluded_values = _array(item["excludePaths"], f"{item_pointer}.excludePaths")
        excluded_paths = tuple(
            _string(value, f"{item_pointer}.excludePaths[{index}]")
            for index, value in enumerate(excluded_values)
        )
        validate_excluded_paths(excluded_paths)
        if excluded_paths != tuple(sorted(excluded_paths)):
            raise ContentPortError(
                f"{item_pointer}.excludePaths: expected sorted exact paths"
            )
        genesis = _migration_pin(item["genesis"], f"{item_pointer}.genesis")
        checkout = donor_checkouts[role]
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
            excluded_paths=excluded_paths,
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
    tuple[LayoutFieldAuthority, ...],
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

    layout_field_records: list[LayoutFieldAuthority] = []
    allowed_layout_fields = {"border_height", "border_width"}
    for index, raw in enumerate(
        _array(document["layoutFieldAuthorities"], f"{pointer}.layoutFieldAuthorities")
    ):
        item_pointer = f"{pointer}.layoutFieldAuthorities[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, {"field", "layoutRole", "sourceRole"}, item_pointer)
        record = LayoutFieldAuthority(
            field=_string(item["field"], f"{item_pointer}.field"),
            layout_role=_string(item["layoutRole"], f"{item_pointer}.layoutRole"),
            source_role=_string(item["sourceRole"], f"{item_pointer}.sourceRole"),
        )
        if record.field not in allowed_layout_fields:
            raise ContentPortError(
                f"{item_pointer}.field: unsupported layout field {record.field!r}"
            )
        for field, role in (
            ("layoutRole", record.layout_role),
            ("sourceRole", record.source_role),
        ):
            if role not in donor_roles:
                raise ContentPortError(
                    f"{item_pointer}.{field}: unknown donor role {role!r}"
                )
        if record.layout_role == record.source_role:
            raise ContentPortError(
                f"{item_pointer}: layout and field source roles must differ"
            )
        layout_field_records.append(record)
    layout_field_keys = [
        (record.layout_role, record.field) for record in layout_field_records
    ]
    if len(layout_field_keys) != len(set(layout_field_keys)):
        raise ContentPortError(
            f"{pointer}.layoutFieldAuthorities: duplicate layout-role field"
        )
    if {record.field for record in layout_field_records} != allowed_layout_fields:
        missing = sorted(
            allowed_layout_fields - {record.field for record in layout_field_records}
        )
        raise ContentPortError(
            f"{pointer}.layoutFieldAuthorities: missing field {missing[0]!r}"
        )

    generated_records: list[GeneratedSectionPolicy] = []
    for index, raw in enumerate(
        _array(document["generatedSections"], f"{pointer}.generatedSections")
    ):
        item_pointer = f"{pointer}.generatedSections[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, {"authorities", "key", "path", "sourceSymbol"}, item_pointer)
        source_symbol = _string(item["sourceSymbol"], f"{item_pointer}.sourceSymbol")
        if source_symbol not in GENERATED_AUTHORITY_CONTRACT:
            raise ContentPortError(
                f"{item_pointer}.sourceSymbol: unknown generated source"
            )
        authorities = tuple(
            _string(value, f"{item_pointer}.authorities[{authority_index}]")
            for authority_index, value in enumerate(
                _array(item["authorities"], f"{item_pointer}.authorities")
            )
        )
        expected_authorities = GENERATED_AUTHORITY_CONTRACT[source_symbol]
        if authorities != expected_authorities:
            raise ContentPortError(
                f"{item_pointer}.authorities: must exactly match generated source contract"
            )
        record = GeneratedSectionPolicy(
            key=_string(item["key"], f"{item_pointer}.key"),
            path=_relative_path(item["path"], f"{item_pointer}.path"),
            source_symbol=source_symbol,
            authorities=authorities,
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
    if set(record.source_symbol for record in generated_records) != set(
        GENERATED_AUTHORITY_CONTRACT
    ):
        missing = sorted(
            set(GENERATED_AUTHORITY_CONTRACT)
            - {record.source_symbol for record in generated_records}
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
        tuple(sorted(layout_field_records)),
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
    if port_dir.name == "johto" and "animationPolicy" not in root:
        raise ContentPortError("$.animationPolicy: required for the Johto port")
    present_port_keys = (
        PORT_KEYS if "legacyReport" in root else PORT_KEYS - {"legacyReport"}
    )
    if "animationPolicy" in root:
        present_port_keys = present_port_keys | {"animationPolicy"}
    _exact_keys(root, present_port_keys, "$")
    if root["schemaVersion"] != 1:
        raise ContentPortError("$.schemaVersion: unsupported port schema")
    forbid_numeric_policy(
        {key: value for key, value in root.items() if key != "allocationLock"}
    )
    donor_checkouts = validated_donor_checkouts(root, donor_root)

    allocation_path = _safe_child(port_dir, root["allocationLock"], "$.allocationLock")
    allocation_index = load_allocation_index(read_json(allocation_path))
    trainer_policy_path = _safe_child(
        port_dir, root["trainerPolicy"], "$.trainerPolicy"
    )
    trainer_inventory = _object(
        root["expectedTrainerInventory"], "$.expectedTrainerInventory"
    )
    _exact_keys(
        trainer_inventory,
        {
            "identities",
            "events",
            "documentDigest",
            "identityClassifications",
            "admittedIdentities",
            "admittedEvents",
            "affectedAdmittedMaps",
        },
        "$.expectedTrainerInventory",
    )
    expected_trainer_inventory: dict[str, object] = {}
    for domain in ("identities", "events"):
        pointer = f"$.expectedTrainerInventory.{domain}"
        sentinel = _object(trainer_inventory[domain], pointer)
        _exact_keys(sentinel, {"count", "digest"}, pointer)
        count = _integer(sentinel["count"], f"{pointer}.count", positive=True)
        digest = _string(sentinel["digest"], f"{pointer}.digest")
        if not DIGEST_RE.fullmatch(digest):
            raise ContentPortError(f"{pointer}.digest: expected 64 lowercase hex")
        expected_trainer_inventory[domain] = MappingProxyType(
            {"count": count, "digest": digest}
        )
    document_digest = _string(
        trainer_inventory["documentDigest"],
        "$.expectedTrainerInventory.documentDigest",
    )
    if not DIGEST_RE.fullmatch(document_digest):
        raise ContentPortError(
            "$.expectedTrainerInventory.documentDigest: expected 64 lowercase hex"
        )
    expected_trainer_inventory["documentDigest"] = document_digest
    classification_pointer = "$.expectedTrainerInventory.identityClassifications"
    classifications = _object(
        trainer_inventory["identityClassifications"], classification_pointer
    )
    _exact_keys(
        classifications,
        {"ordinary", "story-controlled", "unsupported"},
        classification_pointer,
    )
    expected_trainer_inventory["identityClassifications"] = MappingProxyType(
        {
            classification: _integer(
                classifications[classification],
                f"{classification_pointer}.{classification}",
                positive=True,
            )
            for classification in ("ordinary", "story-controlled", "unsupported")
        }
    )
    for field in ("admittedIdentities", "admittedEvents", "affectedAdmittedMaps"):
        expected_trainer_inventory[field] = _integer(
            trainer_inventory[field],
            f"$.expectedTrainerInventory.{field}",
            positive=True,
        )
    capability_path = _safe_child(
        port_dir, root["capabilityPolicy"], "$.capabilityPolicy"
    )
    capability_doc = read_json(capability_path)
    forbid_numeric_policy(capability_doc)
    capabilities, ownership = _load_capabilities(capability_doc, "$")
    for decision in capabilities:
        if (
            decision.state is CapabilityState.ENABLED
            and decision.capability not in MATERIALIZED_CAPABILITIES
        ):
            raise ContentPortError(
                f"$.maps.{decision.map_name}.{decision.capability}: enabled capability "
                "is not materialized by the current render profile"
            )
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
    _validate_adaptation_policy(_thaw(adaptations), "$")
    _validate_encounter_profile_reachability(_thaw(adaptations), capabilities)
    event_path = _safe_child(port_dir, root["eventPolicy"], "$.eventPolicy")
    events = _load_policy(event_path, {"schemaVersion", "entries", "effects"}, "$")
    # Event semantics are part of the descriptor contract, not deferred until a
    # production render happens to enable an event capability.
    from .semantics import load_event_policy, validate_event_policy_capabilities

    event_entries, effect_policy = load_event_policy(event_path)
    validate_event_policy_capabilities(
        event_entries, effect_policy, capabilities, source=event_path
    )
    assets = _load_policy(
        _safe_child(port_dir, root["assetPolicy"], "$.assetPolicy"),
        {"schemaVersion", "permissionRecords", "assets"},
        "$",
    )
    # Asset policy has domain-specific field and permission validation in the
    # donor-governance module. Blocked entries remain loadable by design.
    from .update import validate_assets

    validate_assets(  # type: ignore[arg-type]
        _thaw(assets),
        evidence_root=next(
            (
                candidate
                for candidate in (port_dir, *port_dir.parents)
                if (candidate / ".git").exists()
            ),
            port_dir,
        ),
        require_redistributable=False,
    )
    asset_records = assets["assets"]
    if not isinstance(asset_records, tuple):
        raise ContentPortError("$.assets: expected an immutable array")
    declared_capabilities = {decision.capability for decision in capabilities}
    for index, raw in enumerate(asset_records):
        pointer = f"$.assets[{index}]"
        item = _object(_thaw(raw), pointer)
        capability = _string(item.get("capability"), f"{pointer}.capability")
        if capability not in declared_capabilities:
            raise ContentPortError(
                f"{pointer}.capability: unknown capability {capability!r}"
            )
        support_state = CapabilityState.parse(
            item.get("supportState"), f"{pointer}.supportState"
        )
        if support_state is not CapabilityState.ENABLED:
            raise ContentPortError(
                f"{pointer}.supportState: asset emission requires 'enabled'"
            )
    legacy = (
        _load_policy(
            _safe_child(port_dir, root["legacyReport"], "$.legacyReport"), None, "$"
        )
        if "legacyReport" in root
        else None
    )
    donors_by_role = _load_donors(root["donors"], donor_checkouts, port_dir, "$.donors")
    required_roles = {"content", "mechanical"}
    if not required_roles.issubset(donors_by_role):
        missing = sorted(required_roles - set(donors_by_role))
        raise ContentPortError(f"$.donors: missing authority donor role {missing[0]!r}")
    from .animations import load_animation_policy

    tileset_adaptations = adaptations["tilesetAdaptations"]
    assert isinstance(tileset_adaptations, tuple)
    resident_tilesets = {
        str(item["symbol"]) for item in tileset_adaptations if isinstance(item, Mapping)
    }
    resident_animation_contracts = {
        str(item["symbol"]): item
        for item in tileset_adaptations
        if isinstance(item, Mapping)
    }
    animations = (
        load_animation_policy(
            _safe_child(port_dir, root["animationPolicy"], "$.animationPolicy"),
            donor_root=donors_by_role["content"].root,
            target_root=(
                port_dir.parents[3]
                if (port_dir.parents[3] / "src/tileset_anims.c").is_file()
                else Path.cwd()
            ),
            resident_tilesets=resident_tilesets,
            resident_contracts=resident_animation_contracts,
        )
        if "animationPolicy" in root
        else MappingProxyType({})
    )
    (
        layout_binary_authorities,
        layout_field_authorities,
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
        trainer_policy_path=trainer_policy_path,
        expected_trainer_inventory=MappingProxyType(expected_trainer_inventory),
        allocation_index=allocation_index,
        capabilities=capabilities,
        map_ownership=ownership,
        adaptations=adaptations,
        events=events,
        event_entries=event_entries,
        effect_policy=effect_policy,
        event_policy_path=event_path,
        assets=assets,
        animations=animations,
        legacy_report=legacy,
        layout_binary_authorities=layout_binary_authorities,
        layout_field_authorities=layout_field_authorities,
        generated_sections=generated_sections,
        section_metadata_authorities=section_metadata_authorities,
        target_bindings=target_bindings,
    )
