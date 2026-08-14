from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from tools.content_port.ecology_fallbacks import validate_fallback_document
from tools.content_port.errors import ContentPortError


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "tools/content_port/ports/johto/encounter_fallbacks.json"


def production_document() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


class EcologyFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.document = production_document()

    def assert_rejected(self, changed: dict, message: str) -> None:
        with self.assertRaisesRegex(ContentPortError, message):
            validate_fallback_document(changed)

    def test_production_artifact_is_the_exact_reviewed_contract(self) -> None:
        validate_fallback_document(self.document)
        self.assertEqual(
            [record["targetName"] for record in self.document["records"]],
            [
                "LakeOfRageLowTide",
                "Route26North",
                "JohtoVictoryRoad_1F",
                "JohtoVictoryRoad_B1F",
                "JohtoVictoryRoad_B2F",
            ],
        )
        self.assertEqual(self.document["records"][1]["targetMap"], "MAP_ROUTE26NORTH")

    def test_source_pins_are_exact_and_separate(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["ecologySource"]["commit"] = "0" * 40
        self.assert_rejected(changed, "authenticated|pinned")

        changed = copy.deepcopy(self.document)
        changed["spatialSource"]["treeDigest"] = "0" * 64
        self.assert_rejected(changed, "authenticated|pinned")

        changed = copy.deepcopy(self.document)
        changed["ecologySource"]["layoutIndexPath"] = "data/layouts/layouts.json"
        self.assert_rejected(changed, "unknown field")

    def test_exact_five_targets_and_target_ids_are_enforced(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["records"].pop()
        self.assert_rejected(changed, "exactly five")

        changed = copy.deepcopy(self.document)
        changed["records"][4] = copy.deepcopy(changed["records"][3])
        self.assert_rejected(changed, "duplicate fallback target")

        changed = copy.deepcopy(self.document)
        changed["records"][1]["targetMap"] = "MAP_ROUTE_26_NORTH"
        self.assert_rejected(changed, "targetMap")

    def test_selected_profile_labels_and_day_night_shape_are_exact(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"].pop()
        self.assert_rejected(changed, "day/night profile shape")

        changed = copy.deepcopy(self.document)
        changed["records"][2]["profiles"][0]["sourceLabel"] = "gVictoryRoad_1F_CDay"
        self.assert_rejected(changed, "pinned evidence contract")

        changed = copy.deepcopy(self.document)
        changed["records"][3]["profiles"][1]["condition"] = "day"
        self.assert_rejected(changed, "pinned evidence contract")

        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"][1]["targetLabel"] = changed["records"][1][
            "profiles"
        ][0]["targetLabel"]
        self.assert_rejected(changed, "duplicate label")

    def test_source_maps_and_no_alias_claims_are_enforced(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["records"][0]["sourceMap"] = "MAP_LAKE_OF_RAGE_LOW_TIDE"
        self.assert_rejected(changed, "sourceMap")

        changed = copy.deepcopy(self.document)
        changed["records"][2]["equivalentMap"] = "MAP_VICTORY_ROAD_1F"
        self.assert_rejected(changed, "unknown field 'equivalentMap'")

        changed = copy.deepcopy(self.document)
        changed["records"][1]["profiles"][0]["alias"] = "gRoute26"
        self.assert_rejected(changed, "unknown field 'alias'")

    def test_spatial_paths_layout_facts_and_hashes_fail_closed(self) -> None:
        mutations = (
            (0, "targetMapPath", "data/maps/LakeOfRage/map.json"),
            (0, "relationship", "byte-identical-layout"),
            (1, "sourceMapPath", "data/maps/Route27/map.json"),
        )
        for record_index, key, value in mutations:
            with self.subTest(record=record_index, key=key):
                changed = copy.deepcopy(self.document)
                changed["records"][record_index]["spatialEvidence"][key] = value
                self.assert_rejected(changed, "pinned fallback evidence")

        changed = copy.deepcopy(self.document)
        changed["records"][0]["spatialEvidence"]["target"]["width"] = 63
        self.assert_rejected(changed, "pinned fallback evidence")

        changed = copy.deepcopy(self.document)
        changed["records"][0]["spatialEvidence"]["source"]["secondaryTileset"] = (
            "gTileset_Lake"
        )
        self.assert_rejected(changed, "pinned fallback evidence")

        changed = copy.deepcopy(self.document)
        changed["records"][1]["spatialEvidence"]["facts"][1]["value"]["direction"] = (
            "down"
        )
        self.assert_rejected(changed, "pinned fallback evidence")

        changed = copy.deepcopy(self.document)
        changed["records"][4]["spatialEvidence"]["source"]["mapBinSha256"] = "0" * 64
        self.assert_rejected(changed, "pinned fallback evidence")

    def test_unknown_fields_and_rationale_mutations_fail_closed(self) -> None:
        changed = copy.deepcopy(self.document)
        changed["runtimeSchema"] = "tiers"
        self.assert_rejected(changed, "unknown field")

        changed = copy.deepcopy(self.document)
        changed["records"][0]["rationale"] += " This is an alias."
        self.assert_rejected(changed, "pinned fallback evidence")


if __name__ == "__main__":
    unittest.main()
