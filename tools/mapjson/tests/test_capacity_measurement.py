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


ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "tools/foundation/capacity_policy.json"


class CapacityMeasurementTests(unittest.TestCase):
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

    def test_missing_git_identity_fails_closed_without_reviewed_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(MeasurementError, "--commit"):
                donor_commit(Path(directory), None)


if __name__ == "__main__":
    unittest.main()
