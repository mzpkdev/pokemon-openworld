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
        self.assertEqual(
            index.resolve("TRAINER_FRLG_YOUNGSTER_BEN", domain="trainerIds").value,
            858,
        )
        self.assertEqual(
            index.resolve("TRAINER_CLASS_HEX_MANIAC", domain="trainerIds").value,
            14,
        )
        with self.assertRaisesRegex(ContentPortError, "has no ledger binding"):
            index.resolve("TRAINER_BUG_CATCHER_RICK", domain="trainerIds")

    def test_tombstone_loads_but_is_not_resolvable(self) -> None:
        index = BindingIndex(
            [
                PersistentBinding(
                    "trainerIds",
                    "TRAINER_LIVE",
                    1,
                    "u32-id",
                    "trainer-defeat-flag",
                ),
                PersistentBinding(
                    "trainerIds",
                    "TRAINER_RETIRED",
                    1,
                    "u32-id",
                    "published-tombstone",
                    "TRAINER_LIVE",
                ),
            ]
        )

        self.assertEqual(index.resolve("TRAINER_LIVE").value, 1)
        self.assertNotIn("TRAINER_RETIRED", index)
        with self.assertRaisesRegex(ContentPortError, "has no ledger binding"):
            index.resolve("TRAINER_RETIRED", domain="trainerIds")

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

    def test_rejects_unknown_state_even_when_it_looks_published(self) -> None:
        with self.assertRaisesRegex(ContentPortError, "unallocated"):
            BindingIndex(
                [PersistentBinding("flags", "FLAG_A", 1, "bit", "published-deleted")]
            )

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
