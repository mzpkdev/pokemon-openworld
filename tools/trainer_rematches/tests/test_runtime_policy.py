from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class TrainerRematchRuntimePolicyTests(unittest.TestCase):
    def test_vs_seeker_does_not_touch_match_call_authority_or_storage(self) -> None:
        source = (ROOT / "src/vs_seeker.c").read_text()
        forbidden = (
            "trainerRematches",
            "gRematchTable",
            "TrainerIdToRematchTableId",
            "FirstBattleTrainerIdToRematchTableId",
            "ShouldTryRematchBattleForTrainerId",
        )
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, source)

    def test_hoenn_match_call_shape_remains_78_rows_in_100_bytes(self) -> None:
        constants = (ROOT / "include/constants/rematches.h").read_text()
        global_header = (ROOT / "include/constants/global.h").read_text()
        battle_setup = (ROOT / "src/battle_setup.c").read_text()
        table = battle_setup.split(
            "const struct RematchTrainer gRematchTable[REMATCH_TABLE_ENTRIES] =", 1
        )[1].split("};", 1)[0]

        self.assertIn("#define MAX_REMATCH_ENTRIES 100", global_header)
        enum_body = constants.split("enum {", 1)[1].split("};", 1)[0]
        entries = re.findall(
            r"^\s*REMATCH_[A-Z0-9_]+\s*(?:,|//)", enum_body, re.MULTILINE
        )
        self.assertEqual(len(entries) - 1, 78)  # Exclude REMATCH_TABLE_ENTRIES.
        self.assertEqual(
            len(re.findall(r"^\s*\[REMATCH_[A-Z0-9_]+\]", table, re.MULTILINE)), 78
        )


if __name__ == "__main__":
    unittest.main()
