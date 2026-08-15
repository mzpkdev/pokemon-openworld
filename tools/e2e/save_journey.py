from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct
from typing import Any

from tools.e2e.save_file import decode_box_pokemon


MENU_ACTION_SAVE = 5
SAVE_SCENARIO_SIZE = 36
SAVE_SCENARIO_STATUS_OFFSET = 21
FIELD_MOVE_PROBE_SIZE = 8
FIELD_MOVE_PROBE_STATUS_OFFSET = 6


class SaveScenarioStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    RUNNING = 2
    SUCCESS = 3
    ERROR = 4


class FieldMoveProbeStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    SUCCESS = 2
    ERROR = 3


def probe_field_move(game, field_move: int, request_id: int) -> bool:
    """Query the same field-move policy entry used by scripts and the party menu."""
    request = game.address("gFieldMoveProbeRequest")
    result = game.address("gFieldMoveProbeResult")
    game.pause()
    game.write(
        result,
        struct.pack(
            "<IHBB",
            request_id ^ 0xFFFFFFFF,
            field_move,
            0,
            FieldMoveProbeStatus.IDLE,
        ),
    )
    game.write(
        request,
        struct.pack("<IHBB", request_id, field_move, FieldMoveProbeStatus.IDLE, 0),
    )
    game.write_u8(
        request + FIELD_MOVE_PROBE_STATUS_OFFSET, FieldMoveProbeStatus.PENDING
    )
    game.resume()
    # Never inspect the terminal result from an earlier identical request.
    game.step()

    for _ in range(120):
        payload = game.read(result, FIELD_MOVE_PROBE_SIZE)
        result_id, result_move, unlocked, status = struct.unpack("<IHBB", payload)
        if result_id == request_id and status in (
            FieldMoveProbeStatus.SUCCESS,
            FieldMoveProbeStatus.ERROR,
        ):
            if status == FieldMoveProbeStatus.ERROR:
                raise AssertionError(
                    f"field move probe {request_id:#x} rejected move {field_move}"
                )
            assert result_move == field_move
            assert unlocked in (0, 1)
            return bool(unlocked)
        game.step()
    raise AssertionError(f"field move probe {request_id:#x} timed out")


SAVE_SCENARIO_ERRORS = {
    0: "none",
    1: "field not ready",
    2: "invalid request",
    3: "party setup",
    4: "box setup",
    5: "daycare setup",
    6: "facility setup",
    7: "in-game trade",
    8: "reward grant",
    9: "checkpoint setup",
    10: "trainer defeat",
}


@dataclass(frozen=True)
class SaveScenarioRequest:
    request_id: int
    party_species: int
    box_species: int
    daycare_species_1: int
    daycare_species_2: int
    trade_species: int
    reward_item: int
    checkpoint_id: int
    level: int
    facility_id: int
    facility_level_mode: int
    trainer_id: int
    rng_seed: int = 0x135B32CA
    player_trainer_id: int = 0x12345678
    abi_version: int = 2
    reserved: int = 0

    def pack_idle(self) -> bytes:
        payload = struct.pack(
            "<I7H4BHIIHH",
            self.request_id,
            self.party_species,
            self.box_species,
            self.daycare_species_1,
            self.daycare_species_2,
            self.trade_species,
            self.reward_item,
            self.checkpoint_id,
            self.level,
            self.facility_id,
            self.facility_level_mode,
            SaveScenarioStatus.IDLE,
            self.trainer_id,
            self.rng_seed,
            self.player_trainer_id,
            self.abi_version,
            self.reserved,
        )
        assert len(payload) == SAVE_SCENARIO_SIZE
        return payload


@dataclass(frozen=True)
class SaveScenarioResult:
    request_id: int
    error: int
    party_index: int
    box_index: int
    daycare_egg_species: int
    traded_party_index: int
    reward_item: int
    checkpoint_id: int
    facility_id: int
    facility_challenge_status: int
    facility_paused: int
    status: SaveScenarioStatus
    trainer_flag: int
    rng_seed: int
    player_trainer_id: int
    abi_version: int
    player_name_hash: int

    @classmethod
    def unpack(cls, payload: bytes) -> "SaveScenarioResult":
        if len(payload) != SAVE_SCENARIO_SIZE:
            raise ValueError(f"save scenario result is {len(payload)} bytes")
        fields = struct.unpack("<I7H4BHIIHH", payload)
        return cls(*fields[:11], SaveScenarioStatus(fields[11]), *fields[12:])


def run_save_scenario(game, request: SaveScenarioRequest) -> SaveScenarioResult:
    """Ask the shipped DEBUG hook to create state through real game services."""
    address = game.address("gSaveScenarioRequest")
    game.pause()
    game.write(address, request.pack_idle())
    # Status is the commit byte: no frame may observe a partially written request.
    game.write_u8(address + SAVE_SCENARIO_STATUS_OFFSET, SaveScenarioStatus.PENDING)
    game.resume()

    for _ in range(1_200):
        result = SaveScenarioResult.unpack(
            game.read(game.address("gSaveScenarioResult"), SAVE_SCENARIO_SIZE)
        )
        if result.request_id == request.request_id and result.status in (
            SaveScenarioStatus.SUCCESS,
            SaveScenarioStatus.ERROR,
        ):
            if result.status == SaveScenarioStatus.ERROR:
                detail = SAVE_SCENARIO_ERRORS.get(result.error, "unknown")
                raise AssertionError(
                    f"save scenario {request.request_id:#x} failed: "
                    f"error={result.error} ({detail})"
                )
            assert result.error == 0
            assert result.reward_item == request.reward_item
            assert result.checkpoint_id == request.checkpoint_id
            assert result.facility_id == request.facility_id
            assert result.trainer_flag == request.trainer_id
            assert result.rng_seed == request.rng_seed
            assert result.player_trainer_id == request.player_trainer_id
            assert result.abi_version == request.abi_version
            return result
        game.step()
    raise AssertionError(f"save scenario {request.request_id:#x} timed out")


def _representative_semantics(
    block1: bytes,
    block2: bytes,
    storage: bytes,
    result: SaveScenarioResult,
) -> dict[str, Any]:
    def party_mon(index: int):
        offset = 0x238 + index * 100
        return decode_box_pokemon(block1[offset : offset + 80])

    box_offset = 4 + result.box_index * 80
    encryption_key = struct.unpack_from("<I", block2, 0xAC)[0]
    reward_quantity = 0
    for offset in range(0x560, 0x560 + 30 * 4, 4):
        item, encrypted_quantity = struct.unpack_from("<HH", block1, offset)
        if item == result.reward_item:
            reward_quantity += encrypted_quantity ^ (encryption_key & 0xFFFF)
    frontier = block2[0x64C : 0x64C + 2272]
    return {
        "party": {
            "createdIndex": result.party_index,
            "createdPokemon": party_mon(result.party_index),
            "tradedIndex": result.traded_party_index,
            "tradedPokemon": party_mon(result.traded_party_index),
        },
        "box": {
            "flatIndex": result.box_index,
            "pokemon": decode_box_pokemon(storage[box_offset : box_offset + 80]),
        },
        "daycare": {
            "parent1": decode_box_pokemon(block1[0x3030 : 0x3030 + 80]),
            "parent2": decode_box_pokemon(block1[0x3030 + 140 : 0x3030 + 220]),
            "pendingEgg": bool(block1[0x1270 + 0x86 // 8] & (1 << (0x86 % 8))),
            "eggSpecies": result.daycare_egg_species,
        },
        "facilitySession": {
            # VAR_FRONTIER_FACILITY (0x40CF) is the persisted facility identity;
            # the request/result value is only transport acknowledgement.
            "facilityId": struct.unpack_from("<H", block1, 0x153A)[0],
            "challengeStatus": frontier[1628],
            "levelMode": frontier[1629] & 0x3,
            "paused": bool(frontier[1629] & 0x4),
            "currentBattle": struct.unpack_from("<H", frontier, 1638)[0],
        },
        "reward": {"item": result.reward_item, "quantity": reward_quantity},
        "checkpoint": {
            "id": result.checkpoint_id,
            "lastHealLocationHex": block1[0x1C:0x24].hex(),
        },
        "trainer": {
            "id": result.trainer_flag,
            "defeated": bool(
                block1[0x1270 + (0x500 + result.trainer_flag) // 8]
                & (1 << ((0x500 + result.trainer_flag) % 8))
            ),
        },
    }


def representative_runtime_semantics(
    game, result: SaveScenarioResult
) -> dict[str, Any]:
    def read_region(address: int, size: int) -> bytes:
        # SkyEmu's debug transport encodes byte addresses in the query string.
        return b"".join(
            game.read(address + offset, min(512, size - offset))
            for offset in range(0, size, 512)
        )

    block1 = bytearray(read_region(game.save_block1(), 0x32F8))
    # The live party has a canonical working copy; SaveGame serializes it into
    # SaveBlock1 immediately before flash is written.
    block1[0x234] = game.read_u8(game.address("gPartiesCount"))
    block1[0x238 : 0x238 + 600] = read_region(game.address("gParties"), 600)
    return _representative_semantics(
        bytes(block1),
        read_region(game.save_block2(), 3884),
        read_region(game.pointer("gPokemonStoragePtr"), 0x83D0),
        result,
    )


def representative_saved_semantics(image, result: SaveScenarioResult) -> dict[str, Any]:
    return _representative_semantics(
        image.active_slot.save_block1,
        image.active_slot.save_block2,
        image.active_slot.pokemon_storage,
        result,
    )


def runtime_semantics(game) -> dict[str, Any]:
    block1 = game.save_block1()
    block2 = game.save_block2()
    storage = game.pointer("gPokemonStoragePtr")
    party_count = game.read_u8(block1 + 0x234)
    party_record = game.read(block1 + 0x238, 100)
    box_record = game.read(storage + 4, 80)
    box_pokemon = decode_box_pokemon(box_record)
    return {
        "identity": {
            "playerNameEncodedHex": game.read(block2, 8).hex(),
            "gender": game.read_u8(block2 + 8),
            "trainerIdHex": game.read(block2 + 10, 4).hex(),
        },
        "checkpoint": {
            "position": list(game.position()),
            "locationHex": game.read(block1 + 4, 8).hex(),
            "continueWarpHex": game.read(block1 + 12, 8).hex(),
        },
        "story": {
            "flags": {
                "FLAG_RESCUED_BIRCH": game.read_flag(0x52),
                "FLAG_ADVENTURE_STARTED": game.read_flag(0x74),
                "FLAG_DEFEATED_RIVAL_ROUTE103": game.read_flag(0x82),
                "FLAG_SYS_POKEMON_GET": game.read_flag(0x860),
                "FLAG_SYS_POKEDEX_GET": game.read_flag(0x861),
                "FLAG_RECEIVED_POKEDEX_FROM_BIRCH": game.read_flag(0x8E4),
            },
            "vars": {
                "VAR_LITTLEROOT_TOWN_STATE": game.read_var(0x4050),
                "VAR_OLDALE_TOWN_STATE": game.read_var(0x4051),
                "VAR_ROUTE101_STATE": game.read_var(0x4060),
                "VAR_BIRCH_LAB_STATE": game.read_var(0x4084),
                "VAR_LITTLEROOT_RIVAL_STATE": game.read_var(0x408D),
                "VAR_LITTLEROOT_INTRO_STATE": game.read_var(0x4092),
            },
        },
        "party": {
            "count": party_count,
            "firstRecordHex": party_record.hex(),
            "firstRecordMeaning": (
                "empty-slot-with-mail-sentinel"
                if party_count == 0
                else "occupied-party-slot"
            ),
            "pokemonProvenance": "absent" if party_count == 0 else "encoded",
            "firstPokemon": decode_box_pokemon(party_record[:80]),
        },
        "box": {
            "currentBox": game.read_u8(storage),
            "firstRecordHex": box_record.hex(),
            "firstRecordMeaning": "empty-box-slot"
            if box_pokemon is None
            else "occupied-box-slot",
            "pokemonProvenance": "absent" if box_pokemon is None else "encoded",
            "firstPokemon": box_pokemon,
        },
        "daycare": {
            "recordHex": game.read(block1 + 0x3030, 288).hex(),
            "meaning": "both-mon-slots-empty; no egg; zero step counter",
        },
        "facilitySession": {
            "challengeStatus": game.read_u8(block2 + 0x64C + 1628),
            "levelModeAndPauseBits": game.read_u8(block2 + 0x64C + 1629),
            "selectedPartyHex": game.read(block2 + 0x64C + 1630, 6).hex(),
            "currentBattle": game.read_u16(block2 + 0x64C + 1638),
            "meaning": "no active or paused Battle Frontier challenge",
        },
    }


def add_party_through_debug_menu(game) -> None:
    """Run the shipped Utilities > Cheat start action; do not synthesize mons."""
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

    def utilities_open():
        menu_data = game.pointer("sDebugMenuListData")
        return bool(
            menu_data
            and game.read_u32(menu_data + 4)
            == game.address("sDebugMenu_Actions_Utilities")
        )

    game.advance_until(
        utilities_open,
        description="Utilities debug submenu",
        max_pulses=20,
    )
    game.step(2)
    for _ in range(6):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.read_u8(game.address("gPartiesCount")) >= 3,
        description="debug Cheat start party",
        max_frames=1_200,
        step_frames=2,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)


def assert_runtime_semantics(game, expected: dict[str, Any]) -> None:
    actual = runtime_semantics(game)
    assert actual == expected, (
        "runtime save semantics differ from reviewed provenance: "
        f"expected={expected!r}, actual={actual!r}"
    )


def save_from_start_menu(game):
    """Drive the real field start-menu Save action and await its flash write."""
    before = game.battery_path.read_bytes() if game.battery_path.is_file() else b""
    for _ in range(10):
        game.press("Start", release_frames=30)
        if game.task_active("Task_ShowStartMenu"):
            break
    else:
        raise AssertionError("populated start menu not reached in 300 frames")
    count = game.read_u8(game.address("sNumStartMenuActions"))
    actions = game.read(game.address("sCurrentStartMenuActions"), count)
    try:
        save_index = actions.index(MENU_ACTION_SAVE)
    except ValueError as error:
        raise AssertionError(
            f"start menu has no Save action: {actions.hex()}"
        ) from error
    cursor = game.read_u8(game.address("sStartMenuCursorPos"))
    for _ in range((save_index - cursor) % count):
        game.press("Down", release_frames=4)
    # Selecting Save enters two default-Yes prompts.
    game.press("A", release_frames=12)
    after = game.wait_for_battery_change(
        before, max_pulses=600, button="A", release_frames=6
    )
    assert after.data != before
    return after


def cold_restart_and_continue(game):
    old_process = game.cold_restart()
    assert old_process.poll() is not None
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Continue did not reach the overworld after cold restart")
    game.wait_for_controls_unlocked(max_frames=1_200)
    return old_process
