from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct

import pytest

from tools.e2e.save_journey import (
    add_party_through_debug_menu,
    cold_restart_and_continue,
    save_from_start_menu,
)
from tools.e2e.skyemu import IntegrityLoadStatus, IntegrityMapLoadRequest
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)


ITEM_POKE_BALL = 1
SPECIES_ZIGZAGOON = 263
CAPTURE_REQUEST_STATUS_OFFSET = 9
CAPTURE_REQUEST_SIZE = 12
CAPTURE_RESULT_SIZE = 16
PROVENANCE_REQUEST_STATUS_OFFSET = 5
PROVENANCE_REQUEST_SIZE = 8
PROVENANCE_RESULT_SIZE = 12
SUMMARY_MEMO_BUFFER_SIZE = 256
SUMMARY_MEMO_POISON = 0xEE


class CaptureStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    RUNNING = 2
    SUCCESS = 3
    ERROR = 4


@dataclass(frozen=True)
class CaptureResult:
    request_id: int
    map_section: int
    species: int
    met_location: int
    party_index: int
    status: CaptureStatus
    error: int


@dataclass(frozen=True)
class ProvenanceResult:
    request_id: int
    species: int
    map_section: int
    met_location: int
    party_index: int
    status: CaptureStatus
    error: int


CASES = (
    ("LittlerootTown", 0, 0, "LITTLEROOT TOWN"),
    ("JohtoVictoryRoad_1F", 264, 70, "VICTORY ROAD"),
)


def _quickstart(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach the overworld")


def _read_capture_result(game) -> CaptureResult:
    data = game.read(game.address("gIntegrityCaptureResult"), CAPTURE_RESULT_SIZE)
    request_id, section, species, met, party, status, error, reserved = struct.unpack(
        "<IHHBBBBI", data
    )
    assert reserved == 0
    return CaptureResult(
        request_id, section, species, met, party, CaptureStatus(status), error
    )


def _start_capture(game, request_id: int) -> None:
    address = game.address("gIntegrityCaptureRequest")
    payload = struct.pack(
        "<IHHBBH",
        request_id,
        SPECIES_ZIGZAGOON,
        ITEM_POKE_BALL,
        5,
        CaptureStatus.IDLE,
        0,
    )
    assert len(payload) == CAPTURE_REQUEST_SIZE
    game.pause()
    game.write(address, payload)
    game.write_u8(address + CAPTURE_REQUEST_STATUS_OFFSET, CaptureStatus.PENDING)
    game.resume()


def _inspect_party_provenance(
    game, party_index: int, request_id: int
) -> ProvenanceResult:
    address = game.address("gIntegrityProvenanceRequest")
    payload = struct.pack("<IBBH", request_id, party_index, CaptureStatus.IDLE, 0)
    assert len(payload) == PROVENANCE_REQUEST_SIZE
    game.pause()
    game.write(address, payload)
    game.write_u8(address + PROVENANCE_REQUEST_STATUS_OFFSET, CaptureStatus.PENDING)
    game.resume()

    for _ in range(120):
        data = game.read(
            game.address("gIntegrityProvenanceResult"), PROVENANCE_RESULT_SIZE
        )
        fields = struct.unpack("<IHHBBBB", data)
        result = ProvenanceResult(
            fields[0],
            fields[1],
            fields[2],
            fields[3],
            fields[4],
            CaptureStatus(fields[5]),
            fields[6],
        )
        if result.request_id == request_id and result.status in (
            CaptureStatus.SUCCESS,
            CaptureStatus.ERROR,
        ):
            assert result.party_index == party_index
            return result
        game.step()
    raise AssertionError(f"party provenance inspection {request_id:#x} timed out")


def _catch_through_battle_bag(game, request_id: int) -> CaptureResult:
    _start_capture(game, request_id)
    game.wait_for_callback("BattleMainCB2", max_frames=1_800)
    game.advance_until(
        lambda: (
            game.read_u32(game.address("gBattlerControllerFuncs"))
            in tuple(
                address | 1
                for address in game.symbols.addresses("HandleInputChooseAction")
            )
        ),
        description="wild battle action menu",
        max_pulses=600,
    )
    game.press("Right", release_frames=2)
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: game.task_active("Task_BagMenu_HandleInput"),
        description="battle bag input",
        max_frames=1_200,
    )
    game.press("A", release_frames=4)
    game.press("A", release_frames=8)

    for _ in range(2_400):
        result = _read_capture_result(game)
        if result.status is CaptureStatus.SUCCESS:
            return result
        if result.status is CaptureStatus.ERROR:
            raise AssertionError(f"capture hook failed with error {result.error}")
        game.press("A", release_frames=2)
    raise AssertionError("real capture did not store the caught mon")


def _open_debug_menu(game) -> None:
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


def _give_egg(game) -> int:
    before = game.read_u8(game.address("gPartiesCount"))
    _open_debug_menu(game)
    for _ in range(3):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            game.pointer("sDebugMenuListData")
            and game.read_u32(game.pointer("sDebugMenuListData") + 4)
            == game.address("sDebugMenu_Actions_Give")
        ),
        description="Give X debug submenu",
        max_frames=300,
    )
    game.step(60)
    for _ in range(3):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectId"),
        description="debug Give Egg species picker",
        max_frames=300,
    )
    game.step(2)
    game.press("A", release_frames=4)
    game.wait_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == before + 1,
        description="debug-created egg in party",
        max_frames=600,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    return before


def _hatch_egg_through_debug_script(game, egg_index: int) -> None:
    _open_debug_menu(game)
    for _ in range(2):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            game.pointer("sDebugMenuListData")
            and game.read_u32(game.pointer("sDebugMenuListData") + 4)
            == game.address("sDebugMenu_Actions_Party")
        ),
        description="Party debug submenu",
        max_frames=300,
    )
    game.step(60)
    game.press("Down", release_frames=2)
    game.press("A", release_frames=4)
    game.wait_until(
        lambda: game.task_active("Task_HandleChooseMonInput"),
        description="Debug_HatchAnEgg party picker",
        max_frames=1_200,
    )
    game.step(60)
    _select_party_slot(game, egg_index)
    game.press("A", release_frames=8)
    game.wait_for_callback("CB2_EggHatch", max_frames=2_400)
    for pulse in range(3_000):
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
        game.press("B" if pulse % 5 == 4 else "A", release_frames=2)
    raise AssertionError("Debug_HatchAnEgg did not return to the overworld")


def _encode_display_name(value: str) -> bytes:
    encoded = bytearray()
    for character in value:
        if character == " ":
            encoded.append(0)
        elif "A" <= character <= "Z":
            encoded.append(0xBB + ord(character) - ord("A"))
        else:
            raise ValueError(f"unsupported summary assertion character: {character!r}")
    return bytes(encoded)


def _poison_summary_memo(game, expected_name: str) -> bytes:
    expected = _encode_display_name(expected_name)
    address = game.address("gStringVar4")
    game.write(address, bytes((SUMMARY_MEMO_POISON,)) * SUMMARY_MEMO_BUFFER_SIZE)
    poisoned = game.read(address, SUMMARY_MEMO_BUFFER_SIZE)
    assert expected not in poisoned
    return expected


def _open_summary_and_assert_display(
    game, party_index: int, expected_name: str
) -> None:
    expected = _poison_summary_memo(game, expected_name)
    game.press("Start", release_frames=20)
    game.wait_until(
        lambda: game.read_u8(game.address("sNumStartMenuActions")) > 0,
        description="start menu",
        max_frames=300,
    )
    actions = game.read(
        game.address("sCurrentStartMenuActions"),
        game.read_u8(game.address("sNumStartMenuActions")),
    )
    pokemon_index = actions.index(1)
    cursor = game.read_u8(game.address("sStartMenuCursorPos"))
    for _ in range((pokemon_index - cursor) % len(actions)):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=12)
    game.wait_until(
        lambda: game.task_active("Task_HandleChooseMonInput"),
        description="field party menu",
        max_frames=1_200,
    )
    game.step(60)
    _select_party_slot(game, party_index)
    game.press("A", release_frames=3)
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: game.pointer("sMonSummaryScreen") != 0,
        description="real Pokemon summary",
        max_frames=1_200,
    )
    # BufferMonTrainerMemo only populates this string on the Info page. Since
    # the buffer was poisoned immediately before opening, this cannot pass on
    # text left behind by the previous summary.
    game.wait_until(
        lambda: (
            expected in game.read(game.address("gStringVar4"), SUMMARY_MEMO_BUFFER_SIZE)
        ),
        description=f"rendered summary memo containing {expected_name}",
        max_frames=1_200,
    )
    for _ in range(600):
        game.press("B", release_frames=2)
        if (
            game.callback_is("CB2_Overworld")
            and not game.controls_locked()
            and game.script_status() == 2
        ):
            assert game.read_u8(game.address("gLastViewedMonIndex")) == party_index
            return
    raise AssertionError("summary did not close back to unlocked field controls")


def _select_party_slot(game, party_index: int) -> None:
    # A freshly opened single-layout party menu starts on the large lead slot;
    # the remaining five slots form the column to its right.
    if party_index == 0:
        return
    game.press("Right", hold_frames=3, release_frames=3)
    for _ in range(party_index - 1):
        game.press("Down", hold_frames=3, release_frames=3)


def test_summary_memo_poison_rejects_stale_display_text():
    expected = _encode_display_name("VICTORY ROAD")

    class StaleMemoGame:
        def __init__(self):
            self.data = bytearray(expected + bytes(SUMMARY_MEMO_BUFFER_SIZE))

        def address(self, symbol):
            assert symbol == "gStringVar4"
            return 0

        def write(self, address, data):
            self.data[address : address + len(data)] = data

        def read(self, address, size):
            return bytes(self.data[address : address + size])

    game = StaleMemoGame()
    assert expected in game.read(0, SUMMARY_MEMO_BUFFER_SIZE)
    assert _poison_summary_memo(game, "VICTORY ROAD") == expected
    assert expected not in game.read(0, SUMMARY_MEMO_BUFFER_SIZE)


@pytest.mark.parametrize("map_name,map_section,expected_code,expected_display", CASES)
@pytest.mark.long_journey
def test_catch_hatch_summary_survives_cold_restart(
    integrity_game, map_name, map_section, expected_code, expected_display
):
    _quickstart(integrity_game)
    if integrity_game.read_u8(integrity_game.address("gPartiesCount")) == 0:
        add_party_through_debug_menu(integrity_game)

    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    destination = maps[map_name]
    loaded = integrity_game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=0xF4200000 | expected_code,
            map_group=destination.group,
            map_num=destination.number,
            suppress_scripts=True,
            suppress_events=True,
        ),
        max_frames=1_800,
    )
    assert loaded.status is IntegrityLoadStatus.SUCCESS
    integrity_game.wait_for_controls_unlocked(max_frames=1_200)

    caught = _catch_through_battle_bag(integrity_game, 0xF4210000 | expected_code)
    assert caught.map_section == map_section
    assert caught.met_location == expected_code
    assert caught.species == SPECIES_ZIGZAGOON
    integrity_game.advance_until(
        lambda: integrity_game.callback_is("CB2_Overworld"),
        description="caught-mon return to field",
        max_pulses=1_200,
    )
    integrity_game.wait_for_controls_unlocked(max_frames=1_200)

    egg_index = _give_egg(integrity_game)
    _hatch_egg_through_debug_script(integrity_game, egg_index)

    # These are the exact tables used by CreateMon/EggHatch and summary text.
    assert (
        integrity_game.read_u8(
            integrity_game.address("gMapSectionToMetLocation") + map_section
        )
        == expected_code
    )
    assert integrity_game.read_u16(
        integrity_game.address("gMetLocationToMapSection") + expected_code * 2
    ) == (0 if expected_code == 0 else 70)

    save_from_start_menu(integrity_game)
    cold_restart_and_continue(integrity_game)

    caught_after_restart = _inspect_party_provenance(
        integrity_game, caught.party_index, 0xF4220000 | expected_code
    )
    assert caught_after_restart.status is CaptureStatus.SUCCESS
    assert caught_after_restart.error == 0
    assert caught_after_restart.species == SPECIES_ZIGZAGOON
    assert caught_after_restart.met_location == expected_code
    assert caught_after_restart.map_section == (0 if expected_code == 0 else 70)

    hatched_after_restart = _inspect_party_provenance(
        integrity_game, egg_index, 0xF4230000 | expected_code
    )
    assert hatched_after_restart.status is CaptureStatus.SUCCESS
    assert hatched_after_restart.error == 0
    assert hatched_after_restart.met_location == expected_code
    assert hatched_after_restart.map_section == (0 if expected_code == 0 else 70)

    _open_summary_and_assert_display(
        integrity_game, caught.party_index, expected_display
    )
    _open_summary_and_assert_display(integrity_game, egg_index, expected_display)
