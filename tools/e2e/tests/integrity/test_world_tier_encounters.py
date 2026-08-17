from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import struct

import pytest

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


FIXTURE_MANIFEST = (
    Path(__file__).parents[2] / "fixtures" / "kanto_continuity_start.json"
)
WILD_AREA_WATER = 1
WILD_ENCOUNTER_FISHING_ROD_NONE = 0xFF
SPECIES_TENTACOOL = 72
TRAINER_ROXANNE_1 = 265

# Persistent public binding consumed by TrainerRating_Get.
FLAG_REGIONAL_FACT_HOENN_STONE_BADGE = 32

PROBE_REQUEST_SIZE = 12
PROBE_REQUEST_STATUS_OFFSET = 11
PROBE_RESULT_SIZE = 24
VERMILION_COORDINATES = (24, 25)


class ProbeStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    SUCCESS = 2
    ERROR = 3


@dataclass(frozen=True)
class EncounterProbeResult:
    request_id: int
    header_id: int
    entry_index: int
    entry_count: int
    total_weight: int
    species: int
    weight: int
    area: int
    fishing_rod: int
    trainer_rating: int
    reserved: int
    min_level: int
    max_level: int
    error: int
    status: ProbeStatus


def _continue(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("reviewed continuity fixture did not Continue")


def _controlled_position(game, entry, coordinates, request_id: int) -> None:
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


def _probe_encounter(
    game,
    *,
    request_id: int,
    area: int,
    fishing_rod: int,
    entry_index: int,
) -> EncounterProbeResult:
    request = game.address("gWildEncounterProbeRequest")
    result = game.address("gWildEncounterProbeResult")
    game.pause()
    game.write(
        result,
        struct.pack(
            "<I6H8B",
            request_id ^ 0xFFFFFFFF,
            0,
            entry_index,
            0,
            0,
            0,
            0,
            area,
            fishing_rod,
            0,
            0,
            0,
            0,
            0,
            ProbeStatus.IDLE,
        ),
    )
    game.write(
        request,
        struct.pack(
            "<IH6B",
            request_id,
            entry_index,
            area,
            fishing_rod,
            0,
            0,
            0,
            ProbeStatus.IDLE,
        ),
    )
    game.write_u8(request + PROBE_REQUEST_STATUS_OFFSET, ProbeStatus.PENDING)
    game.resume()
    game.step()

    for _ in range(120):
        payload = game.read(result, PROBE_RESULT_SIZE)
        unpacked = struct.unpack("<I6H8B", payload)
        status = ProbeStatus(unpacked[-1])
        if unpacked[0] == request_id and status in (
            ProbeStatus.SUCCESS,
            ProbeStatus.ERROR,
        ):
            resolved = EncounterProbeResult(*unpacked[:-1], status)
            assert resolved.status is ProbeStatus.SUCCESS, (
                f"encounter probe {request_id:#x} failed with error {resolved.error}"
            )
            assert resolved.entry_index == entry_index
            assert resolved.area == area
            assert resolved.fishing_rod == fishing_rod
            return resolved
        game.step()
    raise AssertionError(f"encounter probe {request_id:#x} timed out")


def _instant_win_real_roxanne_battle(game) -> None:
    game.face("Up")
    game.press("A")
    game.advance_until(
        lambda: game.callback_is("BattleMainCB2"),
        description="real Roxanne NPC battle",
        max_pulses=1_500,
        button="A",
    )
    # Packed TrainerBattleParameter stores opponentA after mode and local-id.
    trainer_battle_parameter = game.address("gTrainerBattleParameter")
    assert game.read_u16(trainer_battle_parameter + 2) == TRAINER_ROXANNE_1

    player_controller = game.address("SetControllerToPlayer")
    partner_controller = game.address("SetControllerToPlayerPartner")
    action_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseAction")
        if player_controller < address < partner_controller
    ]
    assert len(action_handlers) == 1
    game.advance_until(
        lambda: game.battler_controller_is(action_handlers[0]),
        description="Roxanne battle action menu",
        max_pulses=1_500,
        button="B",
    )

    game.advance_until(
        lambda: game.callback_is("CB2_BattleDebugMenu"),
        description="battle debug menu after Roxanne battle start",
        max_pulses=600,
        button="Select",
    )
    game.wait_until(
        lambda: game.task_active("Task_DebugMenuProcessInput"),
        description="battle debug menu input",
        max_frames=600,
        step_frames=2,
    )
    for _ in range(16):
        game.press("Down")
    game.press("A")

    game.advance_until(
        lambda: game.read_flag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE),
        description="production Roxanne victory setting the Stone Badge fact",
        max_pulses=1_800,
        button="A",
    )
    game.advance_until(
        lambda: game.callback_is("CB2_Overworld") and not game.controls_locked(),
        description="Roxanne post-battle script completion",
        max_pulses=1_200,
        button="A",
    )


@pytest.mark.long_journey
def test_one_save_roxanne_updates_trainer_rating_without_rewriting_raw_profile(
    session_factory,
):
    document = json.loads(FIXTURE_MANIFEST.read_text())
    fixture = FIXTURE_MANIFEST.parent / document["fixture"]["file"]
    assert (
        hashlib.sha256(fixture.read_bytes()).hexdigest()
        == document["fixture"]["sha256"]
    )
    assert document["generation"]["postLoadHostWritesAllowed"] is False

    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    game = session_factory(battery_save=fixture)
    _continue(game)

    # The reviewed Kanto cheat-start save carries legacy badge slots. They are
    # not Trainer Rating sources.
    badge_flags = game.address("gBadgeFlags")
    legacy_badges = [game.read_u16(badge_flags + index * 2) for index in range(8)]
    assert all(game.read_flag(flag) for flag in legacy_badges)
    assert not game.read_flag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE)

    vermilion = maps["VermilionCity_Frlg"]
    _controlled_position(game, vermilion, VERMILION_COORDINATES, 0xE2900001)
    before_roxanne = _probe_encounter(
        game,
        request_id=0xE2900010,
        area=WILD_AREA_WATER,
        fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
        entry_index=0,
    )
    assert before_roxanne.trainer_rating == 0
    assert before_roxanne.entry_count > 0
    assert before_roxanne.total_weight > 0
    assert before_roxanne.species == SPECIES_TENTACOOL
    assert before_roxanne.weight > 0
    assert (before_roxanne.min_level, before_roxanne.max_level) == (4, 8)

    rustboro_gym = maps["RustboroCity_Gym"]
    _controlled_position(game, rustboro_gym, (5, 3), 0xE2900002)
    assert not game.read_flag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE)
    _instant_win_real_roxanne_battle(game)
    assert game.read_flag(FLAG_REGIONAL_FACT_HOENN_STONE_BADGE)

    _controlled_position(game, vermilion, VERMILION_COORDINATES, 0xE2900003)
    after_roxanne = _probe_encounter(
        game,
        request_id=0xE2900011,
        area=WILD_AREA_WATER,
        fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
        entry_index=0,
    )
    assert after_roxanne.trainer_rating == 3
    assert (
        after_roxanne.header_id,
        after_roxanne.entry_count,
        after_roxanne.total_weight,
        after_roxanne.species,
        after_roxanne.weight,
    ) == (
        before_roxanne.header_id,
        before_roxanne.entry_count,
        before_roxanne.total_weight,
        before_roxanne.species,
        before_roxanne.weight,
    )
    assert (after_roxanne.min_level, after_roxanne.max_level) == (4, 8)
