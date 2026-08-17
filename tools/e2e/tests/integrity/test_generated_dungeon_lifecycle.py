from tools.e2e.generated_dungeon_fixture import FixtureRequest, activate_fixture
from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)


GENERATED_DUNGEON_RECORD_OFFSET = 0x3D38
GENERATED_DUNGEON_RECORD_SIZE = 64
NORMAL_FIELD_MAP = (0, 9)


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _record(game) -> bytes:
    return game.read(game.save_block1() + GENERATED_DUNGEON_RECORD_OFFSET, GENERATED_DUNGEON_RECORD_SIZE)


def test_generated_dungeon_run_survives_cold_continue_then_clears_on_departure(integrity_game):
    game = integrity_game
    _settle_overworld(game)

    fixture = activate_fixture(game, FixtureRequest(0x90, 0x90C0FFEE))
    assert game.map_id() == (fixture.map_group, fixture.map_num)
    game.wait_for_controls_unlocked(max_frames=1_200)
    snapshot = _record(game)
    assert snapshot != bytes(GENERATED_DUNGEON_RECORD_SIZE)

    saved = save_from_start_menu(game)
    assert saved.active_slot.save_block1[
        GENERATED_DUNGEON_RECORD_OFFSET : GENERATED_DUNGEON_RECORD_OFFSET + GENERATED_DUNGEON_RECORD_SIZE
    ] == snapshot

    cold_restart_and_continue(game)
    assert game.map_id() == (fixture.map_group, fixture.map_num)
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert _record(game) == snapshot

    departure = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=0x91,
            map_group=NORMAL_FIELD_MAP[0],
            map_num=NORMAL_FIELD_MAP[1],
            x=9,
            y=9,
        ),
        max_frames=1_800,
    )
    assert departure.status is IntegrityLoadStatus.SUCCESS
    assert departure.phase is IntegrityLoadPhase.FIELD_READY
    assert departure.error is IntegrityLoadError.NONE
    assert game.map_id() == NORMAL_FIELD_MAP
    assert _record(game) == bytes(GENERATED_DUNGEON_RECORD_SIZE)
