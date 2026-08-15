from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.content_port.errors import ContentPortError
from tools.content_port.trainer_inventory import (
    InventoryExpectations,
    inventory_membership_digest,
    load_trainer_inventory,
    require_identity_exact_cover,
    require_overworld_graphic_exact_cover,
    require_placement_exact_cover,
    require_projection_exact_cover,
    stable_inventory_digest,
    validate_trainer_inventory_document,
)


IDENTITIES = ("TRAINER_JOEY", "TRAINER_TWINS", "TRAINER_ELM", "TRAINER_TULLY")
MAPS = ("Route30", "OlivineGym", "ElmsLab")
EVENTS = {
    "Route30": {
        "Route30/3/YoungsterJoeyScript": ("TRAINER_JOEY",),
        "Route30/4/YoungsterJoeyPartnerScript": ("TRAINER_JOEY",),
    },
    "OlivineGym": {
        "OlivineGym/1/TwinsAmyScript": ("TRAINER_TWINS",),
        "OlivineGym/2/TwinsMayScript": ("TRAINER_TWINS",),
    },
    "ElmsLab": {},
}
EXPECTATIONS = InventoryExpectations(
    identities=4,
    placements=4,
    maps=3,
    identity_classifications={
        "ordinary": 2,
        "story-controlled": 1,
        "unsupported": 1,
    },
    placement_classifications={
        "ordinary": 4,
        "story-controlled": 0,
        "unsupported": 0,
    },
    admitted_identities=2,
    admitted_placements=4,
)
CONTENT_MAPS = ("Route30", "OlivineGym")
PAIRS = {
    "TRAINER_JOEY": (
        "Route30/3/YoungsterJoeyScript",
        "Route30/4/YoungsterJoeyPartnerScript",
    ),
    "TRAINER_TWINS": (
        "OlivineGym/1/TwinsAmyScript",
        "OlivineGym/2/TwinsMayScript",
    ),
}


def inventory() -> dict:
    return {
        "schemaVersion": 2,
        "identities": [
            {
                "trainer": "TRAINER_JOEY",
                "classification": "ordinary",
                "admitted": True,
                "projection": projection("TRAINER_YOUNGSTER_JOEY_JOHTO"),
            },
            {
                "trainer": "TRAINER_TWINS",
                "classification": "ordinary",
                "admitted": True,
                "projection": projection("TRAINER_TWINS_AMY_AND_MAY_JOHTO"),
            },
            {
                "trainer": "TRAINER_ELM",
                "classification": "story-controlled",
                "reason": "story-controlled",
                "admitted": False,
            },
            {
                "trainer": "TRAINER_TULLY",
                "classification": "unsupported",
                "reason": "objectless",
                "admitted": False,
            },
        ],
        "maps": [
            {
                "map": "Route30",
                "authority": "content",
                "events": [
                    {
                        "identity": "Route30/3/YoungsterJoeyScript",
                        "admitted": True,
                        "overworldGraphic": "OBJ_EVENT_GFX_YOUNGSTER",
                    },
                    {
                        "identity": "Route30/4/YoungsterJoeyPartnerScript",
                        "admitted": True,
                        "overworldGraphic": "OBJ_EVENT_GFX_YOUNGSTER",
                    },
                ],
            },
            {
                "map": "OlivineGym",
                "authority": "content",
                "events": [
                    {
                        "identity": "OlivineGym/1/TwinsAmyScript",
                        "admitted": True,
                        "overworldGraphic": "OBJ_EVENT_GFX_TWIN",
                    },
                    {
                        "identity": "OlivineGym/2/TwinsMayScript",
                        "admitted": True,
                        "overworldGraphic": "OBJ_EVENT_GFX_TWIN",
                    },
                ],
            },
            {"map": "ElmsLab", "authority": "absent", "events": []},
        ],
        "pairedDoubles": [
            {"trainer": "TRAINER_TWINS", "events": list(PAIRS["TRAINER_TWINS"])},
            {"trainer": "TRAINER_JOEY", "events": list(PAIRS["TRAINER_JOEY"])},
        ],
    }


def projection(target: str) -> dict:
    return {
        "target": target,
        "class": "Youngster",
        "pic": "Youngster FRLG",
        "gender": "Male",
        "music": "Male",
        "ai": "Check Bad Move",
        "reward": "preserve",
        "party": "preserve",
    }


def validate(document: dict):
    return validate_trainer_inventory_document(
        document,
        IDENTITIES,
        MAPS,
        EVENTS,
        CONTENT_MAPS,
        PAIRS,
        expectations=EXPECTATIONS,
    )


class TrainerInventoryTests(unittest.TestCase):
    def test_inventory_separates_donor_identities_from_map_placements(self) -> None:
        result = validate(inventory())
        self.assertEqual(len(result.identities), 4)
        self.assertEqual(len(result.placements), 4)
        self.assertEqual(result.identities[-1].classification, "unsupported")
        self.assertEqual(result.placements[0].object_index, 3)

    def test_identity_maps_and_events_are_exhaustive_and_canonical(self) -> None:
        document = inventory()
        document["identities"].reverse()
        with self.assertRaisesRegex(ContentPortError, "canonical donor order"):
            validate(document)

        document = inventory()
        document["maps"].pop()
        with self.assertRaisesRegex(
            ContentPortError, "missing canonical record 'ElmsLab'"
        ):
            validate(document)

        document = inventory()
        document["maps"][1]["events"].reverse()
        with self.assertRaisesRegex(ContentPortError, "canonical donor order"):
            validate(document)

    def test_ordinary_omits_reason_and_every_exclusion_is_reasoned(self) -> None:
        document = inventory()
        document["identities"][0]["reason"] = "ordinary-reachable"
        with self.assertRaisesRegex(ContentPortError, "unknown field 'reason'"):
            validate(document)

        document = inventory()
        del document["identities"][-1]["reason"]
        with self.assertRaisesRegex(ContentPortError, "missing field 'reason'"):
            validate(document)

        document = inventory()
        document["identities"][2]["reason"] = ""
        with self.assertRaisesRegex(ContentPortError, "non-empty"):
            validate(document)

    def test_admission_is_explicit_and_matches_linked_identity(self) -> None:
        document = inventory()
        document["identities"][0]["admitted"] = False
        document["identities"][0]["reason"] = "test exclusion"
        del document["identities"][0]["projection"]
        with self.assertRaisesRegex(ContentPortError, "ordinary trainers are admitted"):
            validate(document)

        document = inventory()
        document["maps"][0]["events"][0]["admitted"] = False
        del document["maps"][0]["events"][0]["overworldGraphic"]
        with self.assertRaisesRegex(ContentPortError, "linked trainer admission"):
            validate(document)

    def test_map_authority_distinguishes_absent_from_content_empty(self) -> None:
        document = inventory()
        document["maps"][-1]["authority"] = "content"
        with self.assertRaisesRegex(ContentPortError, "expected 'absent'"):
            validate(document)

    def test_projection_and_graphic_policy_are_strict_and_admitted_only(self) -> None:
        document = inventory()
        del document["identities"][0]["projection"]
        with self.assertRaisesRegex(ContentPortError, "missing field 'projection'"):
            validate(document)

        document = inventory()
        del document["maps"][0]["events"][0]["overworldGraphic"]
        with self.assertRaisesRegex(
            ContentPortError, "missing field 'overworldGraphic'"
        ):
            validate(document)

        document = inventory()
        document["identities"][0]["projection"]["ai"] = "Basic"
        with self.assertRaisesRegex(ContentPortError, "Check Bad Move"):
            validate(document)

        document = inventory()
        document["identities"][2]["projection"] = projection(
            "TRAINER_PROFESSOR_ELM_JOHTO"
        )
        with self.assertRaisesRegex(ContentPortError, "unknown field 'projection'"):
            validate(document)

        document = inventory()
        document["maps"][0]["events"][0]["admitted"] = False
        with self.assertRaisesRegex(
            ContentPortError, "unknown field 'overworldGraphic'"
        ):
            validate(document)

        document = inventory()
        document["maps"][0]["events"][0]["overworldGraphic"] = "Youngster"
        with self.assertRaisesRegex(ContentPortError, "object graphic symbol"):
            validate(document)

    def test_projection_targets_are_unique_and_region_qualified(self) -> None:
        document = inventory()
        document["identities"][1]["projection"]["target"] = document["identities"][0][
            "projection"
        ]["target"]
        with self.assertRaisesRegex(ContentPortError, "duplicate projection target"):
            validate(document)

        document = inventory()
        document["identities"][0]["projection"]["target"] = "TRAINER_JOEY"
        with self.assertRaisesRegex(ContentPortError, "region-qualified"):
            validate(document)

    def test_event_identity_is_authenticated_and_links_one_classified_trainer(
        self,
    ) -> None:
        document = inventory()
        document["maps"][0]["events"][0]["identity"] = "Route30/3/OtherScript"
        with self.assertRaisesRegex(ContentPortError, "exactly one authenticated"):
            validate(document)

        events = copy.deepcopy(EVENTS)
        events["Route30"]["Route30/3/YoungsterJoeyScript"] = ("TRAINER_UNKNOWN",)
        with self.assertRaisesRegex(ContentPortError, "unclassified trainer"):
            validate_trainer_inventory_document(
                inventory(),
                IDENTITIES,
                MAPS,
                events,
                CONTENT_MAPS,
                PAIRS,
                expectations=EXPECTATIONS,
            )

    def test_paired_double_is_one_shared_identity_with_two_placements(self) -> None:
        result = validate(inventory())
        self.assertEqual(result.paired_doubles["TRAINER_TWINS"], PAIRS["TRAINER_TWINS"])
        self.assertEqual(
            tuple(result.paired_doubles), ("TRAINER_TWINS", "TRAINER_JOEY")
        )
        with self.assertRaises(TypeError):
            result.paired_doubles["TRAINER_OTHER"] = ("a", "b")  # type: ignore[index]

        document = inventory()
        document["pairedDoubles"][0]["events"].reverse()
        with self.assertRaisesRegex(ContentPortError, "authenticated topology"):
            validate_trainer_inventory_document(
                document,
                IDENTITIES,
                MAPS,
                EVENTS,
                CONTENT_MAPS,
                PAIRS,
                expectations=EXPECTATIONS,
            )

    def test_digest_is_stable_and_membership_digest_ignores_order(self) -> None:
        document = inventory()
        reordered = {key: document[key] for key in reversed(document)}
        self.assertEqual(
            stable_inventory_digest(document), stable_inventory_digest(reordered)
        )
        self.assertEqual(
            inventory_membership_digest(IDENTITIES),
            inventory_membership_digest(reversed(IDENTITIES)),
        )
        self.assertEqual(validate(document).digest, stable_inventory_digest(document))

    def test_downstream_exact_cover_uses_classification_authority(self) -> None:
        result = validate(inventory())
        require_identity_exact_cover(
            result,
            ("TRAINER_JOEY", "TRAINER_TWINS"),
            admitted=True,
        )
        with self.assertRaisesRegex(ContentPortError, "missing classified identity"):
            require_identity_exact_cover(
                result, ("TRAINER_JOEY",), classification="ordinary"
            )
        require_placement_exact_cover(
            result, (record.identity for record in result.placements), admitted=True
        )
        with self.assertRaisesRegex(ContentPortError, "missing classified placement"):
            require_placement_exact_cover(
                result, (result.placements[0].identity,), admitted=True
            )
        require_projection_exact_cover(
            result, (record.trainer for record in result.identities if record.admitted)
        )
        require_overworld_graphic_exact_cover(
            result, (record.identity for record in result.placements if record.admitted)
        )
        with self.assertRaisesRegex(ContentPortError, "missing projection"):
            require_projection_exact_cover(result, ("TRAINER_JOEY",))

    def test_loader_reports_invalid_json_and_validates_loaded_document(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trainer_inventory.json"
            path.write_text(json.dumps(inventory()), encoding="utf-8")
            self.assertEqual(
                len(
                    load_trainer_inventory(
                        path,
                        IDENTITIES,
                        MAPS,
                        EVENTS,
                        CONTENT_MAPS,
                        PAIRS,
                        expectations=EXPECTATIONS,
                    ).placements
                ),
                4,
            )
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError, "cannot load trainer inventory"
            ):
                load_trainer_inventory(
                    path,
                    IDENTITIES,
                    MAPS,
                    EVENTS,
                    CONTENT_MAPS,
                    PAIRS,
                    expectations=EXPECTATIONS,
                )
            path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
            with self.assertRaisesRegex(ContentPortError, "duplicate JSON field"):
                load_trainer_inventory(
                    path,
                    IDENTITIES,
                    MAPS,
                    EVENTS,
                    CONTENT_MAPS,
                    PAIRS,
                    expectations=EXPECTATIONS,
                )

    def test_caller_can_pin_the_reviewed_document_digest(self) -> None:
        document = inventory()
        digest = stable_inventory_digest(document)
        result = validate_trainer_inventory_document(
            document,
            IDENTITIES,
            MAPS,
            EVENTS,
            CONTENT_MAPS,
            PAIRS,
            expectations=EXPECTATIONS,
            expected_digest=digest,
        )
        self.assertEqual(result.digest, digest)
        with self.assertRaisesRegex(ContentPortError, "digest mismatch"):
            validate_trainer_inventory_document(
                document,
                IDENTITIES,
                MAPS,
                EVENTS,
                CONTENT_MAPS,
                PAIRS,
                expectations=EXPECTATIONS,
                expected_digest="0" * 64,
            )


if __name__ == "__main__":
    unittest.main()
