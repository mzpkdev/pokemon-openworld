"""Schema-neutral contracts for reviewed Johto encounter ecology."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .errors import ContentPortError


COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
SPECIES_RE = re.compile(r"^SPECIES_[A-Z0-9_]+$")
CLASSIFICATION_KINDS = frozenset({"ordinary", "encounter-free", "special"})
CLASSIFICATION_KEYS = frozenset({"schemaVersion", "maps"})
SOURCE_KEYS = frozenset({"role", "name", "repository", "commit", "treeDigest", "path"})
ECOLOGY_KEYS = frozenset({"schemaVersion", "source", "records"})
PROFILE_KEYS = frozenset(
    {"sourceMap", "label", "condition", "provenanceSlice", "methods"}
)
METHOD_KEYS = frozenset({"method", "encounterRate", "slots"})
SLOT_KEYS = frozenset(
    {
        "index",
        "weight",
        "species",
        "observedMinLevel",
        "observedMaxLevel",
    }
)
PROVENANCE_SLICES = frozenset({"primary-johto-block", "supplemental-mixed-tail"})


def _mapping(value: object, pointer: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    return value


def _sequence(value: object, pointer: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContentPortError(f"{pointer}: expected an array")
    return value


def _exact_keys(
    value: Mapping[str, Any], expected: Iterable[str], pointer: str
) -> None:
    expected_set = frozenset(expected)
    unknown = sorted(set(value) - expected_set)
    missing = sorted(expected_set - set(value))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")


def _string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def _integer(value: object, pointer: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContentPortError(f"{pointer}: expected an integer >= {minimum}")
    return value


def _schema_version(document: Mapping[str, Any], pointer: str) -> None:
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise ContentPortError(f"{pointer}.schemaVersion: expected 1")


def _canonical_names(values: Iterable[str], pointer: str) -> tuple[str, ...]:
    names = tuple(values)
    for index, name in enumerate(names):
        _string(name, f"{pointer}[{index}]")
    if len(set(names)) != len(names):
        raise ContentPortError(f"{pointer}: canonical map names must be unique")
    return names


def validate_classification_document(
    document: object, canonical_maps: Iterable[str]
) -> None:
    """Validate the exhaustive classification in canonical resident-map order."""

    root = _mapping(document, "$")
    _exact_keys(root, CLASSIFICATION_KEYS, "$")
    _schema_version(root, "$")
    rows = _sequence(root["maps"], "$.maps")
    expected_maps = _canonical_names(canonical_maps, "canonicalMaps")
    actual_maps: list[str] = []
    for index, raw in enumerate(rows):
        pointer = f"$.maps[{index}]"
        row = _mapping(raw, pointer)
        if "kind" not in row:
            raise ContentPortError(f"{pointer}: missing field 'kind'")
        kind = _string(row["kind"], f"{pointer}.kind")
        if kind not in CLASSIFICATION_KINDS:
            raise ContentPortError(
                f"{pointer}.kind: unsupported classification {kind!r}"
            )
        expected_keys = (
            {"map", "kind", "owner"} if kind == "special" else {"map", "kind"}
        )
        _exact_keys(row, expected_keys, pointer)
        map_name = _string(row["map"], f"{pointer}.map")
        if kind == "special":
            _string(row["owner"], f"{pointer}.owner")
        actual_maps.append(map_name)

    duplicates = sorted(
        name for name in set(actual_maps) if actual_maps.count(name) > 1
    )
    if duplicates:
        raise ContentPortError(
            f"$.maps: duplicate classification for {duplicates[0]!r}"
        )
    if tuple(actual_maps) != expected_maps:
        missing = [name for name in expected_maps if name not in actual_maps]
        extra = [name for name in actual_maps if name not in expected_maps]
        if missing:
            raise ContentPortError(f"$.maps: missing canonical map {missing[0]!r}")
        if extra:
            raise ContentPortError(f"$.maps: unknown canonical map {extra[0]!r}")
        raise ContentPortError("$.maps: classifications must use canonical map order")


def stable_digest(value: object) -> str:
    """Return the canonical digest used for externally protected profile values."""

    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_source(
    raw: object, expected_source: Mapping[str, object]
) -> Mapping[str, Any]:
    source = _mapping(raw, "$.source")
    _exact_keys(source, SOURCE_KEYS, "$.source")
    normalized = {key: _string(source[key], f"$.source.{key}") for key in SOURCE_KEYS}
    if COMMIT_RE.fullmatch(normalized["commit"]) is None:
        raise ContentPortError(
            "$.source.commit: expected a lowercase 40-digit hex commit"
        )
    if DIGEST_RE.fullmatch(normalized["treeDigest"]) is None:
        raise ContentPortError(
            "$.source.treeDigest: expected a lowercase 64-digit hex digest"
        )
    if normalized != dict(expected_source):
        raise ContentPortError("$.source: does not match the authenticated donor pin")
    return source


def _donor_field_index(
    field_definitions: Iterable[object], pointer: str = "donor.fields"
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(field_definitions):
        field = _mapping(raw, f"{pointer}[{index}]")
        method = _string(field.get("type"), f"{pointer}[{index}].type")
        if method in result:
            raise ContentPortError(f"{pointer}: duplicate method definition {method!r}")
        result[method] = field
    return result


def normalize_donor_profile(
    encounter: object,
    field_definitions: Iterable[object],
    *,
    condition: str,
    provenance_slice: str,
) -> dict[str, object]:
    """Convert one authenticated donor encounter without dropping source slots."""

    raw = _mapping(encounter, "donor.encounter")
    source_map = _string(raw.get("map"), "donor.encounter.map")
    label = _string(raw.get("base_label"), "donor.encounter.base_label")
    condition = _string(condition, "condition")
    provenance_slice = _string(provenance_slice, "provenanceSlice")
    fields = _donor_field_index(field_definitions)
    methods: list[dict[str, object]] = []
    for method_name, field in fields.items():
        if method_name not in raw:
            continue
        donor_method = _mapping(raw[method_name], f"donor.encounter.{method_name}")
        encounter_rate = _integer(
            donor_method.get("encounter_rate"),
            f"donor.encounter.{method_name}.encounter_rate",
            minimum=0,
        )
        mons = _sequence(
            donor_method.get("mons"), f"donor.encounter.{method_name}.mons"
        )
        weights = _sequence(
            field.get("encounter_rates"), f"donor.fields.{method_name}.encounter_rates"
        )
        groups = field.get("groups", {})
        if not isinstance(groups, dict):
            raise ContentPortError(
                f"donor.fields.{method_name}.groups: expected an object"
            )
        group_by_index: dict[int, str] = {}
        for group_name, indexes in groups.items():
            group_name = _string(group_name, f"donor.fields.{method_name}.groups")
            for group_index in _sequence(
                indexes, f"donor.fields.{method_name}.groups.{group_name}"
            ):
                slot_index = _integer(
                    group_index,
                    f"donor.fields.{method_name}.groups.{group_name}",
                    minimum=0,
                )
                if slot_index in group_by_index:
                    raise ContentPortError(
                        f"donor.fields.{method_name}: slot {slot_index} has "
                        "multiple groups"
                    )
                group_by_index[slot_index] = group_name
        slots: list[dict[str, object]] = []
        for slot_index, mon_raw in enumerate(mons):
            mon = _mapping(mon_raw, f"donor.encounter.{method_name}.mons[{slot_index}]")
            slot: dict[str, object] = {
                "index": slot_index,
                "weight": weights[slot_index] if slot_index < len(weights) else None,
                "species": mon.get("species"),
                "observedMinLevel": mon.get("min_level"),
                "observedMaxLevel": mon.get("max_level"),
            }
            if method_name == "fishing_mons":
                slot["rodGroup"] = group_by_index.get(slot_index)
            slots.append(slot)
        methods.append(
            {
                "method": method_name,
                "encounterRate": encounter_rate,
                "slots": slots,
            }
        )
    return {
        "sourceMap": source_map,
        "label": label,
        "condition": condition,
        "provenanceSlice": provenance_slice,
        "methods": methods,
    }


def build_authenticated_profile_lookup(
    profiles: Iterable[Mapping[str, object]],
) -> dict[tuple[str, str, str], Mapping[str, object]]:
    """Index normalized donor profiles by their authored identity."""

    result: dict[tuple[str, str, str], Mapping[str, object]] = {}
    for index, profile in enumerate(profiles):
        key = tuple(
            _string(profile.get(field), f"profiles[{index}].{field}")
            for field in ("sourceMap", "label", "condition")
        )
        if key in result:
            raise ContentPortError(f"profiles[{index}]: duplicate donor profile key")
        result[key] = profile
    return result


def donor_profile_matches(
    authored: Mapping[str, object], authenticated: Mapping[str, object]
) -> bool:
    """Compare the complete normalized values, preserving order and multiplicity."""

    return authored == authenticated


def source_method_is_runtime_eligible(method: Mapping[str, object]) -> bool:
    """Identify observations that still need ecology review before runtime use."""

    if method.get("encounterRate") == 0:
        return False
    slots = method.get("slots")
    if not isinstance(slots, list) or not slots:
        return False
    return all(
        isinstance(slot, dict)
        and slot.get("weight") is not None
        and slot.get("species") != "SPECIES_NONE"
        for slot in slots
    )


def _validate_slot(
    raw: object,
    pointer: str,
    expected_index: int,
    method: str,
    supported_species: frozenset[str],
    after_defined_weights: bool,
) -> tuple[bool, bool]:
    slot = _mapping(raw, pointer)
    expected_keys = SLOT_KEYS
    if method == "fishing_mons" and "rodGroup" in slot:
        expected_keys |= {"rodGroup"}
    _exact_keys(slot, expected_keys, pointer)
    index = _integer(slot["index"], f"{pointer}.index", minimum=0)
    if index != expected_index:
        raise ContentPortError(
            f"{pointer}.index: expected ordered slot index {expected_index}"
        )
    weight = slot["weight"]
    if weight is None:
        after_defined_weights = True
    else:
        _integer(weight, f"{pointer}.weight", minimum=1)
        if after_defined_weights:
            raise ContentPortError(
                f"{pointer}.weight: defined weights cannot follow source-only slots"
            )
    species = _string(slot["species"], f"{pointer}.species")
    if SPECIES_RE.fullmatch(species) is None or species not in supported_species | {
        "SPECIES_NONE"
    }:
        raise ContentPortError(
            f"{pointer}.species: unsupported species token {species!r}"
        )
    minimum = _integer(
        slot["observedMinLevel"], f"{pointer}.observedMinLevel", minimum=1
    )
    maximum = _integer(
        slot["observedMaxLevel"], f"{pointer}.observedMaxLevel", minimum=1
    )
    if maximum > 100 or minimum > maximum:
        raise ContentPortError(
            f"{pointer}: expected 1 <= observedMinLevel <= observedMaxLevel <= 100"
        )
    if method == "fishing_mons":
        rod_group = slot.get("rodGroup")
        if weight is None:
            if rod_group is not None:
                raise ContentPortError(
                    f"{pointer}.rodGroup: source-only slots cannot name a rod group"
                )
        else:
            _string(rod_group, f"{pointer}.rodGroup")
    return (
        after_defined_weights,
        weight is None
        or species == "SPECIES_NONE"
        or method == "fishing_mons"
        and rod_group is None,
    )


def _validate_method(
    raw: object,
    pointer: str,
    supported_methods: frozenset[str],
    supported_species: frozenset[str],
) -> tuple[str, bool]:
    method = _mapping(raw, pointer)
    _exact_keys(method, METHOD_KEYS, pointer)
    name = _string(method["method"], f"{pointer}.method")
    if name not in supported_methods:
        raise ContentPortError(f"{pointer}.method: unsupported method {name!r}")
    encounter_rate = _integer(
        method["encounterRate"], f"{pointer}.encounterRate", minimum=0
    )
    slots = _sequence(method["slots"], f"{pointer}.slots")
    if not slots:
        raise ContentPortError(f"{pointer}.slots: expected at least one source slot")
    after_defined_weights = False
    has_source_anomaly = encounter_rate == 0
    for index, slot in enumerate(slots):
        after_defined_weights, slot_anomaly = _validate_slot(
            slot,
            f"{pointer}.slots[{index}]",
            index,
            name,
            supported_species,
            after_defined_weights,
        )
        has_source_anomaly |= slot_anomaly
    return name, has_source_anomaly


def _validate_profile(
    raw: object,
    pointer: str,
    authenticated_profiles: Mapping[tuple[str, str, str], object] | None,
    supported_methods: frozenset[str],
    supported_species: frozenset[str],
) -> tuple[tuple[str, str, str], bool]:
    profile = _mapping(raw, pointer)
    _exact_keys(profile, PROFILE_KEYS, pointer)
    source_map = _string(profile["sourceMap"], f"{pointer}.sourceMap")
    label = _string(profile["label"], f"{pointer}.label")
    condition = _string(profile["condition"], f"{pointer}.condition")
    provenance_slice = _string(profile["provenanceSlice"], f"{pointer}.provenanceSlice")
    if provenance_slice not in PROVENANCE_SLICES:
        raise ContentPortError(
            f"{pointer}.provenanceSlice: unsupported provenance slice"
        )
    methods = _sequence(profile["methods"], f"{pointer}.methods")
    if not methods:
        raise ContentPortError(f"{pointer}.methods: expected at least one method")
    method_results = [
        _validate_method(
            method,
            f"{pointer}.methods[{index}]",
            supported_methods,
            supported_species,
        )
        for index, method in enumerate(methods)
    ]
    method_names = [result[0] for result in method_results]
    if len(set(method_names)) != len(method_names):
        raise ContentPortError(f"{pointer}.methods: duplicate method")
    key = (source_map, label, condition)
    if authenticated_profiles is not None:
        if key not in authenticated_profiles:
            raise ContentPortError(f"{pointer}: donor profile is not authenticated")
        expected = authenticated_profiles[key]
        if not isinstance(expected, Mapping) or not donor_profile_matches(
            profile, expected
        ):
            raise ContentPortError(
                f"{pointer}: differs from authenticated donor values"
            )
    return key, any(result[1] for result in method_results)


def _review_notes(value: object, pointer: str) -> None:
    notes = _sequence(value, pointer)
    if not notes:
        raise ContentPortError(f"{pointer}: expected at least one review note")
    for index, note in enumerate(notes):
        _string(note, f"{pointer}[{index}]")


def validate_ecology_document(
    document: object,
    ordinary_maps: Iterable[str],
    authenticated_donor_profiles: Mapping[tuple[str, str, str], object] | None,
    *,
    source_identity: Mapping[str, object],
    supported_methods: Iterable[str],
    supported_species: Iterable[str],
    protected_route39_profile: object | str | None = None,
) -> None:
    """Validate reviewed source facts without interpreting runtime encounter bands."""

    root = _mapping(document, "$")
    _exact_keys(root, ECOLOGY_KEYS, "$")
    _schema_version(root, "$")
    _validate_source(root["source"], source_identity)
    expected_maps = _canonical_names(ordinary_maps, "ordinaryMaps")
    supported_method_set = frozenset(supported_methods)
    supported_species_set = frozenset(supported_species)
    records = _sequence(root["records"], "$.records")
    actual_maps: list[str] = []
    route39_profiles: object | None = None
    for index, raw in enumerate(records):
        pointer = f"$.records[{index}]"
        record = _mapping(raw, pointer)
        if "status" not in record:
            raise ContentPortError(f"{pointer}: missing field 'status'")
        status = _string(record["status"], f"{pointer}.status")
        if status == "reviewed":
            allowed = {"map", "status", "profiles"}
            if "reviewNotes" in record:
                allowed.add("reviewNotes")
            _exact_keys(record, allowed, pointer)
        elif status == "blocked":
            _exact_keys(record, {"map", "status", "reason", "evidenceNeeded"}, pointer)
        else:
            raise ContentPortError(
                f"{pointer}.status: expected 'reviewed' or 'blocked'"
            )
        map_name = _string(record["map"], f"{pointer}.map")
        actual_maps.append(map_name)
        if status == "blocked":
            _string(record["reason"], f"{pointer}.reason")
            _string(record["evidenceNeeded"], f"{pointer}.evidenceNeeded")
            continue
        if "reviewNotes" in record:
            _review_notes(record["reviewNotes"], f"{pointer}.reviewNotes")
        profiles = _sequence(record["profiles"], f"{pointer}.profiles")
        if not profiles:
            raise ContentPortError(f"{pointer}.profiles: expected at least one profile")
        profile_results = [
            _validate_profile(
                profile,
                f"{pointer}.profiles[{profile_index}]",
                authenticated_donor_profiles,
                supported_method_set,
                supported_species_set,
            )
            for profile_index, profile in enumerate(profiles)
        ]
        profile_keys = [result[0] for result in profile_results]
        if len(set(profile_keys)) != len(profile_keys):
            raise ContentPortError(f"{pointer}.profiles: duplicate donor profile key")
        if any(result[1] for result in profile_results) and "reviewNotes" not in record:
            raise ContentPortError(
                f"{pointer}: source anomalies require explicit reviewNotes"
            )
        if map_name == "Route39":
            route39_profiles = profiles

    duplicates = sorted(
        name for name in set(actual_maps) if actual_maps.count(name) > 1
    )
    if duplicates:
        raise ContentPortError(
            f"$.records: duplicate ecology record for {duplicates[0]!r}"
        )
    if tuple(actual_maps) != expected_maps:
        missing = [name for name in expected_maps if name not in actual_maps]
        extra = [name for name in actual_maps if name not in expected_maps]
        if missing:
            raise ContentPortError(f"$.records: missing ordinary map {missing[0]!r}")
        if extra:
            raise ContentPortError(f"$.records: non-ordinary map {extra[0]!r}")
        raise ContentPortError("$.records: ecology records must use ordinary-map order")

    if protected_route39_profile is not None:
        if route39_profiles is None:
            raise ContentPortError("$.records: Route39 must remain a reviewed profile")
        if isinstance(protected_route39_profile, str):
            if DIGEST_RE.fullmatch(protected_route39_profile) is None:
                raise ContentPortError(
                    "protected Route39 digest is not lowercase sha256"
                )
            matches = stable_digest(route39_profiles) == protected_route39_profile
        else:
            matches = route39_profiles == protected_route39_profile
        if not matches:
            raise ContentPortError(
                "$.records: Route39 differs from its protected profile"
            )
