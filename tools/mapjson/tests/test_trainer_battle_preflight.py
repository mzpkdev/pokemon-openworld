from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]


class TrainerBattlePreflightTests(unittest.TestCase):
    @staticmethod
    def function_body(source, name):
        match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.DOTALL)
        if match is None:
            raise AssertionError(f"missing definition for {name}")
        start = match.end() - 1
        depth = 0
        for index in range(start, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[start : index + 1]
        raise AssertionError(f"unterminated definition for {name}")

    def test_every_ordinary_launch_path_names_the_shared_preflight(self):
        expected = {
            "src/battle_setup.c": {
                "BattleSetup_StartTrainerBattle": "TryGetIntendedTrainerBattle",
                "BattleSetup_StartRematchBattle": "BattleSetup_TryPreflightOrdinaryBattle",
                "SetMultiTrainerBattle": "BattleSetup_TryPreflightOrdinaryBattle",
            },
            "src/battle_special.c": {
                "DoSpecialTrainerBattle": "BattleSetup_TryPreflightOrdinaryBattle",
            },
            "src/recorded_battle.c": {
                "ValidateAndNormalizeRecordedBattleSave": "BattleSetup_TryPreflightOrdinaryBattle",
            },
            "src/trainer_see.c": {
                "CheckForTrainersWantingBattle": "BattleSetup_TryPreflightTrainerBattleData",
                "CheckTrainer": "PreflightSightTrainerBattle",
                "PreflightSightTrainerBattle": "BattleSetup_TryPreflightTrainerBattleData",
                "TrySetUpTwoTrainersBattle": "BattleSetup_TryPreflightOrdinaryBattle",
            },
        }

        for relative, functions in expected.items():
            source = (ROOT / relative).read_text()
            for function, preflight in functions.items():
                body = self.function_body(source, function)
                self.assertIn(
                    preflight,
                    body,
                    f"{relative}:{function} bypasses ordinary trainer preflight",
                )

    def test_scripted_multi_snapshots_follow_successful_preflight(self):
        source = (ROOT / "asm/macros/battle_frontier/battle_tower.inc").read_text()
        for match in re.finditer(
            r"\.macro (multi_(?:fixed_)?(?:2_vs_[12]|wild))\b", source
        ):
            body = source[match.start() : source.index(".endm", match.start())]
            self.assertLess(
                body.index("setmultitrainerbattle"),
                body.index("special SavePlayerParty"),
            )
            self.assertIn("goto_if_eq VAR_RESULT, FALSE", body)
        invocations = re.findall(
            r"^\s*setmultitrainerbattle\s+(.+)$", source, re.MULTILINE
        )
        self.assertEqual(len(invocations), 6)
        for operands in invocations:
            self.assertEqual(len(operands.split(",")), 6)

    def test_preflight_precedes_each_launch_mutation_boundary(self):
        battle_setup = (ROOT / "src/battle_setup.c").read_text()
        start = self.function_body(battle_setup, "BattleSetup_StartTrainerBattle")
        rematch = self.function_body(battle_setup, "BattleSetup_StartRematchBattle")
        special = self.function_body(
            (ROOT / "src/battle_special.c").read_text(), "DoSpecialTrainerBattle"
        )
        playback = self.function_body(
            (ROOT / "src/recorded_battle.c").read_text(), "PlayRecordedBattle"
        )
        sight = self.function_body(
            (ROOT / "src/trainer_see.c").read_text(), "CheckForTrainersWantingBattle"
        )
        two_sight = self.function_body(
            (ROOT / "src/trainer_see.c").read_text(), "TrySetUpTwoTrainersBattle"
        )
        sight_preflight = self.function_body(
            (ROOT / "src/trainer_see.c").read_text(), "PreflightSightTrainerBattle"
        )

        self.assertLess(
            start.index("TryGetIntendedTrainerBattle"),
            start.index("gBattleTypeFlags ="),
        )
        self.assertLess(
            rematch.index("BattleSetup_TryPreflight"),
            rematch.index("gMain.savedCallback ="),
        )
        self.assertLess(
            special.index("BattleSetup_TryPreflight"),
            special.index("gBattleScripting.specialTrainerBattleType ="),
        )
        self.assertLess(
            playback.index("CopyRecordedBattleFromSave"),
            playback.index("RecordedBattle_SaveParties"),
        )
        one = sight.index("if (gNoOfApproachingTrainers == 1)")
        self.assertLess(
            sight.index("BattleSetup_TryPreflightTrainerBattleData", one),
            sight.index("InitTrainerApproachTask", one),
        )
        self.assertLess(
            sight_preflight.index("inTrainerHill"),
            sight_preflight.index("BattleSetup_TryPreflightTrainerBattleData"),
        )
        self.assertLess(
            two_sight.index("BattleSetup_TryPreflightOrdinaryBattle"),
            two_sight.index("InitTrainerApproachTask"),
        )

    def test_typed_defeat_service_replaces_ordinary_flag_translation(self):
        source = (ROOT / "src/battle_setup.c").read_text()
        forbidden = (
            "PersistentId_GetTrainerDefeatFlag",
            "GetTrainerAFlag",
            "GetTrainerBFlag",
        )
        for token in forbidden:
            self.assertNotIn(token, source)
        for token in (
            "PersistentId_GetTrainerDefeated",
            "PersistentId_SetTrainerDefeated",
            "PersistentId_ClearTrainerDefeated",
        ):
            self.assertIn(token, source)

    def test_debug_multi_parser_understands_transactional_script_layout(self):
        source = (ROOT / "src/debug.c").read_text()
        body = self.function_body(source, "ParseObjectEventScript")

        self.assertIn(
            "Script_MatchesCallNative(script, SetMultiTrainerBattle, FALSE)", body
        )
        self.assertIn("ctx->scriptPtr = script + 5", body)
        self.assertNotIn("ctx->scriptPtr = script + 8", body)


if __name__ == "__main__":
    unittest.main()
