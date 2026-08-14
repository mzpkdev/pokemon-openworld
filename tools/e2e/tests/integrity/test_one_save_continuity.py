from __future__ import annotations

import json
from pathlib import Path
import struct

import pytest

from tools.e2e.save_file import (
    SaveImage,
    decode_box_pokemon,
    is_strictly_newer_save_counter,
)
from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import integrity_manifest_path, load_manifest_maps


FIXTURE_MANIFEST = Path(__file__).parents[2] / "fixtures" / "kanto_continuity_start.json"
ITEM_POKE_BALL = 1
ITEM_SUPER_POTION = 29
ITEM_OLD_ROD = 709
SPECIES_MAGIKARP = 129
SPECIES_POLIWHIRL = 61
SPECIES_TAUROS = 128
SPECIES_TREECKO = 252
SPECIES_TORCHIC = 255
SPECIES_MUDKIP = 258
MET_LOCATION_VERMILION_CITY = 93
MET_LOCATION_ROUTE_39 = 233
GAME_VERSION_EMERALD = 3
EUGENE_DEFEAT_BYTE = 78
EUGENE_DEFEAT_MASK = 1
TRAINER_SAILOR_EUGENE_JOHTO = 1482
BATTLE_TYPE_TRAINER = 1 << 3
MENU_ACTION_BAG = 2
MENU_POCKET_ITEMS = 0
MENU_POCKET_KEY_ITEMS = 4
MENU_POCKET_POKE_BALLS = 1
POCKET_ITEMS = 0
POCKET_KEY_ITEMS = 1
POCKET_POKE_BALLS = 2
POCKET_OFFSETS = (0x560, 0x5D8, 0x650)
POCKET_CAPACITIES = (30, 30, 16)
POKEMON_STATUS_OFFSET = 0x50
POKEMON_HP_OFFSET = 0x56
POKEMON_MAX_HP_OFFSET = 0x58
SCRIPT_IDLE = 2
BATTLE_POKEMON_MOVES_OFFSET = 12
BATTLE_POKEMON_PP_OFFSET = 37
MOVE_INFO_SIZE = 68
MOVE_INFO_POWER_WORD_OFFSET = 10


def _continue(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("reviewed continuity fixture did not Continue")


def _item_count(game, pocket: int, item: int) -> int:
    encryption_key = game.read_u32(game.save_block2() + 0xAC) & 0xFFFF
    total = 0
    for index in range(POCKET_CAPACITIES[pocket]):
        address = game.save_block1() + POCKET_OFFSETS[pocket] + index * 4
        if game.read_u16(address) == item:
            total += game.read_u16(address + 2) ^ encryption_key
    return total


def _item_slot(game, pocket: int, item: int) -> int:
    for index in range(POCKET_CAPACITIES[pocket]):
        address = game.save_block1() + POCKET_OFFSETS[pocket] + index * 4
        if game.read_u16(address) == item:
            return index
    raise AssertionError(f"item {item} is absent from pocket {pocket}")


def _money(game) -> int:
    encryption_key = game.read_u32(game.save_block2() + 0xAC)
    return game.read_u32(game.save_block1() + 0x490) ^ encryption_key


def _assert_reviewed_start(game, document: dict) -> None:
    expected = document["semanticExpectations"]
    assert game.read(game.save_block2(), 8).hex() == expected["identity"]["playerNameEncodedHex"]
    assert game.read_u8(game.save_block2() + 8) == expected["identity"]["gender"]
    assert game.read(game.save_block2() + 10, 4).hex() == expected["identity"]["trainerIdHex"]
    assert game.read_u8(game.address("gPartiesCount")) == expected["party"]["count"]
    for index, pokemon in enumerate(expected["party"]["pokemon"]):
        record = game.read(game.address("gParties") + index * 100, 80)
        assert decode_box_pokemon(record) == pokemon
    assert _item_count(game, POCKET_KEY_ITEMS, ITEM_OLD_ROD) == 0
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 0


def _box_pokemon(game, box: int, slot: int) -> dict | None:
    storage = game.pointer("gPokemonStoragePtr")
    assert storage
    return decode_box_pokemon(game.read(storage + 4 + (box * 30 + slot) * 80, 80))


def _last_heal_location(game) -> tuple[int, int, int, int, int]:
    raw = game.read(game.save_block1() + 0x1C, 8)
    group, number, warp, _padding, x, y = struct.unpack("<bbbBhh", raw)
    return group, number, warp, x, y


def _heal_at_olivine_nurse(game) -> None:
    party_count = game.read_u8(game.address("gPartiesCount"))
    party = game.address("gParties")
    game.move_to(x=7, y=4)
    game.face("Up")
    game.press("A")
    saw_heal_task = False
    for _ in range(2_400):
        saw_heal_task |= game.task_active("Task_PokecenterHeal")
        healed = all(
            game.read_u16(party + index * 100 + POKEMON_HP_OFFSET)
            == game.read_u16(party + index * 100 + POKEMON_MAX_HP_OFFSET)
            and game.read_u32(party + index * 100 + POKEMON_STATUS_OFFSET) == 0
            for index in range(party_count)
        )
        if (
            saw_heal_task
            and healed
            and not game.controls_locked()
            and game.script_status() == SCRIPT_IDLE
        ):
            return
        game.press("A", hold_frames=1, release_frames=1)
    raise AssertionError("ordinary Olivine nurse interaction did not heal the party")


def _assert_party_fully_healed(game, expected_count: int) -> None:
    assert game.read_u8(game.address("gPartiesCount")) == expected_count
    party = game.address("gParties")
    for index in range(expected_count):
        max_hp = game.read_u16(party + index * 100 + POKEMON_MAX_HP_OFFSET)
        assert max_hp > 0
        assert game.read_u16(party + index * 100 + POKEMON_HP_OFFSET) == max_hp


def _controlled_position(game, entry, coordinates, request_id: int) -> None:
    """Use the debug map loader only for documented journey positioning."""
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


def _open_storage_from_olivine_console(game) -> None:
    game.move_path((None, 6), (10, None), (None, 5))
    game.face("Right")
    game.press("A")
    for _ in range(600):
        if game.task_active("Task_PCMainMenu"):
            game.step(60)  # Let the PC menu finish loading before navigation.
            return
        game.press("A", release_frames=2)
    raise AssertionError("reachable Olivine console did not open Pokemon storage")


def _deposit_first_party_mon_in_box_one(game, expected: dict) -> None:
    assert _box_pokemon(game, 0, 0) is None
    game.press("Down", release_frames=4)  # Deposit is second in the shipped menu.
    game.press("A", release_frames=8)
    game.wait_for_callback("CB2_PokeStorage", max_frames=1_200)
    game.advance_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="Box 1 deposit screen",
        max_pulses=600,
    )
    game.step(60)  # Let the storage cursor finish its fade-in.
    game.press("A", release_frames=8)  # First party Pokemon.
    game.wait_until(
        lambda: game.task_active("Task_OnSelectedMon"),
        description="first party Pokemon storage menu",
        max_frames=600,
    )
    game.step(60)  # Let the selection menu finish loading.
    game.press("A", release_frames=8)  # Store.
    game.wait_until(
        lambda: game.task_active("Task_DepositMenu"),
        description="Box 1 deposit choice",
        max_frames=600,
    )
    game.step(60)  # Let the box-choice menu finish loading.
    game.press("A", release_frames=8)  # Box 1.
    game.advance_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == 4,
        description="original Kanto Pokemon deposited in Box 1",
        max_pulses=1_200,
    )
    game.wait_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="stable storage screen after original Kanto deposit",
        max_frames=1_200,
        step_frames=4,
    )
    game.step(60)
    assert _box_pokemon(game, 0, 0) == expected


def _withdraw_first_box_mon(game, expected: dict) -> None:
    game.press("B", release_frames=8)
    game.advance_until(
        lambda: game.task_active("Task_PCMainMenu"),
        description="storage main menu after deposit",
        max_pulses=600,
        button="B",
    )
    game.step(60)  # Let the PC menu finish loading before navigation.
    game.press("Down", release_frames=4)  # Withdraw follows Deposit.
    game.press("A", release_frames=8)
    game.wait_for_callback("CB2_PokeStorage", max_frames=1_200)
    game.advance_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="Box 1 withdraw screen",
        max_pulses=600,
    )
    game.step(60)  # Let the storage cursor finish its fade-in.
    game.press("A", release_frames=8)  # First Box 1 Pokemon.
    game.wait_until(
        lambda: game.task_active("Task_OnSelectedMon"),
        description="Box 1 Pokemon withdraw menu",
        max_frames=600,
    )
    game.step(60)  # Let the selection menu finish loading.
    game.press("A", release_frames=8)  # Withdraw.
    game.wait_until(
        lambda: game.task_active("Task_WithdrawMon"),
        description="ordinary Box 1 withdrawal",
        max_frames=600,
    )
    game.advance_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == 5,
        description="original Kanto Pokemon withdrawn from Box 1",
        max_pulses=1_200,
    )
    game.wait_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="stable storage screen after original Kanto withdrawal",
        max_frames=1_200,
        step_frames=4,
    )
    game.step(60)
    assert _box_pokemon(game, 0, 0) is None
    withdrawn = decode_box_pokemon(
        game.read(game.address("gParties") + 4 * 100, 80)
    )
    assert withdrawn == expected


def _deposit_johto_catch_in_box_one(game, expected: dict) -> None:
    game.press("B", release_frames=8)
    game.advance_until(
        lambda: game.task_active("Task_PCMainMenu"),
        description="storage main menu after withdrawal",
        max_pulses=600,
        button="B",
    )
    game.step(60)  # Let the PC menu finish loading before navigation.
    game.press("Up", release_frames=4)  # Deposit precedes Withdraw.
    game.press("A", release_frames=8)
    game.wait_for_callback("CB2_PokeStorage", max_frames=1_200)
    game.advance_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="Box 1 second deposit screen",
        max_pulses=600,
    )
    game.step(60)  # Let the storage cursor finish its fade-in.
    party = game.address("gParties")
    party_count = game.read_u8(game.address("gPartiesCount"))
    target_index = next(
        index
        for index in range(party_count)
        if decode_box_pokemon(game.read(party + index * 100, 80)) == expected
    )
    cursor_position = game.address("sCursorPosition")
    storage = game.pointer("sStorage")
    assert storage
    for next_position in range(1, target_index + 1):
        game.press("Down", release_frames=4)
        game.wait_until(
            lambda position=next_position: game.read_u8(cursor_position) == position
            and game.read_u8(storage) == 0,
            description=f"storage party cursor row {next_position}",
            max_frames=300,
            step_frames=2,
        )
    assert game.read_u8(cursor_position) == target_index
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: game.task_active("Task_OnSelectedMon"),
        description="Johto catch storage menu",
        max_frames=600,
    )
    game.step(60)  # Let the selection menu finish loading.
    game.press("A", release_frames=8)  # Store.
    game.wait_until(
        lambda: game.task_active("Task_DepositMenu"),
        description="Johto catch Box 1 choice",
        max_frames=600,
    )
    game.step(60)  # Let the box-choice menu finish loading.
    game.press("A", release_frames=8)  # Box 1.
    game.advance_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == 4,
        description="Johto catch deposited in shared Box 1",
        max_pulses=1_200,
    )
    game.wait_until(
        lambda: game.task_active("Task_PokeStorageMain"),
        description="stable storage screen after Johto catch deposit",
        max_frames=1_200,
        step_frames=4,
    )
    game.step(60)
    assert _box_pokemon(game, 0, 0) == expected


def _buy_battle_supplies(game) -> None:
    assert _money(game) == 3_000
    game.move_path((None, 5), (2, None))
    game.face("Up")
    game.advance_until(
        lambda: game.task_active("Task_ShopMenu"),
        description="Vermilion clerk shop menu",
        max_pulses=300,
    )
    game.press("A")
    game.wait_for_callback("CB2_BuyMenu", max_frames=1_200)
    game.press("A", release_frames=8)  # Poke Ball is the first stock item.
    game.advance_until(
        lambda: game.task_active("Task_BuyHowManyDialogueHandleInput"),
        description="Poke Ball quantity input",
        max_pulses=300,
    )
    for _ in range(7):
        game.press("Up", release_frames=4)
    game.press("A", release_frames=8)
    for _ in range(600):
        if _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 8:
            break
        game.press("A", release_frames=2)
    else:
        raise AssertionError("ordinary Vermilion Mart purchase did not add eight Poke Balls")

    game.press("A", release_frames=8)  # Dismiss the clerk's thanks.
    game.advance_until(
        lambda: game.task_active("Task_BuyMenu"),
        description="Vermilion Mart stock list after Poke Ball purchase",
        max_pulses=300,
    )
    game.press("Down", release_frames=4)  # Super Potion is second.
    game.press("A", release_frames=8)
    game.advance_until(
        lambda: game.task_active("Task_BuyHowManyDialogueHandleInput"),
        description="Super Potion quantity input",
        max_pulses=300,
    )
    game.press("Up", release_frames=4)
    game.press("A", release_frames=8)
    for _ in range(600):
        if (
            _item_count(game, POCKET_ITEMS, ITEM_SUPER_POTION) == 2
            and _money(game) == 0
        ):
            break
        game.press("A", release_frames=2)
    else:
        raise AssertionError("ordinary Vermilion Mart purchase did not add two Super Potions")
    assert _money(game) == 0
    for _ in range(600):
        if game.callback_is("CB2_Overworld") and not game.controls_locked():
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
        game.press("B", release_frames=3)
    raise AssertionError("Vermilion Mart purchase did not return to field controls")


def _use_old_rod_from_bag(game) -> None:
    game.press("Start", release_frames=20)
    game.wait_until(
        lambda: game.read_u8(game.address("sNumStartMenuActions")) > 0,
        description="field start menu",
        max_frames=300,
    )
    count = game.read_u8(game.address("sNumStartMenuActions"))
    actions = game.read(game.address("sCurrentStartMenuActions"), count)
    bag_index = actions.index(MENU_ACTION_BAG)
    cursor = game.read_u8(game.address("sStartMenuCursorPos"))
    for _ in range((bag_index - cursor) % count):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=12)
    game.wait_until(
        lambda: game.task_active("Task_BagMenu_HandleInput"),
        description="field bag input",
        max_frames=1_200,
    )
    bag_position = game.address("gBagPosition")
    observed_pockets = []
    for _ in range(100):
        pocket = game.read_u8(bag_position + 5)
        observed_pockets.append(pocket)
        if pocket == MENU_POCKET_KEY_ITEMS:
            break
        game.press("Right", release_frames=12)
        game.wait_until(
            lambda: game.task_active("Task_BagMenu_HandleInput"),
            description="key-items pocket input",
            max_frames=300,
        )
    else:
        raise AssertionError(
            f"ordinary Bag navigation did not reach Key Items: {observed_pockets}"
        )
    game.step(60)
    for _ in range(POCKET_CAPACITIES[POCKET_KEY_ITEMS]):
        game.press("Up", release_frames=3)
    for _ in range(_item_slot(game, POCKET_KEY_ITEMS, ITEM_OLD_ROD)):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=8)
    assert game.read_u16(game.address("gSpecialVar_ItemId")) == ITEM_OLD_ROD
    game.wait_until(
        lambda: game.task_active("Task_ItemContext_MultipleRows"),
        description="Old Rod context menu",
        max_frames=300,
    )
    game.press("A", release_frames=8)  # Use.
    game.wait_until(
        lambda: game.task_active("Task_Fishing"),
        description="Old Rod field use",
        max_frames=1_200,
    )


def _fish_until_battle(game) -> None:
    fishing = game.address("Task_Fishing") | 1

    def fishing_step() -> int | None:
        tasks = game.address("gTasks")
        for task_id in range(16):
            task = tasks + task_id * 0x28
            if game.read_u8(task + 4) and game.read_u32(task) == fishing:
                return game.read_u16(task + 8)
        return None

    for _ in range(20):
        for _ in range(1_200):
            if game.callback_is("BattleMainCB2"):
                return
            step = fishing_step()
            if step is None:
                break
            if step in (8, 9):  # Production reel-in input windows.
                game.press("A", release_frames=2)
            elif step >= 15:  # Dismiss a completed no-bite attempt.
                game.press("A", release_frames=2)
            else:
                game.step()
        game.advance_until(
            lambda: game.callback_is("BattleMainCB2")
            or (not game.controls_locked() and game.script_status() == 2),
            description="fishing attempt completion or battle transition",
            max_pulses=600,
        )
        if game.callback_is("BattleMainCB2"):
            return
        _use_old_rod_from_bag(game)
    raise AssertionError("ordinary Old Rod attempts did not start a wild battle")


def _catch_with_battle_bag(game) -> int:
    action_handlers = tuple(
        address | 1 for address in game.symbols.addresses("HandleInputChooseAction")
    )
    balls_used = 0
    while _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL):
        for _ in range(1_200):
            if (
                game.read_u32(game.address("gBattlerControllerFuncs"))
                in action_handlers
            ):
                break
            if game.task_active("Task_HandleChooseMonInput") or game.callback_is(
                "CB2_UpdatePartyMenu"
            ):
                _choose_healthy_party_mon(game)
            else:
                game.press("B", release_frames=2)
        else:
            raise AssertionError("wild battle action menu not reached")
        game.press("Right", release_frames=2)
        game.press("A", release_frames=8)
        game.wait_until(
            lambda: game.task_active("Task_BagMenu_HandleInput"),
            description="wild battle Bag input",
            max_frames=1_200,
        )
        bag_position = game.address("gBagPosition")
        for _ in range(20):
            if game.read_u8(bag_position + 5) == MENU_POCKET_POKE_BALLS:
                break
            game.press("Right", release_frames=12)
            game.wait_until(
                lambda: game.task_active("Task_BagMenu_HandleInput"),
                description="battle Poke Balls pocket input",
                max_frames=300,
            )
        else:
            raise AssertionError(
                "ordinary battle Bag navigation did not reach Poke Balls"
            )
        game.step(60)
        for _ in range(POCKET_CAPACITIES[POCKET_POKE_BALLS]):
            game.press("Up", release_frames=3)
        stock_before = _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL)
        game.press("A", release_frames=4)
        assert game.read_u16(game.address("gSpecialVar_ItemId")) == ITEM_POKE_BALL
        game.wait_until(
            lambda: game.task_active("Task_ItemContext_SingleRow"),
            description="battle Poke Ball context menu",
            max_frames=300,
        )
        game.press("A", release_frames=8)
        for _ in range(2_400):
            if (
                game.callback_is("CB2_Overworld")
                or game.read_u32(game.address("gBattlerControllerFuncs"))
                in action_handlers
            ):
                break
            if game.task_active("Task_HandleChooseMonInput") or game.callback_is(
                "CB2_UpdatePartyMenu"
            ):
                _choose_healthy_party_mon(game)
            else:
                game.press("A", release_frames=2)
        else:
            raise AssertionError("ordinary Poke Ball result did not resolve")
        balls_used += 1
        assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == stock_before - 1
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return balls_used
    raise AssertionError("ordinary Route 39 capture exhausted the purchased Poke Balls")


def _choose_healthy_party_mon(game) -> None:
    game.step(60)  # The party task ignores input while its fade is active.
    if game.read_u16(game.address("gBattleMons") + 42):
        game.press("B", release_frames=8)
        game.wait_until(
            lambda: not game.task_active("Task_HandleChooseMonInput")
            and not game.callback_is("CB2_UpdatePartyMenu"),
            description="ordinary return from voluntary battle party menu",
            max_frames=1_200,
            step_frames=4,
        )
        return
    party = game.address("gParties")
    party_count = game.read_u8(game.address("gPartiesCount"))
    live = [
        index
        for index in range(party_count)
        if game.read_u16(party + index * 100 + POKEMON_HP_OFFSET)
    ]
    assert live
    target = next((index for index in live if index < 3), live[0])
    cursor_position = game.address("gPartyMenu") + 9
    cursor = game.read_u8(cursor_position)
    assert cursor <= 6
    for _ in range((target - cursor) % 7):
        next_position = (cursor + 1) % 7
        game.press("Down", release_frames=4)
        game.wait_until(
            lambda position=next_position: game.read_u8(cursor_position) == position,
            description=f"battle party cursor row {next_position}",
            max_frames=120,
            step_frames=2,
        )
        cursor = next_position
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: game.task_active("Task_HandleSelectionMenuInput"),
        description="ordinary forced-switch Send Out menu",
        max_frames=1_200,
        step_frames=4,
    )
    game.press("A", release_frames=8)  # Send Out.
    game.wait_until(
        lambda: not game.task_active("Task_HandleChooseMonInput")
        and not game.callback_is("CB2_UpdatePartyMenu"),
        description="ordinary forced switch to a healthy party Pokemon",
        max_frames=1_200,
        step_frames=4,
    )


def _weaken_then_catch(game) -> int:
    player_controller = game.address("SetControllerToPlayer")
    partner_controller = game.address("SetControllerToPlayerPartner")
    action_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseAction")
        if player_controller < address < partner_controller
    ]
    move_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseMove")
        if player_controller < address < partner_controller
    ]
    assert len(action_handlers) == len(move_handlers) == 1
    action_handler = action_handlers[0]
    move_handler = move_handlers[0]
    message_handler = game.address("Controller_WaitForString")
    opponent = game.address("gBattleMons") + 140
    for _ in range(2):
        for _ in range(1_500):
            if game.battler_controller_is(action_handler):
                break
            if game.task_active("Task_HandleChooseMonInput") or game.callback_is(
                "CB2_UpdatePartyMenu"
            ):
                _choose_healthy_party_mon(game)
            elif game.battler_controller_is(message_handler):
                game.press("A", release_frames=4)
            else:
                game.press("A", release_frames=2)
        else:
            raise AssertionError("Route 39 wild battle action menu not reached")
        hp = game.read_u16(opponent + 42)
        max_hp = game.read_u16(opponent + 46)
        assert hp > 0 and max_hp > 0
        if hp * 2 <= max_hp:
            break

        game.press("Left", release_frames=4)
        game.press("Up", release_frames=4)
        game.press("A", release_frames=8)  # Fight.
        game.wait_until(
            lambda: game.battler_controller_is(move_handler),
            description="Route 39 wild battle move menu",
            max_frames=1_200,
            step_frames=8,
        )
        battle_mon = game.address("gBattleMons")
        moves_info = game.address("gMovesInfo")
        damaging_moves = []
        for move_index in range(4):
            move = game.read_u16(
                battle_mon + BATTLE_POKEMON_MOVES_OFFSET + move_index * 2
            )
            pp = game.read_u8(battle_mon + BATTLE_POKEMON_PP_OFFSET + move_index)
            power_word = game.read_u16(
                moves_info + move * MOVE_INFO_SIZE + MOVE_INFO_POWER_WORD_OFFSET
            )
            power = power_word >> 7
            if move and pp and power:
                damaging_moves.append((power, move_index))
        assert damaging_moves
        _, move_index = min(damaging_moves)
        game.press("Left", release_frames=2)
        game.press("Up", release_frames=2)
        if move_index & 1:
            game.press("Right", release_frames=2)
        if move_index >= 2:
            game.press("Down", release_frames=2)
        game.press("A", release_frames=8)
    return _catch_with_battle_bag(game)


def _walk_route39_grass_until_battle(game) -> None:
    if game.callback_is("BattleMainCB2"):
        return
    direction = "Left"
    for _ in range(1_200):
        if game.callback_is("BattleMainCB2"):
            return
        x, _ = game.position()
        if x <= 16:
            direction = "Right"
        elif x >= 20:
            direction = "Left"
        game.press(direction, hold_frames=3, release_frames=1)
    raise AssertionError("ordinary Route 39 grass steps did not start a wild battle")


def _choose_eugene_move(game, strategy: dict[str, int]) -> None:
    battle_mon = game.address("gBattleMons")
    species = game.read_u16(battle_mon)
    opponent_species = game.read_u16(battle_mon + 140)
    if species == SPECIES_TREECKO and opponent_species == SPECIES_POLIWHIRL:
        move_index = 0  # Mega Drain is super effective and restores real attrition.
    elif species == SPECIES_TREECKO and opponent_species == SPECIES_TAUROS:
        move_index = 0  # Mega Drain preserves Treecko while damaging Tauros.
    elif species == SPECIES_TORCHIC and opponent_species == SPECIES_TAUROS:
        move_index = 2  # Sand Attack protects the remaining reviewed starters.
        strategy["tauros_sand_attacks"] += 1
    elif species == SPECIES_MUDKIP and opponent_species == SPECIES_TAUROS:
        move_index = 3  # Water Pulse.
    elif species == SPECIES_TORCHIC:
        move_index = 3  # Aerial Ace.
    elif species == SPECIES_MUDKIP:
        move_index = 3  # Water Pulse.
    else:
        move_index = 0
        moves_info = game.address("gMovesInfo")
        for index in range(4):
            move = game.read_u16(battle_mon + BATTLE_POKEMON_MOVES_OFFSET + index * 2)
            pp = game.read_u8(battle_mon + BATTLE_POKEMON_PP_OFFSET + index)
            power_word = game.read_u16(
                moves_info + move * MOVE_INFO_SIZE + MOVE_INFO_POWER_WORD_OFFSET
            )
            if move and pp and power_word >> 7:
                move_index = index
                break

    game.press("Left", release_frames=2)
    game.press("Up", release_frames=2)
    if move_index & 1:
        game.press("Right", release_frames=2)
    if move_index >= 2:
        game.press("Down", release_frames=2)
    game.press("A", release_frames=8)


def _use_super_potion_on_active_starter(game) -> None:
    stock_before = _item_count(game, POCKET_ITEMS, ITEM_SUPER_POTION)
    assert stock_before > 0
    active_party_index = game.read_u8(game.address("gBattlerPartyIndexes"))
    hp_before = game.read_u16(
        game.address("gParties") + active_party_index * 100 + POKEMON_HP_OFFSET
    )

    game.press("Right", release_frames=2)
    game.press("A", release_frames=8)  # Bag.
    game.wait_until(
        lambda: game.task_active("Task_BagMenu_HandleInput"),
        description="Eugene battle Bag input",
        max_frames=1_200,
    )
    bag_position = game.address("gBagPosition")
    for _ in range(20):
        if game.read_u8(bag_position + 5) == MENU_POCKET_ITEMS:
            break
        game.press("Left", release_frames=12)
        game.wait_until(
            lambda: game.task_active("Task_BagMenu_HandleInput"),
            description="Eugene battle Items pocket input",
            max_frames=300,
        )
    else:
        raise AssertionError("ordinary Eugene battle Bag did not reach Items")
    game.step(60)
    for _ in range(POCKET_CAPACITIES[POCKET_ITEMS]):
        game.press("Up", release_frames=3)
    for _ in range(_item_slot(game, POCKET_ITEMS, ITEM_SUPER_POTION)):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=4)
    assert game.read_u16(game.address("gSpecialVar_ItemId")) == ITEM_SUPER_POTION
    game.wait_until(
        lambda: game.task_active("Task_ItemContext_SingleRow"),
        description="Eugene Super Potion context menu",
        max_frames=300,
    )
    game.press("A", release_frames=8)  # Use.
    game.wait_until(
        lambda: game.task_active("Task_HandleChooseMonInput"),
        description="Eugene Super Potion party target",
        max_frames=1_200,
    )
    game.step(60)
    cursor = game.read_u8(game.address("gPartyMenu") + 9)
    assert cursor <= 6
    for _ in range((active_party_index - cursor) % 7):
        game.press("Down", release_frames=4)
    game.press("A", release_frames=8)
    game.advance_until(
        lambda: _item_count(game, POCKET_ITEMS, ITEM_SUPER_POTION) == stock_before - 1,
        description="ordinary Super Potion consumption in Eugene battle",
        max_pulses=1_200,
    )
    party_hp = game.address("gParties") + active_party_index * 100 + POKEMON_HP_OFFSET
    game.advance_until(
        lambda: game.read_u16(game.address("gBattleMons") + 42) > hp_before
        or game.read_u16(party_hp) > hp_before,
        description="Super Potion healing the active starter",
        max_pulses=1_200,
    )


def _defeat_eugene_through_normal_input(game) -> None:
    action_handlers = tuple(
        address | 1 for address in game.symbols.addresses("HandleInputChooseAction")
    )
    move_handlers = tuple(
        address | 1 for address in game.symbols.addresses("HandleInputChooseMove")
    )
    game.move_path((None, 44), (25, None))
    game.advance_until(
        lambda: game.callback_is("BattleMainCB2") or game.position()[1] == 42,
        description="Eugene trainer sight row",
        max_pulses=300,
        button="Up",
    )
    direction = "Left"
    for _ in range(1_200):
        if game.callback_is("BattleMainCB2"):
            break
        if game.controls_locked():
            game.press("A", release_frames=4)
            continue
        x, _ = game.position()
        if x <= 24:
            direction = "Right"
        elif x >= 28:
            direction = "Left"
        game.press(direction, hold_frames=3, release_frames=1)
    else:
        raise AssertionError("ordinary Route 39 movement did not trigger Eugene")

    assert game.read_u32(game.address("gBattleTypeFlags")) & BATTLE_TYPE_TRAINER
    trainer_battle = game.address("gTrainerBattleParameter")
    assert game.read_u16(trainer_battle + 2) == TRAINER_SAILOR_EUGENE_JOHTO

    def eugene_defeated() -> bool:
        defeat_address = game.save_block1() + 0x3CD0 + EUGENE_DEFEAT_BYTE
        return bool(game.read_u8(defeat_address) & EUGENE_DEFEAT_MASK)

    strategy = {"tauros_sand_attacks": 0, "super_potions_used": 0}
    for _ in range(12_000):
        if eugene_defeated():
            break
        party = game.address("gParties")
        party_count = game.read_u8(game.address("gPartiesCount"))
        if party_count and not any(
            game.read_u16(party + index * 100 + POKEMON_HP_OFFSET)
            for index in range(party_count)
        ):
            raise AssertionError("ordinary Eugene battle blacked out the healed party")
        if game.callback_is("CB2_Overworld"):
            raise AssertionError("ordinary Eugene battle returned to the field undefeated")
        controller = game.read_u32(game.address("gBattlerControllerFuncs"))
        if game.task_active("Task_HandleChooseMonInput"):
            _choose_healthy_party_mon(game)
        elif controller in action_handlers:
            battle_mon = game.address("gBattleMons")
            species = game.read_u16(battle_mon)
            opponent_species = game.read_u16(battle_mon + 140)
            hp = game.read_u16(battle_mon + 42)
            max_hp = game.read_u16(battle_mon + 46)
            reviewed_starter = species in (
                SPECIES_TREECKO,
                SPECIES_TORCHIC,
                SPECIES_MUDKIP,
            )
            if (
                opponent_species == SPECIES_TAUROS
                and reviewed_starter
                and hp * 2 <= max_hp
                and strategy["super_potions_used"] < 2
                and _item_count(game, POCKET_ITEMS, ITEM_SUPER_POTION)
            ):
                _use_super_potion_on_active_starter(game)
                strategy["super_potions_used"] += 1
            else:
                game.press("Left", release_frames=4)
                game.press("Up", release_frames=4)
                game.press("A", release_frames=8)
        elif controller in move_handlers:
            _choose_eugene_move(game, strategy)
        else:
            game.press("A", release_frames=2)
    else:
        raise AssertionError("ordinary Fight inputs did not defeat Eugene")
    game.advance_until(
        lambda: game.callback_is("CB2_Overworld") and not game.controls_locked(),
        description="Eugene post-battle field text",
        max_pulses=1_200,
    )
    assert eugene_defeated()

    # The trainer remains in front of the player after his authored battle.
    # Interacting again must show his authored after-text and never rematch.
    game.press("A")
    game.wait_until(
        lambda: game.controls_locked(),
        description="Eugene authored post-battle interaction",
        max_frames=300,
    )
    for _ in range(600):
        assert not game.callback_is("BattleMainCB2")
        if not game.controls_locked():
            break
        game.press("A", release_frames=2)
    else:
        raise AssertionError("Eugene post-battle text did not return field controls")


@pytest.mark.long_journey
def test_one_save_kanto_to_olivine_checkpoint(session_factory):
    document = json.loads(FIXTURE_MANIFEST.read_text())
    save = FIXTURE_MANIFEST.parent / document["fixture"]["file"]
    image = SaveImage.from_path(save)
    assert image.sha256 == document["fixture"]["sha256"]
    assert document["generation"]["postLoadHostWritesAllowed"] is False

    maps = {entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())}
    game = session_factory(battery_save=save)
    _continue(game)
    _assert_reviewed_start(game, document)
    player_identity_baseline = {
        "name": game.read(game.save_block2(), 8),
        "gender": game.read_u8(game.save_block2() + 8),
        "trainer_id": game.read(game.save_block2() + 10, 4),
    }
    original_kanto_pokemon = decode_box_pokemon(
        game.read(game.address("gParties"), 80)
    )
    assert original_kanto_pokemon == document["semanticExpectations"]["party"][
        "pokemon"
    ][0]
    assert game.map_id() == maps["VermilionCity_Mart_Frlg"].map_id

    _buy_battle_supplies(game)

    # Leave the Mart and walk to the Fishing Guru; every transition after the
    # reviewed save boundary is driven by ordinary player controls.
    game.move_path((4, None), (None, 6))
    game.advance_until(
        lambda: game.map_id() == maps["VermilionCity_Frlg"].map_id,
        description="ordinary Vermilion Mart exit",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_path((29, None), (None, 18), (25, None), (None, 8), (9, None), (None, 7))
    game.advance_until(
        lambda: game.map_id() == maps["VermilionCity_House1_Frlg"].map_id,
        description="ordinary Fishing Guru house entrance",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_to(x=4, y=6)
    game.face("Up")
    game.press("A")
    game.advance_until(
        lambda: _item_count(game, POCKET_KEY_ITEMS, ITEM_OLD_ROD) == 1,
        description="Fishing Guru giving the Old Rod",
        max_pulses=600,
    )
    game.advance_until(
        lambda: not game.controls_locked(),
        description="Fishing Guru conversation completion",
        max_pulses=300,
        pulse_frames=8,
    )

    # Checkpoint 1 intentionally continues with the ordinary field fishing,
    # capture, and public ferry interaction below as those controls are proven.
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 8
    assert _item_count(game, POCKET_ITEMS, ITEM_SUPER_POTION) == 2
    assert _item_count(game, POCKET_KEY_ITEMS, ITEM_OLD_ROD) == 1

    # Return to Vermilion's waterfront and use the acquired rod through the
    # ordinary field Bag UI.
    game.move_to(x=4, y=7)
    game.advance_until(
        lambda: game.map_id() == maps["VermilionCity_Frlg"].map_id,
        description="ordinary Fishing Guru house exit",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_path((9, 8), (24, 8), (24, 25))
    game.face("Down")
    _use_old_rod_from_bag(game)
    _fish_until_battle(game)
    kanto_balls_used = _catch_with_battle_bag(game)
    assert game.read_u8(game.address("gPartiesCount")) == 4
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == (
        8 - kanto_balls_used
    )
    caught = decode_box_pokemon(game.read(game.address("gParties") + 3 * 100, 80))
    assert caught is not None
    assert caught["species"] == SPECIES_MAGIKARP
    assert caught["personality"] != 0
    assert caught["otId"] != 0
    assert caught["metLocation"] == MET_LOCATION_VERMILION_CITY
    assert caught["metGame"] == GAME_VERSION_EMERALD
    caught_identity_baseline = (caught["personality"], caught["otId"])

    # Walk around the harbor building to the public sailor, then take both
    # ordinary yes/no interactions into Johto.
    game.move_path((24, 23), (25, 23))
    game.face("Down")
    game.press("A")
    game.advance_until(
        lambda: game.map_id() == maps["VermilionCity_PortInside"].map_id,
        description="public Vermilion ferry terminal entry",
        max_pulses=600,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_to(x=8, y=9)
    game.face("Down")
    game.press("A")
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity_PortInside"].map_id,
        description="ordinary Vermilion-to-Olivine ferry",
        max_pulses=600,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (8, 16)
    assert game.read(game.save_block2(), 8) == player_identity_baseline["name"]
    assert game.read_u8(game.save_block2() + 8) == player_identity_baseline["gender"]
    assert game.read(game.save_block2() + 10, 4) == player_identity_baseline["trainer_id"]
    arrived_catch = decode_box_pokemon(
        game.read(game.address("gParties") + 3 * 100, 80)
    )
    assert arrived_catch is not None
    assert (arrived_catch["personality"], arrived_catch["otId"]) == caught_identity_baseline

    # Leave the terminal and harbor by their ordinary doors, then continue on
    # foot through Olivine toward Route 39.
    game.move_to(x=8, y=10)
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity_PortOutside"].map_id,
        description="ordinary Olivine ferry terminal exit",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_to(x=15, y=0)
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity"].map_id,
        description="ordinary Olivine harbor exit",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)

    # Establish Olivine as the party's checkpoint and restore the party through
    # the ordinary Center service before taking on Route 39.
    game.move_path(
        (None, 39),
        (12, None),
        (21, None),
        (None, 45),
        (15, None),
        (None, 44),
    )
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity_PokemonCenter"].map_id,
        description="ordinary pre-Route-39 Olivine Pokemon Center entrance",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    _heal_at_olivine_nurse(game)
    assert _last_heal_location(game) == (
        maps["OlivineCity"].group,
        maps["OlivineCity"].number,
        -1,
        15,
        44,
    )
    game.move_to(x=7, y=8)
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity"].map_id,
        description="ordinary pre-Route-39 Olivine Pokemon Center exit",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_path(
        (None, 45),
        (21, None),
        (None, 39),
        (15, None),
        (None, 37),
        (13, None),
        (None, 36),
        (12, None),
        (None, 28),
        (16, None),
        (None, 27),
        (17, None),
        (None, 24),
        (18, None),
        (None, 22),
        (19, None),
        (None, 0),
    )
    game.advance_until(
        lambda: game.map_id() == maps["Route39"].map_id,
        description="ordinary Olivine-to-Route-39 walk",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (25, 53)
    game.move_path((None, 44), (20, None))
    game.advance_until(
        lambda: game.callback_is("BattleMainCB2") or game.position()[1] == 43,
        description="Route 39 grass edge",
        max_pulses=60,
        button="Up",
    )
    _walk_route39_grass_until_battle(game)
    route39_stock_before = _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL)
    assert route39_stock_before == 7
    route39_balls_used = _weaken_then_catch(game)
    assert game.read_u8(game.address("gPartiesCount")) == 5
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == (
        route39_stock_before - route39_balls_used
    )
    johto_catch = decode_box_pokemon(
        game.read(game.address("gParties") + 4 * 100, 80)
    )
    assert johto_catch is not None
    assert johto_catch["personality"] != 0
    assert johto_catch["otId"] != 0
    assert johto_catch["metLocation"] == MET_LOCATION_ROUTE_39
    assert johto_catch["metGame"] == GAME_VERSION_EMERALD
    johto_identity_baseline = (johto_catch["personality"], johto_catch["otId"])

    # Capture attrition is real journey state. Return through the ordinary
    # corridor and heal again before taking on Eugene.
    game.move_path((None, 44), (25, None), (None, 53))
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity"].map_id,
        description="ordinary Route-39-to-Olivine return",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (19, 0)
    game.move_path(
        (None, 22),
        (18, None),
        (None, 24),
        (17, None),
        (None, 27),
        (16, None),
        (None, 28),
        (12, None),
        (None, 36),
        (13, None),
        (None, 37),
        (15, None),
        (None, 39),
        (12, None),
        (21, None),
        (None, 45),
        (15, None),
        (None, 44),
    )
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity_PokemonCenter"].map_id,
        description="ordinary Olivine Pokemon Center entrance",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    _heal_at_olivine_nurse(game)
    assert _last_heal_location(game) == (
        maps["OlivineCity"].group,
        maps["OlivineCity"].number,
        -1,
        15,
        44,
    )
    game.move_to(x=7, y=8)
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity"].map_id,
        description="ordinary post-capture Olivine Pokemon Center exit",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    game.move_path(
        (None, 45),
        (21, None),
        (None, 39),
        (15, None),
        (None, 37),
        (13, None),
        (None, 36),
        (12, None),
        (None, 28),
        (16, None),
        (None, 27),
        (17, None),
        (None, 24),
        (18, None),
        (None, 22),
        (19, None),
        (None, 0),
    )
    game.advance_until(
        lambda: game.map_id() == maps["Route39"].map_id,
        description="ordinary healed return to Route 39",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (25, 53)
    _defeat_eugene_through_normal_input(game)

    # Return to Olivine once more and use the city's ordinary PC.
    game.move_path((None, 53), (25, None))
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity"].map_id,
        description="ordinary post-Eugene Route-39-to-Olivine return",
        max_pulses=300,
        button="Down",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.position() == (19, 0)
    game.move_path(
        (None, 22),
        (18, None),
        (None, 24),
        (17, None),
        (None, 27),
        (16, None),
        (None, 28),
        (12, None),
        (None, 36),
        (13, None),
        (None, 37),
        (15, None),
        (None, 39),
        (12, None),
        (21, None),
        (None, 45),
        (15, None),
        (None, 44),
    )
    game.advance_until(
        lambda: game.map_id() == maps["OlivineCity_PokemonCenter"].map_id,
        description="ordinary post-Eugene Olivine Pokemon Center entrance",
        max_pulses=300,
        button="Up",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)

    _heal_at_olivine_nurse(game)
    assert _last_heal_location(game) == (
        maps["OlivineCity"].group,
        maps["OlivineCity"].number,
        -1,
        15,
        44,
    )
    _assert_party_fully_healed(game, expected_count=5)
    task_anchored_kanto_pokemon = decode_box_pokemon(
        game.read(game.address("gParties"), 80)
    )
    assert task_anchored_kanto_pokemon is not None
    assert (
        task_anchored_kanto_pokemon["personality"],
        task_anchored_kanto_pokemon["otId"],
    ) == (original_kanto_pokemon["personality"], original_kanto_pokemon["otId"])
    party = game.address("gParties")
    task_anchored_johto_catch = next(
        decoded
        for index in range(game.read_u8(game.address("gPartiesCount")))
        if (
            decoded := decode_box_pokemon(game.read(party + index * 100, 80))
        )
        is not None
        and (decoded["personality"], decoded["otId"]) == johto_identity_baseline
    )
    assert task_anchored_johto_catch["metLocation"] == MET_LOCATION_ROUTE_39
    assert task_anchored_johto_catch["metGame"] == GAME_VERSION_EMERALD
    _open_storage_from_olivine_console(game)
    _deposit_first_party_mon_in_box_one(game, task_anchored_kanto_pokemon)
    _withdraw_first_box_mon(game, task_anchored_kanto_pokemon)
    _deposit_johto_catch_in_box_one(game, task_anchored_johto_catch)
    assert game.read(game.save_block2(), 8) == player_identity_baseline["name"]
    assert game.read_u8(game.save_block2() + 8) == player_identity_baseline["gender"]
    assert game.read(game.save_block2() + 10, 4) == player_identity_baseline[
        "trainer_id"
    ]
    retained_kanto_pokemon = decode_box_pokemon(
        game.read(game.address("gParties") + 3 * 100, 80)
    )
    assert retained_kanto_pokemon == task_anchored_kanto_pokemon
    retained_kanto_catch = next(
        decoded
        for index in range(game.read_u8(game.address("gPartiesCount")))
        if (
            decoded := decode_box_pokemon(game.read(party + index * 100, 80))
        )
        is not None
        and (decoded["personality"], decoded["otId"]) == caught_identity_baseline
    )
    assert retained_kanto_catch["species"] == SPECIES_MAGIKARP
    assert retained_kanto_catch["metLocation"] == MET_LOCATION_VERMILION_CITY
    assert retained_kanto_catch["metGame"] == GAME_VERSION_EMERALD
    assert _box_pokemon(game, 0, 0) == task_anchored_johto_catch


@pytest.mark.long_journey
def test_same_kanto_save_persists_johto_checkpoint_and_returns(session_factory):
    """Prove the late continuity boundary without replaying stochastic setup.

    Controlled setup is limited to two debug map loads: positioning the reviewed
    Kanto character at the Olivine Center, then at the Olivine ferry terminal.
    The player identity, Kanto party, Olivine heal checkpoint, flash save, cold
    restart, and reverse ferry result are never written by the host.
    """
    document = json.loads(FIXTURE_MANIFEST.read_text())
    fixture = FIXTURE_MANIFEST.parent / document["fixture"]["file"]
    fixture_image = SaveImage.from_path(fixture)
    assert fixture_image.sha256 == document["fixture"]["sha256"]

    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    game = session_factory(battery_save=fixture)
    _continue(game)
    _assert_reviewed_start(game, document)

    player_identity = game.read(game.save_block2(), 14)
    assert game.map_id() == maps["VermilionCity_Mart_Frlg"].map_id

    # Controlled travel setup. The meaningful Johto fact is established below
    # by the production nurse script, rather than by the host map-load request.
    olivine_center = maps["OlivineCity_PokemonCenter"]
    olivine_city = maps["OlivineCity"]
    _controlled_position(game, olivine_center, (7, 4), 0xF2400001)
    _heal_at_olivine_nurse(game)
    johto_checkpoint = (
        olivine_city.group,
        olivine_city.number,
        -1,
        15,
        44,
    )
    assert _last_heal_location(game) == johto_checkpoint
    kanto_party = [
        game.read(game.address("gParties") + index * 100, 80)
        for index in range(game.read_u8(game.address("gPartiesCount")))
    ]

    # This is the sole flash save made by this continuation proof.
    counter_before = SaveImage.from_path(game.battery_path).active_slot.counter
    saved = save_from_start_menu(game)
    assert is_strictly_newer_save_counter(saved.active_slot.counter, counter_before)
    cold_restart_and_continue(game)

    assert game.map_id() == olivine_center.map_id
    assert game.read(game.save_block2(), 14) == player_identity
    assert [
        game.read(game.address("gParties") + index * 100, 80)
        for index in range(game.read_u8(game.address("gPartiesCount")))
    ] == kanto_party
    assert _last_heal_location(game) == johto_checkpoint

    # Controlled positioning removes repeated corridor setup only. The reverse
    # ferry interaction and resulting Kanto residency execute in production.
    olivine_terminal = maps["OlivineCity_PortInside"]
    vermilion_terminal = maps["VermilionCity_PortInside"]
    _controlled_position(game, olivine_terminal, (8, 16), 0xF2400002)
    game.face("Down")
    game.press("A")
    game.advance_until(
        lambda: game.map_id() == vermilion_terminal.map_id,
        description="production Olivine-to-Vermilion return ferry",
        max_pulses=600,
        button="A",
    )
    game.wait_for_controls_unlocked(max_frames=1_200)

    assert vermilion_terminal.region == "REGION_KANTO"
    assert game.position() == (8, 9)
    assert game.read(game.save_block2(), 14) == player_identity
    assert [
        game.read(game.address("gParties") + index * 100, 80)
        for index in range(game.read_u8(game.address("gPartiesCount")))
    ] == kanto_party
    assert _last_heal_location(game) == johto_checkpoint
