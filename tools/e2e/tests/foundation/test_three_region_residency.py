from __future__ import annotations

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
    load_representatives,
)


HERE = Path(__file__).parent


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _require_success(entry, result) -> None:
    assert result.status is FoundationLoadStatus.SUCCESS, (
        f"{entry.name} ({entry.group}, {entry.number}) failed: "
        f"phase={result.phase.name}, error={result.error.name}"
    )
    assert result.phase is FoundationLoadPhase.FIELD_READY, (
        f"{entry.name} stopped at phase {result.phase.name}"
    )
    assert result.error is FoundationLoadError.NONE


def test_all_manifest_maps_are_structurally_loadable(foundation_game, tmp_path):
    maps = load_manifest_maps(foundation_manifest_path())
    assert len(maps) == 935, f"expected 935 registered maps, found {len(maps)}"

    _settle_overworld(foundation_game)
    clean_state = tmp_path / "foundation-clean-state.png"
    foundation_game.save_state(clean_state)
    failures: list[str] = []
    for index, entry in enumerate(maps, 1):
        try:
            foundation_game.load_state(clean_state)
        except Exception as error:
            raise AssertionError(
                f"clean-state reload failed before {entry.name} ({index}/{len(maps)})"
            ) from error
        request = FoundationMapLoadRequest(
            request_id=0xF1000000 + index,
            map_group=entry.group,
            map_num=entry.number,
            suppress_scripts=True,
            suppress_events=True,
        )
        try:
            result = foundation_game.request_map_load(request, max_frames=1_200)
            _require_success(entry, result)
            assert foundation_game.map_id() == entry.map_id
        except Exception as error:
            failures.append(f"{index}/{len(maps)} {entry.name}: {error}")
    assert not failures, "structural map-load failures:\n" + "\n".join(failures)


def test_representative_maps_reach_normal_field_ready_state(foundation_game, tmp_path):
    maps = load_manifest_maps(foundation_manifest_path())
    maps_by_name = {entry.name: entry for entry in maps}
    representatives = load_representatives(HERE / "maps.json")
    representative_names = [representative.name for representative in representatives]
    missing = sorted(set(representative_names) - maps_by_name.keys())
    assert not missing, f"representatives absent from foundation manifest: {missing}"

    _settle_overworld(foundation_game)
    clean_state = tmp_path / "foundation-representative-state.png"
    foundation_game.save_state(clean_state)
    failures: list[str] = []
    for index, representative in enumerate(representatives, 1):
        name = representative.name
        entry = maps_by_name[name]
        try:
            foundation_game.load_state(clean_state)
        except Exception as error:
            raise AssertionError(f"clean-state reload failed before {name}") from error
        for var_id, value in representative.seed_vars:
            foundation_game.set_var(var_id, value)
        request = FoundationMapLoadRequest(
            request_id=0xF2000000 + index,
            map_group=entry.group,
            map_num=entry.number,
            suppress_scripts=False,
            suppress_events=False,
        )
        try:
            result = foundation_game.request_map_load(request, max_frames=1_800)
            _require_success(entry, result)
            assert foundation_game.map_id() == entry.map_id
            foundation_game.wait_for_controls_unlocked(max_frames=1_200)
            assert not foundation_game.controls_locked(), (
                f"controls remained locked on {name}"
            )
        except Exception as error:
            failures.append(
                f"normal field controls did not settle on {name}; "
                f"locked={foundation_game.controls_locked()}, "
                f"scriptStatus={foundation_game.script_status()}; {error}"
            )
    assert not failures, "representative map-load failures:\n" + "\n".join(failures)
