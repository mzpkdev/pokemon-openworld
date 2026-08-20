"""Live topology contract for issue #102's static southern Kanto sea basin.

This test deliberately reads the authored map and layout inputs instead of a
generated manifest.  It guards the append-only registry allocation and the raw
map-grid properties that make an ordinary cardinal connection safe to Surf
across.
"""

from __future__ import annotations

import json
import struct
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPS_ROOT = ROOT / "data/maps"
LAYOUTS = ROOT / "data/layouts/layouts.json"
GROUPS = ROOT / "data/maps/map_groups.json"
ENCOUNTERS = ROOT / "src/data/wild_encounters.json"

MAP_OFFSET = 7
MAX_MAP_DATA_SIZE = 10_240
PRIMARY_FRLG_METATILES = 640
MAPGRID_METATILE_ID_MASK = 0x03FF
MAPGRID_COLLISION_MASK = 0x0C00
MB_FRLG_OCEAN_WATER = 0x15


@dataclass(frozen=True)
class BasinMap:
    name: str
    map_id: str
    layout_id: str
    size: tuple[int, int]
    buffer_cells: int
    section: str


WEST = BasinMap(
    "SouthernKantoSeaBasin_West_Frlg",
    "MAP_SOUTHERN_KANTO_SEA_BASIN_WEST",
    "LAYOUT_SOUTHERN_KANTO_SEA_BASIN_WEST",
    (48, 100),
    7_182,
    "MAPSEC_ROUTE_21",
)
CENTRAL = BasinMap(
    "SouthernKantoSeaBasin_Central_Frlg",
    "MAP_SOUTHERN_KANTO_SEA_BASIN_CENTRAL",
    "LAYOUT_SOUTHERN_KANTO_SEA_BASIN_CENTRAL",
    (60, 100),
    8_550,
    "MAPSEC_ROUTE_20",
)
EAST = BasinMap(
    "SouthernKantoSeaBasin_East_Frlg",
    "MAP_SOUTHERN_KANTO_SEA_BASIN_EAST",
    "LAYOUT_SOUTHERN_KANTO_SEA_BASIN_EAST",
    (12, 31),
    1_215,
    "MAPSEC_ROUTE_19",
)
BASIN = (WEST, CENTRAL, EAST)

# (source map id, direction, destination map id, offset).  This records all
# eight physical seams, while the assertions below require their exact reverse
# links too (sixteen directed cardinal connections in total).
SEAMS = (
    ("MAP_ROUTE21_NORTH", "right", WEST.map_id, 0),
    ("MAP_ROUTE21_SOUTH", "right", WEST.map_id, -50),
    ("MAP_ROUTE20", "up", WEST.map_id, 0),
    ("MAP_ROUTE20", "up", CENTRAL.map_id, 48),
    ("MAP_ROUTE20", "up", EAST.map_id, 108),
    (WEST.map_id, "right", CENTRAL.map_id, 0),
    (CENTRAL.map_id, "right", EAST.map_id, 69),
    ("MAP_ROUTE19", "left", EAST.map_id, 9),
)
REVERSE_DIRECTION = {"up": "down", "down": "up", "left": "right", "right": "left"}


def _map_documents() -> dict[str, dict]:
    documents = {}
    for path in MAPS_ROOT.glob("*/map.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        documents[document["id"]] = document
    return documents


def _layouts() -> dict[str, dict]:
    return {
        layout["id"]: layout
        for layout in json.loads(LAYOUTS.read_text(encoding="utf-8"))["layouts"]
    }


def _connections(document: dict) -> list[dict]:
    return document.get("connections", [])


def _connection(document: dict, destination: str, direction: str) -> dict:
    matches = [
        connection
        for connection in _connections(document)
        if connection["map"] == destination and connection["direction"] == direction
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"{document['name']}: expected one {direction} connection to {destination}, "
            f"found {matches!r}"
        )
    return matches[0]


def _opposite_offset(offset: int) -> int:
    """Cardinal connection offsets are reciprocal signed translations."""
    return -offset


def _grid(layout: dict) -> tuple[int, ...]:
    path = ROOT / layout["blockdata_filepath"]
    words = path.read_bytes()
    expected = layout["width"] * layout["height"] * 2
    if len(words) != expected:
        raise AssertionError(f"{path}: expected {expected} bytes, got {len(words)}")
    return struct.unpack(f"<{layout['width'] * layout['height']}H", words)


def _cell(grid: tuple[int, ...], layout: dict, x: int, y: int) -> int:
    if not (0 <= x < layout["width"] and 0 <= y < layout["height"]):
        raise AssertionError(f"cell ({x}, {y}) outside {layout['name']}")
    return grid[y * layout["width"] + x]


def _attribute_blob() -> tuple[int, ...]:
    blob = ROOT / "data/tilesets/primary/general_frlg/metatile_attributes.bin"
    payload = blob.read_bytes()
    if len(payload) % 4:
        raise AssertionError(f"{blob}: FRLG attributes are not u32 aligned")
    return struct.unpack(f"<{len(payload) // 4}I", payload)


def _is_primary(word: int) -> bool:
    return (word & MAPGRID_METATILE_ID_MASK) < PRIMARY_FRLG_METATILES


def _is_surfable_ocean(word: int, attributes: tuple[int, ...]) -> bool:
    metatile = word & MAPGRID_METATILE_ID_MASK
    return (
        _is_primary(word)
        and not (word & MAPGRID_COLLISION_MASK)
        and attributes[metatile] & 0x1FF == MB_FRLG_OCEAN_WATER
    )


def _seam_cells(
    source_layout: dict, destination_layout: dict, direction: str, offset: int
):
    """Yield paired in-map cells across the authored connection boundary."""
    source_width, source_height = source_layout["width"], source_layout["height"]
    destination_width, destination_height = (
        destination_layout["width"],
        destination_layout["height"],
    )
    if direction == "up":
        for source_x in range(source_width):
            destination_x = source_x - offset
            if 0 <= destination_x < destination_width:
                yield source_x, 0, destination_x, destination_height - 1
    elif direction == "down":
        for source_x in range(source_width):
            destination_x = source_x - offset
            if 0 <= destination_x < destination_width:
                yield source_x, source_height - 1, destination_x, 0
    elif direction == "left":
        for source_y in range(source_height):
            destination_y = source_y - offset
            if 0 <= destination_y < destination_height:
                yield 0, source_y, destination_width - 1, destination_y
    elif direction == "right":
        for source_y in range(source_height):
            destination_y = source_y - offset
            if 0 <= destination_y < destination_height:
                yield source_width - 1, source_y, 0, destination_y
    else:
        raise AssertionError(f"unknown cardinal direction {direction!r}")


class SouthernKantoSeaBasinContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.maps = _map_documents()
        cls.layouts = _layouts()
        cls.attributes = _attribute_blob()
        cls.grids = {
            layout_id: _grid(layout)
            for layout_id, layout in cls.layouts.items()
            if layout_id in {entry.layout_id for entry in BASIN}
            or layout_id in {cls.maps[map_id]["layout"] for map_id, _, _, _ in SEAMS}
        }

    def test_append_only_registry_allocation_and_layout_geometry(self) -> None:
        groups = json.loads(GROUPS.read_text(encoding="utf-8"))
        names = groups["gMapGroup_TownsAndRoutes_Frlg"]
        self.assertEqual(names[-3:], [entry.name for entry in BASIN])

        layouts_in_order = json.loads(LAYOUTS.read_text(encoding="utf-8"))["layouts"]
        self.assertEqual(
            [layout["id"] for layout in layouts_in_order[-3:]],
            [entry.layout_id for entry in BASIN],
        )

        for entry in BASIN:
            with self.subTest(map=entry.name):
                document = self.maps[entry.map_id]
                layout = self.layouts[entry.layout_id]
                self.assertEqual(document["name"], entry.name)
                self.assertEqual(document["layout"], entry.layout_id)
                self.assertEqual((layout["width"], layout["height"]), entry.size)
                self.assertEqual(layout["format"], "frlg")
                self.assertEqual(layout["primary_tileset"], "gTileset_General_Frlg")
                self.assertEqual(
                    layout["blockdata_filepath"], f"data/layouts/{entry.name}/map.bin"
                )
                self.assertEqual(
                    layout["border_filepath"], f"data/layouts/{entry.name}/border.bin"
                )
                self.assertEqual(
                    (ROOT / layout["blockdata_filepath"]).stat().st_size,
                    entry.size[0] * entry.size[1] * 2,
                )
                buffer_cells = (entry.size[0] + MAP_OFFSET * 2 + 1) * (
                    entry.size[1] + MAP_OFFSET * 2
                )
                self.assertEqual(buffer_cells, entry.buffer_cells)
                self.assertLessEqual(buffer_cells, MAX_MAP_DATA_SIZE)

    def test_empty_static_map_contract_and_absent_encounters(self) -> None:
        wild = json.loads(ENCOUNTERS.read_text(encoding="utf-8"))
        encounter_ids = {
            encounter.get("map")
            for group in wild["wild_encounter_groups"]
            for encounter in group.get("encounters", [])
            if "map" in encounter
        }
        for entry in BASIN:
            with self.subTest(map=entry.name):
                document = self.maps[entry.map_id]
                self.assertEqual(document["region"], "REGION_KANTO")
                self.assertEqual(document["region_map_section"], entry.section)
                self.assertEqual(document["music"], "MUS_RG_ROUTE3")
                self.assertEqual(document["weather"], "WEATHER_SUNNY")
                self.assertEqual(document["map_type"], "MAP_TYPE_ROUTE")
                self.assertFalse(document.get("show_map_name", True) is False)
                for event_kind in (
                    "object_events",
                    "warp_events",
                    "coord_events",
                    "bg_events",
                ):
                    self.assertEqual(document.get(event_kind), [], event_kind)
                script = MAPS_ROOT / entry.name / "scripts.inc"
                self.assertEqual(
                    script.read_text(encoding="utf-8").strip(),
                    f"{entry.name}_MapScripts::\n\t.byte 0",
                )
                self.assertNotIn(entry.map_id, encounter_ids)

    def test_all_eight_seams_are_reciprocal_and_route19_remains_disjoint(self) -> None:
        for source_id, direction, destination_id, offset in SEAMS:
            with self.subTest(source=source_id, destination=destination_id):
                source = self.maps[source_id]
                destination = self.maps[destination_id]
                forward = _connection(source, destination_id, direction)
                self.assertEqual(forward["offset"], offset)
                reverse = _connection(
                    destination, source_id, REVERSE_DIRECTION[direction]
                )
                self.assertEqual(reverse["offset"], _opposite_offset(offset))

        route19 = self.maps["MAP_ROUTE19"]
        sea_east = _connection(route19, EAST.map_id, "left")
        route20 = _connection(route19, "MAP_ROUTE20", "left")
        self.assertEqual(sea_east["offset"], 9)
        self.assertEqual(route20["offset"], 40)
        east_height = self.layouts[EAST.layout_id]["height"]
        self.assertEqual(
            (sea_east["offset"], sea_east["offset"] + east_height - 1), (9, 39)
        )
        self.assertEqual((route20["offset"], route20["offset"] + 19), (40, 59))
        self.assertLess(sea_east["offset"] + east_height - 1, route20["offset"])
        self.assertEqual(
            route19["edge_exits"],
            [
                {
                    "exit_edge": "south",
                    "target_map": "MAP_ROUTE40",
                    "target_x": 0,
                    "target_y": 30,
                    "target_facing": "east",
                    "route_profile": "generated_ocean",
                }
            ],
        )

    def test_connection_margins_are_primary_and_open_water_is_surfable(self) -> None:
        for source_id, direction, destination_id, offset in SEAMS:
            source = self.maps[source_id]
            destination = self.maps[destination_id]
            source_layout = self.layouts[source["layout"]]
            destination_layout = self.layouts[destination["layout"]]
            source_grid = self.grids[source["layout"]]
            destination_grid = self.grids[destination["layout"]]
            pairs = list(
                _seam_cells(source_layout, destination_layout, direction, offset)
            )
            self.assertTrue(pairs, f"{source_id} -> {destination_id} has no overlap")
            surfable_pairs = 0
            for source_x, source_y, destination_x, destination_y in pairs:
                source_word = _cell(source_grid, source_layout, source_x, source_y)
                destination_word = _cell(
                    destination_grid, destination_layout, destination_x, destination_y
                )
                self.assertTrue(_is_primary(source_word))
                self.assertTrue(_is_primary(destination_word))
                source_blocked = bool(source_word & MAPGRID_COLLISION_MASK)
                destination_blocked = bool(destination_word & MAPGRID_COLLISION_MASK)
                self.assertEqual(
                    source_blocked,
                    destination_blocked,
                    f"{source['name']} ({source_x}, {source_y}) and "
                    f"{destination['name']} ({destination_x}, {destination_y}) "
                    "disagree on collision",
                )
                self.assertEqual(
                    source_word,
                    destination_word,
                    f"{source['name']} ({source_x}, {source_y}) and "
                    f"{destination['name']} ({destination_x}, {destination_y}) "
                    "do not use matching primary seam geometry",
                )
                if not source_blocked:
                    self.assertTrue(
                        _is_surfable_ocean(source_word, self.attributes),
                        f"{source['name']} ({source_x}, {source_y}) is open but not Surfable ocean",
                    )
                    surfable_pairs += 1
            self.assertGreater(
                surfable_pairs,
                0,
                f"{source['name']} -> {destination['name']} lacks a Surfable seam cell",
            )

    def test_seafoam_and_unfinished_edges_stay_blocked_with_ocean_borders(self) -> None:
        route20 = self.maps["MAP_ROUTE20"]
        route20_layout = self.layouts[route20["layout"]]
        central_layout = self.layouts[CENTRAL.layout_id]
        route20_grid = self.grids[route20["layout"]]
        central_grid = self.grids[CENTRAL.layout_id]
        blocked_seafoam_cells = 0
        for route_x, central_x in zip(range(58, 78), range(10, 30)):
            route_word = _cell(route20_grid, route20_layout, route_x, 0)
            central_word = _cell(
                central_grid, central_layout, central_x, central_layout["height"] - 1
            )
            if route_word & MAPGRID_COLLISION_MASK:
                blocked_seafoam_cells += 1
                self.assertNotEqual(central_word & MAPGRID_COLLISION_MASK, 0)
        self.assertGreater(blocked_seafoam_cells, 0)

        # Every outer edge not occupied by a connection is collision-blocked in
        # the map.  The matching border is primary ocean water so camera margin
        # filling cannot expose a secondary palette or undefined tile.
        unfinished = {
            # Corner cells also participate in an adjacent cardinal connection,
            # so they are connection water rather than unfinished outer rim.
            WEST.layout_id: (("up", range(1, WEST.size[0] - 1)),),
            CENTRAL.layout_id: (
                ("up", range(1, CENTRAL.size[0])),
                ("right", range(69)),
            ),
            EAST.layout_id: (("up", range(1, EAST.size[0] - 1)),),
        }
        for layout_id, edges in unfinished.items():
            layout = self.layouts[layout_id]
            grid = self.grids[layout_id]
            for direction, positions in edges:
                for position in positions:
                    x, y = {
                        "up": (position, 0),
                        "right": (layout["width"] - 1, position),
                    }[direction]
                    self.assertNotEqual(
                        _cell(grid, layout, x, y) & MAPGRID_COLLISION_MASK,
                        0,
                        f"{layout['name']} {direction} outer edge at {position} is open",
                    )
            border = (ROOT / layout["border_filepath"]).read_bytes()
            self.assertTrue(border and len(border) % 2 == 0)
            for word in struct.unpack(f"<{len(border) // 2}H", border):
                self.assertTrue(_is_primary(word))
                self.assertEqual(
                    self.attributes[word & MAPGRID_METATILE_ID_MASK] & 0x1FF,
                    MB_FRLG_OCEAN_WATER,
                )


if __name__ == "__main__":
    unittest.main()
