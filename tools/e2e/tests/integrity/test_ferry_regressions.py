from __future__ import annotations

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


SCRIPT_IDLE = 2
SAILOR_LOCAL_ID = 1
VERMILION_OUTDOOR_SAILOR_LOCAL_ID = 6
VERMILION_OUTDOOR_ENTRY = (24, 32)
VERMILION_PORT_ENTRY = (8, 9)
OLIVINE_PORT_ENTRY = (8, 16)

FERRY_LEGS = (
    (
        "VermilionCity_PortInside",
        VERMILION_PORT_ENTRY,
        "OlivineCity_PortInside",
        OLIVINE_PORT_ENTRY,
        (8, 15),
        0xF3300001,
    ),
    (
        "OlivineCity_PortInside",
        OLIVINE_PORT_ENTRY,
        "VermilionCity_PortInside",
        VERMILION_PORT_ENTRY,
        (8, 8),
        0xF3300002,
    ),
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


@pytest.mark.parametrize(
    (
        "source_name",
        "source_coordinates",
        "destination_name",
        "arrival_coordinates",
        "walk_coordinates",
        "request_id",
    ),
    FERRY_LEGS,
)
def test_ferry_leg_reaches_destination_and_returns_control(
    integrity_game,
    source_name,
    source_coordinates,
    destination_name,
    arrival_coordinates,
    walk_coordinates,
    request_id,
):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    source = maps[source_name]
    destination = maps[destination_name]

    _settle_overworld(integrity_game)
    _load_source(integrity_game, source, source_coordinates, request_id)

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
    assert integrity_game.position() == arrival_coordinates
    assert integrity_game.callback_is("CB2_Overworld")
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert integrity_game.movement_idle()
    integrity_game.move_to(x=walk_coordinates[0], y=walk_coordinates[1])
    assert integrity_game.position() == walk_coordinates


def test_vermilion_outdoor_sailor_enters_usable_terminal(integrity_game):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    vermilion = maps["VermilionCity_Frlg"]
    terminal = maps["VermilionCity_PortInside"]

    _settle_overworld(integrity_game)
    _load_source(
        integrity_game,
        vermilion,
        VERMILION_OUTDOOR_ENTRY,
        0xF3300003,
    )

    integrity_game.face("Down")
    integrity_game.press("A")
    integrity_game.wait_until(
        lambda: (
            integrity_game.controls_locked()
            and integrity_game.read_u16(
                integrity_game.address("gSpecialVar_LastTalked")
            )
            == VERMILION_OUTDOOR_SAILOR_LOCAL_ID
        ),
        description="Vermilion outdoor ferry sailor interaction",
        max_frames=120,
    )
    integrity_game.advance_until(
        lambda: integrity_game.map_id() == terminal.map_id,
        description="public Vermilion ferry terminal entry",
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
        description="usable Vermilion ferry terminal entry",
        max_frames=1_800,
        step_frames=2,
    )

    assert integrity_game.position() == VERMILION_PORT_ENTRY
    integrity_game.move_to(x=8, y=3)
    assert integrity_game.position() == (8, 3)

    integrity_game.advance_until(
        lambda: integrity_game.map_id() == vermilion.map_id,
        description="public Vermilion ferry terminal exit",
        max_pulses=600,
        button="Up",
    )
    integrity_game.wait_until(
        lambda: (
            integrity_game.callback_is("CB2_Overworld")
            and not integrity_game.controls_locked()
            and integrity_game.script_status() == SCRIPT_IDLE
            and integrity_game.movement_idle()
        ),
        description="usable Vermilion city return",
        max_frames=1_800,
        step_frames=2,
    )

    assert integrity_game.map_id() == vermilion.map_id
    assert integrity_game.position() == (24, 34)
    assert integrity_game.callback_is("CB2_Overworld")
    assert not integrity_game.controls_locked()
    assert integrity_game.script_status() == SCRIPT_IDLE
    assert integrity_game.movement_idle()
