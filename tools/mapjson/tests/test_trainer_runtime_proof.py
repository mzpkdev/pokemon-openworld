from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]


class TrainerRuntimeProofTests(unittest.TestCase):
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

    def test_debug_hook_uses_production_preflight_and_launcher(self):
        source = (ROOT / "src/debug_trainer_battle_scenario.c").read_text()
        validate = self.function_body(source, "ValidateRequest")
        start = self.function_body(source, "StartScenario")

        self.assertIn("#ifdef DEBUG", source)
        self.assertIn("BattleSetup_TryPreflightOrdinaryBattle", validate)
        self.assertLess(
            start.index("ValidateRequest"),
            start.index("BattleSetup_StartTrainerBattle"),
        )
        self.assertNotIn("BattleSetup_StartTrainerBattle_Debug", source)

    def test_debug_hook_cannot_mutate_defeat_or_choose_victory(self):
        source = (ROOT / "src/debug_trainer_battle_scenario.c").read_text()
        forbidden = (
            "PersistentId_SetTrainerDefeated",
            "PersistentId_ClearTrainerDefeated",
            "SetTrainerFlag",
            "ClearTrainerFlag",
            "BattleDebug_WonBattle",
            "CB2_BattleDebugMenu",
            "B_ACTION_DEBUG",
        )
        for token in forbidden:
            self.assertNotIn(token, source)

        header = (ROOT / "include/debug_trainer_battle_scenario.h").read_text()
        request_match = re.search(
            r"struct DebugTrainerBattleScenarioRequest\s*\{(?P<body>.*?)\};",
            header,
            re.DOTALL,
        )
        self.assertIsNotNone(request_match)
        request = request_match.group("body")
        self.assertIn("trainerId", request)
        self.assertNotIn("outcome", request.lower())
        self.assertNotIn("victory", request.lower())
        self.assertNotIn("win", request.lower())

    def test_hook_observes_production_post_battle_state(self):
        hook = (ROOT / "src/debug_trainer_battle_scenario.c").read_text()
        finish = self.function_body(hook, "FinishScenario")
        self.assertIn("B_OUTCOME_WON", finish)
        self.assertIn("PersistentId_GetTrainerDefeated", finish)

        battle_setup = (ROOT / "src/battle_setup.c").read_text()
        callback = self.function_body(battle_setup, "CB2_EndTrainerBattle")
        self.assertLess(
            callback.index("RegisterTrainerInMatchCall"),
            callback.index("SetBattledTrainersFlags"),
        )
        defeated = self.function_body(battle_setup, "SetBattledTrainersFlags")
        self.assertIn("PersistentId_SetTrainerDefeated", defeated)

        host = (ROOT / "tools/e2e/trainer_battle_journey.py").read_text()
        self.assertIn('game.address("CB2_EndTrainerBattle")', host)
        self.assertIn("ready.end_callback & ~1 != expected_end_callback", host)
        self.assertNotIn("BattleDebug_WonBattle", host)
        self.assertNotIn("CB2_BattleDebugMenu", host)
        self.assertNotIn("Instant Win", host)

    def test_hook_rejects_invalid_commit_status_before_battle(self):
        hook = (ROOT / "src/debug_trainer_battle_scenario.c").read_text()
        update = self.function_body(hook, "DebugTrainerBattleScenario_Update")
        invalid = update.index(
            "gTrainerBattleScenarioRequest.status > DEBUG_TRAINER_BATTLE_SCENARIO_ERROR"
        )
        launch = update.index("StartScenario")
        self.assertLess(invalid, launch)
        self.assertIn("DEBUG_TRAINER_BATTLE_SCENARIO_ERROR_REQUEST", update)

    def test_main_integrates_hook_only_in_debug_block(self):
        main = (ROOT / "src/main.c").read_text()
        include = '#include "debug_trainer_battle_scenario.h"'
        call = "DebugTrainerBattleScenario_Update();"
        self.assertEqual(main.count(include), 1)
        self.assertEqual(main.count(call), 1)
        include_debug = main.rfind("#ifdef DEBUG", 0, main.index(include))
        include_end = main.find("#endif", main.index(include))
        call_debug = main.rfind("#ifdef DEBUG", 0, main.index(call))
        call_end = main.find("#endif", main.index(call))
        self.assertGreaterEqual(include_debug, 0)
        self.assertLess(main.index(include), include_end)
        self.assertGreaterEqual(call_debug, 0)
        self.assertLess(main.index(call), call_end)


if __name__ == "__main__":
    unittest.main()
