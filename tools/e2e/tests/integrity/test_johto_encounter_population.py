from __future__ import annotations

from dataclasses import dataclass

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
from tools.e2e.tests.integrity.test_world_tier_encounters import (
    WILD_ENCOUNTER_FISHING_ROD_NONE,
    WILD_ENCOUNTER_PROFILE_AUTHORED,
    WORLD_TIER_0,
    EncounterProbeResult,
    _probe_encounter,
)


WILD_AREA_LAND = 0
WILD_AREA_WATER = 1
WILD_AREA_ROCKS = 2
WILD_AREA_FISHING = 3
OLD_ROD = 0
GOOD_ROD = 1
SUPER_ROD = 2


@dataclass(frozen=True)
class EncounterCase:
    map_name: str
    area: int
    fishing_rod: int = WILD_ENCOUNTER_FISHING_ROD_NONE


# These cases cross outdoor, cave, water, and rock-smash dispatch. They also
# exercise each reviewed fallback class: a tide layout, a connected route
# segment, and a spatially identical cave floor.
ORDINARY_CASES = (
    EncounterCase("Route30", WILD_AREA_LAND),
    EncounterCase("UnionCave_1F", WILD_AREA_LAND),
    EncounterCase("LakeOfRageLowTide", WILD_AREA_WATER),
    EncounterCase("Route26North", WILD_AREA_LAND),
    EncounterCase("JohtoVictoryRoad_1F", WILD_AREA_LAND),
    EncounterCase("Route32", WILD_AREA_ROCKS),
)

FISHING_CASES = tuple(
    EncounterCase("Route30", WILD_AREA_FISHING, rod)
    for rod in (OLD_ROD, GOOD_ROD, SUPER_ROD)
)


def _quickstart(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach the overworld")


def _load_map(game, entry, request_id: int) -> None:
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            suppress_scripts=True,
            suppress_events=True,
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    game.wait_for_controls_unlocked(max_frames=1_200)


def _probe_complete_profile(
    game, case: EncounterCase, request_base: int
) -> tuple[EncounterProbeResult, ...]:
    first = _probe_encounter(
        game,
        request_id=request_base,
        area=case.area,
        fishing_rod=case.fishing_rod,
        entry_index=0,
    )
    assert first.source == WILD_ENCOUNTER_PROFILE_AUTHORED
    assert first.tier == WORLD_TIER_0
    assert first.entry_count > 0
    assert first.total_weight > 0

    entries = [first]
    for entry_index in range(1, first.entry_count):
        entries.append(
            _probe_encounter(
                game,
                request_id=request_base + entry_index,
                area=case.area,
                fishing_rod=case.fishing_rod,
                entry_index=entry_index,
            )
        )

    assert all(entry.header_id == first.header_id for entry in entries)
    assert all(entry.entry_count == first.entry_count for entry in entries)
    assert all(entry.total_weight == first.total_weight for entry in entries)
    assert all(entry.source == WILD_ENCOUNTER_PROFILE_AUTHORED for entry in entries)
    assert all(entry.tier == WORLD_TIER_0 for entry in entries)
    assert all(entry.species > 0 and entry.weight > 0 for entry in entries)
    assert all((entry.min_level, entry.max_level) == (4, 8) for entry in entries)
    assert sum(entry.weight for entry in entries) == first.total_weight
    return tuple(entries)


@pytest.mark.long_journey
def test_ordinary_johto_maps_dispatch_complete_authored_profiles(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }

    header_ids = set()
    for case_index, case in enumerate(ORDINARY_CASES):
        _load_map(integrity_game, maps[case.map_name], 0xE3700000 + case_index)
        entries = _probe_complete_profile(
            integrity_game, case, 0xE3710000 + case_index * 0x100
        )
        header_ids.add(entries[0].header_id)

    assert len(header_ids) == len(ORDINARY_CASES)


@pytest.mark.long_journey
def test_johto_fishing_dispatches_each_authored_rod_profile(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    _load_map(integrity_game, maps["Route30"], 0xE3720000)

    profiles = tuple(
        _probe_complete_profile(integrity_game, case, 0xE3730000 + case_index * 0x100)
        for case_index, case in enumerate(FISHING_CASES)
    )

    assert all(profile[0].header_id == profiles[0][0].header_id for profile in profiles)
    assert tuple(profile[0].fishing_rod for profile in profiles) == (
        OLD_ROD,
        GOOD_ROD,
        SUPER_ROD,
    )


@pytest.mark.long_journey
def test_route39_remains_an_authored_runtime_profile(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    _load_map(integrity_game, maps["Route39"], 0xE3740000)

    entries = _probe_complete_profile(
        integrity_game,
        EncounterCase("Route39", WILD_AREA_LAND),
        0xE3750000,
    )

    # The runtime clock selects either the protected day or night profile.
    assert entries[0].species in (52, 77)  # Meowth or Ponyta.


@pytest.mark.long_journey
def test_bug_contest_map_is_not_claimed_by_ordinary_johto_profiles(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    _load_map(integrity_game, maps["NationalPark_BugContest"], 0xE3760000)

    with pytest.raises(AssertionError, match=r"failed with error 3$"):
        _probe_encounter(
            integrity_game,
            request_id=0xE3770000,
            area=WILD_AREA_LAND,
            fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
            entry_index=0,
        )
