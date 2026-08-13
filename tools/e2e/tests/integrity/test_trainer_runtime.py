from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from tools.e2e.save_file import TRAINER_DEFEATED_OFFSET, TRAINER_DEFEATED_SIZE
from tools.e2e.save_journey import (
    cold_restart_and_continue,
    save_from_start_menu,
)
from tools.e2e.skyemu import (
    SAVE_BLOCK1_FLAGS_OFFSET,
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)
from tools.e2e.trainer_battle_journey import (
    BATTLE_TYPE_TRAINER,
    MOVE_WATER_SPOUT,
    TrainerBattleScenarioRequest,
    TrainerDefeatStorage,
    TrainerRematchBindingKind,
    disable_battle_animations_through_options,
    heal_party_through_debug_menu,
    run_ordinary_trainer_battle,
    set_battle_party_through_debug_menu,
)


TRAINER_CALVIN_1 = 318
TRAINER_FRLG_YOUNGSTER_BEN = 858
TRAINER_FRLG_RUIN_MANIAC_LAWSON = 1345
TRAINER_YOUNGSTER_SAMUEL_JOHTO = 1481
FLAG_DEFEATED_CALVIN_1 = 0x63E

SPECIES_RATTATA = 19
SPECIES_SPEAROW = 21
SPECIES_EKANS = 23
SPECIES_SANDSHREW = 27
SPECIES_GRAVELER = 75
SPECIES_ONIX = 95
SPECIES_MAROWAK = 105
SPECIES_TEDDIURSA = 216
SPECIES_POOCHYENA = 261

STATE_VECTORS = ("FFFF", "TFFF", "TTFF", "TTTF", "TTTT")
SAMUEL_LOCAL_ID = 1
MAP_OFFSET = 7
SAMUEL_AFTER_TEXT = bytes.fromhex(
    "c3 b4 e1 00 db e3 dd e2 db 00 e8 e3 00 e8 e6 d5 dd e2 00 "
    "d9 ea d9 e2 00 dc d5 e6 d8 d9 e6 ad fb bb da e8 d9 e6 00 "
    "d5 e0 e0 b8 00 c3 b4 e1 00 e8 e6 ed dd e2 db 00 e8 e3 00 "
    "d6 d9 d7 e3 e1 d9 fe d5 00 c1 d3 c7 00 c6 bf bb be bf cc "
    "ad ff"
)


@dataclass(frozen=True)
class TrainerOracle:
    key: str
    trainer_id: int
    party: tuple[tuple[int, int], ...]
    storage: TrainerDefeatStorage
    defeat_id: int
    defeat_bit: int
    rematch_kind: TrainerRematchBindingKind
    rematch_index: int | None
    rematch_stages: tuple[int | None, ...]


ORACLES = (
    TrainerOracle(
        key="hoenn-calvin",
        trainer_id=TRAINER_CALVIN_1,
        party=((SPECIES_POOCHYENA, 5),),
        storage=TrainerDefeatStorage.FLAG,
        defeat_id=FLAG_DEFEATED_CALVIN_1,
        defeat_bit=0,
        rematch_kind=TrainerRematchBindingKind.MATCH_CALL,
        rematch_index=34,
        rematch_stages=(None,) * 6,
    ),
    TrainerOracle(
        key="frlg-youngster-ben",
        trainer_id=TRAINER_FRLG_YOUNGSTER_BEN,
        party=((SPECIES_RATTATA, 11), (SPECIES_EKANS, 11)),
        storage=TrainerDefeatStorage.BITMAP,
        defeat_id=0,
        defeat_bit=0,
        rematch_kind=TrainerRematchBindingKind.CHAIN,
        rematch_index=0,
        rematch_stages=(858, 870, 870, 1241, 1242, None),
    ),
    TrainerOracle(
        key="sevii-lawson",
        trainer_id=TRAINER_FRLG_RUIN_MANIAC_LAWSON,
        party=((SPECIES_ONIX, 47), (SPECIES_GRAVELER, 48), (SPECIES_MAROWAK, 49)),
        storage=TrainerDefeatStorage.BITMAP,
        defeat_id=60,
        defeat_bit=7,
        rematch_kind=TrainerRematchBindingKind.NONE,
        rematch_index=None,
        rematch_stages=(None,) * 6,
    ),
    TrainerOracle(
        key="johto-samuel",
        trainer_id=TRAINER_YOUNGSTER_SAMUEL_JOHTO,
        party=((SPECIES_TEDDIURSA, 12), (SPECIES_SANDSHREW, 10), (SPECIES_SPEAROW, 12)),
        storage=TrainerDefeatStorage.BITMAP,
        defeat_id=77,
        defeat_bit=7,
        rematch_kind=TrainerRematchBindingKind.NONE,
        rematch_index=None,
        rematch_stages=(None,) * 6,
    ),
)


def _quickstart(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach the overworld")


def _bitmap(game) -> bytes:
    return game.read(
        game.save_block1() + TRAINER_DEFEATED_OFFSET,
        TRAINER_DEFEATED_SIZE,
    )


def _state_vector(game) -> str:
    bitmap = _bitmap(game)
    states = (
        game.read_flag(FLAG_DEFEATED_CALVIN_1),
        bool(bitmap[0] & 0x01),
        bool(bitmap[60] & 0x80),
        bool(bitmap[77] & 0x80),
    )
    return "".join("T" if state else "F" for state in states)


def _expected_bitmap(count: int) -> bytes:
    expected = bytearray(TRAINER_DEFEATED_SIZE)
    if count >= 2:
        expected[0] = 0x01
    if count >= 3:
        expected[60] = 0x80
    if count >= 4:
        expected[77] = 0x80
    return bytes(expected)


def _saved_calvin_flag(save_block1: bytes) -> bool:
    byte = save_block1[SAVE_BLOCK1_FLAGS_OFFSET + FLAG_DEFEATED_CALVIN_1 // 8]
    return bool(byte & (1 << (FLAG_DEFEATED_CALVIN_1 % 8)))


def _evidence_path(pytest_request) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", pytest_request.node.nodeid)
    output = Path(os.environ["E2E_RESULTS"]) / os.environ["E2E_SUITE"] / safe_name
    output.mkdir(parents=True, exist_ok=True)
    return output / "trainer-runtime.json"


def _write_evidence(path: Path, evidence: dict) -> None:
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def _result_evidence(oracle, ready, finished) -> dict:
    return {
        "key": oracle.key,
        "requestId": f"0x{ready.request_id:08x}",
        "trainerId": ready.trainer_id,
        "ordinaryBattle": {
            "callback": "BattleMainCB2",
            "savedEndCallback": {
                "symbol": "CB2_EndTrainerBattle",
                "address": f"0x{ready.end_callback:08x}",
            },
            "battleTypeFlags": f"0x{ready.battle_type_flags:08x}",
            "expectedBattleTypeFlags": f"0x{BATTLE_TYPE_TRAINER:08x}",
            "opponentA": ready.opponent_a,
            "opponentB": ready.opponent_b,
            "isDebugBattle": ready.is_debug_battle,
        },
        "authoredParty": [
            {"species": species, "level": level}
            for species, level in ready.authored_party
        ],
        "difficulty": ready.difficulty,
        "rematch": {
            "kind": ready.rematch_kind.name,
            "index": None
            if ready.rematch_kind is TrainerRematchBindingKind.NONE
            else ready.rematch_index,
            "resolvedStages": list(ready.resolved_rematch_stages),
        },
        "defeatBinding": {
            "storage": ready.defeat_storage.name,
            "id": ready.defeat_id,
            "bit": ready.defeat_bit,
        },
        "victory": {
            "hostInput": "ordinary Options, Fight/move, and party selections",
            "battleOutcome": finished.battle_outcome,
            "defeatedBefore": finished.defeated_before,
            "defeatedAfter": finished.defeated_after,
            "terminalPhase": finished.phase.name,
            "terminalStatus": finished.status.name,
        },
    }


def _assert_overworld_without_battle(game) -> None:
    assert not game.task_active("Task_BattleStart")
    assert not game.callback_is("CB2_InitBattle")
    assert not game.callback_is("BattleMainCB2")
    assert game.callback_is("CB2_Overworld")


def _step_overworld_without_battle(game, frames: int = 1) -> None:
    for _ in range(frames):
        game.step()
        _assert_overworld_without_battle(game)


def _press_overworld_without_battle(
    game, button: str, *, hold_frames: int = 1, release_frames: int = 1
) -> None:
    game.set_buttons(**{button: True})
    try:
        _step_overworld_without_battle(game, hold_frames)
    finally:
        game.set_buttons(**{button: False})
    _step_overworld_without_battle(game, release_frames)


def _wait_for_unlocked_overworld_without_battle(game, max_frames: int) -> None:
    for _ in range(max_frames + 1):
        _assert_overworld_without_battle(game)
        if not game.controls_locked() and game.script_status() == 2:
            return
        _step_overworld_without_battle(game)
    raise AssertionError(f"field controls did not unlock in {max_frames} frames")


def _samuel_object(game, map_group: int, map_num: int) -> tuple[int, int, int]:
    objects = game.address("gObjectEvents")
    matches = []
    for object_id in range(16):
        obj = objects + object_id * 0x24
        if not game.read_u8(obj) & 1:
            continue
        if (
            game.read_u8(obj + 8) == SAMUEL_LOCAL_ID
            and game.read_u8(obj + 9) == map_num
            and game.read_u8(obj + 10) == map_group
        ):
            matches.append(
                (
                    object_id,
                    game.read_u16(obj + 0x10) - MAP_OFFSET,
                    game.read_u16(obj + 0x12) - MAP_OFFSET,
                )
            )
    assert len(matches) == 1, f"expected one live Samuel object, found {matches}"
    return matches[0]


@pytest.mark.long_journey
def test_regional_trainers_share_production_battle_and_persistence(
    integrity_game, request
):
    evidence_path = _evidence_path(request)
    evidence = {
        "schemaVersion": 1,
        "protocol": {
            "abiVersion": 1,
            "requestSymbol": "gTrainerBattleScenarioRequest",
            "resultSymbol": "gTrainerBattleScenarioResult",
            "victoryCommandExposed": False,
        },
        "artifacts": {
            "romSha256": hashlib.sha256(
                Path(os.environ["E2E_ROM"]).read_bytes()
            ).hexdigest(),
            "symbolsSha256": hashlib.sha256(
                Path(os.environ["E2E_SYMS"]).read_bytes()
            ).hexdigest(),
        },
        "expectedStateVectors": list(STATE_VECTORS),
        "observedStateVectors": [],
        "battles": [],
        "save": None,
        "coldReload": None,
    }
    _write_evidence(evidence_path, evidence)

    _quickstart(integrity_game)
    disable_battle_animations_through_options(integrity_game)
    set_battle_party_through_debug_menu(integrity_game)
    assert _bitmap(integrity_game) == _expected_bitmap(0)
    assert _state_vector(integrity_game) == STATE_VECTORS[0]
    evidence["observedStateVectors"].append(STATE_VECTORS[0])
    _write_evidence(evidence_path, evidence)

    for index, oracle in enumerate(ORACLES, start=1):
        ready, finished = run_ordinary_trainer_battle(
            integrity_game,
            TrainerBattleScenarioRequest(
                request_id=0xD6000000 | index,
                trainer_id=oracle.trainer_id,
            ),
            move_id=MOVE_WATER_SPOUT,
        )
        assert ready.trainer_id == oracle.trainer_id
        assert ready.authored_party == oracle.party
        assert ready.defeat_storage is oracle.storage
        assert ready.defeat_id == oracle.defeat_id
        assert ready.defeat_bit == oracle.defeat_bit
        assert ready.rematch_kind is oracle.rematch_kind
        if oracle.rematch_index is not None:
            assert ready.rematch_index == oracle.rematch_index
        assert ready.resolved_rematch_stages == oracle.rematch_stages
        assert not finished.defeated_before
        assert finished.defeated_after

        expected_state = STATE_VECTORS[index]
        assert _state_vector(integrity_game) == expected_state
        assert _bitmap(integrity_game) == _expected_bitmap(index)
        evidence["observedStateVectors"].append(expected_state)
        evidence["battles"].append(_result_evidence(oracle, ready, finished))
        _write_evidence(evidence_path, evidence)
        if index < len(ORACLES):
            heal_party_through_debug_menu(integrity_game)

    saved = save_from_start_menu(integrity_game)
    saved_bitmap = saved.active_slot.trainer_defeated_bitmap
    assert saved_bitmap == _expected_bitmap(4)
    assert _saved_calvin_flag(saved.active_slot.save_block1)
    evidence["save"] = {
        "path": integrity_game.battery_path.name,
        "sha256": hashlib.sha256(saved.data).hexdigest(),
        "activeSlot": saved.active_slot.physical_index,
        "saveCounter": saved.active_slot.counter,
        "calvinFlag": f"0x{FLAG_DEFEATED_CALVIN_1:03x}",
        "calvinFlagSet": True,
        "trainerBitmapOffset": f"0x{TRAINER_DEFEATED_OFFSET:04x}",
        "trainerBitmapSize": TRAINER_DEFEATED_SIZE,
        "trainerBitmapHex": saved_bitmap.hex(),
        "nonzeroBitmapBytes": {"0": "01", "60": "80", "77": "80"},
    }
    _write_evidence(evidence_path, evidence)

    cold_restart_and_continue(integrity_game)
    reloaded_bitmap = _bitmap(integrity_game)
    assert _state_vector(integrity_game) == STATE_VECTORS[-1]
    assert reloaded_bitmap == _expected_bitmap(4)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    route34 = maps["Route34"]
    load_result = integrity_game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=0xD6000034,
            map_group=route34.group,
            map_num=route34.number,
            x=34,
            y=60,
        ),
        max_frames=1_800,
    )
    assert load_result.status is IntegrityLoadStatus.SUCCESS
    assert load_result.phase is IntegrityLoadPhase.FIELD_READY
    assert load_result.error is IntegrityLoadError.NONE
    assert integrity_game.map_id() == route34.map_id
    _wait_for_unlocked_overworld_without_battle(integrity_game, max_frames=1_200)
    assert integrity_game.position() == (34, 60)
    samuel_object_id, samuel_x, samuel_y = _samuel_object(
        integrity_game, route34.group, route34.number
    )
    assert (samuel_x, samuel_y) == (34, 59)

    _press_overworld_without_battle(
        integrity_game, "Up", hold_frames=2, release_frames=1
    )
    assert integrity_game.position() == (34, 60)
    assert integrity_game.facing_direction() == 2
    _press_overworld_without_battle(integrity_game, "A")

    for _ in range(1_200):
        _assert_overworld_without_battle(integrity_game)
        if integrity_game.task_active("Task_DrawFieldMessage"):
            break
        _step_overworld_without_battle(integrity_game)
    else:
        raise AssertionError("Samuel interaction did not draw a field message")
    observed_after_text = integrity_game.read(
        integrity_game.address("gStringVar4"), len(SAMUEL_AFTER_TEXT)
    )
    assert observed_after_text == SAMUEL_AFTER_TEXT

    for _ in range(600):
        _assert_overworld_without_battle(integrity_game)
        if (
            not integrity_game.task_active("Task_DrawFieldMessage")
            and not integrity_game.controls_locked()
            and integrity_game.script_status() == 2
        ):
            break
        _press_overworld_without_battle(
            integrity_game, "A", hold_frames=1, release_frames=2
        )
    else:
        raise AssertionError(
            "Samuel after-battle dialogue did not return field control"
        )

    assert _state_vector(integrity_game) == STATE_VECTORS[-1]
    assert _bitmap(integrity_game) == _expected_bitmap(4)
    evidence["coldReload"] = {
        "oldProcessExited": True,
        "stateVector": _state_vector(integrity_game),
        "calvinFlagSet": integrity_game.read_flag(FLAG_DEFEATED_CALVIN_1),
        "trainerBitmapHex": reloaded_bitmap.hex(),
        "independentDefeatBitsRetained": True,
        "samuelInteraction": {
            "map": "Route34",
            "mapId": {"group": route34.group, "number": route34.number},
            "playerPosition": {"x": 34, "y": 60},
            "object": {
                "localId": SAMUEL_LOCAL_ID,
                "objectEventId": samuel_object_id,
                "position": {"x": samuel_x, "y": samuel_y},
            },
            "input": ["Up", "A"],
            "fieldMessageTask": "Task_DrawFieldMessage",
            "authoredText": (
                "I'm going to train even harder.\\p"
                "After all, I'm trying to become\\na GYM LEADER.$"
            ),
            "gStringVar4Hex": observed_after_text.hex(),
            "battleStartTaskObserved": False,
            "callbacksObserved": ["CB2_Overworld"],
            "controlsUnlockedAfterDismissal": True,
            "samuelDefeatBitRetained": True,
        },
    }
    _write_evidence(evidence_path, evidence)
