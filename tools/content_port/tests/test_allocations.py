from __future__ import annotations

import copy
import unittest

from tools.content_port.allocations import load_allocation_index
from tools.content_port.errors import ContentPortError


def allocation_document() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "groups": [{"name": "gMapGroup_Test", "targetId": 4}],
        "sections": [{"name": "MAPSEC_TEST", "targetId": 9}],
        "layouts": [{"id": "LAYOUT_TEST", "targetIndex": 12}],
        "maps": [
            {
                "name": "TestMap",
                "id": "MAP_TEST",
                "targetGroup": "gMapGroup_Test",
                "targetGroupId": 4,
                "targetMember": 0,
                "layout": "LAYOUT_TEST",
                "targetLayoutIndex": 12,
                "section": "MAPSEC_TEST",
                "targetSection": 9,
            }
        ],
    }


class AllocationTests(unittest.TestCase):
    def test_exposes_numeric_placements_only_through_immutable_index(self):
        index = load_allocation_index(allocation_document())
        self.assertEqual(index.map_slot("TestMap"), ("gMapGroup_Test", 4, 0))
        allocation = index.map_allocation("TestMap")
        self.assertEqual(
            (
                allocation.name,
                allocation.map_id,
                allocation.target_group,
                allocation.target_group_id,
                allocation.target_member,
                allocation.layout,
                allocation.target_layout_index,
                allocation.section,
                allocation.target_section,
            ),
            (
                "TestMap",
                "MAP_TEST",
                "gMapGroup_Test",
                4,
                0,
                "LAYOUT_TEST",
                12,
                "MAPSEC_TEST",
                9,
            ),
        )
        self.assertEqual(index.layout_slot("LAYOUT_TEST"), 12)
        self.assertEqual(index.group_slot("gMapGroup_Test"), 4)
        self.assertEqual(index.section_slot("MAPSEC_TEST"), 9)
        with self.assertRaises(TypeError):
            index.maps["Other"] = allocation  # type: ignore[index]
        with self.assertRaisesRegex(ContentPortError, "has no map Missing"):
            index.map_slot("Missing")

    def test_unknown_fields_and_non_integer_allocations_fail(self):
        unknown = allocation_document()
        unknown["extra"] = []
        with self.assertRaisesRegex(ContentPortError, "unknown field 'extra'"):
            load_allocation_index(unknown)
        boolean = allocation_document()
        boolean["groups"][0]["targetId"] = True  # type: ignore[index]
        with self.assertRaisesRegex(ContentPortError, "non-negative integer"):
            load_allocation_index(boolean)
        for dead_field in ("batch", "materialization"):
            with self.subTest(dead_field=dead_field):
                dead = allocation_document()
                dead["maps"][0][dead_field] = "dead"  # type: ignore[index]
                with self.assertRaisesRegex(
                    ContentPortError, f"unknown field '{dead_field}'"
                ):
                    load_allocation_index(dead)

    def test_mismatched_authority_value_fails(self):
        document = allocation_document()
        document["maps"][0]["targetLayoutIndex"] = 13  # type: ignore[index]
        with self.assertRaisesRegex(ContentPortError, "layout allocation mismatch"):
            load_allocation_index(document)

    def test_duplicate_map_slot_fails(self):
        document = allocation_document()
        duplicate = copy.deepcopy(document["maps"][0])  # type: ignore[index]
        duplicate["name"] = "OtherMap"
        duplicate["id"] = "MAP_OTHER"
        document["maps"].append(duplicate)  # type: ignore[union-attr]
        with self.assertRaisesRegex(ContentPortError, "duplicate allocation"):
            load_allocation_index(document)

    def test_group_members_must_be_contiguous(self):
        document = allocation_document()
        document["maps"][0]["targetMember"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(ContentPortError, "non-contiguous members"):
            load_allocation_index(document)


if __name__ == "__main__":
    unittest.main()
