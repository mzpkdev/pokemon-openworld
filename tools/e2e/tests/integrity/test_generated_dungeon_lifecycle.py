import struct

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
OBJECT_EVENT_TEMPLATES_OFFSET = 0xC70
OBJECT_EVENT_TEMPLATE_SIZE = 0x18
OBJECT_EVENT_TEMPLATE_COUNT = 64
MAP_OFFSET = 7
GENERATED_MAP_WIDTH = 20
GENERATED_MAP_HEIGHT = 20
GENERATED_FLOOR_METATILE = 0x201
MAX_SKYEMU_READ_BYTES = 128
NORMAL_FIELD_MAP = (0, 9)


def _continue_to_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Continue did not reach an unlocked overworld")


def _record(game) -> bytes:
    return game.read(
        game.save_block1() + GENERATED_DUNGEON_RECORD_OFFSET,
        GENERATED_DUNGEON_RECORD_SIZE,
    )


def _read_bytes(game, address: int, size: int) -> bytes:
    return b"".join(
        game.read(address + offset, min(MAX_SKYEMU_READ_BYTES, size - offset))
        for offset in range(0, size, MAX_SKYEMU_READ_BYTES)
    )


def _generated_runtime_snapshot(game) -> tuple[bytes, bytes]:
    backup_layout = game.read(game.address("gBackupMapLayout"), 12)
    width, height, map_address = struct.unpack("<iiI", backup_layout)
    assert (width, height) == (
        GENERATED_MAP_WIDTH + MAP_OFFSET * 2 + 1,
        GENERATED_MAP_HEIGHT + MAP_OFFSET * 2,
    )

    start = map_address + 2 * (width * MAP_OFFSET + MAP_OFFSET)
    cell_count = GENERATED_MAP_WIDTH * GENERATED_MAP_HEIGHT
    row_size = GENERATED_MAP_WIDTH * 2
    cells = b"".join(
        _read_bytes(game, start + row * width * 2, row_size)
        for row in range(GENERATED_MAP_HEIGHT)
    )
    assert (
        struct.unpack(f"<{cell_count}H", cells)
        == (GENERATED_FLOOR_METATILE,) * cell_count
    )

    templates = _read_bytes(
        game,
        game.save_block1() + OBJECT_EVENT_TEMPLATES_OFFSET,
        OBJECT_EVENT_TEMPLATE_SIZE * OBJECT_EVENT_TEMPLATE_COUNT,
    )
    assert templates == bytes(len(templates))
    return cells, templates


def test_generated_dungeon_run_survives_cold_continue_then_clears_on_departure(
    game_from_hoenn_save,
):
    game = game_from_hoenn_save
    _continue_to_overworld(game)

    fixture = activate_fixture(game, FixtureRequest(0x90, 0x90C0FFEE))
    assert game.map_id() == (fixture.map_group, fixture.map_num)
    game.wait_for_controls_unlocked(max_frames=1_200)
    snapshot = _record(game)
    assert snapshot != bytes(GENERATED_DUNGEON_RECORD_SIZE)
    runtime_snapshot = _generated_runtime_snapshot(game)

    saved = save_from_start_menu(
        game, max_pulses=1_200, release_frames=2, persist_to_disk=True
    )
    assert (
        saved.active_slot.save_block1[
            GENERATED_DUNGEON_RECORD_OFFSET : GENERATED_DUNGEON_RECORD_OFFSET
            + GENERATED_DUNGEON_RECORD_SIZE
        ]
        == snapshot
    )

    cold_restart_and_continue(game)
    assert game.map_id() == (fixture.map_group, fixture.map_num)
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert _record(game) == snapshot
    assert _generated_runtime_snapshot(game) == runtime_snapshot

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
