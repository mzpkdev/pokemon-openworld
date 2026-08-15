"""Fail-closed contracts for the authored Johto trainer inventory."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .errors import ContentPortError


ROOT_KEYS = frozenset({"schemaVersion", "identities", "maps", "pairedDoubles"})
IDENTITY_KEYS = frozenset({"trainer", "classification", "admitted"})
MAP_KEYS = frozenset({"map", "authority", "events"})
EVENT_KEYS = frozenset({"identity", "admitted"})
PAIR_KEYS = frozenset({"trainer", "events"})
CLASSIFICATIONS = frozenset({"ordinary", "story-controlled", "unsupported"})
MAP_AUTHORITIES = frozenset({"content", "absent"})


@dataclass(frozen=True)
class InventoryExpectations:
    identities: int
    placements: int
    maps: int | None = None
    identity_classifications: Mapping[str, int] | None = None
    placement_classifications: Mapping[str, int] | None = None
    admitted_identities: int | None = None
    admitted_placements: int | None = None


@dataclass(frozen=True)
class TrainerIdentity:
    trainer: str
    classification: str
    reason: str | None
    admitted: bool


@dataclass(frozen=True)
class TrainerPlacement:
    identity: str
    map_name: str
    object_index: int
    script: str
    trainer: str
    admitted: bool


@dataclass(frozen=True)
class TrainerInventory:
    identities: tuple[TrainerIdentity, ...]
    placements: tuple[TrainerPlacement, ...]
    paired_doubles: Mapping[str, tuple[str, str]]
    digest: str
    identity_membership_digest: str
    placement_membership_digest: str


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


def _boolean(value: object, pointer: str) -> bool:
    if type(value) is not bool:
        raise ContentPortError(f"{pointer}: expected a boolean")
    return value


def _canonical(values: Iterable[str], pointer: str) -> tuple[str, ...]:
    result = tuple(
        _string(value, f"{pointer}[{index}]") for index, value in enumerate(values)
    )
    if len(set(result)) != len(result):
        raise ContentPortError(f"{pointer}: canonical records must be unique")
    return result


def _require_order(
    actual: Sequence[str], expected: Sequence[str], pointer: str
) -> None:
    if tuple(actual) == tuple(expected):
        return
    missing = [key for key in expected if key not in actual]
    extra = [key for key in actual if key not in expected]
    if missing:
        raise ContentPortError(f"{pointer}: missing canonical record {missing[0]!r}")
    if extra:
        raise ContentPortError(f"{pointer}: unknown canonical record {extra[0]!r}")
    raise ContentPortError(f"{pointer}: records must use canonical donor order")


def stable_inventory_digest(value: object) -> str:
    """Hash authored inventory data with stable JSON encoding."""

    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def inventory_membership_digest(values: Iterable[str]) -> str:
    """Hash unique membership independently from required authored order."""

    members = tuple(values)
    if len(set(members)) != len(members):
        raise ContentPortError("inventory membership digest requires unique identities")
    return stable_inventory_digest(sorted(members))


def _identity_row(raw: object, pointer: str) -> TrainerIdentity:
    row = _mapping(raw, pointer)
    classification = row.get("classification")
    expected = (
        IDENTITY_KEYS if classification == "ordinary" else IDENTITY_KEYS | {"reason"}
    )
    _exact_keys(row, expected, pointer)
    trainer = _string(row["trainer"], f"{pointer}.trainer")
    classification = _string(classification, f"{pointer}.classification")
    admitted = _boolean(row["admitted"], f"{pointer}.admitted")
    if classification not in CLASSIFICATIONS:
        raise ContentPortError(
            f"{pointer}.classification: unsupported classification {classification!r}"
        )
    if classification == "ordinary":
        if not admitted:
            raise ContentPortError(
                f"{pointer}.admitted: ordinary trainers are admitted"
            )
        return TrainerIdentity(trainer, classification, None, admitted)
    reason = _string(row["reason"], f"{pointer}.reason")
    if admitted:
        raise ContentPortError(
            f"{pointer}.admitted: excluded trainers are not admitted"
        )
    return TrainerIdentity(trainer, classification, reason, admitted)


def _event_parts(identity: str, pointer: str) -> tuple[str, int, str]:
    parts = identity.rsplit("/", 2)
    if len(parts) != 3 or not parts[0] or not parts[2]:
        raise ContentPortError(
            f"{pointer}: expected map/object_index/script event identity"
        )
    try:
        object_index = int(parts[1])
    except ValueError as error:
        raise ContentPortError(f"{pointer}: object index must be an integer") from error
    if object_index < 0 or str(object_index) != parts[1]:
        raise ContentPortError(f"{pointer}: object index must be canonical")
    return parts[0], object_index, parts[2]


def validate_trainer_inventory_document(
    document: object,
    canonical_identities: Iterable[str],
    canonical_maps: Iterable[str],
    authenticated_events: Mapping[str, Mapping[str, Iterable[str]]],
    content_maps: Iterable[str],
    authenticated_pairs: Mapping[str, Sequence[str]],
    *,
    expectations: InventoryExpectations,
    expected_digest: str | None = None,
) -> TrainerInventory:
    """Validate exhaustive donor identities and resident-map trainer events."""

    root = _mapping(document, "$")
    _exact_keys(root, ROOT_KEYS, "$")
    if type(root["schemaVersion"]) is not int or root["schemaVersion"] != 1:
        raise ContentPortError("$.schemaVersion: expected 1")
    expected_identities = _canonical(canonical_identities, "canonicalIdentities")
    expected_maps = _canonical(canonical_maps, "canonicalMaps")
    if len(expected_identities) != expectations.identities:
        raise ContentPortError(
            f"canonicalIdentities: expected {expectations.identities} donor identities"
        )
    if expectations.maps is not None and len(expected_maps) != expectations.maps:
        raise ContentPortError(
            f"canonicalMaps: expected {expectations.maps} resident maps"
        )
    _require_order(tuple(authenticated_events), expected_maps, "authenticatedEvents")
    content_map_set = frozenset(content_maps)
    unknown_content_maps = sorted(content_map_set - set(expected_maps))
    if unknown_content_maps:
        raise ContentPortError(
            f"contentMaps: unknown canonical map {unknown_content_maps[0]!r}"
        )

    identities = tuple(
        _identity_row(raw, f"$.identities[{index}]")
        for index, raw in enumerate(_sequence(root["identities"], "$.identities"))
    )
    _require_order(
        [record.trainer for record in identities], expected_identities, "$.identities"
    )
    identity_index = {record.trainer: record for record in identities}

    map_rows = _sequence(root["maps"], "$.maps")
    actual_maps: list[str] = []
    placements: list[TrainerPlacement] = []
    for map_index, raw in enumerate(map_rows):
        pointer = f"$.maps[{map_index}]"
        row = _mapping(raw, pointer)
        _exact_keys(row, MAP_KEYS, pointer)
        map_name = _string(row["map"], f"{pointer}.map")
        actual_maps.append(map_name)
        authority = _string(row["authority"], f"{pointer}.authority")
        if authority not in MAP_AUTHORITIES:
            raise ContentPortError(
                f"{pointer}.authority: unsupported authority {authority!r}"
            )
        expected_authority = "content" if map_name in content_map_set else "absent"
        if authority != expected_authority:
            raise ContentPortError(
                f"{pointer}.authority: expected {expected_authority!r}"
            )
        expected_events = authenticated_events[map_name]
        if authority == "absent" and expected_events:
            raise ContentPortError(
                f"{pointer}: absent donor map cannot own trainer events"
            )
        actual_events: list[str] = []
        for event_index, raw_event in enumerate(
            _sequence(row["events"], f"{pointer}.events")
        ):
            event_pointer = f"{pointer}.events[{event_index}]"
            event = _mapping(raw_event, event_pointer)
            _exact_keys(event, EVENT_KEYS, event_pointer)
            identity = _string(event["identity"], f"{event_pointer}.identity")
            admitted = _boolean(event["admitted"], f"{event_pointer}.admitted")
            event_map, object_index, script = _event_parts(
                identity, f"{event_pointer}.identity"
            )
            if event_map != map_name:
                raise ContentPortError(
                    f"{event_pointer}.identity: event belongs to {event_map!r}, not {map_name!r}"
                )
            trainers = tuple(expected_events.get(identity, ()))
            if len(trainers) != 1:
                raise ContentPortError(
                    f"{event_pointer}.identity: expected exactly one authenticated trainer"
                )
            trainer = trainers[0]
            if trainer not in identity_index:
                raise ContentPortError(
                    f"{event_pointer}.identity: unclassified trainer {trainer!r}"
                )
            if admitted != identity_index[trainer].admitted:
                raise ContentPortError(
                    f"{event_pointer}.admitted: must match linked trainer admission"
                )
            placements.append(
                TrainerPlacement(
                    identity, map_name, object_index, script, trainer, admitted
                )
            )
            actual_events.append(identity)
        _require_order(actual_events, tuple(expected_events), f"{pointer}.events")
    _require_order(actual_maps, expected_maps, "$.maps")

    if len(placements) != expectations.placements:
        raise ContentPortError(
            f"$.maps: expected {expectations.placements} authenticated trainer events"
        )
    raw_identity_counts = Counter(record.classification for record in identities)
    identity_counts = {
        classification: raw_identity_counts[classification]
        for classification in CLASSIFICATIONS
    }
    expected_identity_counts = (
        None
        if expectations.identity_classifications is None
        else dict(expectations.identity_classifications)
    )
    if (
        expected_identity_counts is not None
        and identity_counts != expected_identity_counts
    ):
        raise ContentPortError(
            "$.identities: classification totals differ from accepted scope"
        )
    if (
        expectations.admitted_identities is not None
        and sum(record.admitted for record in identities)
        != expectations.admitted_identities
    ):
        raise ContentPortError(
            "$.identities: admitted total differs from accepted scope"
        )
    raw_placement_counts = Counter(
        identity_index[placement.trainer].classification for placement in placements
    )
    placement_counts = {
        classification: raw_placement_counts[classification]
        for classification in CLASSIFICATIONS
    }
    expected_placement_counts = (
        None
        if expectations.placement_classifications is None
        else dict(expectations.placement_classifications)
    )
    if (
        expected_placement_counts is not None
        and placement_counts != expected_placement_counts
    ):
        raise ContentPortError(
            "$.maps: classification totals differ from accepted scope"
        )
    if (
        expectations.admitted_placements is not None
        and sum(record.admitted for record in placements)
        != expectations.admitted_placements
    ):
        raise ContentPortError("$.maps: admitted total differs from accepted scope")

    validated_pairs = _validate_paired_doubles(
        root["pairedDoubles"],
        authenticated_pairs,
        placements,
        identity_index,
    )
    digest = stable_inventory_digest(root)
    if expected_digest is not None:
        if re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
            raise ContentPortError(
                "expected trainer inventory digest must be lowercase SHA-256"
            )
        if digest != expected_digest:
            raise ContentPortError(
                f"trainer inventory digest mismatch: expected {expected_digest}, got {digest}"
            )
    return TrainerInventory(
        identities,
        tuple(placements),
        MappingProxyType(dict(validated_pairs)),
        digest,
        inventory_membership_digest(record.trainer for record in identities),
        inventory_membership_digest(record.identity for record in placements),
    )


def _validate_paired_doubles(
    raw_groups: object,
    authenticated_pairs: Mapping[str, Sequence[str]],
    placements: Sequence[TrainerPlacement],
    identities: Mapping[str, TrainerIdentity],
) -> Mapping[str, tuple[str, str]]:
    groups = _sequence(raw_groups, "$.pairedDoubles")
    if len(groups) != len(authenticated_pairs):
        raise ContentPortError(
            "pairedDoubles: group count differs from authenticated double topology"
        )
    placement_index = {record.identity: record for record in placements}
    result: dict[str, tuple[str, str]] = {}
    claimed: set[str] = set()
    actual_trainers: list[str] = []
    for index, raw_group in enumerate(groups):
        pointer = f"$.pairedDoubles[{index}]"
        group = _mapping(raw_group, pointer)
        _exact_keys(group, PAIR_KEYS, pointer)
        trainer = _string(group["trainer"], f"{pointer}.trainer")
        raw_members = _sequence(group["events"], f"{pointer}.events")
        record = identities.get(_string(trainer, "pairedDoubles.trainer"))
        if record is None or record.classification != "ordinary":
            raise ContentPortError(
                f"paired double {trainer!r}: shared identity must be ordinary"
            )
        members = tuple(raw_members)
        if len(members) != 2 or len(set(members)) != 2:
            raise ContentPortError(
                f"paired double {trainer!r}: expected two unique events"
            )
        for member in members:
            _string(member, f"{pointer}.events")
            placement = placement_index.get(member)
            if placement is None:
                raise ContentPortError(
                    f"paired double {trainer!r}: unknown trainer event {member!r}"
                )
            if placement.trainer != trainer:
                raise ContentPortError(
                    f"paired double {trainer!r}: both events must share the trainer identity"
                )
            if not placement.admitted:
                raise ContentPortError(
                    f"paired double {trainer!r}: both placements must be admitted"
                )
            if member in claimed:
                raise ContentPortError(
                    f"paired double {trainer!r}: trainer event {member!r} is already grouped"
                )
            claimed.add(member)
        result[trainer] = members
        actual_trainers.append(trainer)
    duplicates = sorted(
        trainer
        for trainer in set(actual_trainers)
        if actual_trainers.count(trainer) > 1
    )
    if duplicates:
        raise ContentPortError(
            f"$.pairedDoubles: duplicate shared trainer identity {duplicates[0]!r}"
        )
    missing = sorted(set(authenticated_pairs) - set(actual_trainers))
    extra = sorted(set(actual_trainers) - set(authenticated_pairs))
    if missing:
        raise ContentPortError(
            f"$.pairedDoubles: missing authenticated group {missing[0]!r}"
        )
    if extra:
        raise ContentPortError(f"$.pairedDoubles: unknown group {extra[0]!r}")
    for trainer, members in result.items():
        expected_members = tuple(authenticated_pairs[trainer])
        if members != expected_members:
            raise ContentPortError(
                f"paired double {trainer!r}: events differ from authenticated topology"
            )
        maps = {placement_index[member].map_name for member in members}
        if len(maps) != 1:
            raise ContentPortError(
                f"paired double {trainer!r}: paired events must share one map"
            )
    return result


def load_trainer_inventory(
    path: Path,
    canonical_identities: Iterable[str],
    canonical_maps: Iterable[str],
    authenticated_events: Mapping[str, Mapping[str, Iterable[str]]],
    content_maps: Iterable[str],
    authenticated_pairs: Mapping[str, Sequence[str]],
    *,
    expectations: InventoryExpectations,
    expected_digest: str | None = None,
) -> TrainerInventory:
    """Load and validate an authored trainer inventory JSON document."""

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_json_object
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ContentPortError) as error:
        raise ContentPortError(
            f"{path}: cannot load trainer inventory: {error}"
        ) from error
    return validate_trainer_inventory_document(
        document,
        canonical_identities,
        canonical_maps,
        authenticated_events,
        content_maps,
        authenticated_pairs,
        expectations=expectations,
        expected_digest=expected_digest,
    )


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContentPortError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def require_identity_exact_cover(
    inventory: TrainerInventory,
    downstream_identities: Iterable[str],
    *,
    classification: str | None = None,
    admitted: bool | None = None,
    owner: str = "downstream identity surface",
) -> None:
    """Require a downstream surface to cover classified identities exactly."""

    if classification is not None and classification not in CLASSIFICATIONS:
        raise ContentPortError(f"unsupported classification {classification!r}")
    expected = {
        record.trainer
        for record in inventory.identities
        if (classification is None or record.classification == classification)
        and (admitted is None or record.admitted == admitted)
    }
    actual_sequence = tuple(downstream_identities)
    if len(set(actual_sequence)) != len(actual_sequence):
        raise ContentPortError(f"{owner}: duplicate identity")
    actual = set(actual_sequence)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ContentPortError(f"{owner}: missing classified identity {missing[0]!r}")
    if extra:
        raise ContentPortError(f"{owner}: unexpected classified identity {extra[0]!r}")


def require_placement_exact_cover(
    inventory: TrainerInventory,
    downstream_placements: Iterable[str],
    *,
    admitted: bool | None = None,
    owner: str = "downstream placement surface",
) -> None:
    """Require a downstream surface to cover classified placements exactly."""

    expected = {
        record.identity
        for record in inventory.placements
        if admitted is None or record.admitted == admitted
    }
    actual_sequence = tuple(downstream_placements)
    if len(set(actual_sequence)) != len(actual_sequence):
        raise ContentPortError(f"{owner}: duplicate placement")
    actual = set(actual_sequence)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ContentPortError(f"{owner}: missing classified placement {missing[0]!r}")
    if extra:
        raise ContentPortError(f"{owner}: unexpected classified placement {extra[0]!r}")
