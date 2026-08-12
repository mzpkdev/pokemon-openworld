from __future__ import annotations

from enum import IntEnum
import struct


START_PROFILE_REQUEST_SIZE = 8
START_PROFILE_REQUEST_STATUS_OFFSET = 7


class StartProfile(IntEnum):
    HOENN = 0
    KANTO = 1
    JOHTO = 2


class StartProfileStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    ACCEPTED = 2
    ERROR = 3


def submit_start_profile(game, profile: int, request_id: int) -> None:
    payload = struct.pack(
        "<IHBB", request_id, 1, profile, StartProfileStatus.IDLE
    )
    assert len(payload) == START_PROFILE_REQUEST_SIZE
    address = game.address("gDebugNewGameStartProfileRequest")
    game.pause()
    game.write(address, payload)
    # PENDING is the commit byte and must be the final host write.
    game.write_u8(
        address + START_PROFILE_REQUEST_STATUS_OFFSET,
        StartProfileStatus.PENDING,
    )
    game.resume()


def start_profile_status(game) -> StartProfileStatus:
    address = game.address("gDebugNewGameStartProfileRequest")
    return StartProfileStatus(
        game.read_u8(address + START_PROFILE_REQUEST_STATUS_OFFSET)
    )


def quickstart_with_profile(game, profile: int, request_id: int) -> None:
    # Let crt0 clear BSS and enter AgbMain before committing the host request.
    game.step(2)
    submit_start_profile(game, profile, request_id)
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not initialize a new game")
    game.wait_for_controls_unlocked(max_frames=1_200)
