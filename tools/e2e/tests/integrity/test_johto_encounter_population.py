from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import json
from pathlib import Path
import re
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

WILD_AREA_LAND = 0
WILD_AREA_WATER = 1
WILD_AREA_ROCKS = 2
WILD_AREA_FISHING = 3
OLD_ROD = 0
GOOD_ROD = 1
SUPER_ROD = 2
WILD_ENCOUNTER_FISHING_ROD_NONE = 0xFF
PROBE_REQUEST_SIZE = 12
PROBE_REQUEST_STATUS_OFFSET = 11
PROBE_RESULT_SIZE = 24
FLAG_REGIONAL_FACT_HOENN_STONE_BADGE = 32
FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE = 33
FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE = 34
ROOT = Path(__file__).resolve().parents[4]
STANDARD_ENCOUNTERS = ROOT / "src/data/wild_encounters.json"
SPECIES_CONSTANTS = ROOT / "include/constants/species.h"

AREA_FIELDS = {
    WILD_AREA_LAND: "land_mons",
    WILD_AREA_WATER: "water_mons",
    WILD_AREA_ROCKS: "rock_smash_mons",
    WILD_AREA_FISHING: "fishing_mons",
}
AREA_WEIGHTS = {
    WILD_AREA_LAND: (20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1),
    WILD_AREA_WATER: (60, 30, 5, 4, 1),
    WILD_AREA_ROCKS: (60, 30, 5, 4, 1),
}
FISHING_SLICES = {
    OLD_ROD: (0, 2, (70, 30)),
    GOOD_ROD: (2, 5, (60, 20, 20)),
    SUPER_ROD: (5, 10, (40, 40, 15, 4, 1)),
}


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


@dataclass(frozen=True)
class EncounterCase:
    map_name: str
    area: int
    labels: tuple[str, ...]
    fishing_rod: int = WILD_ENCOUNTER_FISHING_ROD_NONE


# These cases cross outdoor, cave, water, and rock-smash dispatch. They also
# exercise each reviewed fallback class: a tide layout, a connected route
# segment, and a spatially identical cave floor.
ORDINARY_CASES = (
    EncounterCase("Route30", WILD_AREA_LAND, ("gRoute30", "gRoute30_Night")),
    EncounterCase("UnionCave_1F", WILD_AREA_LAND, ("gUnionCave_1F",)),
    EncounterCase("LakeOfRageLowTide", WILD_AREA_WATER, ("gLakeOfRageLowTide",)),
    EncounterCase(
        "Route26North",
        WILD_AREA_LAND,
        ("gRoute26North", "gRoute26North_Night"),
    ),
    EncounterCase(
        "JohtoVictoryRoad_1F",
        WILD_AREA_LAND,
        ("gJohtoVictoryRoad_1F", "gJohtoVictoryRoad_1F_Night"),
    ),
    EncounterCase(
        "JohtoVictoryRoad_B1F",
        WILD_AREA_LAND,
        ("gJohtoVictoryRoad_B1F", "gJohtoVictoryRoad_B1F_Night"),
    ),
    EncounterCase(
        "JohtoVictoryRoad_B2F",
        WILD_AREA_LAND,
        ("gJohtoVictoryRoad_B2F", "gJohtoVictoryRoad_B2F_Night"),
    ),
    EncounterCase("Route32", WILD_AREA_ROCKS, ("gRoute32", "gRoute32_Night")),
)

FISHING_CASES = tuple(
    EncounterCase(
        "Route30",
        WILD_AREA_FISHING,
        ("gRoute30", "gRoute30_Night"),
        rod,
    )
    for rod in (OLD_ROD, GOOD_ROD, SUPER_ROD)
)


def _species_ids() -> dict[str, int]:
    pattern = re.compile(r"^\s*(SPECIES_[A-Z0-9_]+)\s*=\s*(\d+),", re.MULTILINE)
    return {
        match.group(1): int(match.group(2))
        for match in pattern.finditer(SPECIES_CONSTANTS.read_text())
    }


def _standard_profiles() -> dict[str, dict]:
    document = json.loads(STANDARD_ENCOUNTERS.read_text())
    group = next(
        group
        for group in document["wild_encounter_groups"]
        if group["label"] == "gWildMonHeaders"
    )
    return {profile["base_label"]: profile for profile in group["encounters"]}


def _expected_profile_signatures(
    case: EncounterCase,
) -> set[tuple[tuple[int, ...], ...]]:
    species = _species_ids()
    profiles = _standard_profiles()
    expected = set()
    for label in case.labels:
        method = profiles[label][AREA_FIELDS[case.area]]
        mons = method["mons"]
        if case.area == WILD_AREA_FISHING:
            start, end, weights = FISHING_SLICES[case.fishing_rod]
            mons = mons[start:end]
        else:
            weights = AREA_WEIGHTS[case.area]
        expected.add(
            tuple(
                (
                    species[mon["species"]],
                    weight,
                    min(mon["min_level"], mon["max_level"]),
                    max(mon["min_level"], mon["max_level"]),
                )
                for mon, weight in zip(mons, weights, strict=True)
            )
        )
    return expected


def _runtime_profile_signature(
    entries: tuple[EncounterProbeResult, ...],
) -> tuple[tuple[int, ...], ...]:
    return tuple(
        (entry.species, entry.weight, entry.min_level, entry.max_level)
        for entry in entries
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
    assert first.trainer_rating <= 46
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
    assert all(entry.trainer_rating == first.trainer_rating for entry in entries)
    assert all(entry.species > 0 and entry.weight > 0 for entry in entries)
    assert sum(entry.weight for entry in entries) == first.total_weight
    assert _runtime_profile_signature(tuple(entries)) in _expected_profile_signatures(
        case
    )
    return tuple(entries)


@pytest.mark.long_journey
def test_ordinary_johto_maps_dispatch_exact_standard_profiles(integrity_game):
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
def test_johto_fishing_dispatches_each_standard_rod_profile(integrity_game):
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
def test_route39_remains_an_exact_standard_runtime_profile(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    _load_map(integrity_game, maps["Route39"], 0xE3740000)

    entries = _probe_complete_profile(
        integrity_game,
        EncounterCase("Route39", WILD_AREA_LAND, ("gRoute39", "gRoute39_Night")),
        0xE3750000,
    )

    # The runtime clock selects either the protected day or night profile.
    assert entries[0].species in (52, 77)  # Meowth or Ponyta.


@pytest.mark.long_journey
def test_johto_raw_profile_is_invariant_across_trainer_rating_changes(
    integrity_game,
):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    case = EncounterCase("Route32", WILD_AREA_LAND, ("gRoute32", "gRoute32_Night"))
    _load_map(integrity_game, maps[case.map_name], 0xE3780000)

    for flag in (
        FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
        FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
        FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
    ):
        integrity_game.set_flag(flag, False)
    rating_zero = _probe_complete_profile(integrity_game, case, 0xE3790000)
    assert rating_zero[0].trainer_rating == 0

    for flag in (
        FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
        FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
        FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
    ):
        integrity_game.set_flag(flag)
    rating_nine = _probe_complete_profile(integrity_game, case, 0xE37A0000)
    assert rating_nine[0].trainer_rating == 9

    assert _runtime_profile_signature(rating_nine) == _runtime_profile_signature(
        rating_zero
    )


@pytest.mark.long_journey
def test_bug_contest_map_is_not_claimed_by_ordinary_johto_profiles(integrity_game):
    _quickstart(integrity_game)
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    _load_map(integrity_game, maps["NationalPark_BugContest"], 0xE3760000)

    with pytest.raises(AssertionError, match=r"failed with error 2"):
        _probe_encounter(
            integrity_game,
            request_id=0xE3770000,
            area=WILD_AREA_LAND,
            fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
            entry_index=0,
        )
