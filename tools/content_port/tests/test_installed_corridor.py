from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
CORRIDOR = {
    "VermilionCity_Frlg",
    "VermilionCity_PortInside",
    "OlivineCity_PortInside",
    "OlivineCity_PortOutside",
    "OlivineCity",
    "OlivineCity_PokemonCenter",
    "Route39",
}


def _map(name: str) -> dict:
    return json.loads((ROOT / f"data/maps/{name}/map.json").read_text())


def _script_warps(name: str) -> list[tuple[str, str, int, int]]:
    script = (ROOT / f"data/maps/{name}/scripts.inc").read_text()
    current_label = None
    warps = []
    for line in script.splitlines():
        label = re.fullmatch(r"([A-Za-z0-9_]+)::", line)
        if label:
            current_label = label.group(1)
            continue
        warp = re.fullmatch(
            r"\s*warp\s+(MAP_[A-Z0-9_]+),\s*([0-9]+),\s*([0-9]+)", line
        )
        if warp and current_label is not None:
            warps.append(
                (current_label, warp.group(1), int(warp.group(2)), int(warp.group(3)))
            )
    return warps


class InstalledCorridorTests(unittest.TestCase):
    def test_olivine_center_has_reachable_pokemon_storage_console(self) -> None:
        layout = (
            ROOT / "data/layouts/OlivineCity_PokemonCenter/map.bin"
        ).read_bytes()
        attributes = (
            ROOT
            / "data/tilesets/secondary/kanto_pokemon_center/metatile_attributes.bin"
        ).read_bytes()
        width = 16
        console_x, console_y = 11, 5
        console = int.from_bytes(
            layout[(console_y * width + console_x) * 2 :][0:2], "little"
        )
        stand = int.from_bytes(
            layout[((console_y + 1) * width + console_x) * 2 :][0:2], "little"
        )
        self.assertEqual(console, 0x32F6)
        self.assertEqual(console & 0x3FF, 640 + 118)
        self.assertEqual(
            int.from_bytes(attributes[118 * 2 : 118 * 2 + 2], "little") & 0xFF,
            0x83,
        )
        self.assertEqual(stand & 0x3FF, 0x29C)

    def test_installed_corridor_is_reachable_in_both_directions(self) -> None:
        documents = {name: _map(name) for name in CORRIDOR}
        name_by_id = {document["id"]: name for name, document in documents.items()}
        adjacency = {name: set() for name in CORRIDOR}
        for name, document in documents.items():
            destinations = [
                connection["map"] for connection in document["connections"]
            ] + [warp["dest_map"] for warp in document["warp_events"]]
            destinations.extend(destination for _, destination, _, _ in _script_warps(name))
            adjacency[name].update(
                name_by_id[destination]
                for destination in destinations
                if destination in name_by_id
            )

        for start in CORRIDOR:
            reached = {start}
            pending = [start]
            while pending:
                for destination in adjacency[pending.pop()]:
                    if destination not in reached:
                        reached.add(destination)
                        pending.append(destination)
            self.assertEqual(reached, CORRIDOR, start)

    def test_installed_gateway_and_route_endpoints_are_exact(self) -> None:
        vermilion = _map("VermilionCity_Frlg")
        ferry_sailor = next(
            event
            for event in vermilion["object_events"]
            if event.get("local_id") == "LOCALID_VERMILION_FERRY_SAILOR"
        )
        self.assertEqual(
            ferry_sailor,
            {
                "local_id": "LOCALID_VERMILION_FERRY_SAILOR",
                "type": "object",
                "graphics_id": "OBJ_EVENT_GFX_SAILOR_FRLG",
                "x": 24,
                "y": 33,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_UP",
                "movement_range_x": 1,
                "movement_range_y": 1,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "VermilionCity_EventScript_FerrySailor",
                "flag": "0",
            },
        )
        fast_ship_attendant = next(
            event
            for event in vermilion["object_events"]
            if event.get("local_id") == "LOCALID_VERMILION_FAST_SHIP_ATTENDANT"
        )
        self.assertEqual(
            fast_ship_attendant,
            {
                "local_id": "LOCALID_VERMILION_FAST_SHIP_ATTENDANT",
                "type": "object",
                "graphics_id": "OBJ_EVENT_GFX_SAILOR_FRLG",
                "x": 25,
                "y": 24,
                "elevation": 3,
                "movement_type": "MOVEMENT_TYPE_FACE_UP",
                "movement_range_x": 1,
                "movement_range_y": 1,
                "trainer_type": "TRAINER_TYPE_NONE",
                "trainer_sight_or_berry_tree_id": "0",
                "script": "VermilionCity_EventScript_FerrySailor",
                "flag": "0",
            },
        )
        self.assertIn(
            (
                "VermilionCity_EventScript_EnterFastShipTerminal",
                "MAP_VERMILION_CITY_PORT_INSIDE",
                8,
                9,
            ),
            _script_warps("VermilionCity_Frlg"),
        )
        self.assertEqual(
            _map("VermilionCity_PortInside")["warp_events"],
            [
                {
                    "x": 8,
                    "y": 2,
                    "elevation": 0,
                    "dest_map": "MAP_VERMILION_CITY",
                    "dest_warp_id": "2",
                }
            ],
        )
        self.assertIn(
            (
                "VermilionCity_PortInside_EventScript_TravelToOlivine",
                "MAP_OLIVINE_CITY_PORT_INSIDE",
                8,
                16,
            ),
            _script_warps("VermilionCity_PortInside"),
        )
        self.assertIn(
            (
                "OlivineCity_PortInside_EventScript_TravelToVermilion",
                "MAP_VERMILION_CITY_PORT_INSIDE",
                8,
                9,
            ),
            _script_warps("OlivineCity_PortInside"),
        )
        self.assertEqual(
            _map("OlivineCity_PortInside")["warp_events"],
            [
                {
                    "x": 8,
                    "y": 9,
                    "elevation": 0,
                    "dest_map": "MAP_OLIVINE_CITY_PORT_OUTSIDE",
                    "dest_warp_id": "0",
                }
            ],
        )
        self.assertEqual(
            _map("OlivineCity_PortOutside")["warp_events"],
            [
                {
                    "x": 15,
                    "y": 10,
                    "elevation": 0,
                    "dest_map": "MAP_OLIVINE_CITY_PORT_INSIDE",
                    "dest_warp_id": "0",
                }
            ],
        )
        self.assertIn(
            {"map": "MAP_OLIVINE_CITY", "offset": -5, "direction": "up"},
            _map("OlivineCity_PortOutside")["connections"],
        )
        self.assertIn(
            {
                "map": "MAP_OLIVINE_CITY_PORT_OUTSIDE",
                "offset": 5,
                "direction": "down",
            },
            _map("OlivineCity")["connections"],
        )
        self.assertIn(
            {"map": "MAP_ROUTE39", "offset": -6, "direction": "up"},
            _map("OlivineCity")["connections"],
        )
        self.assertIn(
            {"map": "MAP_OLIVINE_CITY", "offset": 6, "direction": "down"},
            _map("Route39")["connections"],
        )
        self.assertIn(
            {
                "x": 15,
                "y": 43,
                "elevation": 0,
                "dest_map": "MAP_OLIVINE_CITY_POKEMON_CENTER",
                "dest_warp_id": "0",
            },
            _map("OlivineCity")["warp_events"],
        )
        self.assertEqual(
            _map("OlivineCity_PokemonCenter")["warp_events"],
            [
                {
                    "x": 7,
                    "y": 8,
                    "elevation": 0,
                    "dest_map": "MAP_OLIVINE_CITY",
                    "dest_warp_id": "7",
                }
            ],
        )

    def test_route39_installs_only_exact_eugene_object_and_script(self) -> None:
        document = _map("Route39")
        self.assertEqual(
            document["object_events"],
            [
                {
                    "graphics_id": "OBJ_EVENT_GFX_SAILOR",
                    "x": 22,
                    "y": 42,
                    "elevation": 0,
                    "movement_type": "MOVEMENT_TYPE_WALK_RIGHT_AND_LEFT",
                    "movement_range_x": 6,
                    "movement_range_y": 0,
                    "trainer_type": "TRAINER_TYPE_NORMAL",
                    "trainer_sight_or_berry_tree_id": "6",
                    "script": "Route39_EventScript_Eugene",
                    "flag": "0",
                }
            ],
        )
        script = (ROOT / "data/maps/Route39/scripts.inc").read_text()
        self.assertEqual(
            re.findall(r"^Route39_EventScript_([A-Za-z0-9_]+)::", script, re.MULTILINE),
            ["Eugene"],
        )
        self.assertIn(
            "trainerbattle_single TRAINER_SAILOR_EUGENE_JOHTO, "
            "Route39_Text_SailorEugeneSeen, Route39_Text_SailorEugeneBeaten",
            script,
        )
        self.assertIn(
            "msgbox Route39_Text_SailorEugeneAfter, MSGBOX_AUTOCLOSE", script
        )


if __name__ == "__main__":
    unittest.main()
