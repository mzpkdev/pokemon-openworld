from __future__ import annotations

import json
import os
from pathlib import Path
import re

from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
    load_representatives,
)


HERE = Path(__file__).parent
MAP_HEADER_SIZE = 0x20
MAP_LAYOUT_SIZE = 0x1C
SCRIPT_IDLE = 2
LAYOUT_FORMATS = {"emerald": 0, "frlg": 1, "johto": 2}
MAP_SECTION_METADATA_SIZE = 4
SAVED_LOCATION_INVALID = 0xFF
MET_LOCATION_INVALID = 0xFC
MAPSEC_INVALID = 0xFFFF


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _clean_state_fingerprint(game) -> bytes:
    save_block = game.save_block1()
    return b"".join(
        (
            game.read(game.address("gMain"), 12),
            game.read(game.address("gMapHeader"), MAP_HEADER_SIZE),
            game.read(save_block, 8),
            game.read(game.address("gIntegrityMapLoadRequest"), 16),
            game.read(game.address("gIntegrityMapLoadResult"), 12),
            bytes((game.controls_locked(), game.script_status())),
        )
    )


def _reload_clean_state(game, state: Path, fingerprint: bytes, entry, index, total):
    try:
        game.load_state(state)
    except Exception as error:
        raise AssertionError(
            f"clean-state reload failed before {entry.name} ({index}/{total})"
        ) from error
    actual = _clean_state_fingerprint(game)
    assert actual == fingerprint, (
        f"clean-state reload did not restore exact emulator state before "
        f"{entry.name} ({index}/{total})"
    )


def _expected_header_address(game, entry) -> int:
    group_table = game.read_u32(game.address("gMapGroups") + entry.group * 4)
    assert group_table != 0, f"{entry.name} has a null group table"
    header = game.read_u32(group_table + entry.number * 4)
    assert header != 0, f"{entry.name} has a null registered MapHeader"
    return header


def _assert_exact_section_metadata(game, entry) -> None:
    section = entry.section
    registry = game.address("gMapSectionRegistry")
    assert game.read_u32(registry) == game.address("gMapSectionMetadata")
    assert game.read_u32(registry + 0x04) == game.address("gMapSectionToSavedLocation")
    assert game.read_u32(registry + 0x08) == game.address("gMapSectionToMetLocation")
    assert game.read_u32(registry + 0x0C) == game.address("gSavedLocationToMapSection")
    assert game.read_u32(registry + 0x10) == game.address("gMetLocationToMapSection")
    section_count = game.read_u32(registry + 0x14)
    assert section.value < section_count, (
        f"{entry.name} section {section.value} is outside linked registry count "
        f"{section_count}"
    )

    metadata_address = game.address("gMapSectionMetadata") + (
        section.value * MAP_SECTION_METADATA_SIZE
    )
    expected_metadata = bytes(
        (
            section.region_value,
            section.kind_value,
            section.region_map_type_value,
            0,
        )
    )
    assert (
        game.read(metadata_address, MAP_SECTION_METADATA_SIZE) == expected_metadata
    ), (
        f"{entry.name} linked metadata mismatch for {section.id}: "
        f"region={section.region}, kind={section.kind}, "
        f"regionMapType={section.region_map_type}"
    )

    expected_saved_code = (
        SAVED_LOCATION_INVALID
        if section.saved_location_code < 0
        else section.saved_location_code
    )
    expected_met_code = (
        MET_LOCATION_INVALID
        if section.met_location_code < 0
        else section.met_location_code
    )
    assert (
        game.read_u8(game.address("gMapSectionToSavedLocation") + section.value)
        == expected_saved_code
    )
    assert (
        game.read_u8(game.address("gMapSectionToMetLocation") + section.value)
        == expected_met_code
    )
    if section.saved_location_code >= 0:
        expected = (
            MAPSEC_INVALID
            if section.saved_location_reverse_target < 0
            else section.saved_location_reverse_target
        )
        assert (
            game.read_u16(
                game.address("gSavedLocationToMapSection")
                + section.saved_location_code * 2
            )
            == expected
        )
    if section.met_location_code >= 0:
        expected = (
            MAPSEC_INVALID
            if section.met_location_reverse_target < 0
            else section.met_location_reverse_target
        )
        assert (
            game.read_u16(
                game.address("gMetLocationToMapSection") + section.met_location_code * 2
            )
            == expected
        )


def _assert_load_contract(game, entry, request, result, *, exact_field_state) -> None:
    assert result.request_id == request.request_id, (
        f"{entry.name} request echo mismatch: "
        f"expected={request.request_id}, actual={result.request_id}"
    )
    request_map_id = (request.map_group, request.map_num)
    assert (result.map_group, result.map_num) == request_map_id, (
        f"{entry.name} map echo mismatch: expected={request_map_id}, "
        f"actual={(result.map_group, result.map_num)}"
    )
    assert result.status is IntegrityLoadStatus.SUCCESS, (
        f"{entry.name} ({entry.group}, {entry.number}) failed: "
        f"phase={result.phase.name}, error={result.error.name}"
    )
    assert result.phase is IntegrityLoadPhase.FIELD_READY, (
        f"{entry.name} stopped at phase {result.phase.name}"
    )
    assert result.error is IntegrityLoadError.NONE

    if exact_field_state:
        # The protocol result is committed by the final load step. Representative
        # loads must also complete the ordinary callback/control handoff.
        game.wait_for_callback("CB2_Overworld", max_frames=120)
        game.wait_for_controls_unlocked(max_frames=1_200)

    runtime_header_address = game.address("gMapHeader")
    expected_header_address = _expected_header_address(game, entry)
    runtime_header = game.read(runtime_header_address, MAP_HEADER_SIZE)
    expected_header = game.read(expected_header_address, MAP_HEADER_SIZE)
    assert runtime_header == expected_header, (
        f"{entry.name} runtime MapHeader is not the exact registered header"
    )

    layout_address = game.read_u32(runtime_header_address)
    assert layout_address == game.address(entry.layout), (
        f"{entry.name} layout mismatch: expected={entry.layout}, "
        f"actual=0x{layout_address:08x}"
    )
    assert game.read(layout_address, MAP_LAYOUT_SIZE) == game.read(
        game.address(entry.layout), MAP_LAYOUT_SIZE
    ), f"{entry.name} runtime layout data differs from {entry.layout}"
    assert game.read_u16(runtime_header_address + 0x12) == entry.layout_number
    assert (
        game.read_u16(runtime_header_address + 0x14) == entry.region_map_section_value
    )
    _assert_exact_section_metadata(game, entry)
    assert game.read_u8(runtime_header_address + 0x1C) == entry.battle_type
    assert game.read_u32(runtime_header_address + 0x04) == game.address(entry.events)
    assert game.read_u32(runtime_header_address + 0x08) == game.address(entry.scripts)
    expected_connections = (
        0 if entry.connections is None else game.address(entry.connections)
    )
    assert game.read_u32(runtime_header_address + 0x0C) == expected_connections

    assert game.read_u32(layout_address + 0x10) == game.address(
        entry.primary_tileset
    ), f"{entry.name} primary tileset is not {entry.primary_tileset}"
    assert game.read_u32(layout_address + 0x14) == game.address(
        entry.secondary_tileset
    ), f"{entry.name} secondary tileset is not {entry.secondary_tileset}"
    assert game.read_u8(layout_address + 0x18) == LAYOUT_FORMATS[entry.layout_format]

    if not exact_field_state:
        callback2 = game.read_u32(game.address("gMain") + 4)
        safe_callbacks = {
            game.address("CB2_LoadMap") | 1,
            game.address("CB2_Overworld") | 1,
        }
        assert callback2 in safe_callbacks, (
            f"{entry.name} structural load returned through unsafe callback "
            f"0x{callback2:08x}"
        )
        return

    assert game.map_id() == request_map_id
    assert game.position() == (request.x, request.y), (
        f"{entry.name} coordinate mismatch: expected={(request.x, request.y)}, "
        f"actual={game.position()}"
    )
    assert game.read_u32(game.address("gMain")) == game.address("CB1_Overworld") | 1
    assert game.callback_is("CB2_Overworld"), (
        f"{entry.name} callback is not CB2_Overworld"
    )
    assert not game.controls_locked(), f"{entry.name} left field controls locked"
    assert game.script_status() == SCRIPT_IDLE, (
        f"{entry.name} script context is not idle: {game.script_status()}"
    )
    assert game.movement_idle(), f"{entry.name} player movement did not settle"


def _runtime_diagnostics(game) -> dict[str, object]:
    diagnostics: dict[str, object] = {}
    readers = {
        "mapId": game.map_id,
        "position": game.position,
        "controlsLocked": game.controls_locked,
        "scriptStatus": game.script_status,
        "movementIdle": game.movement_idle,
        "integrityResult": lambda: repr(game.integrity_result()),
        "callback1": lambda: f"0x{game.read_u32(game.address('gMain')):08x}",
        "callback2": lambda: f"0x{game.read_u32(game.address('gMain') + 4):08x}",
    }
    for name, reader in readers.items():
        try:
            diagnostics[name] = reader()
        except Exception as error:
            diagnostics[name] = f"unavailable: {error!r}"
    return diagnostics


def _capture_map_failure(
    game, tmp_path: Path, entry, index: int, error: Exception, *, phase: str
):
    root = Path(os.environ.get("E2E_RESULTS", tmp_path)) / "integrity" / "maps" / phase
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", entry.name)
    output = root / f"{index:04d}-{safe_name}"
    output.mkdir(parents=True, exist_ok=True)
    evidence = {
        "index": index,
        "name": entry.name,
        "mapGroup": entry.group,
        "mapNum": entry.number,
        "error": repr(error),
        "runtime": _runtime_diagnostics(game),
    }
    capture_errors: list[str] = []
    for name, capture in (
        ("screen.png", game.screenshot),
        ("state.png", game.save_state),
    ):
        try:
            capture(output / name)
        except Exception as capture_error:
            capture_errors.append(f"{name}: {capture_error!r}")
    if capture_errors:
        evidence["captureErrors"] = capture_errors
    (output / "diagnostics.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n"
    )
    return output


def _request_for(entry, request_id: int, *, structural: bool):
    return IntegrityMapLoadRequest(
        request_id=request_id,
        map_group=entry.group,
        map_num=entry.number,
        x=entry.width // 2,
        y=entry.height // 2,
        suppress_scripts=structural,
        suppress_events=structural,
    )


def test_all_manifest_maps_are_structurally_loadable(integrity_game, tmp_path):
    maps = load_manifest_maps(integrity_manifest_path())
    assert len(maps) == 935, f"expected 935 registered maps, found {len(maps)}"

    _settle_overworld(integrity_game)
    clean_state = tmp_path / "integrity-clean-state.png"
    integrity_game.save_state(clean_state)
    clean_fingerprint = _clean_state_fingerprint(integrity_game)
    failures: list[str] = []
    for index, entry in enumerate(maps, 1):
        _reload_clean_state(
            integrity_game, clean_state, clean_fingerprint, entry, index, len(maps)
        )
        request = _request_for(entry, 0xF1000000 + index, structural=True)
        assert request.suppress_scripts and request.suppress_events
        try:
            result = integrity_game.request_map_load(request, max_frames=1_200)
            _assert_load_contract(
                integrity_game,
                entry,
                request,
                result,
                exact_field_state=False,
            )
        except Exception as error:
            evidence = _capture_map_failure(
                integrity_game,
                tmp_path,
                entry,
                index,
                error,
                phase="structural",
            )
            failures.append(
                f"{index}/{len(maps)} {entry.name}: {error}; evidence={evidence}"
            )
    assert not failures, "structural map-load failures:\n" + "\n".join(failures)


def test_representative_maps_reach_normal_field_ready_state(integrity_game, tmp_path):
    maps = load_manifest_maps(integrity_manifest_path())
    maps_by_name = {entry.name: entry for entry in maps}
    representatives = load_representatives(HERE / "maps.json", maps)

    _settle_overworld(integrity_game)
    clean_state = tmp_path / "integrity-representative-state.png"
    integrity_game.save_state(clean_state)
    clean_fingerprint = _clean_state_fingerprint(integrity_game)
    failures: list[str] = []
    for index, representative in enumerate(representatives, 1):
        entry = maps_by_name[representative.name]
        _reload_clean_state(
            integrity_game,
            clean_state,
            clean_fingerprint,
            entry,
            index,
            len(representatives),
        )
        for var_id, value in representative.seed_vars:
            integrity_game.set_var(var_id, value)
        request = _request_for(entry, 0xF2000000 + index, structural=False)
        assert not request.suppress_scripts and not request.suppress_events
        try:
            result = integrity_game.request_map_load(request, max_frames=1_800)
            _assert_load_contract(
                integrity_game,
                entry,
                request,
                result,
                exact_field_state=True,
            )
        except Exception as error:
            evidence = _capture_map_failure(
                integrity_game,
                tmp_path,
                entry,
                index,
                error,
                phase="representative",
            )
            failures.append(
                f"{index}/{len(representatives)} {entry.name}: {error}; "
                f"evidence={evidence}"
            )
    assert not failures, "representative map-load failures:\n" + "\n".join(failures)
