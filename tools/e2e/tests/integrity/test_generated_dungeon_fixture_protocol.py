import pytest

from tools.e2e.generated_dungeon_fixture import (
    FIXTURE_REQUEST_STATUS_OFFSET,
    FIXTURE_RESULT_SIZE,
    FIXTURE_PROVIDER_ID,
    FIXTURE_GENERATION_VERSION,
    FixtureRequest,
    FixtureResult,
    FixtureStatus,
    activate_fixture,
)


def test_fixture_request_has_status_last_idle_payload():
    payload = FixtureRequest(0x10203040, 0x55667788).payload()

    assert len(payload) == 12
    assert payload[FIXTURE_REQUEST_STATUS_OFFSET] == FixtureStatus.IDLE
    assert payload[-3:] == bytes(3)


def test_fixture_result_rejects_unknown_status():
    payload = bytearray(FIXTURE_RESULT_SIZE)
    payload[-1] = 0xFF

    with pytest.raises(
        RuntimeError, match="malformed generated dungeon fixture result"
    ):
        FixtureResult.unpack(bytes(payload))


class Harness:
    def __init__(self, result):
        self.result = result
        self.writes = []
        self.steps = 0

    def address(self, symbol):
        return {
            "gDebugGeneratedDungeonFixtureRequest": 0x03000000,
            "gDebugGeneratedDungeonFixtureResult": 0x03000020,
        }[symbol]

    def pause(self):
        pass

    def resume(self):
        pass

    def write(self, address, value):
        self.writes.append((address, value))

    def write_u8(self, address, value):
        self.writes.append((address, value))

    def read(self, address, size):
        assert address == 0x03000020
        assert size == FIXTURE_RESULT_SIZE
        return self.result

    def step(self):
        self.steps += 1


def test_fixture_activation_commits_status_last():
    request = FixtureRequest(7, 0xDEADBEEF)
    result = FixtureResult(
        request_id=request.request_id,
        seed=request.seed,
        provider_id=FIXTURE_PROVIDER_ID,
        generation_version=FIXTURE_GENERATION_VERSION,
        map_group=0,
        map_num=0,
        error=0,
        status=FixtureStatus.SUCCESS,
    )
    encoded = __import__("struct").pack(
        "<IIHHBBBB",
        result.request_id,
        result.seed,
        result.provider_id,
        result.generation_version,
        result.map_group,
        result.map_num,
        result.error,
        result.status,
    )
    harness = Harness(encoded)

    observed = activate_fixture(harness, request, max_frames=1)

    assert observed == result
    assert harness.writes[0] == (0x03000000, request.payload())
    assert harness.writes[1] == (
        0x03000000 + FIXTURE_REQUEST_STATUS_OFFSET,
        FixtureStatus.PENDING,
    )
