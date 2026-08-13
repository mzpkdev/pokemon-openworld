from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.start_profile import StartProfile, quickstart_with_profile
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)


def _load_contract() -> dict:
    contract = json.loads(Path(__file__).with_name("pokecenters.json").read_text())
    if contract.get("schemaVersion") != 1:
        raise ValueError("pokecenters.json requires schemaVersion 1")
    required = {
        "schemaVersion",
        "ordinaryNurses",
        "facilityNurses",
        "whiteoutCases",
        "runtimeCases",
        "escalatorRoundTrip",
    }
    if set(contract) != required:
        raise ValueError(
            f"pokecenters.json fields differ: {sorted(set(contract) ^ required)}"
        )
    interactive = contract["ordinaryNurses"] + contract["facilityNurses"]
    if len(interactive) != len(set(interactive)):
        raise ValueError("ordinaryNurses and facilityNurses must be unique")
    runtime_names = set(contract["runtimeCases"])
    missing = set(interactive) | set(contract["whiteoutCases"])
    if missing - runtime_names:
        raise ValueError(
            f"runtimeCases missing maps: {sorted(missing - runtime_names)}"
        )
    return contract


CONTRACT = _load_contract()
RUNTIME_CASES = CONTRACT["runtimeCases"]

# Raw offsets below are test ABI pinned to the named C members in the current ROM:
# struct Pokemon (include/pokemon.h), SaveBlock1/2 (include/global.h), and
# struct Main (include/main.h). Symbol lookup anchors each containing object.
SCRIPT_IDLE = 2
POKEMON_STATUS_OFFSET = 0x50
POKEMON_HP_OFFSET = 0x56
POKEMON_MAX_HP_OFFSET = 0x58
STATUS1_POISON = 1 << 3
SAVE_BLOCK1_GAME_STATS_OFFSET = 0x159C
SAVE_BLOCK2_ENCRYPTION_KEY_OFFSET = 0xAC
GAME_STAT_USED_POKECENTER = 15
G_MAIN_STATE_OFFSET = 0x438
UNION_ROOM_SENTINEL = 0xBEEF
EWRAM_RANGE = range(0x02000000, 0x02040000)
IWRAM_RANGE = range(0x03000000, 0x03008000)


def _assert_writable_ram(address: int, size: int, label: str) -> None:
    assert size > 0
    end = address + size - 1
    assert (address in EWRAM_RANGE and end in EWRAM_RANGE) or (
        address in IWRAM_RANGE and end in IWRAM_RANGE
    ), f"{label} resolved outside writable GBA RAM: 0x{address:08x}+0x{size:x}"


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _current_debug_menu_is(game, menu_symbol: str, level: int) -> bool:
    menu_data = game.pointer("sDebugMenuListData")
    return bool(
        menu_data and game.read_u32(menu_data + level * 4) == game.address(menu_symbol)
    )


def _add_debug_party(game) -> None:
    """Use the shipped debug menu so healing operates on valid Pokemon data."""
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


def _boot_with_party(game) -> None:
    _settle_overworld(game)
    _add_debug_party(game)


def _maps_by_name():
    return {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }


def _load_case(game, name: str, request_id: int):
    maps = _maps_by_name()
    entry = maps[name]
    case = RUNTIME_CASES[name]
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=case["x"],
            y=case["y"],
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    game.wait_for_controls_unlocked(max_frames=1_200)
    return maps, entry, case


def _lead_mon(game) -> int:
    assert game.read_u8(game.address("gPartiesCount")) > 0
    mon = game.address("gParties")
    _assert_writable_ram(mon, POKEMON_MAX_HP_OFFSET + 2, "gParties[0]")
    return mon


def _damage_and_poison_lead(game) -> tuple[int, int]:
    mon = _lead_mon(game)
    max_hp = game.read_u16(mon + POKEMON_MAX_HP_OFFSET)
    assert max_hp > 1
    game.write_u16(mon + POKEMON_HP_OFFSET, 1)
    game.write(mon + POKEMON_STATUS_OFFSET, STATUS1_POISON.to_bytes(4, "little"))
    assert game.read_u16(mon + POKEMON_HP_OFFSET) == 1
    assert game.read_u32(mon + POKEMON_STATUS_OFFSET) == STATUS1_POISON
    return mon, max_hp


def _game_stat(game, stat: int) -> int:
    assert 0 <= stat < 64
    stat_address = game.save_block1() + SAVE_BLOCK1_GAME_STATS_OFFSET + stat * 4
    key_address = game.save_block2() + SAVE_BLOCK2_ENCRYPTION_KEY_OFFSET
    _assert_writable_ram(stat_address, 4, "SaveBlock1.gameStats entry")
    _assert_writable_ram(key_address, 4, "SaveBlock2.encryptionKey")
    encrypted = game.read_u32(stat_address)
    key = game.read_u32(key_address)
    return encrypted ^ key


def _drive_heal_dialogue(game, mon: int, max_hp: int) -> None:
    saw_heal_task = False
    for _ in range(2_400):
        saw_heal_task |= game.task_active("Task_PokecenterHeal")
        healed = (
            game.read_u16(mon + POKEMON_HP_OFFSET) == max_hp
            and game.read_u32(mon + POKEMON_STATUS_OFFSET) == 0
        )
        if (
            saw_heal_task
            and healed
            and not game.controls_locked()
            and game.script_status() == SCRIPT_IDLE
        ):
            return
        game.press("A", hold_frames=1, release_frames=1)
    raise AssertionError(
        "nurse interaction did not heal and return control; "
        f"task={saw_heal_task}, hp={game.read_u16(mon + POKEMON_HP_OFFSET)}/"
        f"{max_hp}, status=0x{game.read_u32(mon + POKEMON_STATUS_OFFSET):08x}, "
        f"locked={game.controls_locked()}, script={game.script_status()}"
    )


def _interact_with_nurse(game, case: dict, mon: int, max_hp: int) -> None:
    game.face(case["direction"])
    game.press("A")
    _drive_heal_dialogue(game, mon, max_hp)


def _last_heal_location(game) -> tuple[int, int, int, int, int]:
    raw = game.read(game.save_block1() + 0x1C, 8)
    map_group, map_num, warp_id, _padding, x, y = struct.unpack("<bbbBhh", raw)
    return map_group, map_num, warp_id, x, y


def _force_whiteout_and_wait_for_center(game, entry, case: dict) -> None:
    mon, max_hp = _damage_and_poison_lead(game)
    main = game.address("gMain")
    _assert_writable_ram(main, G_MAIN_STATE_OFFSET + 1, "gMain")
    game.write_u8(main + G_MAIN_STATE_OFFSET, 0)
    game.write(main + 4, (game.address("CB2_WhiteOut") | 1).to_bytes(4, "little"))

    saw_heal_task = False
    for _ in range(4_000):
        saw_heal_task |= game.task_active("Task_PokecenterHeal")
        settled = (
            saw_heal_task
            and game.map_id() == entry.map_id
            and game.read_u16(mon + POKEMON_HP_OFFSET) == max_hp
            and game.read_u32(mon + POKEMON_STATUS_OFFSET) == 0
            and not game.controls_locked()
            and game.script_status() == SCRIPT_IDLE
        )
        if settled:
            break
        game.press("A", hold_frames=1, release_frames=1)
    else:
        raise AssertionError(
            "whiteout did not heal at the selected center and settle; "
            f"task={saw_heal_task}, map={game.map_id()}, "
            f"hp={game.read_u16(mon + POKEMON_HP_OFFSET)}/{max_hp}, "
            f"status=0x{game.read_u32(mon + POKEMON_STATUS_OFFSET):08x}, "
            f"locked={game.controls_locked()}, script={game.script_status()}"
        )

    assert saw_heal_task
    assert game.read_u16(game.address("gSpecialVar_LastTalked")) == case["nurseLocalId"]


@pytest.mark.parametrize("map_name", CONTRACT["ordinaryNurses"])
def test_nurse_heals_and_returns_control(integrity_game, map_name):
    _boot_with_party(integrity_game)
    _, _, case = _load_case(integrity_game, map_name, 0xF5000001)
    mon, max_hp = _damage_and_poison_lead(integrity_game)
    stat_before = _game_stat(integrity_game, GAME_STAT_USED_POKECENTER)

    _interact_with_nurse(integrity_game, case, mon, max_hp)

    assert _game_stat(integrity_game, GAME_STAT_USED_POKECENTER) == stat_before + 1
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE


@pytest.mark.parametrize("map_name", CONTRACT["facilityNurses"])
def test_facility_nurse_skips_union_room_probe(integrity_game, map_name):
    _boot_with_party(integrity_game)
    _, _, case = _load_case(integrity_game, map_name, 0xF5000002)
    mon, max_hp = _damage_and_poison_lead(integrity_game)
    union_probe_value = integrity_game.address("gSpecialVar_0x8008")
    integrity_game.write_u16(union_probe_value, UNION_ROOM_SENTINEL)

    _interact_with_nurse(integrity_game, case, mon, max_hp)

    assert integrity_game.read_u16(union_probe_value) == UNION_ROOM_SENTINEL
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE


@pytest.mark.parametrize("map_name", CONTRACT["whiteoutCases"])
def test_whiteout_heals_at_last_center_and_returns_control(integrity_game, map_name):
    _boot_with_party(integrity_game)
    _, entry, case = _load_case(integrity_game, map_name, 0xF5000003)
    _force_whiteout_and_wait_for_center(integrity_game, entry, case)


def test_olivine_checkpoint_survives_cross_region_save_restart_and_whiteout(
    session_factory,
):
    game = session_factory()
    quickstart_with_profile(game, StartProfile.JOHTO, 0xF5000010)
    maps = _maps_by_name()
    olivine_city = maps["OlivineCity"]
    olivine_center = maps["OlivineCity_PokemonCenter"]
    assert game.map_id() == olivine_city.map_id
    assert not game.controls_locked()
    _add_debug_party(game)

    _, loaded_center, olivine_case = _load_case(
        game, "OlivineCity_PokemonCenter", 0xF5000011
    )
    assert loaded_center == olivine_center
    mon, max_hp = _damage_and_poison_lead(game)
    _interact_with_nurse(game, olivine_case, mon, max_hp)
    expected_checkpoint = (
        olivine_city.group,
        olivine_city.number,
        -1,
        15,
        44,
    )
    assert _last_heal_location(game) == expected_checkpoint

    pallet = maps["PalletTown_Frlg"]
    travel = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=0xF5000012,
            map_group=pallet.group,
            map_num=pallet.number,
            x=6,
            y=8,
        ),
        max_frames=1_800,
    )
    assert travel.status is IntegrityLoadStatus.SUCCESS
    assert travel.phase is IntegrityLoadPhase.FIELD_READY
    assert travel.error is IntegrityLoadError.NONE
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.map_id() == pallet.map_id
    assert _last_heal_location(game) == expected_checkpoint

    save_from_start_menu(game)
    game.wait_for_controls_unlocked(max_frames=1_200)
    cold_restart_and_continue(game)
    assert game.map_id() == pallet.map_id
    assert _last_heal_location(game) == expected_checkpoint

    _force_whiteout_and_wait_for_center(game, olivine_center, olivine_case)
    assert _last_heal_location(game) == expected_checkpoint


def _hold_direction_until_map(game, direction: str, destination):
    saw_warp_out = False
    game.set_buttons(**{direction: True})
    try:
        for _ in range(1_800):
            game.step()
            saw_warp_out |= game.task_active("Task_EscalatorWarpOut")
            if game.map_id() == destination.map_id:
                game.set_buttons(**{direction: False})
                game.wait_for_controls_unlocked(max_frames=1_200)
                return saw_warp_out
    finally:
        game.set_buttons(**{direction: False})
    raise AssertionError(
        f"{direction} escalator did not reach {destination.name}; map={game.map_id()}"
    )


def test_pokecenter_escalator_round_trip(integrity_game):
    fixture = CONTRACT["escalatorRoundTrip"]
    _settle_overworld(integrity_game)
    maps = _maps_by_name()
    source = maps[fixture["map"]]
    destination = maps[fixture["destination"]]
    result = integrity_game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=0xF5000004,
            map_group=source.group,
            map_num=source.number,
            x=fixture["x"],
            y=fixture["y"],
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    integrity_game.wait_for_controls_unlocked(max_frames=1_200)

    assert _hold_direction_until_map(
        integrity_game, fixture["direction"], destination
    ), "Pewter 1F escalator warp-out task never ran"
    assert _hold_direction_until_map(
        integrity_game, fixture["returnDirection"], source
    ), "Pewter 2F escalator warp-out task never ran"
    assert integrity_game.map_id() == source.map_id
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
