"""Append-only authority for cumulatively materialized Johto trainers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .bindings import BindingIndex
from .errors import ContentPortError
from .trainer_inventory import TrainerInventory


SCHEMA_VERSION = 1
ROOT_KEYS = frozenset({"schemaVersion", "appendOnlyBaseline", "batches"})
BASELINE_KEYS = frozenset({"batchCount", "sha256"})
BATCH_KEYS = frozenset({"sequence", "key", "kind", "identities"})
IDENTITY_KEYS = frozenset({"identity", "placements"})
BATCH_KINDS = frozenset({"seeded-legacy-closure", "standard-singles"})
KEY_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReviewedMaterializationPrefix:
    """Externally reviewed pins for an immutable prefix of landed batches."""

    batch_count: int
    sha256: str


PRODUCTION_REVIEWED_PREFIX = ReviewedMaterializationPrefix(
    7, "cb499c77993df896c441b997605b67d421b31d2a52a493f4bbb4d4dc40ea85a6"
)


@dataclass(frozen=True)
class MaterializedTrainer:
    identity: str
    target: str
    placements: tuple[str, ...]


@dataclass(frozen=True)
class MaterializationBatch:
    sequence: int
    key: str
    kind: str
    identities: tuple[MaterializedTrainer, ...]


@dataclass(frozen=True)
class TrainerMaterializationAuthority:
    batches: tuple[MaterializationBatch, ...]
    baseline_digest: str
    digest: str

    @property
    def identities(self) -> tuple[MaterializedTrainer, ...]:
        return tuple(record for batch in self.batches for record in batch.identities)

    @property
    def identity_names(self) -> tuple[str, ...]:
        return tuple(record.identity for record in self.identities)

    @property
    def placement_names(self) -> tuple[str, ...]:
        return tuple(
            placement for record in self.identities for placement in record.placements
        )


def stable_materialization_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def candidate_reviewed_prefix(
    batches: Sequence[object],
) -> ReviewedMaterializationPrefix:
    """Return candidate pins for the full authority after external review.

    Callers must persist these pins in an independent reviewed contract before
    using them for validation. Deriving them from the document being validated
    would defeat the append-only guarantee.
    """

    if not batches:
        raise ContentPortError("reviewed materialization prefix must not be empty")
    return ReviewedMaterializationPrefix(
        len(batches), stable_materialization_digest(batches)
    )


def _mapping(value: object, pointer: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    return value


def _array(value: object, pointer: str) -> list[object]:
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


def _string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def validate_trainer_materialization_document(
    document: object,
    inventory: TrainerInventory,
    allocations: BindingIndex,
    *,
    reviewed_prefix: ReviewedMaterializationPrefix = PRODUCTION_REVIEWED_PREFIX,
) -> TrainerMaterializationAuthority:
    """Validate cumulative Phase 3 closure against authenticated authorities."""

    root = _mapping(document, "$")
    _exact_keys(root, ROOT_KEYS, "$")
    if root["schemaVersion"] != SCHEMA_VERSION:
        raise ContentPortError(f"$.schemaVersion: expected {SCHEMA_VERSION}")
    baseline = _mapping(root["appendOnlyBaseline"], "$.appendOnlyBaseline")
    _exact_keys(baseline, BASELINE_KEYS, "$.appendOnlyBaseline")
    if type(reviewed_prefix.batch_count) is not int or reviewed_prefix.batch_count < 1:
        raise ContentPortError("reviewed materialization prefix count must be positive")
    if DIGEST_RE.fullmatch(reviewed_prefix.sha256) is None:
        raise ContentPortError(
            "reviewed materialization prefix digest must be lowercase SHA-256"
        )
    if baseline["batchCount"] != reviewed_prefix.batch_count:
        raise ContentPortError(
            "$.appendOnlyBaseline.batchCount: reviewed prefix count drifted"
        )
    baseline_digest = _string(baseline["sha256"], "$.appendOnlyBaseline.sha256")
    if (
        DIGEST_RE.fullmatch(baseline_digest) is None
        or baseline_digest != reviewed_prefix.sha256
    ):
        raise ContentPortError(
            "$.appendOnlyBaseline.sha256: reviewed prefix digest drifted"
        )

    raw_batches = _array(root["batches"], "$.batches")
    if len(raw_batches) < reviewed_prefix.batch_count:
        raise ContentPortError("$.batches: reviewed append-only prefix was removed")
    actual_prefix_digest = stable_materialization_digest(
        raw_batches[: reviewed_prefix.batch_count]
    )
    if actual_prefix_digest != baseline_digest:
        raise ContentPortError(
            "$.batches: reviewed append-only prefix was removed, reordered, or changed"
        )

    inventory_identities = {record.trainer: record for record in inventory.identities}
    placements_by_identity: dict[str, tuple[str, ...]] = {}
    for record in inventory.identities:
        placements_by_identity[record.trainer] = tuple(
            placement.identity
            for placement in inventory.placements
            if placement.trainer == record.trainer and placement.admitted
        )

    batches: list[MaterializationBatch] = []
    batch_keys: set[str] = set()
    claimed_identities: set[str] = set()
    claimed_placements: set[str] = set()
    for batch_index, raw_batch in enumerate(raw_batches):
        pointer = f"$.batches[{batch_index}]"
        batch = _mapping(raw_batch, pointer)
        _exact_keys(batch, BATCH_KEYS, pointer)
        sequence = batch["sequence"]
        if type(sequence) is not int or sequence != batch_index:
            raise ContentPortError(
                f"{pointer}.sequence: batches must be contiguous and ordered"
            )
        key = _string(batch["key"], f"{pointer}.key")
        if KEY_RE.fullmatch(key) is None:
            raise ContentPortError(f"{pointer}.key: expected a canonical slug")
        if key in batch_keys:
            raise ContentPortError(f"{pointer}.key: duplicate batch key {key!r}")
        batch_keys.add(key)
        kind = _string(batch["kind"], f"{pointer}.kind")
        if kind not in BATCH_KINDS:
            raise ContentPortError(f"{pointer}.kind: unsupported batch kind {kind!r}")
        if (batch_index == 0) != (kind == "seeded-legacy-closure"):
            raise ContentPortError(
                f"{pointer}.kind: only the reviewed initial batch may seed legacy closure"
            )

        raw_identities = _array(batch["identities"], f"{pointer}.identities")
        if not raw_identities:
            raise ContentPortError(f"{pointer}.identities: batch must not be empty")
        materialized: list[MaterializedTrainer] = []
        for identity_index, raw_identity in enumerate(raw_identities):
            identity_pointer = f"{pointer}.identities[{identity_index}]"
            item = _mapping(raw_identity, identity_pointer)
            _exact_keys(item, IDENTITY_KEYS, identity_pointer)
            identity = _string(item["identity"], f"{identity_pointer}.identity")
            if identity in claimed_identities:
                raise ContentPortError(
                    f"{identity_pointer}.identity: duplicate materialized identity {identity!r}"
                )
            claimed_identities.add(identity)
            inventory_record = inventory_identities.get(identity)
            if (
                inventory_record is None
                or inventory_record.classification != "ordinary"
                or not inventory_record.admitted
                or inventory_record.projection is None
            ):
                raise ContentPortError(
                    f"{identity_pointer}.identity: identity is not an admitted projected ordinary trainer"
                )
            if identity in inventory.paired_doubles:
                raise ContentPortError(
                    f"{identity_pointer}.identity: paired doubles are outside Phase 3"
                )
            target = inventory_record.projection.target
            allocations.resolve(target, domain="trainerIds")

            placements = tuple(
                _string(value, f"{identity_pointer}.placements[{index}]")
                for index, value in enumerate(
                    _array(item["placements"], f"{identity_pointer}.placements")
                )
            )
            expected_placements = placements_by_identity[identity]
            if placements != expected_placements:
                if len(placements) != len(set(placements)):
                    raise ContentPortError(
                        f"{identity_pointer}.placements: placements must be unique"
                    )
                if set(placements) == set(expected_placements):
                    raise ContentPortError(
                        f"{identity_pointer}.placements: canonical inventory order drifted"
                    )
                missing = [
                    value for value in expected_placements if value not in placements
                ]
                extra = [
                    value for value in placements if value not in expected_placements
                ]
                raise ContentPortError(
                    f"{identity_pointer}.placements: must exactly cover every admitted inventory placement; "
                    f"missing={missing[:1]}, extra={extra[:1]}"
                )
            if not placements:
                raise ContentPortError(
                    f"{identity_pointer}.placements: materialized trainer has no admitted placement"
                )
            duplicate_placement = next(
                (value for value in placements if value in claimed_placements), None
            )
            if duplicate_placement is not None:
                raise ContentPortError(
                    f"{identity_pointer}.placements: duplicate materialized placement {duplicate_placement!r}"
                )
            claimed_placements.update(placements)
            materialized.append(MaterializedTrainer(identity, target, placements))
        batches.append(MaterializationBatch(sequence, key, kind, tuple(materialized)))

    return TrainerMaterializationAuthority(
        tuple(batches),
        baseline_digest,
        stable_materialization_digest(root),
    )


def load_trainer_materialization(
    path: Path | str,
    inventory: TrainerInventory,
    allocations: BindingIndex,
    *,
    reviewed_prefix: ReviewedMaterializationPrefix = PRODUCTION_REVIEWED_PREFIX,
) -> TrainerMaterializationAuthority:
    source = Path(path)
    try:
        document = json.loads(
            source.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object
        )
    except ContentPortError as error:
        raise ContentPortError(
            f"{source}: invalid materialization authority: {error}"
        ) from error
    except (OSError, json.JSONDecodeError) as error:
        raise ContentPortError(
            f"{source}: invalid materialization authority: {error}"
        ) from error
    return validate_trainer_materialization_document(
        document,
        inventory,
        allocations,
        reviewed_prefix=reviewed_prefix,
    )


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContentPortError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def require_materialization_exact_cover(
    authority: TrainerMaterializationAuthority,
    observed: Mapping[str, Iterable[str]],
    *,
    owner: str,
) -> None:
    """Require an observed cumulative surface to equal the authored authority."""

    expected = materialized_placements(authority)
    expected_identities = set(expected)
    actual_identities = set(observed)
    if actual_identities != expected_identities:
        missing = sorted(expected_identities - actual_identities)
        extra = sorted(actual_identities - expected_identities)
        raise ContentPortError(
            f"{owner}: materialized identities differ from cumulative authority; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    for identity in sorted(expected_identities):
        actual_placements = tuple(observed[identity])
        if len(actual_placements) != len(set(actual_placements)):
            raise ContentPortError(
                f"{owner}: {identity} has duplicate observed placements"
            )
        expected_placements = set(expected[identity])
        actual_placement_set = set(actual_placements)
        if actual_placement_set == expected_placements:
            continue
        missing = sorted(expected_placements - actual_placement_set)
        extra = sorted(actual_placement_set - expected_placements)
        raise ContentPortError(
            f"{owner}: {identity} placement ownership differs from cumulative authority; "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )


def materialized_targets(
    authority: TrainerMaterializationAuthority,
) -> Mapping[str, str]:
    """Return an immutable source-to-target view for downstream consumers."""

    return MappingProxyType(
        {record.identity: record.target for record in authority.identities}
    )


def materialized_placements(
    authority: TrainerMaterializationAuthority,
) -> Mapping[str, tuple[str, ...]]:
    """Return immutable canonical placements keyed by source identity."""

    return MappingProxyType(
        {record.identity: record.placements for record in authority.identities}
    )
