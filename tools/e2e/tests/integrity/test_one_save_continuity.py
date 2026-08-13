from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.e2e.save_file import SaveImage, decode_box_pokemon
from tools.e2e.tests.integrity.manifest import integrity_manifest_path, load_manifest_maps


FIXTURE_MANIFEST = Path(__file__).parents[2] / "fixtures" / "kanto_continuity_start.json"
ITEM_POKE_BALL = 1
ITEM_OLD_ROD = 709
SPECIES_MAGIKARP = 129
MET_LOCATION_VERMILION_CITY = 93
GAME_VERSION_EMERALD = 3
MENU_ACTION_BAG = 2
MENU_POCKET_KEY_ITEMS = 4
MENU_POCKET_POKE_BALLS = 1
POCKET_KEY_ITEMS = 1
POCKET_POKE_BALLS = 2
POCKET_OFFSETS = (0x560, 0x5D8, 0x650)
POCKET_CAPACITIES = (30, 30, 16)


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


def _buy_one_poke_ball(game) -> None:
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
    game.press("A", release_frames=8)  # Buy the default quantity of one.
    for _ in range(600):
        if _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 1:
            break
        game.press("A", release_frames=2)
    else:
        raise AssertionError("ordinary Vermilion Mart purchase did not add a Poke Ball")
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
    for _ in range(20):
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


def _catch_with_battle_bag(game) -> None:
    action_handlers = tuple(
        address | 1 for address in game.symbols.addresses("HandleInputChooseAction")
    )
    game.advance_until(
        lambda: game.read_u32(game.address("gBattlerControllerFuncs"))
        in action_handlers,
        description="fished wild battle action menu",
        max_pulses=1_200,
        button="B",
    )
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
        raise AssertionError("ordinary battle Bag navigation did not reach Poke Balls")
    game.step(60)
    for _ in range(POCKET_CAPACITIES[POCKET_POKE_BALLS]):
        game.press("Up", release_frames=3)
    game.press("A", release_frames=4)
    assert game.read_u16(game.address("gSpecialVar_ItemId")) == ITEM_POKE_BALL
    game.wait_until(
        lambda: game.task_active("Task_ItemContext_SingleRow"),
        description="battle Poke Ball context menu",
        max_frames=300,
    )
    game.press("A", release_frames=8)
    game.advance_until(
        lambda: game.callback_is("CB2_Overworld"),
        description="ordinary Poke Ball capture",
        max_pulses=2_400,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)


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
    assert game.map_id() == maps["VermilionCity_Mart_Frlg"].map_id

    _buy_one_poke_ball(game)

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
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 1
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
    _catch_with_battle_bag(game)
    assert game.read_u8(game.address("gPartiesCount")) == 4
    assert _item_count(game, POCKET_POKE_BALLS, ITEM_POKE_BALL) == 0
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
