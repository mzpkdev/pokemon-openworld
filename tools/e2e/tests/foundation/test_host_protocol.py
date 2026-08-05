import pytest

from tools.e2e.skyemu import (
    FoundationLoadError,
    FoundationLoadPhase,
    FoundationLoadStatus,
    FoundationMapLoadRequest,
    FoundationMapLoadResult,
    SkyEmuSession,
)


def result(
    *,
    request_id=7,
    map_group=0,
    map_num=9,
    status=FoundationLoadStatus.RUNNING,
):
    return FoundationMapLoadResult(
        request_id=request_id,
        map_group=map_group,
        map_num=map_num,
        status=status,
        phase=FoundationLoadPhase.GRAPHICS,
        error=FoundationLoadError.NONE,
    )


class ResultWaitHarness:
    def __init__(self, results):
        self.results = iter(results)
        self.last = None
        self.steps = 0

    def foundation_result(self):
        self.last = next(self.results, self.last)
        return self.last

    def step(self):
        self.steps += 1


def test_foundation_wait_times_out_with_last_phase():
    harness = ResultWaitHarness([result(), result(), result()])

    with pytest.raises(
        TimeoutError,
        match=r"request 7 timed out after 2 frames; .*phase=GRAPHICS",
    ):
        SkyEmuSession.wait_for_foundation_result(harness, 7, max_frames=2)

    assert harness.steps == 2


def test_foundation_wait_rejects_wrong_request_echo():
    harness = ResultWaitHarness(
        [result(), result(request_id=8, status=FoundationLoadStatus.ERROR)]
    )

    with pytest.raises(RuntimeError, match="echoed the wrong request id"):
        SkyEmuSession.wait_for_foundation_result(harness, 7, max_frames=1)


class RequestHarness:
    def __init__(self, response):
        self.response = response

    def address(self, symbol):
        assert symbol == "gFoundationMapLoadRequest"
        return 0x03000000

    def pause(self):
        pass

    def write(self, address, payload):
        pass

    def write_u8(self, address, value):
        pass

    def resume(self):
        pass

    def wait_for_foundation_result(self, request_id, *, max_frames):
        return self.response


def test_foundation_request_rejects_wrong_map_echo():
    request = FoundationMapLoadRequest(request_id=7, map_group=0, map_num=9)
    harness = RequestHarness(result(map_num=10, status=FoundationLoadStatus.ERROR))

    with pytest.raises(RuntimeError, match="echoed the wrong map id"):
        SkyEmuSession.request_map_load(harness, request, max_frames=1)


class StateHarness:
    def __init__(self):
        self.calls = []
        self.buttons = None

    def _text(self, command, params):
        self.calls.append((command, params))
        return "ok"

    def set_buttons(self, **states):
        self.buttons = states


def test_load_state_uses_skyemu_load_endpoint_and_releases_buttons(tmp_path):
    state = tmp_path / "clean-state.png"
    state.write_bytes(b"state")
    harness = StateHarness()

    SkyEmuSession.load_state(harness, state)

    assert harness.calls == [("load", [("path", str(state.resolve()))])]
    assert harness.buttons and not any(harness.buttons.values())


class SavedVarHarness:
    def __init__(self):
        self.value = 0
        self.address_written = None

    def save_block1(self):
        return 0x02000000

    def write_u16(self, address, value):
        self.address_written = address
        self.value = value

    def read_var(self, var_id):
        return self.value


def test_set_var_writes_and_verifies_saved_variable():
    harness = SavedVarHarness()

    SkyEmuSession.set_var(harness, 0x4086, 1)

    assert harness.address_written == 0x02000000 + 0x139C + 0x86 * 2
    assert harness.value == 1
