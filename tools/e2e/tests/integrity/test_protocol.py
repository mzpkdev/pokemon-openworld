from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)


def test_invalid_map_group_reports_controlled_validation_error(integrity_game):
    request = IntegrityMapLoadRequest(
        request_id=0xF0010001,
        map_group=0xFFFF,
        map_num=0,
    )

    result = integrity_game.request_map_load(request, max_frames=120)

    assert result.request_id == request.request_id
    assert (result.map_group, result.map_num) == (request.map_group, request.map_num)
    assert result.status is IntegrityLoadStatus.ERROR
    assert result.phase is IntegrityLoadPhase.VALIDATE
    assert result.error is IntegrityLoadError.MAP_GROUP


def test_valid_map_is_rejected_until_overworld_is_ready(integrity_game):
    request = IntegrityMapLoadRequest(
        request_id=0xF0010002,
        map_group=0,
        map_num=9,
    )

    result = integrity_game.request_map_load(request, max_frames=120)

    assert result.request_id == request.request_id
    assert (result.map_group, result.map_num) == (request.map_group, request.map_num)
    assert result.status is IntegrityLoadStatus.ERROR
    assert result.phase is IntegrityLoadPhase.VALIDATE
    assert result.error is IntegrityLoadError.NOT_READY


def test_valid_map_load_runs_from_settled_overworld(integrity_game):
    integrity_game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        integrity_game.press("Select")
        if integrity_game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not reach the overworld")

    request = IntegrityMapLoadRequest(
        request_id=0xF0010003,
        map_group=0,
        map_num=9,
        suppress_scripts=True,
        suppress_events=True,
    )
    result = integrity_game.request_map_load(request, max_frames=1_200)

    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert integrity_game.map_id() == (request.map_group, request.map_num)


def test_suppressed_route120_load_does_not_run_on_load_scripts(integrity_game):
    integrity_game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        integrity_game.press("Select")
        if integrity_game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not reach the overworld")

    # Route120's MAP_SCRIPT_ON_LOAD mutates a Kecleon object. Structural loads
    # suppress those objects, so the script must be suppressed at the same
    # boundary as transition, resume, and warp-in scripts.
    request = IntegrityMapLoadRequest(
        request_id=0xF0010004,
        map_group=0,
        map_num=35,
        suppress_scripts=True,
        suppress_events=True,
    )
    result = integrity_game.request_map_load(request, max_frames=1_200)

    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert integrity_game.map_id() == (request.map_group, request.map_num)
