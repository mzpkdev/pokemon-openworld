from __future__ import annotations

import struct

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


SCRIPT_IDLE = 2
SAILOR_LOCAL_ID = 1
VERMILION_PORT_ENTRY = (8, 9)
OLIVINE_PORT_ENTRY = (8, 16)

REGIONAL_STORY_STATE = (
    ("Hoenn", 0x20, 0x40A4, 1),
    ("Kanto", 0x21, 0x4052, 1),
    ("Sevii", 0x2A1, 0x4075, 2),
    ("Johto", 0x22, 0x40F7, 1),
)


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _load_map(game, entry, coordinates: tuple[int, int], request_id: int) -> None:
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=coordinates[0],
            y=coordinates[1],
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    assert game.position() == coordinates
    game.wait_for_controls_unlocked(max_frames=1_200)


def _take_ferry(game, destination, arrival: tuple[int, int]) -> None:
    game.face("Down")
    game.press("A")
    game.wait_until(
        lambda: (
            game.controls_locked()
            and game.read_u16(game.address("gSpecialVar_LastTalked")) == SAILOR_LOCAL_ID
        ),
        description="reachable regional ferry sailor",
        max_frames=120,
    )
    game.advance_until(
        lambda: game.map_id() == destination.map_id,
        description=f"regional ferry arrival in {destination.name}",
        max_pulses=600,
        button="A",
    )
    game.wait_until(
        lambda: (
            game.callback_is("CB2_Overworld")
            and not game.controls_locked()
            and game.script_status() == SCRIPT_IDLE
            and game.movement_idle()
        ),
        description=f"{destination.name} field-ready ferry arrival",
        max_frames=1_800,
        step_frames=2,
    )
    assert game.position() == arrival


def _assert_runtime_story_state(game) -> None:
    for region, flag_id, var_id, value in REGIONAL_STORY_STATE:
        assert game.read_flag(flag_id), f"{region} regional fact was lost"
        assert game.read_var(var_id) == value, f"{region} regional variable was lost"


def _assert_serialized_story_state(image) -> None:
    block1 = image.active_slot.save_block1
    for region, flag_id, var_id, value in REGIONAL_STORY_STATE:
        assert image.active_slot.saved_flag(flag_id), (
            f"{region} regional fact was not serialized"
        )
        offset = 0x139C + (var_id - 0x4000) * 2
        assert struct.unpack_from("<H", block1, offset)[0] == value, (
            f"{region} regional variable was not serialized"
        )


def test_four_region_story_state_survives_round_trip_and_cold_restart(
    integrity_game,
):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    vermilion = maps["VermilionCity_PortInside"]
    olivine = maps["OlivineCity_PortInside"]

    _settle_overworld(integrity_game)

    # These two regions are outside the focused travel leg. Establish their
    # admitted pairs through the same DEBUG state interface used by product E2E.
    for region in ("Hoenn", "Sevii"):
        _, flag_id, var_id, value = next(
            state for state in REGIONAL_STORY_STATE if state[0] == region
        )
        integrity_game.set_flag(flag_id)
        integrity_game.set_var(var_id, value)

    _load_map(integrity_game, vermilion, VERMILION_PORT_ENTRY, 0x53544F01)
    _, kanto_flag, kanto_var, kanto_value = REGIONAL_STORY_STATE[1]
    integrity_game.set_flag(kanto_flag)
    integrity_game.set_var(kanto_var, kanto_value)
    assert integrity_game.read_flag(kanto_flag)
    assert integrity_game.read_var(kanto_var) == kanto_value

    _take_ferry(integrity_game, olivine, OLIVINE_PORT_ENTRY)
    _, johto_flag, johto_var, johto_value = REGIONAL_STORY_STATE[3]
    integrity_game.set_flag(johto_flag)
    integrity_game.set_var(johto_var, johto_value)
    _assert_runtime_story_state(integrity_game)

    saved = save_from_start_menu(integrity_game)
    _assert_serialized_story_state(saved)
    cold_restart_and_continue(integrity_game)
    assert integrity_game.map_id() == olivine.map_id
    _assert_runtime_story_state(integrity_game)
    _assert_serialized_story_state(integrity_game.battery_snapshot())

    _take_ferry(integrity_game, vermilion, VERMILION_PORT_ENTRY)
    _assert_runtime_story_state(integrity_game)
