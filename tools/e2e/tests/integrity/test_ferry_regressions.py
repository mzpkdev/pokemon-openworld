from __future__ import annotations

from dataclasses import dataclass

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
SHIP_LOCAL_ID = 2
CAMERA_LOCAL_ID = 127
PLAYER_LOCAL_ID = 255
MAP_OFFSET = 7
OBJECT_EVENT_COUNT = 16
OBJECT_EVENT_SIZE = 0x24
TASK_COUNT = 16
TASK_SIZE = 0x28
SPRITE_SIZE = 0x44
POKEMON_STORAGE_SIZE = 0x8560
CUTSCENE_TASKS = (
    "ScriptMovement_MoveObjects",
    "Task_WarpAndLoadMap",
    "Task_DoDoorWarp",
)
VERMILION_FERRY_SAILOR_LOCAL_ID = 6
VERMILION_FAST_SHIP_ATTENDANT_LOCAL_ID = 9
FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED = 0x8E3
FLAG_HIDE_SS_ANNE = 0x087
CAMPAIGN_FLAGS_START = 0x20
VAR_FRIENDSHIP_STEP_COUNTER = 0x402A
VAR_MAP_SCENE_VERMILION_CITY = 0x407E
PROMPTLESS_RESULT_SENTINEL = 0xA55A
YES_NO_PENDING = 0xFF
LEGACY_SS_ANNE_TEXT = bytes.fromhex(
    "d1 d9 e0 d7 e3 e1 d9 00 e8 e3 00 e8 dc d9 00 cd ad cd ad 00 bb c8 c8 bf ab ff"
)
VERMILION_FERRY_SAILOR_ENTRY = (24, 32)
VERMILION_FAST_SHIP_ATTENDANT_ENTRY = (25, 23)
VERMILION_PORT_ENTRY = (8, 9)
OLIVINE_PORT_ENTRY = (8, 16)
SS_AQUA_ENTRY = (29, 3)
SS_AQUA_EXIT_APPROACH = (29, 2)


@dataclass(frozen=True)
class Berth:
    name: str
    entry: tuple[int, int]
    sailor: tuple[int, int]
    ship: tuple[int, int]
    departure_dx: int
    destination: str
    arrival: tuple[int, int]


VERMILION_BERTH = Berth(
    name="VermilionCity_PortInside",
    entry=VERMILION_PORT_ENTRY,
    sailor=(8, 10),
    ship=(8, 13),
    departure_dx=-1,
    destination="OlivineCity_PortInside",
    arrival=OLIVINE_PORT_ENTRY,
)
OLIVINE_BERTH = Berth(
    name="OlivineCity_PortInside",
    entry=OLIVINE_PORT_ENTRY,
    sailor=(8, 17),
    ship=(8, 20),
    departure_dx=1,
    destination="VermilionCity_PortInside",
    arrival=VERMILION_PORT_ENTRY,
)
FOUR_LEG_JOURNEY = (
    VERMILION_BERTH,
    OLIVINE_BERTH,
    VERMILION_BERTH,
    OLIVINE_BERTH,
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


def _read_region(game, address: int, size: int) -> bytes:
    return b"".join(
        game.read(address + offset, min(512, size - offset))
        for offset in range(0, size, 512)
    )


def _bag_state(game) -> bytes:
    encryption_key = game.read_u32(game.save_block2() + 0xAC) & 0xFFFF
    bag = _read_region(game, game.save_block1() + 0x560, 0x848 - 0x560)
    return b"".join(
        bag[offset : offset + 2]
        + (
            int.from_bytes(bag[offset + 2 : offset + 4], "little") ^ encryption_key
        ).to_bytes(2, "little")
        for offset in range(0, len(bag), 4)
    )


def _player_state(game) -> tuple[bytes, ...]:
    flags_offset = CAMPAIGN_FLAGS_START // 8
    flags_size = (FLAGS_COUNT + 7) // 8 - flags_offset
    vars_size = (VARS_END - VARS_START + 1) * 2
    variables = game.read(game.save_block1() + SAVE_BLOCK1_VARS_OFFSET, vars_size)
    friendship_offset = (VAR_FRIENDSHIP_STEP_COUNTER - VARS_START) * 2
    return (
        # Identity, live party, PC storage, bag/PC items, Pok\u00e9dex, and money.
        game.read(game.save_block2(), 14),
        bytes((game.read_u8(game.address("gPartiesCount")),)),
        _read_region(game, game.address("gParties"), 600),
        _read_region(game, game.pointer("gPokemonStoragePtr"), POKEMON_STORAGE_SIZE),
        game.read(game.save_block1() + 0x498, 0x560 - 0x498),
        _bag_state(game),
        game.read(game.save_block2() + 0x18, 0x90 - 0x18),
        (
            game.read_u32(game.save_block1() + 0x490)
            ^ game.read_u32(game.save_block2() + 0xAC)
        ).to_bytes(4, "little"),
        (
            game.read_u16(game.save_block1() + 0x494)
            ^ (game.read_u32(game.save_block2() + 0xAC) & 0xFFFF)
        ).to_bytes(2, "little")
        + game.read(game.save_block1() + 0x496, 2),
        # Respawn/checkpoint and all saved campaign facts. The friendship step
        # counter is the sole normal walking side effect intentionally omitted.
        game.read(game.save_block1() + 0x1C, 8),
        game.read(
            game.save_block1() + SAVE_BLOCK1_FLAGS_OFFSET + flags_offset,
            flags_size,
        ),
        variables[:friendship_offset] + variables[friendship_offset + 2 :],
    )


def _assert_player_state(game, expected: tuple[bytes, ...]) -> None:
    actual = _player_state(game)
    differences = {
        index: [
            offset
            for offset, (before, after) in enumerate(zip(expected_value, actual[index]))
            if before != after
        ]
        for index, expected_value in enumerate(expected)
        if actual[index] != expected_value
    }
    assert not differences, f"player-state byte differences: {differences}"


def _object(game, local_id: int, map_id: tuple[int, int]):
    objects = game.address("gObjectEvents")
    matches = []
    for object_id in range(OBJECT_EVENT_COUNT):
        obj = objects + object_id * OBJECT_EVENT_SIZE
        if not game.read_u8(obj) & 1:
            continue
        if (
            game.read_u8(obj + 8) == local_id
            and game.read_u8(obj + 9) == map_id[1]
            and game.read_u8(obj + 10) == map_id[0]
        ):
            matches.append(
                (
                    object_id,
                    game.read_u16(obj + 0x10) - MAP_OFFSET,
                    game.read_u16(obj + 0x12) - MAP_OFFSET,
                    game.read_u8(obj + 0x23),
                )
            )
    assert len(matches) <= 1, f"duplicate local id {local_id}: {matches}"
    return matches[0] if matches else None


def _active_task_functions(game) -> tuple[int, ...]:
    tasks = game.address("gTasks")
    return tuple(
        game.read_u32(tasks + task_id * TASK_SIZE)
        for task_id in range(TASK_COUNT)
        if game.read_u8(tasks + task_id * TASK_SIZE + 4)
    )


def _field_readiness(game, map_id: tuple[int, int]) -> tuple[object, ...]:
    return (
        game.position(),
        _object(game, PLAYER_LOCAL_ID, map_id),
        _object(game, SAILOR_LOCAL_ID, map_id),
        _object(game, SHIP_LOCAL_ID, map_id),
        _object(game, CAMERA_LOCAL_ID, map_id),
        game.read(game.save_block1() + 0x14, 8),
        game.read(game.save_block1() + 0x1C, 8),
        game.read(game.address("gFieldCamera"), 24),
        _active_task_functions(game),
        game.callback_is("CB2_Overworld"),
        game.controls_locked(),
        game.script_status(),
        game.movement_idle(),
        _player_state(game),
    )


def _wait_for_yes_no(game, description: str) -> None:
    game.advance_until(
        lambda: game.read_u16(game.address("gSpecialVar_Result")) == YES_NO_PENDING,
        description=description,
        max_pulses=300,
        button="A",
    )
    game.step(6)


def _decline_boarding(game, berth: Berth, map_id: tuple[int, int]) -> None:
    before = _field_readiness(game, map_id)
    _interact_with(game, SAILOR_LOCAL_ID, f"{berth.name} NO interaction")
    _wait_for_yes_no(game, f"{berth.name} NO prompt")
    game.press("B")
    _wait_for_field_ready(game, f"{berth.name} NO returns field readiness")
    assert _field_readiness(game, map_id) == before


def _assert_camera_tracks_local_object(game, camera) -> None:
    camera_sprite_id = game.read_u32(game.address("gFieldCamera") + 4)
    followed_sprite_id = game.read_u16(
        game.address("gSprites") + camera_sprite_id * SPRITE_SIZE + 0x2E
    )
    assert followed_sprite_id == camera[3]


def _assert_arrival_cleanup(game, destination, arrival: tuple[int, int]) -> None:
    player = _object(game, PLAYER_LOCAL_ID, destination.map_id)
    assert player is not None
    assert player[1:3] == arrival
    assert _object(game, CAMERA_LOCAL_ID, destination.map_id) is None
    _assert_camera_tracks_local_object(game, player)
    assert game.callback_is("CB2_Overworld")
    assert not game.controls_locked()
    assert game.script_status() == SCRIPT_IDLE
    assert game.movement_idle()
    for task in CUTSCENE_TASKS:
        assert not game.task_active(task), f"arrival leaked {task}"


def _board_with_choreography(game, berth: Berth, source, ship) -> None:
    _interact_with(game, SAILOR_LOCAL_ID, f"{berth.name} YES interaction")
    _wait_for_yes_no(game, f"{berth.name} YES prompt")
    game.press("A")

    observations = []
    camera_tracked_when_player_disappeared = False
    for _ in range(1_800):
        if game.map_id() == ship.map_id:
            break
        assert game.map_id() == source.map_id
        observation = (
            _object(game, SAILOR_LOCAL_ID, source.map_id),
            _object(game, SHIP_LOCAL_ID, source.map_id),
            _object(game, PLAYER_LOCAL_ID, source.map_id),
            _object(game, CAMERA_LOCAL_ID, source.map_id),
        )
        observations.append(observation)
        if observation[2] is None and observation[3] is not None:
            _assert_camera_tracks_local_object(game, observation[3])
            camera_tracked_when_player_disappeared = True
        game.step()
    else:
        raise AssertionError(f"{berth.name} did not board S.S. Aqua")

    first_player_step = next(
        observation
        for observation in observations
        if observation[2] is not None and observation[2][2] > berth.entry[1]
    )
    assert first_player_step[0][1:3] == (
        berth.sailor[0],
        berth.sailor[1] + 2,
    )

    first_player_absent = next(
        observation for observation in observations if observation[2] is None
    )
    assert first_player_absent[3] is not None
    assert first_player_absent[3][1:3] == (
        berth.entry[0],
        berth.entry[1] + 2,
    )
    assert camera_tracked_when_player_disappeared

    departure = [
        (
            observation[0][1],
            observation[0][2],
            observation[1][1],
            observation[1][2],
        )
        for observation in observations
        if observation[2] is None
        and observation[0] is not None
        and observation[1] is not None
    ]
    unique_departure = list(dict.fromkeys(departure))
    expected_x = [berth.ship[0] + berth.departure_dx * step for step in range(6)]
    assert unique_departure == [
        (x, berth.sailor[1] + 2, x, berth.ship[1]) for x in expected_x
    ]
    assert observations[-1][0][1] == expected_x[-1]
    assert observations[-1][0][2] == berth.sailor[1] + 2
    assert observations[-1][1][1] == expected_x[-1]
    assert observations[-1][1][2] == berth.ship[1]

    _wait_for_field_ready(game, f"{berth.name} field-ready S.S. Aqua boarding")
    assert game.map_id() == ship.map_id
    assert game.position() == SS_AQUA_ENTRY


def test_ferry_four_leg_journey_preserves_state_and_replays_both_departures(
    integrity_game,
):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    ship = maps["SSAqua_1F"]

    _settle_overworld(integrity_game)
    first = maps[VERMILION_BERTH.name]
    _load_source(integrity_game, first, VERMILION_BERTH.entry, 0xF3300001)
    player_state = _player_state(integrity_game)
    friendship_steps = integrity_game.read_var(VAR_FRIENDSHIP_STEP_COUNTER)
    assert integrity_game.read_flag(FLAG_HIDE_SS_ANNE) is False
    ss_anne_scene = integrity_game.read_var(VAR_MAP_SCENE_VERMILION_CITY)

    for leg_index, berth in enumerate(FOUR_LEG_JOURNEY):
        source = maps[berth.name]
        destination = maps[berth.destination]
        assert integrity_game.map_id() == source.map_id
        assert integrity_game.position() == berth.entry
        assert (
            _object(integrity_game, SAILOR_LOCAL_ID, source.map_id)[1:3] == berth.sailor
        )
        assert _object(integrity_game, SHIP_LOCAL_ID, source.map_id)[1:3] == berth.ship

        if leg_index < 2:
            _decline_boarding(integrity_game, berth, source.map_id)

        _board_with_choreography(integrity_game, berth, source, ship)
        _assert_player_state(integrity_game, player_state)
        expected_warp = integrity_game.read(integrity_game.save_block1() + 0x14, 8)
        assert expected_warp[0:2] == bytes(destination.map_id)
        assert expected_warp[2] == 0xFF
        assert int.from_bytes(expected_warp[4:6], "little") == berth.arrival[0]
        assert int.from_bytes(expected_warp[6:8], "little") == berth.arrival[1]

        if leg_index == 0:
            save_from_start_menu(integrity_game)
            cold_restart_and_continue(integrity_game)
            assert integrity_game.map_id() == ship.map_id
            assert integrity_game.position() == SS_AQUA_ENTRY
            _assert_player_state(integrity_game, player_state)

        integrity_game.move_to(x=SS_AQUA_EXIT_APPROACH[0], y=SS_AQUA_EXIT_APPROACH[1])
        integrity_game.advance_until(
            lambda: integrity_game.map_id() == destination.map_id,
            description=f"S.S. Aqua exit into {berth.destination}",
            max_pulses=600,
            button="Up",
        )
        _wait_for_field_ready(
            integrity_game, f"{berth.destination} field-ready ferry arrival"
        )
        assert integrity_game.position() == berth.arrival
        _assert_arrival_cleanup(integrity_game, destination, berth.arrival)
        assert _object(integrity_game, SAILOR_LOCAL_ID, destination.map_id)[1:3] == (
            8,
            berth.arrival[1] + 1,
        )
        assert _object(integrity_game, SHIP_LOCAL_ID, destination.map_id)[1:3] == (
            8,
            berth.arrival[1] + 4,
        )
        _assert_player_state(integrity_game, player_state)
        assert integrity_game.read_flag(FLAG_HIDE_SS_ANNE) is False
        assert integrity_game.read_var(VAR_MAP_SCENE_VERMILION_CITY) == ss_anne_scene

    assert (
        integrity_game.read_var(VAR_FRIENDSHIP_STEP_COUNTER)
        == (friendship_steps + len(FOUR_LEG_JOURNEY)) % 128
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
