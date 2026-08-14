"""Strict evidence contract for reviewed Johto ecology fallbacks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import ContentPortError


HNS_ECOLOGY_SOURCE = {
    "role": "ecology",
    "name": "Pokemon Heart & Soul",
    "repository": "PokemonHnS-Development/pokemonHnS",
    "commit": "751823abaf677020bcd72c45fe3e7cb2b8a576e4",
    "treeDigest": "6fc60f734085eb0ba6df3f68855cc8b91564499fb0f960eb2d7cffe3cc379703",
    "path": "src/data/wild_encounters.json",
}

PKMN_WORLD_SPATIAL_SOURCE = {
    "role": "spatial",
    "name": "PKMN-World",
    "repository": "evilchinesefood/PKMN-World",
    "commit": "d40affe26e58a20f445daad84af5e45be812e69f",
    "treeDigest": "6bca91e491e7e8304f9268aa41a4c9d629d50baa6d3150fe45d55632b6f4f762",
    "mapIndexPath": "data/maps/map_groups.json",
    "layoutIndexPath": "data/layouts/layouts.json",
}

EXPECTED_TARGETS = {
    "LakeOfRageLowTide": "MAP_LAKE_OF_RAGE_LOW_TIDE",
    "Route26North": "MAP_ROUTE26NORTH",
    "JohtoVictoryRoad_1F": "MAP_JOHTO_VICTORY_ROAD_1F",
    "JohtoVictoryRoad_B1F": "MAP_JOHTO_VICTORY_ROAD_B1F",
    "JohtoVictoryRoad_B2F": "MAP_JOHTO_VICTORY_ROAD_B2F",
}

EXPECTED_SOURCE_MAPS = {
    "LakeOfRageLowTide": "MAP_LAKE_OF_RAGE",
    "Route26North": "MAP_ROUTE26",
    "JohtoVictoryRoad_1F": "MAP_VICTORY_ROAD_1F",
    "JohtoVictoryRoad_B1F": "MAP_VICTORY_ROAD_B1F",
    "JohtoVictoryRoad_B2F": "MAP_VICTORY_ROAD_B2F",
}

EXPECTED_DOCUMENT_DIGEST = (
    "0f6e513798dcc18749ab86d1ccb7441408224dffd4fe60c314fc77532e03d8ac"
)

EXPECTED_SELECTIONS = {
    "LakeOfRageLowTide": (("gLakeOfRage", "gLakeOfRageLowTide", "day"),),
    "Route26North": (
        ("gRoute26", "gRoute26North", "day"),
        ("gRoute26_Night", "gRoute26North_Night", "night"),
    ),
    "JohtoVictoryRoad_1F": (
        ("gVictoryRoad_1F", "gJohtoVictoryRoad_1F", "day"),
        ("gVictoryRoad_1F_Night", "gJohtoVictoryRoad_1F_Night", "night"),
    ),
    "JohtoVictoryRoad_B1F": (
        ("gVictoryRoad_B1F", "gJohtoVictoryRoad_B1F", "day"),
        ("gVictoryRoad_B1F_Night", "gJohtoVictoryRoad_B1F_Night", "night"),
    ),
    "JohtoVictoryRoad_B2F": (
        ("gVictoryRoad_B2F", "gJohtoVictoryRoad_B2F", "day"),
        ("gVictoryRoad_B2F_Night", "gJohtoVictoryRoad_B2F_Night", "night"),
    ),
}

ROOT_KEYS = frozenset({"schemaVersion", "ecologySource", "spatialSource", "records"})
SOURCE_KEYS = frozenset(HNS_ECOLOGY_SOURCE)
SPATIAL_SOURCE_KEYS = frozenset(PKMN_WORLD_SPATIAL_SOURCE)
RECORD_KEYS = frozenset(
    {
        "targetMap",
        "targetName",
        "sourceMap",
        "profiles",
        "rationale",
        "spatialEvidence",
    }
)
PROFILE_KEYS = frozenset({"sourceLabel", "targetLabel", "condition"})
EVIDENCE_KEYS = frozenset(
    {"relationship", "targetMapPath", "sourceMapPath", "target", "source", "facts"}
)
LAYOUT_KEYS = frozenset(
    {
        "mapId",
        "layoutId",
        "regionMapSection",
        "width",
        "height",
        "primaryTileset",
        "secondaryTileset",
        "mapBinPath",
        "mapBinSha256",
    }
)
FACT_KEYS = frozenset({"kind", "value"})


def _mapping(value: object, pointer: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    return value


def _sequence(value: object, pointer: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContentPortError(f"{pointer}: expected an array")
    return value


def _exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], pointer: str
) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")


def _exact_value(actual: object, expected: object, pointer: str) -> None:
    if actual != expected:
        raise ContentPortError(
            f"{pointer}: does not match the pinned evidence contract"
        )


def _string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def _validate_layout(raw: object, pointer: str) -> Mapping[str, Any]:
    layout = _mapping(raw, pointer)
    _exact_keys(layout, LAYOUT_KEYS, pointer)
    for key in LAYOUT_KEYS:
        value = layout[key]
        if key in {"width", "height"}:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContentPortError(f"{pointer}.{key}: expected a positive integer")
        else:
            _string(value, f"{pointer}.{key}")
    return layout


def validate_fallback_document(document: object) -> None:
    """Validate the complete, pinned five-map fallback evidence document.

    This contract deliberately does not interpret or produce a runtime encounter
    schema. It only authorizes exact source-profile selections using independently
    pinned spatial evidence.
    """

    root = _mapping(document, "$")
    _exact_keys(root, ROOT_KEYS, "$")
    if type(root["schemaVersion"]) is not int or root["schemaVersion"] != 1:
        raise ContentPortError("$.schemaVersion: expected 1")

    ecology_source = _mapping(root["ecologySource"], "$.ecologySource")
    _exact_keys(ecology_source, SOURCE_KEYS, "$.ecologySource")
    _exact_value(ecology_source, HNS_ECOLOGY_SOURCE, "$.ecologySource")
    spatial_source = _mapping(root["spatialSource"], "$.spatialSource")
    _exact_keys(spatial_source, SPATIAL_SOURCE_KEYS, "$.spatialSource")
    _exact_value(spatial_source, PKMN_WORLD_SPATIAL_SOURCE, "$.spatialSource")

    records = _sequence(root["records"], "$.records")
    if len(records) != len(EXPECTED_TARGETS):
        raise ContentPortError("$.records: expected exactly five fallback targets")

    seen_targets: set[str] = set()
    seen_source_labels: set[str] = set()
    seen_target_labels: set[str] = set()
    for index, raw_record in enumerate(records):
        pointer = f"$.records[{index}]"
        record = _mapping(raw_record, pointer)
        _exact_keys(record, RECORD_KEYS, pointer)
        target_name = record["targetName"]
        if not isinstance(target_name, str) or target_name not in EXPECTED_TARGETS:
            raise ContentPortError(f"{pointer}.targetName: unexpected fallback target")
        if target_name in seen_targets:
            raise ContentPortError(f"{pointer}.targetName: duplicate fallback target")
        seen_targets.add(target_name)
        _exact_value(
            record["targetMap"], EXPECTED_TARGETS[target_name], f"{pointer}.targetMap"
        )

        expected_profiles = EXPECTED_SELECTIONS[target_name]
        profiles = _sequence(record["profiles"], f"{pointer}.profiles")
        if len(profiles) != len(expected_profiles):
            raise ContentPortError(
                f"{pointer}.profiles: incorrect day/night profile shape"
            )
        actual_profiles: list[tuple[object, object, object]] = []
        for profile_index, raw_profile in enumerate(profiles):
            profile_pointer = f"{pointer}.profiles[{profile_index}]"
            profile = _mapping(raw_profile, profile_pointer)
            _exact_keys(profile, PROFILE_KEYS, profile_pointer)
            source_label = _string(
                profile["sourceLabel"], f"{profile_pointer}.sourceLabel"
            )
            target_label = _string(
                profile["targetLabel"], f"{profile_pointer}.targetLabel"
            )
            condition = _string(profile["condition"], f"{profile_pointer}.condition")
            if condition not in {"day", "night"}:
                raise ContentPortError(
                    f"{profile_pointer}.condition: expected day or night"
                )
            if source_label in seen_source_labels:
                raise ContentPortError(
                    f"{profile_pointer}.sourceLabel: duplicate label"
                )
            if target_label in seen_target_labels:
                raise ContentPortError(
                    f"{profile_pointer}.targetLabel: duplicate label"
                )
            seen_source_labels.add(source_label)
            seen_target_labels.add(target_label)
            actual_profiles.append((source_label, target_label, condition))
        _exact_value(tuple(actual_profiles), expected_profiles, f"{pointer}.profiles")

        _exact_value(
            record["sourceMap"],
            EXPECTED_SOURCE_MAPS[target_name],
            f"{pointer}.sourceMap",
        )
        _string(record["rationale"], f"{pointer}.rationale")
        evidence = _mapping(record["spatialEvidence"], f"{pointer}.spatialEvidence")
        _exact_keys(evidence, EVIDENCE_KEYS, f"{pointer}.spatialEvidence")
        for evidence_key in ("relationship", "targetMapPath", "sourceMapPath"):
            _string(
                evidence[evidence_key],
                f"{pointer}.spatialEvidence.{evidence_key}",
            )
        _validate_layout(evidence["target"], f"{pointer}.spatialEvidence.target")
        _validate_layout(evidence["source"], f"{pointer}.spatialEvidence.source")
        facts = _sequence(evidence["facts"], f"{pointer}.spatialEvidence.facts")
        if not facts:
            raise ContentPortError(
                f"{pointer}.spatialEvidence.facts: expected evidence"
            )
        for fact_index, raw_fact in enumerate(facts):
            fact_pointer = f"{pointer}.spatialEvidence.facts[{fact_index}]"
            fact = _mapping(raw_fact, fact_pointer)
            _exact_keys(fact, FACT_KEYS, fact_pointer)
            _string(fact["kind"], f"{fact_pointer}.kind")

    if seen_targets != set(EXPECTED_TARGETS):
        missing = sorted(set(EXPECTED_TARGETS) - seen_targets)[0]
        raise ContentPortError(f"$.records: missing fallback target {missing!r}")

    # The digest protects every reviewed rationale and spatial value without
    # coupling this evidence-only module to the runtime encounter schema.
    try:
        encoded = json.dumps(
            root, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContentPortError("$: expected JSON-compatible evidence values") from error
    if hashlib.sha256(encoded).hexdigest() != EXPECTED_DOCUMENT_DIGEST:
        raise ContentPortError("$: does not match the pinned fallback evidence")
