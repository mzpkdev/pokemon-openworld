from __future__ import annotations

import unittest
from pathlib import Path

from tools.content_port.bindings import (
    BindingIndex,
    PersistentBinding,
    load_binding_index,
)
from tools.content_port.errors import ContentPortError


class BindingTests(unittest.TestCase):
    def test_reads_project_ledger(self) -> None:
        index = load_binding_index(Path("src/data/persistence/persistent_ids.json"))
        self.assertEqual(
            index.resolve("FLAG_WORLD_MAP_CELADON_CITY", domain="destinations").symbol,
            "FLAG_WORLD_MAP_BIRTH_ISLAND_EXTERIOR",
        )

    def test_rejects_unreviewed_collision(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "collision"):
            BindingIndex(
                [
                    PersistentBinding("flags", "FLAG_A", 1, "bit", "allocated-binding"),
                    PersistentBinding("flags", "FLAG_B", 1, "bit", "allocated-binding"),
                ]
            )

    def test_rejects_unallocated_symbol(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "unallocated"):
            BindingIndex([PersistentBinding("flags", "FLAG_A", 1, "bit", "reserved")])

    def test_alias_must_match_target_slot(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "alias disagrees"):
            BindingIndex(
                [
                    PersistentBinding("flags", "FLAG_A", 1, "bit", "allocated-binding"),
                    PersistentBinding(
                        "flags", "FLAG_B", 2, "bit", "allocated-binding", "FLAG_A"
                    ),
                ]
            )


if __name__ == "__main__":
    unittest.main()
