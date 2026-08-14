import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

COMMON_ATTENDANTS = {
    "Common_EventScript_UnionRoomAttendant",
    "Common_EventScript_WirelessClubAttendant",
    "Common_EventScript_DirectCornerAttendant",
}

VERSION_TRADES = {
    "data/maps/UndergroundPath_NorthEntrance_Frlg": "INGAME_TRADE_NIDORAN",
    "data/maps/Route11_EastEntrance_2F_Frlg": "INGAME_TRADE_NIDORINOA",
    "data/maps/Route18_EastEntrance_2F_Frlg": "INGAME_TRADE_LICKITUNG",
}


def load_map(relative: str) -> dict:
    return json.loads((ROOT / relative / "map.json").read_text(encoding="utf-8"))


def script_section(source: str, label: str) -> str:
    section = source.split(f"{label}::", 1)[1]
    return section.split("::", 1)[0]


class DeferredStoryServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventory = json.loads(
            (ROOT / "tools/persistence/resident_story_admission.json").read_text(
                encoding="utf-8"
            )
        )

    def test_route5_day_care_interaction_cannot_reach_storage(self):
        source = (ROOT / "data/scripts/day_care_frlg.inc").read_text(encoding="utf-8")
        entry = script_section(source, "Route5_PokemonDayCare_EventScript_DaycareMan")
        self.assertIn("Route5_PokemonDayCare_Text_ServiceUnavailable", entry)
        self.assertNotIn("special", entry)
        daycare_map = load_map("data/maps/Route5_PokemonDayCare_Frlg")
        self.assertEqual(len(daycare_map["warp_events"]), 3)
        self.assertEqual(
            daycare_map["object_events"][0]["script"],
            "Route5_PokemonDayCare_EventScript_DaycareMan",
        )

    def test_trainer_tower_entry_uses_only_temporary_state_and_ejects(self):
        exterior = (
            ROOT / "data/maps/SevenIsland_TrainerTower_Frlg/scripts.inc"
        ).read_text(encoding="utf-8")
        self.assertNotIn("VAR_MAP_SCENE_TRAINER_TOWER", exterior)

        lobby = (ROOT / "data/maps/TrainerTower_Lobby_Frlg/scripts.inc").read_text(
            encoding="utf-8"
        )
        entry = script_section(lobby, "TrainerTower_Lobby_EventScript_Enter")
        self.assertIn("setvar VAR_TEMP_0, 1", entry)
        self.assertIn("TrainerTower_Lobby_Text_ServiceUnavailable", entry)
        self.assertIn("warp MAP_SEVEN_ISLAND_TRAINER_TOWER, 58, 8", entry)
        self.assertNotIn("VAR_MAP_SCENE", entry)
        self.assertNotIn("ttower_", entry)

        exterior_map = load_map("data/maps/SevenIsland_TrainerTower_Frlg")
        lobby_map = load_map("data/maps/TrainerTower_Lobby_Frlg")
        self.assertEqual(lobby_map["coord_events"][0]["var"], "VAR_TEMP_0")
        self.assertEqual(
            exterior_map["warp_events"],
            [
                {
                    "x": 58,
                    "y": 7,
                    "elevation": 3,
                    "dest_map": "MAP_TRAINER_TOWER_LOBBY",
                    "dest_warp_id": "1",
                }
            ],
        )
        self.assertEqual(
            [
                (warp["dest_map"], warp["dest_warp_id"])
                for warp in lobby_map["warp_events"]
            ],
            [
                ("MAP_TRAINER_TOWER_1F", "1"),
                ("MAP_SEVEN_ISLAND_TRAINER_TOWER", "0"),
                ("MAP_TRAINER_TOWER_ELEVATOR", "0"),
            ],
        )

    def test_only_kanto_and_sevii_attendants_fail_closed(self):
        kanto_maps = sorted(
            (ROOT / "data/maps").glob("*PokemonCenter_2F_Frlg/map.json")
        )
        self.assertEqual(len(kanto_maps), 19)
        for path in kanto_maps:
            scripts = [
                obj["script"]
                for obj in json.loads(path.read_text(encoding="utf-8"))["object_events"]
            ]
            with self.subTest(map=path.parent.name):
                self.assertEqual(
                    scripts.count("Common_EventScript_RegionalCableClubUnavailable"),
                    3,
                )
                self.assertTrue(COMMON_ATTENDANTS.isdisjoint(scripts))

        hoenn_maps = sorted((ROOT / "data/maps").glob("*PokemonCenter_2F/map.json"))
        self.assertGreater(len(hoenn_maps), 0)
        for path in hoenn_maps:
            scripts = {
                obj["script"]
                for obj in json.loads(path.read_text(encoding="utf-8"))["object_events"]
            }
            with self.subTest(map=path.parent.name):
                self.assertTrue(COMMON_ATTENDANTS.issubset(scripts))

    def test_only_audited_version_trade_npcs_are_repointed(self):
        for relative, trade_id in VERSION_TRADES.items():
            with self.subTest(map=relative):
                map_data = load_map(relative)
                self.assertEqual(
                    map_data["object_events"][0]["script"],
                    "Common_EventScript_DeferredVersionTrade",
                )
                dormant = (ROOT / relative / "scripts.inc").read_text(encoding="utf-8")
                self.assertIn(trade_id, dormant)

    def test_inventory_records_the_runtime_boundaries(self):
        entries = {entry["id"]: entry for entry in self.inventory["entries"]}
        for entry_id in (
            "route-5-day-care",
            "trainer-tower",
            "kanto-cable-club",
            "version-exclusive-trades",
        ):
            with self.subTest(entry=entry_id):
                self.assertEqual(entries[entry_id]["outcome"], "deferred")
                self.assertTrue(entries[entry_id]["boundary"])
                self.assertTrue(entries[entry_id]["rationale"])


if __name__ == "__main__":
    unittest.main()
