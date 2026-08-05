from __future__ import annotations

import json
from pathlib import Path

from tools.e2e.skyemu import (
    FoundationLoadError,
    FoundationLoadPhase,
    FoundationLoadStatus,
    FoundationMapLoadRequest,
)
from tools.e2e.tests.foundation.manifest import (
    foundation_manifest_path,
    load_manifest_maps,
)


FIXTURES = json.loads(Path(__file__).with_name("maps.json").read_text())["interactions"]


def _fixture(behavior: str) -> dict:
    [fixture] = [entry for entry in FIXTURES if entry["behavior"] == behavior]
    return fixture


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _load_fixture(game, fixture: dict, request_id: int):
    maps = {
        entry.name: entry for entry in load_manifest_maps(foundation_manifest_path())
    }
    entry = maps[fixture["map"]]
    for seed_var in fixture.get("seedVars", []):
        game.set_var(seed_var["id"], seed_var["value"])
    result = game.request_map_load(
        FoundationMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=fixture["x"],
            y=fixture["y"],
        ),
        max_frames=1_800,
    )
    assert result.status is FoundationLoadStatus.SUCCESS
    assert result.phase is FoundationLoadPhase.FIELD_READY
    assert result.error is FoundationLoadError.NONE
    assert game.map_id() == entry.map_id
    game.wait_for_controls_unlocked(max_frames=1_200)
    return maps


def _hold_direction_until_map(game, direction: str, destination, task_symbols):
    saw_tasks = {symbol: False for symbol in task_symbols}
    game.set_buttons(**{direction: True})
    try:
        for _ in range(1_800):
            game.step()
            for symbol in task_symbols:
                saw_tasks[symbol] |= game.task_active(symbol)
            if game.map_id() == destination.map_id:
                game.set_buttons(**{direction: False})
                for _ in range(1_200):
                    for symbol in task_symbols:
                        saw_tasks[symbol] |= game.task_active(symbol)
                    if not game.controls_locked() and game.script_status() == 2:
                        return saw_tasks
                    game.step()
                raise AssertionError(
                    f"{destination.name} did not restore controls after interaction"
                )
    finally:
        game.set_buttons(**{direction: False})
    raise AssertionError(
        f"{direction} interaction did not reach {destination.name}; map={game.map_id()}"
    )


def test_frlg_door_animates_and_warps(foundation_game):
    fixture = _fixture("door")
    _settle_overworld(foundation_game)
    maps = _load_fixture(foundation_game, fixture, 0xF4000001)

    saw = _hold_direction_until_map(
        foundation_game,
        fixture["direction"],
        maps[fixture["destination"]],
        ("Task_DoDoorWarp", "Task_AnimateDoor"),
    )

    assert saw["Task_DoDoorWarp"], "door warp task never ran"
    assert saw["Task_AnimateDoor"], "FRLG door animation task never ran"


def test_frlg_escalator_runs_transition_and_warps(foundation_game):
    fixture = _fixture("escalator")
    _settle_overworld(foundation_game)
    maps = _load_fixture(foundation_game, fixture, 0xF4000002)

    saw = _hold_direction_until_map(
        foundation_game,
        fixture["direction"],
        maps[fixture["destination"]],
        ("Task_EscalatorWarpOut", "Task_EscalatorWarpIn"),
    )

    assert saw["Task_EscalatorWarpOut"], "FRLG escalator warp-out task never ran"


def test_frlg_mart_clerk_opens_buy_menu(foundation_game):
    fixture = _fixture("shop")
    _settle_overworld(foundation_game)
    _load_fixture(foundation_game, fixture, 0xF4000003)
    foundation_game.face(fixture["direction"])

    foundation_game.advance_until(
        lambda: foundation_game.task_active("Task_ShopMenu"),
        description="FRLG shop menu",
        max_pulses=300,
    )
    assert foundation_game.task_active("Task_ShopMenu")

    foundation_game.press("A")
    foundation_game.wait_for_callback("CB2_BuyMenu", max_frames=1_200)
    assert foundation_game.callback_is("CB2_BuyMenu")


def test_frlg_primary_tileset_animates_vram(foundation_game):
    fixture = _fixture("animated_tileset")
    _settle_overworld(foundation_game)
    _load_fixture(foundation_game, fixture, 0xF4000004)

    callback = foundation_game.read_u32(
        foundation_game.address("sPrimaryTilesetAnimCallback")
    )
    assert callback == foundation_game.address(fixture["callback"]) | 1
    counter_address = foundation_game.address("sPrimaryTilesetAnimCounter")
    counters = []
    frames = set()
    for _ in range(40):
        counters.append(foundation_game.read_u16(counter_address))
        frames.add(foundation_game.read(fixture["vramAddress"], fixture["vramSize"]))
        foundation_game.step()

    assert len(set(counters)) > 1, "FRLG tileset animation counter did not advance"
    assert len(frames) > 1, "FRLG animated tile frames did not change in VRAM"
