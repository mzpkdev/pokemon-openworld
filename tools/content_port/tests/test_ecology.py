from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.content_port.ecology import (
    build_authenticated_profile_lookup,
    donor_profile_matches,
    normalize_donor_profile,
    source_method_is_runtime_eligible,
    stable_digest,
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
        condition="day",
        provenance_slice="primary-johto-block",
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

    def test_source_placeholders_are_never_runtime_eligible(self) -> None:
        normalized = profile()
        self.assertFalse(source_method_is_runtime_eligible(normalized["methods"][0]))
        self.assertFalse(source_method_is_runtime_eligible(normalized["methods"][1]))


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
                    "status": "reviewed",
                    "profiles": [route39],
                    "reviewNotes": ["Preserves the complete donor observation."],
                },
            ]
        )
        self.authenticated = build_authenticated_profile_lookup([route39])

    def test_reviewed_and_blocked_records_are_valid(self) -> None:
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
        validate_classification_document(classification, canonical_maps)
        ordinary_maps = [
            row["map"] for row in classification["maps"] if row["kind"] == "ordinary"
        ]
        species = {
            slot["species"]
            for record in ecology_document["records"]
            for profile_value in record.get("profiles", [])
            for method in profile_value["methods"]
            for slot in method["slots"]
        }
        methods = {
            method["method"]
            for record in ecology_document["records"]
            for profile_value in record.get("profiles", [])
            for method in profile_value["methods"]
        }
        validate_ecology_document(
            ecology_document,
            ordinary_maps,
            None,
            source_identity=source_identity,
            supported_methods=methods,
            supported_species=species,
        )
        self.assertEqual(len(canonical_maps), 254)
        self.assertEqual(len(ordinary_maps), 89)
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
