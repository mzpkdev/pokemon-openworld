"""Runtime integrity coverage for issue #102's seamless southern Kanto basin."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)
from tools.e2e.tests.integrity.test_surf_edge_exits import (
    DIR_EAST,
    DIR_NORTH,
    DIR_SOUTH,
    DIR_WEST,
    MUS_RG_ROUTE3,
    PLAYER_AVATAR_FLAG_SURFING,
    WEATHER_SUNNY,
    _assert_field_ready,
    _assert_map_presentation,
    _settle_overworld,
)
from tools.e2e.tests.integrity.test_world_tier_encounters import (
    PROBE_REQUEST_STATUS_OFFSET,
    PROBE_RESULT_FORMAT,
    PROBE_RESULT_SIZE,
    ProbeStatus,
    WILD_AREA_WATER,
    WILD_ENCOUNTER_FISHING_ROD_NONE,
)


ROOT = Path(__file__).resolve().parents[4]
MAPS_ROOT = ROOT / "data/maps"
LAYOUTS = ROOT / "data/layouts/layouts.json"

MAPGRID_METATILE_ID_MASK = 0x03FF
MAPGRID_COLLISION_MASK = 0x0C00
PRIMARY_FRLG_METATILES = 640
MB_FRLG_OCEAN_WATER = 0x15
WILD_AREA_FISHING = 3
PALETTE_FADE_ACTIVE_MASK = 1 << 31
WARP_TASKS = ("Task_WarpAndLoadMap", "Task_DoDoorWarp")
PROBE_ERROR_HEADER = 2

WEST = "SouthernKantoSeaBasin_West_Frlg"
CENTRAL = "SouthernKantoSeaBasin_Central_Frlg"
EAST = "SouthernKantoSeaBasin_East_Frlg"

# One physical seam per row.  The runtime test traverses each row forward and
# backward, providing all sixteen directed connections as independent checks.
SEAMS = (
    ("Route21_North_Frlg", "Right", WEST, 0),
    ("Route21_South_Frlg", "Right", WEST, -50),
    ("Route20_Frlg", "Up", WEST, 0),
    ("Route20_Frlg", "Up", CENTRAL, 48),
    ("Route20_Frlg", "Up", EAST, 108),
    (WEST, "Right", CENTRAL, 0),
    (CENTRAL, "Right", EAST, 69),
    ("Route19_Frlg", "Left", EAST, 9),
)
OPPOSITE_BUTTON = {"Up": "Down", "Down": "Up", "Left": "Right", "Right": "Left"}
FACING = {"Up": DIR_NORTH, "Down": DIR_SOUTH, "Left": DIR_WEST, "Right": DIR_EAST}


def _maps_by_name() -> dict[str, dict]:
    return {
        document["name"]: document
        for path in MAPS_ROOT.glob("*/map.json")
        if (document := json.loads(path.read_text(encoding="utf-8")))
    }


def _layouts_by_id() -> dict[str, dict]:
    return {
        layout["id"]: layout
        for layout in json.loads(LAYOUTS.read_text(encoding="utf-8"))["layouts"]
    }


def _grid(layout: dict) -> tuple[int, ...]:
    payload = (ROOT / layout["blockdata_filepath"]).read_bytes()
    return struct.unpack(f"<{layout['width'] * layout['height']}H", payload)


def _attributes() -> tuple[int, ...]:
    payload = (
        ROOT / "data/tilesets/primary/general_frlg/metatile_attributes.bin"
    ).read_bytes()
    return struct.unpack(f"<{len(payload) // 4}I", payload)


def _is_surfable_ocean(word: int, attributes: tuple[int, ...]) -> bool:
    metatile = word & MAPGRID_METATILE_ID_MASK
    return (
        metatile < PRIMARY_FRLG_METATILES
        and not word & MAPGRID_COLLISION_MASK
        and attributes[metatile] & 0x1FF == MB_FRLG_OCEAN_WATER
    )


def _paired_seam_cells(source: dict, target: dict, direction: str, offset: int):
    source_layout = _layouts_by_id()[source["layout"]]
    target_layout = _layouts_by_id()[target["layout"]]
    source_grid = _grid(source_layout)
    target_grid = _grid(target_layout)
    attributes = _attributes()
    source_width, source_height = source_layout["width"], source_layout["height"]
    target_width, target_height = target_layout["width"], target_layout["height"]
    if direction == "Up":
        candidates = (
            (x, 0, x - offset, target_height - 1) for x in range(source_width)
        )
    elif direction == "Down":
        candidates = (
            (x, source_height - 1, x - offset, 0) for x in range(source_width)
        )
    elif direction == "Left":
        candidates = (
            (0, y, target_width - 1, y - offset) for y in range(source_height)
        )
    else:
        candidates = (
            (source_width - 1, y, 0, y - offset) for y in range(source_height)
        )
    for source_x, source_y, target_x, target_y in candidates:
        if not (0 <= target_x < target_width and 0 <= target_y < target_height):
            continue
        source_word = source_grid[source_y * source_width + source_x]
        target_word = target_grid[target_y * target_width + target_x]
        if _is_surfable_ocean(source_word, attributes) and _is_surfable_ocean(
            target_word, attributes
        ):
            return (source_x, source_y), (target_x, target_y)
    raise AssertionError(
        f"{source['name']} {direction} -> {target['name']} has no paired Surf cells"
    )


def _load_map(game, entry, position: tuple[int, int], request_id: int) -> None:
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=position[0],
            y=position[1],
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    game.wait_for_controls_unlocked(max_frames=1_200)


def _set_surfing(game) -> None:
    avatar = game.address("gPlayerAvatar")
    game.write_u8(avatar, game.read_u8(avatar) | PLAYER_AVATAR_FLAG_SURFING)
    assert game.read_u8(avatar) & PLAYER_AVATAR_FLAG_SURFING


def _assert_no_transition(game) -> None:
    assert (
        not game.read_u32(game.address("gPaletteFade") + 12) & PALETTE_FADE_ACTIVE_MASK
    )
    assert not any(game.task_active(task) for task in WARP_TASKS)


def _cross_without_warp(
    game, button: str, destination, position: tuple[int, int]
) -> None:
    """Cross one cardinal seam while observing every frame for warp/fade state."""
    for _ in range(80):
        _assert_no_transition(game)
        game.set_buttons(**{button: True})
        game.step()
        _assert_no_transition(game)
        game.set_buttons(**{button: False})
        game.step()
        _assert_no_transition(game)
        if game.map_id() == destination.map_id:
            _assert_field_ready(game, destination, position, FACING[button])
            return
    raise AssertionError(f"did not reach {destination.name} by crossing {button}")


def _probe_missing_header(
    game, *, request_id: int, area: int, fishing_rod: int
) -> None:
    request = game.address("gWildEncounterProbeRequest")
    result = game.address("gWildEncounterProbeResult")
    game.pause()
    game.write(result, bytes(PROBE_RESULT_SIZE))
    game.write(
        request,
        struct.pack(
            "<IH6B",
            request_id,
            0,
            area,
            fishing_rod,
            0,
            0,
            0,
            ProbeStatus.IDLE,
        ),
    )
    game.write_u8(request + PROBE_REQUEST_STATUS_OFFSET, ProbeStatus.PENDING)
    game.resume()
    for _ in range(120):
        fields = struct.unpack(
            PROBE_RESULT_FORMAT, game.read(result, PROBE_RESULT_SIZE)
        )
        status = ProbeStatus(fields[-1])
        if fields[0] == request_id and status is ProbeStatus.ERROR:
            assert fields[-2] == PROBE_ERROR_HEADER
            assert fields[7] == area
            assert fields[8] == fishing_rod
            return
        game.step()
    raise AssertionError(f"missing-header probe {request_id:#x} timed out")


def test_southern_kanto_basin_crosses_all_seams_without_warps_or_fades(integrity_game):
    manifest = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    documents = _maps_by_name()
    _settle_overworld(integrity_game)

    for index, (source_name, direction, destination_name, offset) in enumerate(SEAMS):
        source_document = documents[source_name]
        destination_document = documents[destination_name]
        source = manifest[source_name]
        destination = manifest[destination_name]
        source_position, destination_position = _paired_seam_cells(
            source_document, destination_document, direction, offset
        )
        _load_map(integrity_game, source, source_position, 0x10200000 + index * 2)
        _set_surfing(integrity_game)
        _cross_without_warp(
            integrity_game, direction, destination, destination_position
        )
        _assert_map_presentation(
            integrity_game, destination, MUS_RG_ROUTE3, WEATHER_SUNNY
        )

        reverse_direction = OPPOSITE_BUTTON[direction]
        _load_map(
            integrity_game,
            destination,
            destination_position,
            0x10200001 + index * 2,
        )
        _set_surfing(integrity_game)
        _cross_without_warp(integrity_game, reverse_direction, source, source_position)
        _assert_map_presentation(integrity_game, source, MUS_RG_ROUTE3, WEATHER_SUNNY)


def test_southern_kanto_basin_has_no_encounters_or_fishing_and_persists(integrity_game):
    manifest = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    documents = _maps_by_name()
    _settle_overworld(integrity_game)

    # The established Route 19 generated-ocean round trip remains covered by
    # test_surf_edges_cross_kanto_and_johto_and_survive_cold_restart.  Here we
    # exercise each new static sector's independent persistence and empty wild
    # encounter registry behavior.
    entry_positions = {
        WEST: _paired_seam_cells(
            documents["Route21_North_Frlg"], documents[WEST], "Right", 0
        )[1],
        CENTRAL: _paired_seam_cells(documents[WEST], documents[CENTRAL], "Right", 0)[1],
        EAST: _paired_seam_cells(documents[CENTRAL], documents[EAST], "Right", 69)[1],
    }
    for index, name in enumerate((WEST, CENTRAL, EAST)):
        entry = manifest[name]
        position = entry_positions[name]
        _load_map(integrity_game, entry, position, 0x10200100 + index)
        _set_surfing(integrity_game)
        _probe_missing_header(
            integrity_game,
            request_id=0x10200200 + index * 4,
            area=WILD_AREA_WATER,
            fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
        )
        for rod in range(3):
            _probe_missing_header(
                integrity_game,
                request_id=0x10200201 + index * 4 + rod,
                area=WILD_AREA_FISHING,
                fishing_rod=rod,
            )
        facing = integrity_game.facing_direction()
        save_from_start_menu(integrity_game)
        cold_restart_and_continue(integrity_game)
        _assert_field_ready(integrity_game, entry, position, facing)
