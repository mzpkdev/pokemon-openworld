from __future__ import annotations

import hashlib

import pytest

from tools.e2e.save_journey import (
    SaveScenarioRequest,
    representative_runtime_semantics,
    run_save_scenario,
)
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
FERRY_X = 8
FERRY_Y = 16
POKEMON_STORAGE_SIZE = 0x83D0
PLAYER_IDENTITY_SIZE = 0x0E
POKEDEX_OFFSET = 0x18
POKEDEX_SIZE = 0x78

# These ranges are the established serialized SaveBlock1 ABI documented in
# include/global.h and frozen by tools/integrity/save_contract.json.
MONEY_OFFSET = 0x490
MONEY_SIZE = 4
PC_ITEMS_OFFSET = 0x498
PC_ITEMS_SIZE = 0x560 - PC_ITEMS_OFFSET
BAG_OFFSET = 0x560
BAG_SLOT_SIZE = 4
BAG_SLOT_COUNT = 30 + 30 + 16 + 64 + 46
LAST_HEAL_LOCATION_OFFSET = 0x1C
WARP_DATA_SIZE = 8
FLAGS_AND_VARS_OFFSET = 0x1270
FLAGS_AND_VARS_SIZE = 0x159C - FLAGS_AND_VARS_OFFSET

SPECIES_PIKACHU = 25
SPECIES_DITTO = 132
SPECIES_EEVEE = 133
SPECIES_SEEDOT = 273
ITEM_NUGGET = 135
HEAL_LOCATION_LITTLEROOT_BRENDAN_2F = 1
TRAINER_RICKY_1 = 64

FERRY_LEGS = (
    ("VermilionCity_PortInside", "OlivineCity_PortInside", 0xF3300001),
    ("OlivineCity_PortInside", "VermilionCity_PortInside", 0xF3300002),
)


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _read_chunked(game, address: int, size: int) -> bytes:
    return b"".join(
        game.read(address + offset, min(512, size - offset))
        for offset in range(0, size, 512)
    )


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_bag(game, block1: int, encryption_key: int) -> tuple[tuple[int, int], ...]:
    slots = []
    for index in range(BAG_SLOT_COUNT):
        slot = game.read(block1 + BAG_OFFSET + index * BAG_SLOT_SIZE, BAG_SLOT_SIZE)
        item = int.from_bytes(slot[:2], "little")
        quantity = int.from_bytes(slot[2:], "little") ^ (encryption_key & 0xFFFF)
        slots.append((item, quantity))
    return tuple(slots)


def _continuity_snapshot(game, scenario_result) -> dict[str, object]:
    block1 = game.save_block1()
    block2 = game.save_block2()
    encryption_key = game.read_u32(block2 + 0xAC)
    representative = representative_runtime_semantics(game, scenario_result)
    return {
        # This established semantic view covers the live party, boxed Pokémon,
        # daycare, reward inventory, healing checkpoint, trainer flags, and
        # facility/campaign session state.
        "representativeState": representative,
        "playerIdentity": game.read(block2, PLAYER_IDENTITY_SIZE),
        "pokedex": _digest(game.read(block2 + POKEDEX_OFFSET, POKEDEX_SIZE)),
        # Map transitions deliberately rotate the save encryption key. Compare
        # canonical values, not ciphertext that must change during travel.
        "money": int.from_bytes(
            game.read(block1 + MONEY_OFFSET, MONEY_SIZE), "little"
        )
        ^ encryption_key,
        "pcItems": _digest(game.read(block1 + PC_ITEMS_OFFSET, PC_ITEMS_SIZE)),
        "bag": _canonical_bag(game, block1, encryption_key),
        "pokemonStorage": _digest(
            _read_chunked(
                game, game.pointer("gPokemonStoragePtr"), POKEMON_STORAGE_SIZE
            )
        ),
        "lastHealLocation": game.read(
            block1 + LAST_HEAL_LOCATION_OFFSET, WARP_DATA_SIZE
        ),
        # The complete persistent flag/variable domains include campaign and
        # regional facts. Comparing the full ranges prevents a travel helper
        # from hiding a narrowly targeted story mutation.
        "campaignAndRegionalFacts": _digest(
            _read_chunked(
                game, block1 + FLAGS_AND_VARS_OFFSET, FLAGS_AND_VARS_SIZE
            )
        ),
    }


def _populate_continuity_state(game):
    return run_save_scenario(
        game,
        SaveScenarioRequest(
            request_id=0x46455252,
            party_species=SPECIES_PIKACHU,
            box_species=SPECIES_EEVEE,
            daycare_species_1=SPECIES_DITTO,
            daycare_species_2=SPECIES_EEVEE,
            trade_species=SPECIES_SEEDOT,
            reward_item=ITEM_NUGGET,
            checkpoint_id=HEAL_LOCATION_LITTLEROOT_BRENDAN_2F,
            level=20,
            facility_id=0,
            facility_level_mode=0,
            trainer_id=TRAINER_RICKY_1,
        ),
    )


def _load_source(game, entry, request_id: int) -> None:
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=FERRY_X,
            y=FERRY_Y,
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    assert game.position() == (FERRY_X, FERRY_Y)
    game.wait_for_controls_unlocked(max_frames=1_200)


@pytest.mark.parametrize(
    ("source_name", "destination_name", "request_id"), FERRY_LEGS
)
def test_ferry_leg_preserves_state_and_returns_control(
    integrity_game, source_name, destination_name, request_id
):
    maps = {
        entry.name: entry
        for entry in load_manifest_maps(integrity_manifest_path())
    }
    source = maps[source_name]
    destination = maps[destination_name]

    _settle_overworld(integrity_game)
    scenario_result = _populate_continuity_state(integrity_game)
    _load_source(integrity_game, source, request_id)
    before = _continuity_snapshot(integrity_game, scenario_result)

    integrity_game.face("Down")
    integrity_game.press("A")
    integrity_game.wait_until(
        lambda: (
            integrity_game.controls_locked()
            and integrity_game.read_u16(
                integrity_game.address("gSpecialVar_LastTalked")
            )
            == SAILOR_LOCAL_ID
        ),
        description=f"reachable sailor interaction in {source_name}",
        max_frames=120,
    )
    integrity_game.advance_until(
        lambda: integrity_game.map_id() == destination.map_id,
        description=f"{source_name} ferry arrival in {destination_name}",
        max_pulses=600,
        button="A",
    )
    integrity_game.wait_until(
        lambda: (
            integrity_game.callback_is("CB2_Overworld")
            and not integrity_game.controls_locked()
            and integrity_game.script_status() == SCRIPT_IDLE
            and integrity_game.movement_idle()
        ),
        description=f"{destination_name} fully field-ready ferry arrival",
        max_frames=1_800,
        step_frames=2,
    )

    assert integrity_game.map_id() == destination.map_id
    assert integrity_game.position() == (FERRY_X, FERRY_Y)
    assert integrity_game.callback_is("CB2_Overworld")
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert integrity_game.movement_idle()
    assert _continuity_snapshot(integrity_game, scenario_result) == before
