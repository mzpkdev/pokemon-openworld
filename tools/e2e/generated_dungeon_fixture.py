from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct


FIXTURE_REQUEST_SIZE = 12
FIXTURE_REQUEST_STATUS_OFFSET = 8
FIXTURE_RESULT_SIZE = 16
FIXTURE_PROVIDER_ID = 0xD090
FIXTURE_GENERATION_VERSION = 1


class FixtureStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    RUNNING = 2
    SUCCESS = 3
    ERROR = 4


class FixtureError(IntEnum):
    NONE = 0
    NOT_READY = 1
    REQUEST = 2
    BEGIN = 3


@dataclass(frozen=True)
class FixtureRequest:
    request_id: int
    seed: int

    def payload(self) -> bytes:
        if not 0 <= self.request_id <= 0xFFFFFFFF:
            raise ValueError("request_id is outside u32")
        if not 0 <= self.seed <= 0xFFFFFFFF:
            raise ValueError("seed is outside u32")
        return struct.pack("<IIB3x", self.request_id, self.seed, FixtureStatus.IDLE)


@dataclass(frozen=True)
class FixtureResult:
    request_id: int
    seed: int
    provider_id: int
    generation_version: int
    map_group: int
    map_num: int
    error: FixtureError
    status: FixtureStatus

    @classmethod
    def unpack(cls, payload: bytes) -> "FixtureResult":
        if len(payload) != FIXTURE_RESULT_SIZE:
            raise ValueError(f"fixture result is {len(payload)} bytes")
        request_id, seed, provider_id, version, group, number, error, status = (
            struct.unpack("<IIHHBBBB", payload)
        )
        try:
            return cls(
                request_id,
                seed,
                provider_id,
                version,
                group,
                number,
                FixtureError(error),
                FixtureStatus(status),
            )
        except ValueError as value_error:
            raise RuntimeError(
                f"malformed generated dungeon fixture result: {payload.hex()}"
            ) from value_error


def activate_fixture(
    game, request: FixtureRequest, *, max_frames: int = 1_800
) -> FixtureResult:
    """Activate the DEBUG-only fixed provider with a status-last request."""
    if max_frames < 1:
        raise ValueError("max_frames must be positive")
    address = game.address("gDebugGeneratedDungeonFixtureRequest")
    payload = request.payload()
    if len(payload) != FIXTURE_REQUEST_SIZE:
        raise AssertionError("generated dungeon fixture request ABI size drifted")

    game.pause()
    game.write(address, payload)
    game.write_u8(address + FIXTURE_REQUEST_STATUS_OFFSET, FixtureStatus.PENDING)
    game.resume()

    result = None
    for _ in range(max_frames):
        result = FixtureResult.unpack(
            game.read(
                game.address("gDebugGeneratedDungeonFixtureResult"), FIXTURE_RESULT_SIZE
            )
        )
        if result.status not in (FixtureStatus.SUCCESS, FixtureStatus.ERROR):
            game.step()
            continue
        if result.request_id != request.request_id:
            raise RuntimeError(
                "generated dungeon fixture echoed the wrong request id: "
                f"expected={request.request_id}, actual={result.request_id}"
            )
        if result.seed != request.seed:
            raise RuntimeError(
                "generated dungeon fixture echoed the wrong seed: "
                f"expected={request.seed:#x}, actual={result.seed:#x}"
            )
        if result.status is FixtureStatus.ERROR:
            raise AssertionError(
                f"generated dungeon fixture failed: error={result.error.name}"
            )
        if (result.provider_id, result.generation_version) != (
            FIXTURE_PROVIDER_ID,
            FIXTURE_GENERATION_VERSION,
        ):
            raise RuntimeError("generated dungeon fixture provider identity drifted")
        return result
    raise TimeoutError(
        f"generated dungeon fixture {request.request_id:#x} timed out after {max_frames} frames; "
        f"last_status={result.status.name if result else 'unread'}"
    )
