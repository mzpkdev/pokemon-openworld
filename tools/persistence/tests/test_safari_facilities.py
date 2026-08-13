import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

FACILITIES = {
    "HOENN_ROUTE_121": {
        "entry": "data/maps/Route121_SafariZoneEntrance/scripts.inc",
        "entry_special": "special EnterHoennSafariMode",
        "scene": "VAR_SAFARI_ZONE_STATE",
        "entrance": "MAP_ROUTE121_SAFARI_ZONE_ENTRANCE",
    },
    "KANTO_FUCHSIA": {
        "entry": "data/maps/FuchsiaCity_SafariZone_Entrance_Frlg/scripts.inc",
        "entry_special": "special EnterKantoSafariMode",
        "scene": "VAR_MAP_SCENE_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE",
        "entrance": "MAP_FUCHSIA_CITY_SAFARI_ZONE_ENTRANCE",
    },
}


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\([^)]*\)\s*\{{", source)
    if match is None:
        raise AssertionError(f"missing function {name}")
    depth = 1
    cursor = match.end()
    while cursor < len(source) and depth:
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
        cursor += 1
    if depth:
        raise AssertionError(f"unterminated function {name}")
    return source[match.start() : cursor]


class SafariFacilityPolicyTests(unittest.TestCase):
    def test_each_entrance_assigns_an_explicit_facility(self):
        for facility, contract in FACILITIES.items():
            with self.subTest(facility=facility):
                source = (ROOT / contract["entry"]).read_text(encoding="utf-8")
                self.assertIn(contract["entry_special"], source)
                self.assertNotIn("special EnterSafariMode", source)

    def test_all_session_exit_paths_dispatch_from_facility_identity(self):
        source = (ROOT / "data/scripts/safari_zone.inc").read_text(encoding="utf-8")
        self.assertNotIn("IS_FRLG", source)
        for facility, contract in FACILITIES.items():
            with self.subTest(facility=facility):
                self.assertGreaterEqual(
                    source.count(
                        f"goto_if_eq VAR_RESULT, SAFARI_ZONE_FACILITY_{facility}"
                    ),
                    2,
                )
                self.assertIn(contract["scene"], source)
                self.assertIn(contract["entrance"], source)
        self.assertGreaterEqual(
            source.count("specialvar VAR_RESULT, GetSafariZoneFacility"), 2
        )

    def test_safari_rules_do_not_use_product_identity(self):
        functions = {
            "src/safari_zone.c": (
                "EnterSafariModeForFacility",
                "GetSafariZoneStepLimit",
            ),
            "src/battle_controller_safari.c": ("SafariHandleChooseAction",),
            "src/battle_main.c": ("HandleTurnActionSelectionState",),
            "src/battle_util.c": (
                "HandleAction_WatchesCarefully",
                "HandleAction_ThrowPokeblock",
                "HandleAction_GoNear",
            ),
            "src/start_menu.c": ("ShowSafariBallsWindow",),
        }
        for relative, names in functions.items():
            source = (ROOT / relative).read_text(encoding="utf-8")
            for name in names:
                with self.subTest(path=relative, function=name):
                    body = function_body(source, name)
                    self.assertNotIn("IS_FRLG", body)
                    self.assertNotIn("GetCurrentRegion", body)

    def test_only_hoenn_exit_publishes_the_hoenn_tv_show(self):
        source = (ROOT / "src/safari_zone.c").read_text(encoding="utf-8")
        body = function_body(source, "ExitSafariMode")
        self.assertIn("SafariZonePublishesFanClubShow()", body)
        self.assertIn("TryPutSafariFanClubOnAir", body)

    def test_timeout_and_all_common_completion_paths_share_facility_exit(self):
        source = (ROOT / "data/scripts/safari_zone.inc").read_text(encoding="utf-8")
        for label in (
            "SafariZone_EventScript_Retire",
            "SafariZone_EventScript_TimesUp",
            "SafariZone_EventScript_OutOfBalls",
        ):
            section = source.split(f"{label}::", 1)[1].split("::", 1)[0]
            self.assertIn("goto SafariZone_EventScript_Exit", section)

    def test_early_exit_guards_match_the_resident_facility(self):
        hoenn = (ROOT / "data/maps/SafariZone_South/scripts.inc").read_text(
            encoding="utf-8"
        )
        kanto = (ROOT / FACILITIES["KANTO_FUCHSIA"]["entry"]).read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "goto_if_ne VAR_RESULT, SAFARI_ZONE_FACILITY_HOENN_ROUTE_121",
            hoenn,
        )
        self.assertIn(
            "goto_if_ne VAR_RESULT, SAFARI_ZONE_FACILITY_KANTO_FUCHSIA",
            kanto,
        )

    def test_invalid_hoenn_session_is_cleaned_and_warped_out(self):
        source = (ROOT / "data/maps/SafariZone_South/scripts.inc").read_text(
            encoding="utf-8"
        )
        section = source.split("SafariZone_South_EventScript_InvalidSession::", 1)[1]
        section = section.split("SafariZone_South_EventScript_GoodLuck::", 1)[0]
        self.assertEqual(
            [line.strip() for line in section.splitlines() if line.strip()],
            [
                "setvar VAR_SAFARI_ZONE_STATE, 1",
                "special ExitSafariMode",
                "warpdoor MAP_ROUTE121_SAFARI_ZONE_ENTRANCE, 2, 5",
                "waitstate",
                "end",
            ],
        )

    def test_corrected_safari_authority_is_admitted(self):
        inventory = json.loads(
            (ROOT / "tools/persistence/resident_story_admission.json").read_text(
                encoding="utf-8"
            )
        )
        entry = next(
            item for item in inventory["entries"] if item["id"] == "safari-facilities"
        )
        self.assertEqual(entry["outcome"], "admitted")
        self.assertIsNone(entry["boundary"])
        self.assertEqual(
            set(entry["paths"]),
            {"data/scripts/safari_zone.inc", "src/safari_zone.c"},
        )


if __name__ == "__main__":
    unittest.main()
