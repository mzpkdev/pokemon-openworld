from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
CORRIDOR = {
    "VermilionCity_Frlg",
    "VermilionCity_PortInside",
    "SSAqua_1F",
    "OlivineCity_PortInside",
    "OlivineCity_PortOutside",
    "OlivineCity",
    "OlivineCity_PokemonCenter",
    "Route39",
}


def _map(name: str) -> dict:
    return json.loads((ROOT / f"data/maps/{name}/map.json").read_text())


def _script_warps(name: str) -> list[tuple[str, str, int, int]]:
    script_path = ROOT / f"data/maps/{name}/scripts.inc"
    if not script_path.is_file():
        return []
    script = script_path.read_text()
    current_label = None
    warps = []
    for line in script.splitlines():
        label = re.fullmatch(r"([A-Za-z0-9_]+)::", line)
        if label:
            current_label = label.group(1)
            continue
        warp = re.fullmatch(r"\s*warp\s+(MAP_[A-Z0-9_]+),\s*([0-9]+),\s*([0-9]+)", line)
        if warp and current_label is not None:
            warps.append(
                (current_label, warp.group(1), int(warp.group(2)), int(warp.group(3)))
            )
    return warps


def _dynamic_warps(name: str) -> list[tuple[str, str, int, int]]:
    script = (ROOT / f"data/maps/{name}/scripts.inc").read_text()
    current_label = None
    warps = []
    for line in script.splitlines():
        label = re.fullmatch(r"([A-Za-z0-9_]+)::", line)
        if label:
            current_label = label.group(1)
            continue
        warp = re.fullmatch(
            r"\s*setdynamicwarp\s+(MAP_[A-Z0-9_]+),\s*([0-9]+),\s*([0-9]+)",
            line,
        )
        if warp and current_label is not None:
            warps.append(
                (current_label, warp.group(1), int(warp.group(2)), int(warp.group(3)))
            )
    return warps


def _script_commands(name: str, label: str) -> list[str]:
    script = (ROOT / f"data/maps/{name}/scripts.inc").read_text()
    match = re.search(
        rf"^{re.escape(label)}::\n(?P<body>.*?)(?=^[A-Za-z0-9_]+::|\Z)",
        script,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing script label: {label}")
    return [line.strip() for line in match.group("body").splitlines() if line.strip()]


def _paired_dynamic_transitions(
    name: str,
) -> list[tuple[str, str, int, int, str, int, int]]:
    """Return an arm only when the next command is its ship transition."""

    script_path = ROOT / f"data/maps/{name}/scripts.inc"
    if not script_path.is_file():
        return []
    current_label = None
    pending = None
    pairs = []
    for line in script_path.read_text().splitlines():
        label = re.fullmatch(r"([A-Za-z0-9_]+)::", line)
        if label:
            current_label = label.group(1)
            pending = None
            continue
        arm = re.fullmatch(
            r"\s*setdynamicwarp\s+(MAP_[A-Z0-9_]+),\s*([0-9]+),\s*([0-9]+)",
            line,
        )
        if arm and current_label is not None:
            pending = (
                current_label,
                arm.group(1),
                int(arm.group(2)),
                int(arm.group(3)),
            )
            continue
        transition = re.fullmatch(
            r"\s*warp(?:silent)?\s+(MAP_[A-Z0-9_]+),\s*([0-9]+),\s*([0-9]+)",
            line,
        )
        if transition and pending is not None:
            pairs.append(
                (
                    *pending,
                    transition.group(1),
                    int(transition.group(2)),
                    int(transition.group(3)),
                )
            )
        pending = None
    return pairs


class InstalledCorridorTests(unittest.TestCase):
    def test_olivine_center_has_reachable_pokemon_storage_console(self) -> None:
        layout = (ROOT / "data/layouts/OlivineCity_PokemonCenter/map.bin").read_bytes()
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
            destinations.extend(
                destination for _, destination, _, _ in _script_warps(name)
            )
            if any(
                warp["dest_map"] == "MAP_DYNAMIC" for warp in document["warp_events"]
            ):
                dynamic_map = f"MAP_{name.upper()}"
                destinations.extend(
                    armed_destination
                    for arming_map in CORRIDOR
                    for _, armed_destination, _, _, immediate_destination, _, _ in _paired_dynamic_transitions(
                        arming_map
                    )
                    if immediate_destination == dynamic_map
                )
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
        self.assertEqual(vermilion["object_events"][5], ferry_sailor)
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
                "script": "VermilionCity_EventScript_FastShipAttendant",
                "flag": "0",
            },
        )
        self.assertEqual(
            _script_commands(
                "VermilionCity_Frlg", "VermilionCity_EventScript_FerrySailor"
            ),
            [
                "lock",
                "faceplayer",
                "goto_if_unset FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED, VermilionCity_EventScript_FerrySailorLegacy",
                "msgbox VermilionCity_Text_EnterFastShipTerminal",
                "release",
                "end",
            ],
        )
        self.assertEqual(
            _script_commands(
                "VermilionCity_Frlg", "VermilionCity_EventScript_FastShipAttendant"
            ),
            [
                "lock",
                "faceplayer",
                "goto_if_unset FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED, VermilionCity_EventScript_FastShipTerminalUnavailable",
                "goto VermilionCity_EventScript_EnterFastShipTerminal",
                "end",
            ],
        )
        terminal_entry = _script_commands(
            "VermilionCity_Frlg", "VermilionCity_EventScript_EnterFastShipTerminal"
        )
        self.assertEqual(
            terminal_entry,
            [
                "msgbox VermilionCity_Text_EnterFastShipTerminal",
                "closemessage",
                "warp MAP_VERMILION_CITY_PORT_INSIDE, 8, 9",
                "waitstate",
                "release",
                "end",
            ],
        )
        self.assertNotIn("MSGBOX_YESNO", "\n".join(terminal_entry))
        self.assertFalse(
            any(command.startswith("switch ") for command in terminal_entry)
        )
        self.assertEqual(
            _script_commands(
                "VermilionCity_Frlg", "VermilionCity_Text_EnterFastShipTerminal"
            ),
            [
                r'.string "The FAST SHIP terminal is open.\p"',
                r'.string "Please proceed to the berth.$"',
            ],
        )
        self.assertEqual(
            _script_commands(
                "VermilionCity_Frlg", "VermilionCity_EventScript_FerrySailorLegacy"
            ),
            [
                "goto_if_eq VAR_MAP_SCENE_VERMILION_CITY, 3, VermilionCity_EventScript_CheckSeagallopPresent",
                "msgbox VermilionCity_Text_WelcomeToTheSSAnne",
                "release",
                "end",
            ],
        )
        self.assertEqual(
            _script_commands(
                "VermilionCity_Frlg",
                "VermilionCity_EventScript_FastShipTerminalUnavailable",
            ),
            [
                "msgbox VermilionCity_Text_FastShipTerminalUnavailable",
                "release",
                "end",
            ],
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
        self.assertEqual(
            _dynamic_warps("VermilionCity_PortInside"),
            [
                (
                    "VermilionCity_PortInside_EventScript_TravelToOlivine",
                    "MAP_OLIVINE_CITY_PORT_INSIDE",
                    8,
                    16,
                )
            ],
        )
        self.assertEqual(
            _script_warps("VermilionCity_PortInside"),
            [
                (
                    "VermilionCity_PortInside_EventScript_TravelToOlivine",
                    "MAP_SSAQUA_1F",
                    29,
                    3,
                )
            ],
        )
        self.assertEqual(
            _dynamic_warps("OlivineCity_PortInside"),
            [
                (
                    "OlivineCity_PortInside_EventScript_TravelToVermilion",
                    "MAP_VERMILION_CITY_PORT_INSIDE",
                    8,
                    9,
                )
            ],
        )
        self.assertEqual(
            _script_warps("OlivineCity_PortInside"),
            [
                (
                    "OlivineCity_PortInside_EventScript_TravelToVermilion",
                    "MAP_SSAQUA_1F",
                    29,
                    3,
                )
            ],
        )
        self.assertEqual(
            _map("SSAqua_1F")["warp_events"][0],
            {
                "x": 29,
                "y": 1,
                "elevation": 0,
                "dest_map": "MAP_DYNAMIC",
                "dest_warp_id": "WARP_ID_DYNAMIC",
            },
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

    def test_vermilion_dock_enters_berth_without_ticket_triggers(self) -> None:
        vermilion = _map("VermilionCity_Frlg")
        self.assertEqual(
            vermilion["warp_events"][:3],
            [
                {
                    "x": x,
                    "y": 34,
                    "elevation": 3,
                    "dest_map": "MAP_VERMILION_CITY_PORT_INSIDE",
                    "dest_warp_id": "0",
                }
                for x in (22, 23, 24)
            ],
        )
        self.assertEqual(vermilion["coord_events"], [])

    def test_ss_anne_is_registered_but_has_no_ordinary_world_inbound_edge(self) -> None:
        anne_maps = {
            path.parent.name for path in ROOT.glob("data/maps/SSAnne*/map.json")
        }
        self.assertTrue(anne_maps)

        map_groups = json.loads((ROOT / "data/maps/map_groups.json").read_text())
        registered_maps = {
            name
            for group in map_groups.values()
            if isinstance(group, list)
            for name in group
        }
        self.assertLessEqual(anne_maps, registered_maps)

        layouts = json.loads((ROOT / "data/layouts/layouts.json").read_text())[
            "layouts"
        ]
        registered_layouts = {layout["id"] for layout in layouts}
        scripts = (ROOT / "data/event_scripts.s").read_text()
        for name in anne_maps:
            document = _map(name)
            self.assertIn(document["layout"], registered_layouts)
            self.assertIn(f'"data/maps/{name}/scripts.inc"', scripts)

        inbound = []
        for path in ROOT.glob("data/maps/*/map.json"):
            source = path.parent.name
            if source in anne_maps:
                continue
            document = json.loads(path.read_text())
            for index, warp in enumerate(document.get("warp_events") or []):
                if warp["dest_map"].startswith("MAP_SSANNE_"):
                    inbound.append((source, "warp", index, warp["dest_map"]))
            for label, destination, x, y in _script_warps(source):
                if destination.startswith("MAP_SSANNE_"):
                    inbound.append((source, label, x, y, destination))
        self.assertEqual(inbound, [])

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
        self.assertIn("msgbox Route39_Text_SailorEugeneAfter, MSGBOX_AUTOCLOSE", script)

    def test_route31_installs_wade_as_compact_local_id_one(self) -> None:
        document = _map("Route31")
        self.assertEqual(
            document["object_events"],
            [
                {
                    "graphics_id": "OBJ_EVENT_GFX_BUG_CATCHER",
                    "x": 27,
                    "y": 10,
                    "elevation": 0,
                    "movement_type": "MOVEMENT_TYPE_LOOK_AROUND",
                    "movement_range_x": 0,
                    "movement_range_y": 3,
                    "trainer_type": "TRAINER_TYPE_NORMAL",
                    "trainer_sight_or_berry_tree_id": "3",
                    "script": "Route31_EventScript_Bugcatcher_Wade",
                    "flag": "0",
                }
            ],
        )
        script = (ROOT / "data/maps/Route31/scripts.inc").read_text()
        self.assertEqual(
            re.findall(r"^Route31_EventScript_([A-Za-z0-9_]+)::", script, re.MULTILINE),
            ["Bugcatcher_Wade"],
        )
        self.assertIn(
            "trainerbattle_single TRAINER_BUG_CATCHER_WADE_JOHTO, "
            "Route31_Text_BugCatcherWade1_Seen, "
            "Route31_Text_BugCatcherWade1_Beaten",
            script,
        )
        self.assertIn(
            "msgbox Route31_Text_BugCatcherWade1_After, MSGBOX_AUTOCLOSE", script
        )


if __name__ == "__main__":
    unittest.main()
