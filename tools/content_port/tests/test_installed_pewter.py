from __future__ import annotations

import json
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
PORT = ROOT / "tools/content_port/ports/johto"
HNS = "PewterCity_Hns"
FRLG = "PewterCity_Frlg"
HNS_ID = "MAP_PEWTER_CITY_HNS"
FRLG_ID = "MAP_PEWTER_CITY"
HNS_SAMPLES = {
    "hg_010bsna3.aif",
    "hg_011bsnc3.aif",
    "hg_012bsne2.aif",
    "hg_041ampega2.aif",
    "hg_042ampega3.aif",
    "hg_115martinc5.aif",
    "hg_116martine4.aif",
    "hg_117marting2.aif",
    "hg_118marting3.aif",
    "hg_128jdruml.aif",
    "hg_148vibrc4.aif",
    "hg_149vibrc5.aif",
}


def _json(path: Path) -> object:
    return json.loads(path.read_text())


def _map(name: str) -> dict:
    return _json(ROOT / f"data/maps/{name}/map.json")  # type: ignore[return-value]


def _commands(path: Path, label: str) -> list[str]:
    text = path.read_text()
    match = re.search(
        rf"^{re.escape(label)}::\n(?P<body>.*?)(?=^[A-Za-z0-9_]+::|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing script label: {label}")
    return [line.strip() for line in match.group("body").splitlines() if line.strip()]


class InstalledPewterTests(unittest.TestCase):
    def setUp(self) -> None:
        groups = _json(ROOT / "data/maps/map_groups.json")
        if HNS not in groups.get("gMapGroup_HnsPewterCity", []):
            self.skipTest("HnS Pewter registry state is supplied by the pending port bundle")

    def test_hns_and_frlg_are_separate_append_only_identities(self) -> None:
        groups = _json(ROOT / "data/maps/map_groups.json")
        self.assertEqual(groups["group_order"][-1], "gMapGroup_HnsPewterCity")
        self.assertEqual(len(groups["group_order"]), 101)
        self.assertEqual(groups["group_order"].index("gMapGroup_HnsPewterCity"), 100)
        self.assertEqual(groups["gMapGroup_HnsPewterCity"], [HNS])
        self.assertIn(FRLG, groups["gMapGroup_TownsAndRoutes_Frlg"])

        layouts = _json(ROOT / "data/layouts/layouts.json")["layouts"]
        self.assertEqual(len(layouts), 1041)
        self.assertEqual(layouts[-1]["id"], "LAYOUT_PEWTER_CITY_HNS")
        self.assertEqual(layouts[-1]["name"], "PewterCity_Hns_Layout")

        hns, frlg = _map(HNS), _map(FRLG)
        self.assertEqual((hns["id"], hns["layout"]), (HNS_ID, "LAYOUT_PEWTER_CITY_HNS"))
        self.assertEqual((frlg["id"], frlg["layout"]), (FRLG_ID, "LAYOUT_PEWTER_CITY"))
        self.assertNotEqual(hns["id"], frlg["id"])
        self.assertNotEqual(hns["layout"], frlg["layout"])

        lock = _json(PORT / "allocation_lock.json")
        self.assertEqual(
            lock["groups"][-1], {"name": "gMapGroup_HnsPewterCity", "targetId": 100}
        )
        self.assertEqual(lock["layouts"][-1]["targetIndex"], 1040)
        self.assertEqual(
            lock["maps"][-1],
            {
                "name": HNS,
                "id": HNS_ID,
                "targetGroup": "gMapGroup_HnsPewterCity",
                "targetGroupId": 100,
                "targetMember": 0,
                "layout": "LAYOUT_PEWTER_CITY_HNS",
                "targetLayoutIndex": 1040,
                "section": "MAPSEC_PEWTER_CITY",
                "targetSection": 90,
                "sectionOwnership": "reference",
            },
        )

    def test_normal_route_seams_are_reciprocal_and_frlg_is_not_normal(self) -> None:
        hns, route2, route3, frlg = (
            _map(name) for name in (HNS, "Route2_Frlg", "Route3_Frlg", FRLG)
        )
        self.assertEqual(
            hns["connections"],
            [
                {"map": "MAP_ROUTE2", "offset": 14, "direction": "down"},
                {"map": "MAP_ROUTE3", "offset": 15, "direction": "right"},
            ],
        )
        self.assertIn(
            {"map": HNS_ID, "offset": -14, "direction": "up"}, route2["connections"]
        )
        self.assertIn(
            {"map": HNS_ID, "offset": -15, "direction": "left"}, route3["connections"]
        )
        self.assertFalse(any(edge["map"] == HNS_ID for edge in frlg["connections"]))
        self.assertFalse(
            any(
                edge["map"] == FRLG_ID
                for edge in route2["connections"] + route3["connections"]
            )
        )

    def test_hns_warps_and_existing_interior_returns_are_exact(self) -> None:
        hns = _map(HNS)
        expected = [
            ("MAP_PEWTER_CITY_MUSEUM_1F", "1"),
            ("MAP_PEWTER_CITY_MUSEUM_1F", "3"),
            ("MAP_PEWTER_CITY_GYM", "1"),
            ("MAP_PEWTER_CITY_MART", "1"),
            ("MAP_PEWTER_CITY_HOUSE1", "1"),
            ("MAP_PEWTER_CITY_POKEMON_CENTER_1F", "1"),
            ("MAP_PEWTER_CITY_HOUSE2", "1"),
        ]
        self.assertEqual(
            [(warp["dest_map"], warp["dest_warp_id"]) for warp in hns["warp_events"]],
            expected,
        )
        returns = {
            "PewterCity_Gym_Frlg": "2",
            "PewterCity_Mart_Frlg": "3",
            "PewterCity_House1_Frlg": "4",
            "PewterCity_PokemonCenter_1F_Frlg": "5",
            "PewterCity_House2_Frlg": "6",
        }
        for name, warp_id in returns.items():
            exterior_returns = [
                warp
                for warp in _map(name)["warp_events"]
                if warp["dest_map"] == HNS_ID
            ]
            self.assertTrue(exterior_returns)
            self.assertEqual(
                {warp["dest_warp_id"] for warp in exterior_returns}, {warp_id}
            )
        museum_returns = _map("PewterCity_Museum_1F_Frlg")["warp_events"]
        self.assertEqual(
            [(warp["dest_map"], warp["dest_warp_id"]) for warp in museum_returns[:-1]],
            [(HNS_ID, "0")] * 3 + [(HNS_ID, "1")] * 2,
        )
        self.assertEqual(museum_returns[-1]["dest_map"], "MAP_PEWTER_CITY_MUSEUM_2F")

    def test_heal_fly_and_debug_bindings_follow_normal_hns_pewter(self) -> None:
        heals = _json(ROOT / "src/data/heal_locations.json")["heal_locations"]
        pewter = next(row for row in heals if row["id"] == "HEAL_LOCATION_PEWTER_CITY")
        self.assertEqual(pewter["map"], HNS_ID)
        self.assertEqual((pewter["x"], pewter["y"]), (19, 30))
        self.assertEqual(pewter["respawn_map"], "MAP_PEWTER_CITY_POKEMON_CENTER_1F")
        region_map = (ROOT / "src/region_map.c").read_text()
        self.assertIn(
            "[MAPSEC_PEWTER_CITY] = {MAP_GROUP(MAP_PEWTER_CITY_HNS), MAP_NUM(MAP_PEWTER_CITY_HNS), HEAL_LOCATION_PEWTER_CITY}",
            region_map,
        )
        debug = (ROOT / "src/debug.c").read_text()
        self.assertIn("MUS_HG_PEWTER", debug)

    def test_hns_event_inventory_preserves_one_time_state_without_donor_extras(
        self,
    ) -> None:
        hns = _map(HNS)
        self.assertEqual(len(hns["object_events"]), 7)
        self.assertEqual(len(hns["coord_events"]), 8)
        self.assertEqual(len(hns["bg_events"]), 6)
        self.assertFalse(
            any(
                event["trainer_type"] != "TRAINER_TYPE_NONE"
                for event in hns["object_events"]
            )
        )
        scripts = {event["script"] for event in hns["object_events"]}
        self.assertEqual(
            scripts,
            {
                "PewterCity_Hns_EventScript_Lass",
                "PewterCity_Hns_EventScript_MuseumGuide",
                "PewterCity_Hns_EventScript_FatMan",
                "PewterCity_Hns_EventScript_BugCatcher",
                "PewterCity_Hns_EventScript_GymGuide",
                "EventScript_CutTree",
                "PewterCity_Hns_EventScript_RunningShoesAide",
            },
        )
        self.assertEqual(
            {event["flag"] for event in hns["object_events"] if event["flag"] != "0"},
            {
                "FLAG_HIDE_PEWTER_MUSEUM_GUIDE",
                "FLAG_HIDE_PEWTER_CITY_GYM_GUIDE",
                "FLAG_TEMP_12",
                "FLAG_HIDE_PEWTER_CITY_RUNNING_SHOES_GUY",
            },
        )
        script = ROOT / "data/maps/PewterCity_Hns/scripts.inc"
        running = _commands(script, "PewterCity_Hns_EventScript_GiveRunningShoes")
        self.assertIn(
            "goto_if_set FLAG_SYS_B_DASH, PewterCity_Hns_EventScript_RunningShoesAlreadyDelivered",
            running,
        )
        self.assertIn("setvar VAR_MAP_SCENE_PEWTER_CITY, 2", running)
        self.assertEqual(
            _commands(
                script, "PewterCity_Hns_EventScript_RunningShoesAlreadyDelivered"
            ),
            ["return"],
        )

    def test_hns_music_is_closed_over_the_exact_sample_manifest(self) -> None:
        songs = (ROOT / "include/constants/songs.h").read_text()
        self.assertRegex(songs, r"#define MUS_HG_PEWTER\s+610\b")
        self.assertIn(
            "song mus_hg_pewter, MUSIC_PLAYER_BGM, 0",
            (ROOT / "sound/song_table.inc").read_text(),
        )
        self.assertIn(
            "mus_hg_pewter.mid:", (ROOT / "sound/songs/midi/midi.cfg").read_text()
        )
        self.assertIn(
            '.include "sound/voicegroups/hns_pewter.inc"',
            (ROOT / "sound/voice_groups.inc").read_text(),
        )
        self.assertEqual(
            {
                path.name
                for path in (ROOT / "sound/direct_sound_samples").glob("hg_*.aif")
            },
            HNS_SAMPLES,
        )
        voices = (ROOT / "sound/voicegroups/hns_pewter.inc").read_text()
        direct = (ROOT / "sound/direct_sound_data.inc").read_text()
        for sample in HNS_SAMPLES:
            stem = sample.removesuffix(".aif")
            self.assertIn(f"DirectSoundWaveData_{stem}", voices)
            self.assertIn(f'"sound/direct_sound_samples/{stem}.bin"', direct)

    def test_content_port_records_hns_aliases_provenance_and_preserve_ownership(
        self,
    ) -> None:
        adaptations = _json(PORT / "adaptations.json")
        self.assertIn(
            {
                "layout": "LAYOUT_PEWTER_CITY_HNS",
                "field": "secondary_tileset",
                "source": "gTileset_PewterCity",
                "target": "gTileset_PewterCity_Hns",
            },
            adaptations["layoutTilesetRemaps"],
        )
        self.assertIn(
            {"hns": "MUS_HG_PEWTER", "target": "MUS_HG_PEWTER"},
            adaptations["musicAdaptations"],
        )
        aliases = [
            item
            for item in adaptations["tilesetAdaptations"]
            if item.get("targetSymbol") == "PewterCity_Hns"
        ]
        self.assertEqual(
            aliases,
            [
                {
                    "role": "secondary",
                    "directory": "pewter_city",
                    "symbol": "PewterCity",
                    "targetDirectory": "pewter_city_hns",
                    "targetSymbol": "PewterCity_Hns",
                    "secondary": True,
                    "paletteCount": 13,
                    "authority": "hns",
                }
            ],
        )
        capability = next(
            item
            for item in _json(PORT / "capabilities.json")["maps"]
            if item["map"] == HNS
        )
        self.assertEqual(
            (capability["sourceMap"], capability["ownership"]),
            ("PewterCity", "preserve"),
        )
        self.assertTrue(
            all(
                value == "story-owned"
                for key, value in capability["capabilities"].items()
                if key not in {"spatial", "environment-assets"}
            )
        )
        assets = _json(PORT / "assets.json")["assets"]
        self.assertTrue(
            any(
                item.get("semanticTarget")
                == "data/tilesets/secondary/pewter_city_hns/tiles.png"
                and item.get("donor") == "content"
                for item in assets
            )
        )
        permissions = _json(PORT / "assets.json")["permissionRecords"]
        self.assertTrue(
            any(
                item["path"] == "CREDITS.md" and item["permission"] == "redistributable"
                for item in permissions.values()
            )
        )

    def test_hns_events_fit_layout_bounds_and_the_local_graph_is_reachable(
        self,
    ) -> None:
        hns = _map(HNS)
        layouts = _json(ROOT / "data/layouts/layouts.json")["layouts"]
        layout = next(item for item in layouts if item["id"] == hns["layout"])
        for event in (
            hns["object_events"]
            + hns["warp_events"]
            + hns["coord_events"]
            + hns["bg_events"]
        ):
            self.assertGreaterEqual(event["x"], 0)
            self.assertGreaterEqual(event["y"], 0)
            self.assertLess(event["x"], layout["width"])
            self.assertLess(event["y"], layout["height"])
        nodes = {
            HNS,
            "Route2_Frlg",
            "Route3_Frlg",
            "PewterCity_Gym_Frlg",
            "PewterCity_Mart_Frlg",
            "PewterCity_House1_Frlg",
            "PewterCity_House2_Frlg",
            "PewterCity_PokemonCenter_1F_Frlg",
            "PewterCity_Museum_1F_Frlg",
        }
        docs = {name: _map(name) for name in nodes}
        ids = {document["id"]: name for name, document in docs.items()}
        edges = {name: set() for name in nodes}
        for name, document in docs.items():
            for destination in (document.get("connections") or []) + document["warp_events"]:
                target = destination.get("map", destination.get("dest_map"))
                if target in ids:
                    edges[name].add(ids[target])
        reached, pending = {HNS}, [HNS]
        while pending:
            for target in edges[pending.pop()]:
                if target not in reached:
                    reached.add(target)
                    pending.append(target)
        self.assertEqual(reached, nodes)
