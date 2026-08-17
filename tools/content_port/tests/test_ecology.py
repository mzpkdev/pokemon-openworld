from __future__ import annotations

import copy
import json
import re
import unittest
from pathlib import Path

from tools.content_port.ecology import (
    build_authenticated_profile_lookup,
    donor_profile_condition,
    donor_provenance_slice,
    donor_profile_matches,
    normalize_donor_profile,
    stable_digest,
    SUPPORTED_SOURCE_METHODS,
    validate_classification_document,
    validate_ecology_document,
)
from tools.content_port.errors import ContentPortError


ROOT = Path(__file__).resolve().parents[3]
JOHTO = ROOT / "tools/content_port/ports/johto"
SOURCE = {
    "role": "content",
    "name": "Pokemon Heart & Soul",
    "repository": "PokemonHnS-Development/pokemonHnS",
    "commit": "1" * 40,
    "treeDigest": "2" * 64,
    "path": "src/data/wild_encounters.json",
}
SPECIES = {"SPECIES_RATTATA", "SPECIES_SENTRET"}
METHODS = {"land_mons", "fishing_mons"}
ALIAS_MAPS = {
    "LakeOfRageLowTide",
    "Route26North",
    "JohtoVictoryRoad_1F",
    "JohtoVictoryRoad_B1F",
    "JohtoVictoryRoad_B2F",
}
SPECIAL_OWNERS = {
    "NationalPark_BugContest": "bug-catching-contest-reservation",
    "TinTower_RoofDay": "static-legendary-reservation",
    "WhirlIslands_LugiaChamber": "static-legendary-reservation",
    "EmbeddedTower": "static-legendary-reservation",
    "DragonsDen_Shrine": "gift-encounter-reservation",
    "SafariZoneGate": "safari-reservation",
    "SafariZoneGate_PokemonCenter": "safari-reservation",
    "SafariZoneGate_SafariZoneEntrance": "safari-reservation",
    "SafariZoneIndoor": "safari-reservation",
    "SafariZone_Enterance": "safari-reservation",
    "SafariZone_Low_Left": "safari-reservation",
    "SafariZone_Low_Mid": "safari-reservation",
    "SafariZone_Low_Right": "safari-reservation",
    "SafariZone_Top_Mid": "safari-reservation",
    "SafariZone_Top_Right": "safari-reservation",
    "SafariZone1": "safari-reservation",
    "SafariZone2": "safari-reservation",
    "SafariZone3": "safari-reservation",
}
ROUTE39_SOURCE_DIGEST = (
    "0bc050ec9aeb066e2b5fe3b8c178e0064aeeb636b51649c600c0dbfa4718f033"
)
FIELDS = [
    {"type": "land_mons", "encounter_rates": [70, 30]},
    {
        "type": "fishing_mons",
        "encounter_rates": [70],
        "groups": {"old_rod": [0]},
    },
]


def donor_encounter() -> dict:
    return {
        "map": "MAP_ROUTE39",
        "base_label": "gRoute39",
        "land_mons": {
            "encounter_rate": 0,
            "mons": [
                {"min_level": 4, "max_level": 5, "species": "SPECIES_NONE"},
                {"min_level": 5, "max_level": 5, "species": "SPECIES_SENTRET"},
            ],
        },
        "fishing_mons": {
            "encounter_rate": 15,
            "mons": [
                {"min_level": 5, "max_level": 5, "species": "SPECIES_RATTATA"},
                {"min_level": 6, "max_level": 6, "species": "SPECIES_SENTRET"},
            ],
        },
    }


def profile() -> dict:
    return normalize_donor_profile(
        donor_encounter(),
        FIELDS,
        source_index=339,
    )


def ecology(records: list[dict]) -> dict:
    return {"schemaVersion": 1, "source": dict(SOURCE), "records": records}


def validate(document: dict, authenticated: dict | None, **kwargs: object) -> None:
    validate_ecology_document(
        document,
        ["Route38", "Route39"],
        authenticated,
        source_identity=SOURCE,
        supported_methods=METHODS,
        supported_species=SPECIES,
        **kwargs,
    )


class ClassificationTests(unittest.TestCase):
    def test_classification_uses_caller_provided_canonical_order(self) -> None:
        document = {
            "schemaVersion": 1,
            "maps": [
                {"map": "Route39", "kind": "special", "owner": "roamer"},
                {"map": "Route38", "kind": "ordinary"},
            ],
        }
        validate_classification_document(document, ["Route39", "Route38"])
        with self.assertRaisesRegex(ContentPortError, "canonical map order"):
            validate_classification_document(document, ["Route38", "Route39"])

    def test_special_reservations_are_an_exact_contract(self) -> None:
        document = {
            "schemaVersion": 1,
            "maps": [{"map": "A", "kind": "special", "owner": "static-reservation"}],
        }
        validate_classification_document(
            document,
            ["A"],
            expected_special_owners={"A": "static-reservation"},
        )
        with self.assertRaisesRegex(ContentPortError, "ownership contract"):
            validate_classification_document(
                document,
                ["A"],
                expected_special_owners={"A": "other-reservation"},
            )

    def test_classification_is_exhaustive_disjoint_and_strict(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "missing canonical map"):
            validate_classification_document(
                {"schemaVersion": 1, "maps": [{"map": "A", "kind": "ordinary"}]},
                ["A", "B"],
            )
        with self.assertRaisesRegex(ContentPortError, "duplicate classification"):
            validate_classification_document(
                {
                    "schemaVersion": 1,
                    "maps": [
                        {"map": "A", "kind": "ordinary"},
                        {"map": "A", "kind": "ordinary"},
                    ],
                },
                ["A"],
            )
        with self.assertRaisesRegex(ContentPortError, "missing field 'owner'"):
            validate_classification_document(
                {"schemaVersion": 1, "maps": [{"map": "A", "kind": "special"}]},
                ["A"],
            )
        validate_classification_document(
            {"schemaVersion": 1, "maps": [{"map": "A", "kind": "alias"}]},
            ["A"],
        )
        with self.assertRaisesRegex(ContentPortError, "unknown field 'owner'"):
            validate_classification_document(
                {
                    "schemaVersion": 1,
                    "maps": [{"map": "A", "kind": "alias", "owner": "other"}],
                },
                ["A"],
            )


class DonorNormalizationTests(unittest.TestCase):
    def test_normalization_preserves_source_order_and_undefined_weights(self) -> None:
        normalized = profile()
        self.assertEqual(
            normalized["methods"][0],
            {
                "method": "land_mons",
                "encounterRate": 0,
                "slots": [
                    {
                        "index": 0,
                        "weight": 70,
                        "species": "SPECIES_NONE",
                        "observedMinLevel": 4,
                        "observedMaxLevel": 5,
                    },
                    {
                        "index": 1,
                        "weight": 30,
                        "species": "SPECIES_SENTRET",
                        "observedMinLevel": 5,
                        "observedMaxLevel": 5,
                    },
                ],
            },
        )
        self.assertEqual(normalized["methods"][1]["slots"][1]["weight"], None)
        self.assertEqual(normalized["methods"][1]["slots"][1]["rodGroup"], None)

    def test_lookup_and_matching_compare_every_normalized_value(self) -> None:
        normalized = profile()
        lookup = build_authenticated_profile_lookup([normalized])
        key = ("MAP_ROUTE39", "gRoute39", "day")
        self.assertTrue(donor_profile_matches(normalized, lookup[key]))
        changed = copy.deepcopy(normalized)
        changed["methods"][0]["slots"].reverse()
        self.assertFalse(donor_profile_matches(changed, lookup[key]))
        with self.assertRaisesRegex(ContentPortError, "duplicate donor profile"):
            build_authenticated_profile_lookup([normalized, normalized])

    def test_condition_and_slice_are_derived_from_donor_facts(self) -> None:
        self.assertEqual(donor_profile_condition("gRoute39_Night"), "night")
        self.assertEqual(donor_profile_condition("gRoute39"), "day")
        self.assertEqual(donor_profile_condition("gMtSilver_SnowUnused"), "legacy-day")
        self.assertEqual(donor_profile_condition("gMtSilver_Snow"), "modern-day")
        self.assertEqual(donor_provenance_slice(339), "primary-johto-block")
        self.assertEqual(donor_provenance_slice(503), "supplemental-mixed-tail")
        with self.assertRaisesRegex(ContentPortError, "outside the reviewed"):
            donor_provenance_slice(442)

    def test_unknown_nested_donor_fields_fail_closed(self) -> None:
        changed_fields = copy.deepcopy(FIELDS)
        changed_fields[0]["new_semantic"] = True
        with self.assertRaisesRegex(ContentPortError, "unknown field"):
            normalize_donor_profile(donor_encounter(), changed_fields, source_index=339)
        changed_encounter = donor_encounter()
        changed_encounter["land_mons"]["new_semantic"] = True
        with self.assertRaisesRegex(ContentPortError, "unknown field"):
            normalize_donor_profile(changed_encounter, FIELDS, source_index=339)
        changed_encounter = donor_encounter()
        changed_encounter["land_mons"]["mons"][0]["new_semantic"] = True
        with self.assertRaisesRegex(ContentPortError, "unknown field"):
            normalize_donor_profile(changed_encounter, FIELDS, source_index=339)


class EcologyTests(unittest.TestCase):
    def setUp(self) -> None:
        route39 = profile()
        self.document = ecology(
            [
                {
                    "map": "Route38",
                    "status": "blocked",
                    "reason": "donor conflict",
                    "evidenceNeeded": "reviewed variant decision",
                },
                {
                    "map": "Route39",
                    "status": "inventoried",
                    "profiles": [route39],
                    "reviewNotes": ["Preserves the complete donor observation."],
                },
            ]
        )
        self.authenticated = build_authenticated_profile_lookup([route39])

    def test_inventoried_and_blocked_records_are_valid(self) -> None:
        protected = copy.deepcopy(self.document["records"][1]["profiles"])
        validate(
            self.document,
            self.authenticated,
            protected_route39_profile=protected,
        )
        validate(
            self.document,
            self.authenticated,
            protected_route39_profile=stable_digest(protected),
        )

    def test_source_pin_profile_and_record_fields_are_strict(self) -> None:
        changed = copy.deepcopy(self.document)
        del changed["source"]["role"]
        with self.assertRaisesRegex(ContentPortError, "missing field 'role'"):
            validate(changed, self.authenticated)
        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"][0]["tier"] = 1
        with self.assertRaisesRegex(ContentPortError, "unknown field 'tier'"):
            validate(changed, self.authenticated)
        changed = copy.deepcopy(self.document)
        changed["records"][1]["reviewNotes"] = []
        with self.assertRaisesRegex(ContentPortError, "at least one review note"):
            validate(changed, self.authenticated)

    def test_exact_donor_values_order_and_identity_are_enforced(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"][0]["methods"][0]["slots"][0]["weight"] = 60
        with self.assertRaisesRegex(ContentPortError, "authenticated donor values"):
            validate(changed, self.authenticated)
        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"].append(
            copy.deepcopy(changed["records"][1]["profiles"][0])
        )
        with self.assertRaisesRegex(ContentPortError, "duplicate donor profile"):
            validate(changed, self.authenticated)

    def test_target_identity_and_global_profile_ownership_are_enforced(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "target map identity"):
            validate(
                self.document,
                self.authenticated,
                source_map_by_target={"Route39": "MAP_ROUTE38"},
            )
        changed = copy.deepcopy(self.document)
        changed["records"][0] = {
            "map": "Route38",
            "status": "inventoried",
            "profiles": [copy.deepcopy(changed["records"][1]["profiles"][0])],
            "reviewNotes": ["Synthetic ownership collision."],
        }
        with self.assertRaisesRegex(ContentPortError, "already assigned"):
            validate(changed, self.authenticated)

    def test_blocked_map_gate_is_exact(self) -> None:
        validate(
            self.document,
            self.authenticated,
            expected_blocked_maps={"Route38"},
        )
        with self.assertRaisesRegex(ContentPortError, "evidence gate"):
            validate(
                self.document,
                self.authenticated,
                expected_blocked_maps={"Route39"},
            )

    def test_source_slot_shape_levels_and_fishing_groups_are_enforced(self) -> None:
        changed = copy.deepcopy(self.document)
        slots = changed["records"][1]["profiles"][0]["methods"][1]["slots"]
        slots[0]["weight"] = None
        slots[0]["rodGroup"] = None
        slots[1]["weight"] = 5
        slots[1]["rodGroup"] = "old_rod"
        with self.assertRaisesRegex(ContentPortError, "defined weights cannot follow"):
            validate(changed, None)
        changed = copy.deepcopy(self.document)
        slot = changed["records"][1]["profiles"][0]["methods"][1]["slots"][0]
        slot["rodGroup"] = None
        with self.assertRaisesRegex(ContentPortError, "non-empty"):
            validate(changed, None)
        changed = copy.deepcopy(self.document)
        slot = changed["records"][1]["profiles"][0]["methods"][0]["slots"][0]
        slot["observedMaxLevel"] = 101
        with self.assertRaisesRegex(ContentPortError, "observedMinLevel"):
            validate(changed, None)

    def test_blocked_records_have_no_profiles_and_route39_is_protected(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["records"][0]["profiles"] = []
        with self.assertRaisesRegex(ContentPortError, "unknown field 'profiles'"):
            validate(changed, self.authenticated)
        with self.assertRaisesRegex(ContentPortError, "protected profile"):
            validate(
                self.document,
                self.authenticated,
                protected_route39_profile=[],
            )


class ProductionArtifactsTests(unittest.TestCase):
    def test_production_documents_cover_resident_and_ordinary_maps(self) -> None:
        capabilities = json.loads((JOHTO / "capabilities.json").read_text())
        classification = json.loads(
            (JOHTO / "encounter_classification.json").read_text()
        )
        ecology_document = json.loads((JOHTO / "encounter_ecology.json").read_text())
        port = json.loads((JOHTO / "port.json").read_text())
        donor = port["donors"]["content"]
        source_identity = {
            "role": "content",
            "name": donor["name"],
            "repository": donor["repository"],
            "commit": donor["commit"],
            "treeDigest": donor["treeDigest"],
            "path": "src/data/wild_encounters.json",
        }
        canonical_maps = [row["map"] for row in capabilities["maps"]]
        validate_classification_document(
            classification,
            canonical_maps,
            expected_special_owners=SPECIAL_OWNERS,
        )
        ordinary_maps = [
            row["map"] for row in classification["maps"] if row["kind"] == "ordinary"
        ]
        alias_maps = {
            row["map"] for row in classification["maps"] if row["kind"] == "alias"
        }
        species = set(
            re.findall(
                r"\bSPECIES_[A-Z0-9_]+\b",
                (ROOT / "include/constants/species.h").read_text(),
            )
        )
        source_map_by_target = {
            record["map"]: json.loads(
                (ROOT / "data/maps" / record["map"] / "map.json").read_text()
            )["id"]
            for record in ecology_document["records"]
            if record["status"] == "inventoried"
        }
        validate_ecology_document(
            ecology_document,
            ordinary_maps,
            None,
            source_identity=source_identity,
            supported_methods=SUPPORTED_SOURCE_METHODS,
            supported_species=species,
            source_map_by_target=source_map_by_target,
            expected_blocked_maps=set(),
            protected_route39_profile=ROUTE39_SOURCE_DIGEST,
        )
        self.assertEqual(len(canonical_maps), 255)
        self.assertEqual(len(ordinary_maps), 89)
        kinds = [row["kind"] for row in classification["maps"]]
        self.assertEqual(kinds.count("ordinary"), 89)
        self.assertEqual(kinds.count("encounter-free"), 148)
        self.assertEqual(kinds.count("special"), 18)
        statuses = [record["status"] for record in ecology_document["records"]]
        self.assertEqual(statuses.count("inventoried"), 84)
        self.assertEqual(statuses.count("blocked"), 0)
        profiles = [
            profile_value
            for record in ecology_document["records"]
            for profile_value in record.get("profiles", [])
        ]
        primary = [
            value
            for value in profiles
            if value["provenanceSlice"] == "primary-johto-block"
        ]
        supplemental = [
            value
            for value in profiles
            if value["provenanceSlice"] == "supplemental-mixed-tail"
        ]
        self.assertEqual(len(primary), 103)
        self.assertEqual(len({value["sourceMap"] for value in primary}), 59)
        self.assertEqual(len(supplemental), 37)
        self.assertEqual(len({value["sourceMap"] for value in supplemental}), 25)
        forbidden = {"tier", "tiers", "band", "bands", "runtime", "fallback"}

        def inspect(value: object) -> None:
            if isinstance(value, dict):
                self.assertFalse(
                    {
                        key
                        for key in value
                        if any(token in key.lower() for token in forbidden)
                    }
                )
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(classification)
        inspect(ecology_document)


if __name__ == "__main__":
    unittest.main()
