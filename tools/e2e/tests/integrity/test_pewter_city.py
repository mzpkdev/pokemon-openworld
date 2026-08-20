from __future__ import annotations

from dataclasses import dataclass

import pytest

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
from tools.e2e.tests.integrity.test_pokecenter_regressions import (
    _add_debug_party,
    _current_debug_menu_is,
    _damage_and_poison_lead,
    _force_whiteout_and_wait_for_center,
    _interact_with_nurse,
    _last_heal_location,
)


SCRIPT_IDLE = 2
VAR_MAP_SCENE_PEWTER_CITY = 0x406C
FLAG_SYS_B_DASH = 0x8C0
G_MAIN_STATE_OFFSET = 0x438
G_MAIN_IN_BATTLE_MASK = 1 << 1


@dataclass(frozen=True)
class DoorCase:
    name: str
    x: int
    y: int
    destination: str


DOORS = (
    DoorCase("museum public", 19, 9, "PewterCity_Museum_1F_Frlg"),
    DoorCase("museum side", 27, 7, "PewterCity_Museum_1F_Frlg"),
    DoorCase("gym", 16, 19, "PewterCity_Gym_Frlg"),
    DoorCase("mart", 30, 23, "PewterCity_Mart_Frlg"),
    DoorCase("house one", 35, 16, "PewterCity_House1_Frlg"),
    DoorCase("pokemon center", 19, 30, "PewterCity_PokemonCenter_1F_Frlg"),
    DoorCase("house two", 11, 35, "PewterCity_House2_Frlg"),
)


def _maps():
    return {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }


def _integrity_load_ready(game) -> bool:
    """Mirror IntegrityMapLoad_IsReady before committing a host request."""
    main = game.address("gMain")
    return (
        game.read_u32(main) == (game.address("CB1_Overworld") | 1)
        and game.callback_is("CB2_Overworld")
        and game.read_u8(main + G_MAIN_STATE_OFFSET) == 0
        and not game.read_u8(main + G_MAIN_STATE_OFFSET + 1) & G_MAIN_IN_BATTLE_MASK
        and not game.read_u8(game.address("gLinkTransferringData"))
    )


def _wait_for_integrity_load_ready(game, description: str) -> None:
    game.wait_until(
        lambda: _integrity_load_ready(game),
        description=description,
        max_frames=1_800,
        step_frames=2,
    )


def _field_controls_ready(game) -> bool:
    """Return whether ordinary field input is safe after a map transition."""
    return (
        _integrity_load_ready(game)
        and not game.controls_locked()
        and game.script_status() == SCRIPT_IDLE
        and game.movement_idle()
    )


def _advance_to_field_controls(game, description: str) -> None:
    """Finish any real arrival script before sending the next test input.

    The integrity request reports FIELD_READY once its host-side transaction is
    complete.  Map and coordinate scripts begin afterwards, so that state is
    deliberately not also treated as permission to move the player or open
    the debug menu.
    """
    # Map and coordinate scripts are dispatched on the following field frame.
    # Give them a chance to claim control before accepting an idle field.
    game.step(2)
    game.advance_until(
        lambda: _field_controls_ready(game),
        description=description,
        max_pulses=1_800,
    )


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            _advance_to_field_controls(game, "settled Quickstart overworld")
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _load(game, entry, x: int, y: int, request_id: int) -> None:
    _wait_for_integrity_load_ready(game, f"ready to load {entry.name}")
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=x,
            y=y,
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    _advance_to_field_controls(game, f"settled {entry.name} load")


def _hold_until_map(game, direction: str, destination) -> None:
    game.set_buttons(**{direction: True})
    try:
        for _ in range(1_800):
            game.step()
            if game.map_id() == destination.map_id:
                game.set_buttons(**{direction: False})
                _advance_to_field_controls(game, f"settled {destination.name} arrival")
                return
    finally:
        game.set_buttons(**{direction: False})
    raise AssertionError(
        f"{direction} did not reach {destination.name}; map={game.map_id()}"
    )


def _open_utilities(game) -> None:
    assert _field_controls_ready(game), "debug utilities require field controls"
    game.set_buttons(R=True)
    game.step()
    game.set_buttons(R=True, Start=True)
    game.step()
    game.set_buttons(R=False, Start=False)
    game.step()
    game.wait_until(
        lambda: game.task_active("DebugTask_HandleMenuInput_General"),
        description="debug main menu",
        max_frames=300,
    )
    game.advance_until(
        lambda: _current_debug_menu_is(game, "sDebugMenu_Actions_Utilities", level=1),
        description="Utilities debug submenu",
        max_pulses=20,
    )
    game.step(2)


def _named_warp_task(game, function: str) -> int:
    expected = game.address(function) | 1
    tasks = game.address("gTasks")
    for task_id in range(16):
        task = tasks + task_id * 0x28
        if game.read_u8(task + 4) and game.read_u32(task) == expected:
            return task
    raise AssertionError(f"named-warp task {function} is not active")


def _wait_for_named_warp_task(game, function: str) -> int:
    task = None

    def active() -> bool:
        nonlocal task
        expected = game.address(function) | 1
        tasks = game.address("gTasks")
        for task_id in range(16):
            candidate = tasks + task_id * 0x28
            if game.read_u8(candidate + 4) and game.read_u32(candidate) == expected:
                task = candidate
                return True
        return False

    game.wait_until(
        active,
        description=f"named-warp task {function}",
        max_frames=300,
        step_frames=2,
    )
    assert task is not None
    return task


def _select_named_warp_map(game, target) -> None:
    """Drive Utilities > Warp by name using the live task selection state."""
    _open_utilities(game)
    game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.press("Down", release_frames=2)  # Hoenn -> Kanto
    game.press("A", release_frames=2)

    for _ in range(128):
        task = _wait_for_named_warp_task(
            game, "DebugAction_Util_Warp_SelectNamedMapGroup"
        )
        if game.read_u16(task + 8 + 5 * 2) == target.group:
            break
        game.press("Down", release_frames=2)
    else:
        raise AssertionError(
            f"Kanto named-warp group {target.group} was not selectable"
        )
    game.press("A", release_frames=2)

    for _ in range(128):
        task = _wait_for_named_warp_task(game, "DebugAction_Util_Warp_SelectNamedMap")
        if game.read_u16(task + 8 + 6 * 2) == target.number:
            return
        game.press("Down", release_frames=2)
    raise AssertionError(f"named-warp map {target.name} was not selectable")


@pytest.mark.parametrize("case", DOORS, ids=lambda case: case.name)
def test_hns_pewter_doors_round_trip_to_frlg_interiors(integrity_game, case):
    _settle_overworld(integrity_game)
    maps = _maps()
    hns = maps["PewterCity_Hns"]
    interior = maps[case.destination]
    _load(integrity_game, hns, case.x, case.y, 0xF5820001)

    _hold_until_map(integrity_game, "Up", interior)
    _hold_until_map(integrity_game, "Down", hns)
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert not integrity_game.controls_locked()


def test_hns_museum_public_and_side_entries_stay_distinct(integrity_game):
    _settle_overworld(integrity_game)
    maps = _maps()
    hns = maps["PewterCity_Hns"]
    museum = maps["PewterCity_Museum_1F_Frlg"]
    entries = []
    for request_id, case in enumerate(DOORS[:2], 0xF5820100):
        _load(integrity_game, hns, case.x, case.y, request_id)
        _hold_until_map(integrity_game, "Up", museum)
        entries.append(integrity_game.position())
    assert entries[0] != entries[1], "museum public and side doors collapsed"


@pytest.mark.parametrize(
    ("source", "x", "y", "direction", "destination", "request_id"),
    (
        ("Route2_Frlg", 8, 1, "Up", "PewterCity_Hns", 0xF5820200),
        ("Route3_Frlg", 1, 9, "Left", "PewterCity_Hns", 0xF5820201),
        ("PewterCity_Hns", 22, 42, "Down", "Route2_Frlg", 0xF5820202),
        ("PewterCity_Hns", 50, 24, "Right", "Route3_Frlg", 0xF5820203),
    ),
)
def test_normal_kanto_pewter_seams_are_bidirectional(
    integrity_game, source, x, y, direction, destination, request_id
):
    _settle_overworld(integrity_game)
    maps = _maps()
    _load(integrity_game, maps[source], x, y, request_id)
    _hold_until_map(integrity_game, direction, maps[destination])


def test_hns_running_shoes_progression_is_one_time(integrity_game):
    _settle_overworld(integrity_game)
    hns = _maps()["PewterCity_Hns"]
    integrity_game.set_flag(FLAG_SYS_B_DASH, False)
    integrity_game.set_var(VAR_MAP_SCENE_PEWTER_CITY, 1)
    _load(integrity_game, hns, 49, 25, 0xF5820300)
    assert integrity_game.read_flag(FLAG_SYS_B_DASH)
    assert integrity_game.read_var(VAR_MAP_SCENE_PEWTER_CITY) == 2
    integrity_game.set_var(VAR_MAP_SCENE_PEWTER_CITY, 1)
    _load(integrity_game, hns, 49, 25, 0xF5820301)
    assert integrity_game.read_flag(FLAG_SYS_B_DASH)
    assert integrity_game.read_var(VAR_MAP_SCENE_PEWTER_CITY) == 1


def test_debug_named_warp_frlg_gym_exit_returns_to_hns(integrity_game):
    _settle_overworld(integrity_game)
    maps = _maps()
    _select_named_warp_map(integrity_game, maps["PewterCity_Frlg"])
    integrity_game.press("A", release_frames=2)  # map -> entry picker
    for _ in range(3):
        integrity_game.press("Down", release_frames=2)  # third FRLG warp is Gym
    integrity_game.press("A", release_frames=2)
    integrity_game.wait_for_map(maps["PewterCity_Gym_Frlg"].map_id, max_frames=1_800)
    integrity_game.wait_for_controls_unlocked(max_frames=1_200)
    _hold_until_map(integrity_game, "Down", maps["PewterCity_Hns"])


def test_hns_pokecenter_heal_and_whiteout_use_hns_checkpoint(integrity_game):
    _settle_overworld(integrity_game)
    _add_debug_party(integrity_game)
    maps = _maps()
    center = maps["PewterCity_PokemonCenter_1F_Frlg"]
    _load(integrity_game, center, 7, 3, 0xF5820350)
    mon, max_hp = _damage_and_poison_lead(integrity_game)
    nurse = {"direction": "Up", "nurseLocalId": 3}
    _interact_with_nurse(integrity_game, nurse, mon, max_hp)
    hns = maps["PewterCity_Hns"]
    expected = (hns.group, hns.number, -1, 19, 30)
    assert _last_heal_location(integrity_game) == expected
    _force_whiteout_and_wait_for_center(integrity_game, center, nurse)
    assert _last_heal_location(integrity_game) == expected


def test_debug_fly_ui_returns_to_hns_pewter_heal_coordinate(integrity_game):
    _settle_overworld(integrity_game)
    hns = _maps()["PewterCity_Hns"]
    _load(integrity_game, hns, 19, 30, 0xF5820400)
    _open_utilities(integrity_game)
    game = integrity_game
    game.press("A", release_frames=2)  # Utilities > Fly to map
    game.wait_for_callback("CB2_FlyMap", max_frames=1_200)
    game.step(180)
    game.press("A", release_frames=2)
    game.wait_for_map(hns.map_id, max_frames=2_400)
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (19, 30)
