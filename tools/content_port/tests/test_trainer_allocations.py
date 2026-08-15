from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import unittest

from tools.content_port.trainer_allocations import (
    AllocationError,
    BITMAP_BITS,
    BITMAP_BYTES,
    BITMAP_FIRST,
    EXISTING,
    FIRST_NEW_ID,
    INVENTORY,
    PUBLICATION,
    SOURCES,
    TRAINER_CAPACITY,
    TRAINER_COUNT,
    admitted_targets,
    new_allocations,
    update_publication,
)


ROOT = Path(__file__).resolve().parents[3]


class JohtoTrainerAllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY.read_text())
        cls.sources = json.loads(SOURCES.read_text())
        cls.publication = json.loads(PUBLICATION.read_text())

    def test_inventory_exactly_covers_existing_and_appended_identities(self) -> None:
        admitted = admitted_targets(self.inventory)
        allocations = new_allocations(self.inventory)

        self.assertEqual(len(admitted), 195)
        self.assertEqual(
            set(EXISTING), set(admitted) - {item[0] for item in allocations}
        )
        self.assertEqual(len(allocations), 193)
        self.assertEqual(allocations[0][1], FIRST_NEW_ID)
        self.assertEqual(allocations[-1][1], TRAINER_COUNT - 1)
        self.assertEqual({value for _, value in allocations}, set(range(1483, 1676)))
        self.assertEqual(TRAINER_CAPACITY, 1792)

    def test_persistence_policy_has_exact_bitmap_bounds(self) -> None:
        defeat = self.sources["trainerDefeat"]
        self.assertEqual(defeat["count"], TRAINER_COUNT)
        self.assertEqual(
            defeat["bitmapStorage"],
            {
                "firstTrainerId": BITMAP_FIRST,
                "bitCount": BITMAP_BITS,
                "byteCount": BITMAP_BYTES,
            },
        )
        self.assertEqual((BITMAP_BITS, BITMAP_BYTES), (818, 103))

    def test_append_only_publication_has_unique_exact_physical_bindings(self) -> None:
        allocations = dict(new_allocations(self.inventory))
        published = {
            item["symbol"]: item
            for item in self.publication["entries"]
            if item["domain"] == "trainerIds" and item["symbol"] in allocations
        }
        self.assertEqual(set(published), set(allocations))
        for symbol, value in allocations.items():
            self.assertEqual(published[symbol]["value"], value)
            self.assertEqual(
                published[symbol]["physicalBinding"],
                {"bitIndex": value - BITMAP_FIRST, "kind": "trainer-defeat-bitmap"},
            )

    def test_capacity_headroom_is_not_allocated_content(self) -> None:
        allocated = {
            item["value"]
            for item in self.publication["entries"]
            if item["domain"] == "trainerIds"
        }
        self.assertTrue(
            set(range(TRAINER_COUNT, TRAINER_CAPACITY)).isdisjoint(allocated)
        )

    def test_checked_in_allocation_surfaces_match_read_only_generator(self) -> None:
        result = subprocess.run(
            ["python3", "tools/content_port/trainer_allocations.py", "check"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_published_allocation_suffix_rejects_reordering(self) -> None:
        publication = copy.deepcopy(self.publication)
        publication["entries"][-1], publication["entries"][-2] = (
            publication["entries"][-2],
            publication["entries"][-1],
        )

        with self.assertRaisesRegex(AllocationError, "exact append-only suffix"):
            update_publication(publication, new_allocations(self.inventory))

    def test_missing_existing_identity_fails_closed(self) -> None:
        document = copy.deepcopy(self.inventory)
        samuel = next(
            item
            for item in document["identities"]
            if item.get("projection", {}).get("target")
            == "TRAINER_YOUNGSTER_SAMUEL_JOHTO"
        )
        samuel["admitted"] = False
        with self.assertRaisesRegex(AllocationError, "195 admitted"):
            new_allocations(document)


if __name__ == "__main__":
    unittest.main()
