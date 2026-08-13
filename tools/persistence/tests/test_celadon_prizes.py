import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PRIZE_MAP = "MAP_CELADON_CITY_GAME_CORNER_PRIZE_ROOM"
SCRIPT_PATH = "data/maps/CeladonCity_GameCorner_PrizeRoom_Frlg/scripts.inc"
EXTERIOR_PATH = "data/maps/CeladonCity_Frlg/map.json"
PRIZE_WARP_ID = 5


class CeladonPrizeAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = (ROOT / SCRIPT_PATH).read_text(encoding="utf-8")
        cls.exterior = json.loads((ROOT / EXTERIOR_PATH).read_text(encoding="utf-8"))
        cls.inventory = json.loads(
            (ROOT / "tools/persistence/resident_story_admission.json").read_text(
                encoding="utf-8"
            )
        )

    def test_prize_room_has_no_inbound_warp(self):
        inbound = []
        for path in (ROOT / "data/maps").glob("*/map.json"):
            map_data = json.loads(path.read_text(encoding="utf-8"))
            for warp in map_data.get("warp_events", []):
                if warp.get("dest_map") == PRIZE_MAP:
                    inbound.append((path.relative_to(ROOT).as_posix(), warp))
        self.assertEqual(inbound, [])

    def test_prize_door_returns_to_its_same_exterior_slot(self):
        warp = self.exterior["warp_events"][PRIZE_WARP_ID]
        self.assertEqual((warp["x"], warp["y"]), (39, 20))
        self.assertEqual(warp["dest_map"], "MAP_CELADON_CITY")
        self.assertEqual(warp["dest_warp_id"], str(PRIZE_WARP_ID))

    def test_later_warp_ids_keep_their_round_trip_destinations(self):
        expected = [
            "MAP_CELADON_CITY_GYM",
            "MAP_CELADON_CITY_RESTAURANT",
            "MAP_CELADON_CITY_HOUSE1",
            "MAP_CELADON_CITY_HOTEL",
            "MAP_CELADON_CITY_CONDOMINIUMS_1F",
            "MAP_CELADON_CITY_CONDOMINIUMS_1F",
            "MAP_CELADON_CITY_CONDOMINIUMS_1F",
        ]
        actual = [
            warp["dest_map"]
            for warp in self.exterior["warp_events"][PRIZE_WARP_ID + 1 :]
        ]
        self.assertEqual(actual, expected)

    def test_dormant_catalog_remains_explicitly_deferred(self):
        self.assertIn("FLAG_GOT_COIN_CASE", self.script)
        self.assertIn("#ifdef FIRERED", self.script)
        self.assertIn("#ifdef LEAFGREEN", self.script)
        entry = next(
            item for item in self.inventory["entries"] if item["id"] == "celadon-prizes"
        )
        self.assertEqual(entry["outcome"], "deferred")
        self.assertEqual(entry["paths"], [SCRIPT_PATH])
        self.assertIn("no inbound warp targets", entry["boundary"])
        self.assertIn("collides with shipped Hoenn state", entry["rationale"])


if __name__ == "__main__":
    unittest.main()
