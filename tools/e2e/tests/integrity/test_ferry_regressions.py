from __future__ import annotations

import pytest

from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    FLAGS_COUNT,
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
    SAVE_BLOCK1_FLAGS_OFFSET,
    SAVE_BLOCK1_VARS_OFFSET,
    VARS_END,
    VARS_START,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)


SCRIPT_IDLE = 2
SAILOR_LOCAL_ID = 1
VERMILION_FERRY_SAILOR_LOCAL_ID = 6
VERMILION_FAST_SHIP_ATTENDANT_LOCAL_ID = 9
FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED = 0x8E3
CAMPAIGN_FLAGS_START = 0x20
VAR_FRIENDSHIP_STEP_COUNTER = 0x402A
PROMPTLESS_RESULT_SENTINEL = 0xA55A
LEGACY_SS_ANNE_TEXT = bytes.fromhex(
    "d1 d9 e0 d7 e3 e1 d9 00 e8 e3 00 e8 dc d9 00 cd ad cd ad 00 bb c8 c8 bf ab ff"
)
VERMILION_FERRY_SAILOR_ENTRY = (24, 32)
VERMILION_FAST_SHIP_ATTENDANT_ENTRY = (25, 23)
VERMILION_PORT_ENTRY = (8, 9)
OLIVINE_PORT_ENTRY = (8, 16)
SS_AQUA_ENTRY = (29, 3)
SS_AQUA_EXIT_APPROACH = (29, 2)

FERRY_LEGS = (
    (
        "VermilionCity_PortInside",
        VERMILION_PORT_ENTRY,
        "OlivineCity_PortInside",
        OLIVINE_PORT_ENTRY,
        0xF3300001,
        True,
    ),
    (
        "OlivineCity_PortInside",
        OLIVINE_PORT_ENTRY,
        "VermilionCity_PortInside",
        VERMILION_PORT_ENTRY,
        0xF3300002,
        False,
    ),
)


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _load_source(game, entry, coordinates: tuple[int, int], request_id: int) -> None:
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


def _wait_for_field_ready(game, description: str) -> None:
    game.wait_until(
        lambda: (
            game.callback_is("CB2_Overworld")
            and not game.controls_locked()
            and game.script_status() == SCRIPT_IDLE
            and game.movement_idle()
        ),
        description=description,
        max_frames=1_800,
        step_frames=2,
    )


def _interact_with(
    game, local_id: int, description: str, direction: str = "Down"
) -> None:
    game.face(direction)
    game.press("A")
    game.wait_until(
        lambda: (
            game.controls_locked()
            and game.read_u16(game.address("gSpecialVar_LastTalked")) == local_id
        ),
        description=description,
        max_frames=120,
    )


def _finish_dialogue(game, description: str) -> None:
    game.advance_until(
        lambda: not game.controls_locked() and game.script_status() == SCRIPT_IDLE,
        description=description,
        max_pulses=600,
        button="A",
    )
    _wait_for_field_ready(game, description)


def _assert_active_field_message(game, expected: bytes, description: str) -> None:
    game.wait_until(
        lambda: game.task_active("Task_DrawFieldMessage"),
        description=description,
        max_frames=1_200,
    )
    assert game.read(game.address("gStringVar4"), len(expected)) == expected


def _focused_player_state(game) -> tuple[bytes, bytes, bytes]:
    flags_offset = CAMPAIGN_FLAGS_START // 8
    flags_size = (FLAGS_COUNT + 7) // 8 - flags_offset
    vars_size = (VARS_END - VARS_START + 1) * 2
    variables = game.read(game.save_block1() + SAVE_BLOCK1_VARS_OFFSET, vars_size)
    friendship_offset = (VAR_FRIENDSHIP_STEP_COUNTER - VARS_START) * 2
    return (
        game.read(game.save_block2(), 14),
        game.read(
            game.save_block1() + SAVE_BLOCK1_FLAGS_OFFSET + flags_offset,
            flags_size,
        ),
        variables[:friendship_offset] + variables[friendship_offset + 2 :],
    )


@pytest.mark.parametrize(
    (
        "source_name",
        "source_coordinates",
        "destination_name",
        "arrival_coordinates",
        "request_id",
        "save_aboard",
    ),
    FERRY_LEGS,
)
def test_ferry_leg_reaches_destination_and_returns_control(
    integrity_game,
    source_name,
    source_coordinates,
    destination_name,
    arrival_coordinates,
    request_id,
    save_aboard,
):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    source = maps[source_name]
    ship = maps["SSAqua_1F"]
    destination = maps[destination_name]

    _settle_overworld(integrity_game)
    _load_source(integrity_game, source, source_coordinates, request_id)

    _interact_with(
        integrity_game,
        SAILOR_LOCAL_ID,
        f"reachable sailor interaction in {source_name}",
    )
    integrity_game.advance_until(
        lambda: integrity_game.map_id() == ship.map_id,
        description=f"{source_name} boarding into S.S. Aqua",
        max_pulses=600,
        button="A",
    )
    _wait_for_field_ready(
        integrity_game, f"{source_name} fully field-ready S.S. Aqua boarding"
    )
    assert integrity_game.position() == SS_AQUA_ENTRY

    player_state = _focused_player_state(integrity_game)
    friendship_steps = integrity_game.read_var(VAR_FRIENDSHIP_STEP_COUNTER)
    if save_aboard:
        save_from_start_menu(integrity_game)
        cold_restart_and_continue(integrity_game)
        assert integrity_game.map_id() == ship.map_id
        assert integrity_game.position() == SS_AQUA_ENTRY
        assert _focused_player_state(integrity_game) == player_state

    integrity_game.move_to(x=SS_AQUA_EXIT_APPROACH[0], y=SS_AQUA_EXIT_APPROACH[1])
    assert integrity_game.position() == SS_AQUA_EXIT_APPROACH
    integrity_game.advance_until(
        lambda: integrity_game.map_id() == destination.map_id,
        description=f"S.S. Aqua exit into {destination_name}",
        max_pulses=600,
        button="Up",
    )
    _wait_for_field_ready(
        integrity_game, f"{destination_name} fully field-ready ferry arrival"
    )

    assert integrity_game.map_id() == destination.map_id
    assert integrity_game.position() == arrival_coordinates
    assert integrity_game.callback_is("CB2_Overworld")
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert integrity_game.movement_idle()
    assert _focused_player_state(integrity_game) == player_state
    assert (
        integrity_game.read_var(VAR_FRIENDSHIP_STEP_COUNTER)
        == (friendship_steps + 1) % 128
    )


def test_vermilion_pier_lock_preserves_legacy_sailor_and_terminal_geometry(
    integrity_game,
):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    vermilion = maps["VermilionCity_Frlg"]
    terminal = maps["VermilionCity_PortInside"]

    _settle_overworld(integrity_game)
    _load_source(
        integrity_game,
        vermilion,
        VERMILION_FERRY_SAILOR_ENTRY,
        0xF3300003,
    )
    assert integrity_game.read_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    integrity_game.write_u16(
        integrity_game.address("gSpecialVar_Result"), PROMPTLESS_RESULT_SENTINEL
    )

    _interact_with(
        integrity_game,
        VERMILION_FERRY_SAILOR_LOCAL_ID,
        "original Vermilion pier sailor interaction",
    )
    _finish_dialogue(integrity_game, "open fast-ship terminal dialogue completion")
    assert integrity_game.map_id() == vermilion.map_id
    assert integrity_game.position() == VERMILION_FERRY_SAILOR_ENTRY
    assert (
        integrity_game.read_u16(integrity_game.address("gSpecialVar_Result"))
        == PROMPTLESS_RESULT_SENTINEL
    )

    _load_source(
        integrity_game,
        vermilion,
        VERMILION_FAST_SHIP_ATTENDANT_ENTRY,
        0xF3300005,
    )
    _interact_with(
        integrity_game,
        VERMILION_FAST_SHIP_ATTENDANT_LOCAL_ID,
        "operational fast-ship attendant interaction",
    )
    integrity_game.advance_until(
        lambda: integrity_game.map_id() == terminal.map_id,
        description="promptless public Vermilion ferry terminal entry",
        max_pulses=600,
        button="A",
    )
    _wait_for_field_ready(integrity_game, "usable Vermilion ferry terminal entry")

    assert integrity_game.position() == VERMILION_PORT_ENTRY
    integrity_game.move_to(x=8, y=3)
    assert integrity_game.position() == (8, 3)

    integrity_game.advance_until(
        lambda: integrity_game.map_id() == vermilion.map_id,
        description="public Vermilion ferry terminal exit",
        max_pulses=600,
        button="Up",
    )
    _wait_for_field_ready(integrity_game, "usable Vermilion city return")

    assert integrity_game.map_id() == vermilion.map_id
    assert integrity_game.position() == (24, 34)
    assert integrity_game.callback_is("CB2_Overworld")
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert integrity_game.movement_idle()

    integrity_game.set_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED, False)
    _interact_with(
        integrity_game,
        VERMILION_FERRY_SAILOR_LOCAL_ID,
        "legacy S.S. Anne sailor interaction",
        direction="Up",
    )
    _assert_active_field_message(
        integrity_game,
        LEGACY_SS_ANNE_TEXT,
        "rendered legacy S.S. Anne welcome dialogue",
    )
    _finish_dialogue(integrity_game, "legacy S.S. Anne dialogue completion")
    assert integrity_game.map_id() == vermilion.map_id
    assert integrity_game.position() == (24, 34)

    _load_source(
        integrity_game,
        vermilion,
        VERMILION_FAST_SHIP_ATTENDANT_ENTRY,
        0xF3300004,
    )
    assert not integrity_game.read_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    _interact_with(
        integrity_game,
        VERMILION_FAST_SHIP_ATTENDANT_LOCAL_ID,
        "locked fast-ship attendant interaction",
    )
    _finish_dialogue(integrity_game, "unavailable fast-ship dialogue completion")
    assert integrity_game.map_id() == vermilion.map_id
    assert integrity_game.position() == VERMILION_FAST_SHIP_ATTENDANT_ENTRY

    integrity_game.set_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    assert integrity_game.read_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
