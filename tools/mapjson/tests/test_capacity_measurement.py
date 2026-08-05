import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from tools.foundation.measure_reference_headroom import (
    MeasurementError,
    donor_commit,
    union_bytes,
)
from tools.foundation.validate_artifact import ValidationError, load_capacity_policy


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "tools/foundation/capacity_policy.json"


class CapacityMeasurementTests(unittest.TestCase):
    def assert_policy_rejected(self, policy: dict) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capacity-policy.json"
            path.write_text(json.dumps(policy))
            with self.assertRaises(ValidationError):
                load_capacity_policy(path)

    def test_checked_policy_is_linked_symbol_evidence_with_exact_commit(self) -> None:
        policy = json.loads(POLICY.read_text())
        self.assertEqual(policy["schemaVersion"], 2)
        self.assertEqual(policy["measurementKind"], "linked-symbol-range-attribution")
        self.assertRegex(policy["commit"], r"^[0-9a-f]{40}$")
        self.assertFalse(policy["commit"].startswith("snapshot-sha256:"))
        self.assertEqual(
            policy["requiredHeadroomBytes"],
            math.ceil(policy["johtoResidentBytes"] * 1.25) + 524288,
        )
        categories = policy["evidenceCategories"]
        for required in (
            "mapLayoutEventData",
            "scriptsTextCallbacks",
            "tilesetResourcesCallbacks",
            "objectGraphics",
            "trainerParties",
            "trainerArt",
            "trainerRecords",
            "regionMapEntries",
        ):
            self.assertGreater(categories[required], 0, required)
        self.assertEqual(categories["trainerParties"], 25632)
        self.assertEqual(categories["trainerArt"], 8460)

    def test_symbol_range_mutation_changes_resident_cost_without_double_counting(
        self,
    ) -> None:
        original = union_bytes([(0x08000100, 0x08000120), (0x08000110, 0x08000130)])
        mutated = union_bytes(
            [
                (0x08000100, 0x08000120),
                (0x08000110, 0x08000130),
                (0x08000200, 0x08000211),
            ]
        )
        self.assertEqual(original, 0x30)
        self.assertEqual(mutated - original, 0x11)

    def test_resident_bytes_are_bound_to_measured_evidence_categories(self) -> None:
        policy = json.loads(POLICY.read_text())
        policy["evidenceCategories"]["deduplicatedSymbolRanges"] -= 1
        self.assert_policy_rejected(policy)

    def test_every_reviewed_evidence_category_is_pinned(self) -> None:
        policy = json.loads(POLICY.read_text())
        for category in policy["evidenceCategories"]:
            mutation = copy.deepcopy(policy)
            mutation["evidenceCategories"][category] += 1
            with self.subTest(category=category):
                self.assert_policy_rejected(mutation)

    def test_coordinated_measurement_mutation_cannot_collapse_capacity_floor(
        self,
    ) -> None:
        policy = json.loads(POLICY.read_text())
        mutations = []

        resident = copy.deepcopy(policy)
        resident["evidenceCategories"]["deduplicatedSymbolRanges"] -= 1
        resident["johtoResidentBytes"] -= 1
        resident["requiredHeadroomBytes"] = (
            math.ceil(resident["johtoResidentBytes"] * 1.25)
            + resident["travelStoryReserveBytes"]
        )
        mutations.append(("resident evidence", resident))

        reserve = copy.deepcopy(policy)
        reserve["travelStoryReserveBytes"] -= 1
        reserve["requiredHeadroomBytes"] -= 1
        mutations.append(("travel and story reserve", reserve))

        multiplier = copy.deepcopy(policy)
        multiplier["integrationMultiplier"] = 1.0
        multiplier["requiredHeadroomBytes"] = (
            multiplier["johtoResidentBytes"] + multiplier["travelStoryReserveBytes"]
        )
        mutations.append(("integration multiplier", multiplier))

        for label, mutation in mutations:
            with self.subTest(label=label):
                self.assert_policy_rejected(mutation)

    def test_policy_rejects_schema_and_valid_shaped_provenance_substitutions(
        self,
    ) -> None:
        policy = json.loads(POLICY.read_text())
        mutations = {
            "schema": ("schemaVersion", 1),
            "source": ("source", ".references/another-donor"),
            "measurement": ("measurementKind", "source-file-size"),
            "commit": ("commit", "0" * 40),
            "provenance": ("provenanceMode", "git"),
            "source tree": ("sourceTreeDigest", "0" * 64),
            "linked evidence": ("evidenceDigest", "0" * 64),
            "evidence file count": (
                "evidenceFileCount",
                policy["evidenceFileCount"] + 1,
            ),
            "layout count": ("johtoLayoutCount", policy["johtoLayoutCount"] + 1),
            "map count": ("johtoMapCount", policy["johtoMapCount"] + 1),
        }
        for label, (field, value) in mutations.items():
            mutation = copy.deepcopy(policy)
            mutation[field] = value
            with self.subTest(label=label):
                self.assert_policy_rejected(mutation)

    def test_missing_git_identity_fails_closed_without_reviewed_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MeasurementError, "--commit"):
                donor_commit(Path(directory), None)


if __name__ == "__main__":
    unittest.main()
