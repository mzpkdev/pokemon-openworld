from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest

from tools.content_port.bindings import (
    BindingIndex,
    PersistentBinding,
    load_binding_index,
)
from tools.content_port.descriptor import load_port
from tools.content_port.errors import ContentPortError
from tools.content_port.sources import resolve_port_sources
from tools.content_port.trainer_inventory import (
    TrainerIdentity,
    TrainerInventory,
    TrainerPlacement,
    TrainerProjection,
)
from tools.content_port.trainer_materialization import (
    PRODUCTION_REVIEWED_PREFIX,
    ReviewedMaterializationPrefix,
    candidate_reviewed_prefix,
    load_trainer_materialization,
    materialized_placements,
    materialized_targets,
    require_materialization_exact_cover,
    validate_trainer_materialization_document,
)


ROOT = Path(__file__).parents[3]
PORT = ROOT / "tools/content_port/ports/johto"
POLICY = PORT / "trainer_materialization.json"
SAMUEL_PLACEMENT = "Route34/0/Route34_EventScript_YoungsterSamuel"
EUGENE_PLACEMENT = "Route39/4/Route39_EventScript_Eugene"
WADE_PLACEMENT = "Route31/0/Route31_EventScript_Bugcatcher_Wade"
DON_PLACEMENT = "Route30/3/Route30_EventScript_Bugcatcher_Don"
MIKEY_PLACEMENT = "Route30/6/Route30_EventScript_Youngster_Mikey"
ANTHONY_PLACEMENT = "Route33/0/Route33_EventScript_HikerAnthony"
SEEDED_REVIEWED_PREFIX = ReviewedMaterializationPrefix(
    1, "7dc0cdbee3a86a518a7910679a0d108610cfb822c41b7077082097fcbd2104c1"
)


def projection(target: str) -> TrainerProjection:
    return TrainerProjection(
        target,
        "Youngster",
        "Youngster FRLG",
        "Male",
        "Male",
        "Check Bad Move",
        "preserve",
        "preserve",
    )


def inventory() -> TrainerInventory:
    identities = [
        TrainerIdentity(
            "TRAINER_SAMUEL",
            "ordinary",
            None,
            True,
            projection("TRAINER_YOUNGSTER_SAMUEL_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_EUGENE",
            "ordinary",
            None,
            True,
            projection("TRAINER_SAILOR_EUGENE_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_WADE",
            "ordinary",
            None,
            True,
            projection("TRAINER_BUG_CATCHER_WADE_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_DON",
            "ordinary",
            None,
            True,
            projection("TRAINER_BUG_CATCHER_DON_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_MIKEY",
            "ordinary",
            None,
            True,
            projection("TRAINER_YOUNGSTER_MIKEY_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_ANTHONY",
            "ordinary",
            None,
            True,
            projection("TRAINER_HIKER_ANTHONY_JOHTO"),
        ),
        TrainerIdentity(
            "TRAINER_TWINS",
            "ordinary",
            None,
            True,
            projection("TRAINER_TWINS_AMY_AND_MAY_JOHTO"),
        ),
        TrainerIdentity("TRAINER_STORY", "story-controlled", "story", False, None),
    ]
    placements = [
        TrainerPlacement(
            SAMUEL_PLACEMENT,
            "Route34",
            0,
            "Route34_EventScript_YoungsterSamuel",
            "TRAINER_SAMUEL",
            True,
            "OBJ_EVENT_GFX_YOUNGSTER",
        ),
        TrainerPlacement(
            EUGENE_PLACEMENT,
            "Route39",
            4,
            "Route39_EventScript_Eugene",
            "TRAINER_EUGENE",
            True,
            "OBJ_EVENT_GFX_SAILOR",
        ),
        TrainerPlacement(
            WADE_PLACEMENT,
            "Route31",
            0,
            "Route31_EventScript_Bugcatcher_Wade",
            "TRAINER_WADE",
            True,
            "OBJ_EVENT_GFX_BUG_CATCHER",
        ),
        TrainerPlacement(
            DON_PLACEMENT,
            "Route30",
            3,
            "Route30_EventScript_Bugcatcher_Don",
            "TRAINER_DON",
            True,
            "OBJ_EVENT_GFX_BUG_CATCHER",
        ),
        TrainerPlacement(
            MIKEY_PLACEMENT,
            "Route30",
            6,
            "Route30_EventScript_Youngster_Mikey",
            "TRAINER_MIKEY",
            True,
            "OBJ_EVENT_GFX_YOUNGSTER",
        ),
        TrainerPlacement(
            ANTHONY_PLACEMENT,
            "Route33",
            0,
            "Route33_EventScript_HikerAnthony",
            "TRAINER_ANTHONY",
            True,
            "OBJ_EVENT_GFX_HIKER",
        ),
        TrainerPlacement(
            "Gym/1/TwinA",
            "Gym",
            1,
            "TwinA",
            "TRAINER_TWINS",
            True,
            "OBJ_EVENT_GFX_TWIN",
        ),
        TrainerPlacement(
            "Gym/2/TwinB",
            "Gym",
            2,
            "TwinB",
            "TRAINER_TWINS",
            True,
            "OBJ_EVENT_GFX_TWIN",
        ),
    ]
    classification = json.loads((PORT / "trainer_classification.json").read_text())
    projections = {
        row["trainer"]: row["projection"]["target"]
        for row in classification["identities"]
        if "projection" in row
    }
    graphics = {
        event["identity"]: event["overworldGraphic"]
        for map_row in classification["maps"]
        for event in map_row["events"]
        if event.get("admitted")
    }
    for batch in document()["batches"][3:]:
        for row in batch["identities"]:
            trainer = row["identity"]
            placement_name = row["placements"][0]
            map_name, object_index, script_name = placement_name.split("/", 2)
            identities.append(
                TrainerIdentity(
                    trainer,
                    "ordinary",
                    None,
                    True,
                    projection(projections[trainer]),
                )
            )
            placements.append(
                TrainerPlacement(
                    placement_name,
                    map_name,
                    int(object_index),
                    script_name,
                    trainer,
                    True,
                    graphics[placement_name],
                )
            )
    return TrainerInventory(
        tuple(identities),
        tuple(placements),
        MappingProxyType({"TRAINER_TWINS": ("Gym/1/TwinA", "Gym/2/TwinB")}),
        "inventory-digest",
        "identity-digest",
        "placement-digest",
    )


def allocations(*, include_wade: bool = True) -> BindingIndex:
    symbols = [
        ("TRAINER_YOUNGSTER_SAMUEL_JOHTO", 1481),
        ("TRAINER_SAILOR_EUGENE_JOHTO", 1482),
        ("TRAINER_TWINS_AMY_AND_MAY_JOHTO", 1609),
    ]
    if include_wade:
        symbols.extend(
            (
                ("TRAINER_BUG_CATCHER_WADE_JOHTO", 1570),
                ("TRAINER_HIKER_ANTHONY_JOHTO", 1576),
                ("TRAINER_YOUNGSTER_MIKEY_JOHTO", 1619),
                ("TRAINER_BUG_CATCHER_DON_JOHTO", 1662),
            )
        )
        classification = json.loads((PORT / "trainer_classification.json").read_text())
        targets = {
            row["trainer"]: row["projection"]["target"]
            for row in classification["identities"]
            if "projection" in row
        }
        production = load_binding_index(
            ROOT / "src/data/persistence/persistent_ids.json"
        )
        for batch in document()["batches"][3:]:
            for row in batch["identities"]:
                target = targets[row["identity"]]
                binding = production.resolve(target, domain="trainerIds")
                symbols.append((target, binding.value))
    return BindingIndex(
        PersistentBinding(
            "trainerIds", symbol, value, "u32-id", "trainer-defeat-bitmap"
        )
        for symbol, value in symbols
    )


def document() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def pending_wade_document() -> dict:
    value = document()
    value["batches"] = value["batches"][:2]
    value["appendOnlyBaseline"] = {
        "batchCount": SEEDED_REVIEWED_PREFIX.batch_count,
        "sha256": SEEDED_REVIEWED_PREFIX.sha256,
    }
    return value


class TrainerMaterializationTests(unittest.TestCase):
    def test_seeded_authority_is_immutable_and_allocation_backed(self) -> None:
        expected_identities = tuple(
            row["identity"]
            for batch in document()["batches"]
            for row in batch["identities"]
        )
        expected_placements = tuple(
            placement
            for batch in document()["batches"]
            for row in batch["identities"]
            for placement in row["placements"]
        )
        result = validate_trainer_materialization_document(
            document(), inventory(), allocations()
        )
        self.assertEqual(result.baseline_digest, PRODUCTION_REVIEWED_PREFIX.sha256)
        self.assertEqual(result.identity_names, expected_identities)
        self.assertEqual(result.placement_names, expected_placements)
        expected_targets = {
            row.trainer: row.projection.target
            for row in inventory().identities
            if row.trainer in expected_identities and row.projection is not None
        }
        self.assertEqual(
            dict(materialized_targets(result)),
            expected_targets,
        )
        with self.assertRaises(TypeError):
            materialized_targets(result)["TRAINER_WADE"] = "changed"  # type: ignore[index]
        with self.assertRaises(TypeError):
            materialized_placements(result)["TRAINER_WADE"] = ()  # type: ignore[index]

    def test_external_review_can_freeze_every_landed_batch(self) -> None:
        value = document()
        reviewed = candidate_reviewed_prefix(value["batches"])
        value["appendOnlyBaseline"] = {
            "batchCount": reviewed.batch_count,
            "sha256": reviewed.sha256,
        }
        result = validate_trainer_materialization_document(
            value,
            inventory(),
            allocations(),
            reviewed_prefix=reviewed,
        )
        self.assertEqual(result.batches[-1].key, "bulk-surf-field-standard-singles-33")

        changed = copy.deepcopy(value)
        changed["batches"][1]["identities"][0]["placements"] = []
        with self.assertRaisesRegex(ContentPortError, "prefix .*changed"):
            validate_trainer_materialization_document(
                changed,
                inventory(),
                allocations(),
                reviewed_prefix=reviewed,
            )
        with self.assertRaisesRegex(ContentPortError, "prefix count drifted"):
            validate_trainer_materialization_document(
                value,
                inventory(),
                allocations(),
                reviewed_prefix=SEEDED_REVIEWED_PREFIX,
            )

    def test_reviewed_prefix_cannot_be_removed_reordered_or_changed(self) -> None:
        for mutation in (
            lambda value: value["batches"].clear(),
            lambda value: value["batches"][0]["identities"].reverse(),
            lambda value: value["batches"][0]["identities"][0].update(
                {"placements": [EUGENE_PLACEMENT]}
            ),
        ):
            with self.subTest(mutation=mutation):
                value = document()
                mutation(value)
                with self.assertRaisesRegex(
                    ContentPortError, "append-only prefix|prefix was removed"
                ):
                    validate_trainer_materialization_document(
                        value, inventory(), allocations()
                    )

    def test_appended_batches_are_unique_contiguous_and_nonempty(self) -> None:
        valid = pending_wade_document()
        result = validate_trainer_materialization_document(
            valid,
            inventory(),
            allocations(),
            reviewed_prefix=SEEDED_REVIEWED_PREFIX,
        )
        self.assertEqual(result.batches[-1].key, "route31-wade")

        for label, mutation, message in (
            (
                "sequence gap",
                lambda value: value["batches"][1].update({"sequence": 2}),
                "contiguous and ordered",
            ),
            (
                "duplicate key",
                lambda value: value["batches"][1].update(
                    {"key": "seeded-samuel-eugene"}
                ),
                "duplicate batch key",
            ),
            (
                "empty",
                lambda value: value["batches"][1].update({"identities": []}),
                "must not be empty",
            ),
            (
                "second seed",
                lambda value: value["batches"][1].update(
                    {"kind": "seeded-legacy-closure"}
                ),
                "only the reviewed initial batch",
            ),
        ):
            with self.subTest(label=label):
                value = copy.deepcopy(valid)
                mutation(value)
                with self.assertRaisesRegex(ContentPortError, message):
                    validate_trainer_materialization_document(
                        value,
                        inventory(),
                        allocations(),
                        reviewed_prefix=SEEDED_REVIEWED_PREFIX,
                    )

    def test_identity_requires_exact_placements_and_unique_ownership(self) -> None:
        value = pending_wade_document()
        value["batches"][1]["identities"][0]["placements"] = []
        with self.assertRaisesRegex(ContentPortError, "exactly cover every admitted"):
            validate_trainer_materialization_document(
                value,
                inventory(),
                allocations(),
                reviewed_prefix=SEEDED_REVIEWED_PREFIX,
            )

        value = pending_wade_document()
        value["batches"][1]["identities"].append(
            {"identity": "TRAINER_SAMUEL", "placements": [SAMUEL_PLACEMENT]}
        )
        with self.assertRaisesRegex(
            ContentPortError, "duplicate materialized identity"
        ):
            validate_trainer_materialization_document(
                value,
                inventory(),
                allocations(),
                reviewed_prefix=SEEDED_REVIEWED_PREFIX,
            )

        base = inventory()
        ungrouped = TrainerInventory(
            base.identities,
            base.placements,
            MappingProxyType({}),
            base.digest,
            base.identity_membership_digest,
            base.placement_membership_digest,
        )
        reordered = document()
        reordered["batches"].append(
            {
                "sequence": len(reordered["batches"]),
                "key": "repeat-placement",
                "kind": "standard-singles",
                "identities": [
                    {
                        "identity": "TRAINER_TWINS",
                        "placements": ["Gym/2/TwinB", "Gym/1/TwinA"],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(
            ContentPortError, "canonical inventory order drifted"
        ):
            validate_trainer_materialization_document(
                reordered, ungrouped, allocations()
            )

    def test_phase3_rejects_grouped_excluded_and_unallocated_identities(self) -> None:
        grouped = document()
        grouped["batches"].append(
            {
                "sequence": len(grouped["batches"]),
                "key": "grouped",
                "kind": "standard-singles",
                "identities": [
                    {
                        "identity": "TRAINER_TWINS",
                        "placements": ["Gym/1/TwinA", "Gym/2/TwinB"],
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ContentPortError, "outside Phase 3"):
            validate_trainer_materialization_document(
                grouped, inventory(), allocations()
            )

        excluded = copy.deepcopy(grouped)
        excluded["batches"][-1]["identities"] = [
            {"identity": "TRAINER_STORY", "placements": []}
        ]
        with self.assertRaisesRegex(ContentPortError, "not an admitted projected"):
            validate_trainer_materialization_document(
                excluded, inventory(), allocations()
            )

        unallocated = document()
        with self.assertRaisesRegex(ContentPortError, "no ledger binding"):
            validate_trainer_materialization_document(
                unallocated, inventory(), allocations(include_wade=False)
            )

    def test_exact_cover_compares_unique_identity_placement_mapping(self) -> None:
        result = validate_trainer_materialization_document(
            document(), inventory(), allocations()
        )
        observed = dict(materialized_placements(result))
        require_materialization_exact_cover(
            result,
            observed,
            owner="selected trainer surface",
        )
        with self.assertRaisesRegex(ContentPortError, "missing=.*TRAINER_EUGENE"):
            require_materialization_exact_cover(
                result,
                {
                    key: value
                    for key, value in observed.items()
                    if key != "TRAINER_EUGENE"
                },
                owner="selected trainer surface",
            )
        with self.assertRaisesRegex(ContentPortError, "duplicate observed placements"):
            duplicated = dict(observed)
            duplicated["TRAINER_SAMUEL"] = (SAMUEL_PLACEMENT, SAMUEL_PLACEMENT)
            require_materialization_exact_cover(
                result,
                duplicated,
                owner="selected trainer surface",
            )

        base = inventory()
        ungrouped = TrainerInventory(
            base.identities,
            base.placements,
            MappingProxyType({}),
            base.digest,
            base.identity_membership_digest,
            base.placement_membership_digest,
        )
        multiple = document()
        multiple["batches"].append(
            {
                "sequence": len(multiple["batches"]),
                "key": "repeat-placement",
                "kind": "standard-singles",
                "identities": [
                    {
                        "identity": "TRAINER_TWINS",
                        "placements": ["Gym/1/TwinA", "Gym/2/TwinB"],
                    }
                ],
            }
        )
        multiple_result = validate_trainer_materialization_document(
            multiple, ungrouped, allocations()
        )
        multiple_observed = dict(materialized_placements(multiple_result))
        multiple_observed["TRAINER_TWINS"] = ("Gym/2/TwinB", "Gym/1/TwinA")
        require_materialization_exact_cover(
            multiple_result,
            multiple_observed,
            owner="selected trainer surface",
        )

    def test_loader_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schemaVersion":1,"schemaVersion":1,'
                '"appendOnlyBaseline":{},"batches":[]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContentPortError, "duplicate JSON key"):
                load_trainer_materialization(path, inventory(), allocations())

    def test_real_policy_validates_against_authenticated_inventory(self) -> None:
        donor_root = Path(
            os.environ.get(
                "CONTENT_PORT_DONOR_ROOT", str(ROOT.parents[2] / ".references")
            )
        ).resolve()
        if not all(
            (donor_root / name).is_dir() for name in ("PKMN-World", "pokemonHnS")
        ):
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(PORT, donor_root)
        _, state = resolve_port_sources(descriptor, ROOT)
        self.assertIsNotNone(state.trainer_materialization)
        expected_identities = tuple(
            row["identity"]
            for batch in document()["batches"]
            for row in batch["identities"]
        )
        self.assertEqual(
            state.trainer_materialization.identity_names,
            expected_identities,
        )
        result = load_trainer_materialization(
            POLICY,
            state.trainer_inventory,
            load_binding_index(ROOT / "src/data/persistence/persistent_ids.json"),
        )
        self.assertEqual(result.identity_names, expected_identities)
        selected: dict[str, list[str]] = {}
        for events in state.trainer_events.values():
            for event in events:
                for trainer in event.trainers:
                    selected.setdefault(trainer, []).append(
                        f"{event.map_name}/{event.object_index}/{event.script_name}"
                    )
        require_materialization_exact_cover(
            result,
            selected,
            owner="authenticated selected trainer closure",
        )


if __name__ == "__main__":
    unittest.main()
