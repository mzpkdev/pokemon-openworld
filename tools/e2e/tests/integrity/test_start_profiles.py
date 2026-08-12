import struct

import pytest

from tools.e2e.save_journey import save_from_start_menu
from tools.e2e.start_profile import (
    StartProfile,
    StartProfileStatus,
    quickstart_with_profile,
    start_profile_status,
)


DIR_SOUTH = 1
PROFILE_EXPECTATIONS = {
    StartProfile.HOENN: {"map": (25, 40), "position": None, "checkpoint": None},
    StartProfile.KANTO: {"map": (37, 0), "position": (6, 8), "checkpoint": (37, 0, 6, 8)},
    StartProfile.JOHTO: {"map": (89, 0), "position": (15, 44), "checkpoint": (89, 0, 15, 44)},
}


def _checkpoint(game) -> tuple[int, int, int, int, int]:
    raw = game.read(game.save_block1() + 0x1C, 8)
    map_group, map_num, warp_id, _padding, x, y = struct.unpack("<bbbBhh", raw)
    return map_group, map_num, warp_id, x, y


def _assert_profile(game, profile: StartProfile) -> None:
    expected = PROFILE_EXPECTATIONS[profile]
    assert game.map_id() == expected["map"]
    if expected["position"] is not None:
        assert game.position() == expected["position"]
    assert game.facing_direction() == DIR_SOUTH
    assert not game.controls_locked()
    encryption_key = game.read_u32(game.save_block2() + 0xAC)
    assert game.read_u32(game.save_block1() + 0x490) ^ encryption_key == 3000
    assert game.read_u16(game.save_block1() + 0x494) ^ (encryption_key & 0xFFFF) == 0
    assert game.read_u8(game.address("gPartiesCount")) == 0
    if profile == StartProfile.HOENN:
        # The unchanged truck onboarding owns the gender-dependent home checkpoint;
        # the regional profile must not preempt it before the player exits the truck.
        assert _checkpoint(game) == (0, 0, 0, 0, 0)
    else:
        group, number, x, y = expected["checkpoint"]
        assert _checkpoint(game) == (group, number, -1, x, y)


def _serialized_payloads(image) -> tuple[bytes, bytes, bytes]:
    block1 = bytearray(image.active_slot.save_block1)
    block2 = bytearray(image.active_slot.save_block2)
    # Saving legitimately increments GAME_STAT_SAVED_GAME and the play timer.
    # The truck's live player object also records the last copyable movement used
    # to enter the menu. Normalize only those established fields before comparing
    # every other byte.
    block1[0xA52] = 0
    block1[0x159C:0x15A0] = bytes(4)
    block2[0x0E:0x13] = bytes(5)
    return bytes(block1), bytes(block2), image.active_slot.pokemon_storage


def _save_and_settle(game):
    save_from_start_menu(game)
    game.wait_for_controls_unlocked(max_frames=1_200)
    return game.battery_snapshot()


@pytest.mark.parametrize("profile", list(StartProfile))
def test_profile_start_and_transient_selector_are_save_neutral(session_factory, profile):
    game = session_factory()
    quickstart_with_profile(game, profile, 0x53544110 + profile)
    assert start_profile_status(game) == StartProfileStatus.ACCEPTED
    _assert_profile(game, profile)
    before = _serialized_payloads(_save_and_settle(game))

    # Mutate every selector identity field after consumption, including an invalid
    # ABI/profile pair. A second real flash save must serialize no trace of it.
    request = struct.pack("<IHBB", 0xA5A50000 + profile, 0xFFFF, 0xFE, 0)
    game.pause()
    game.write(game.address("gDebugNewGameStartProfileRequest"), request)
    game.resume()
    after = _serialized_payloads(_save_and_settle(game))

    differences = [
        (domain, index)
        for domain, (left, right) in enumerate(zip(before, after))
        for index, (a, b) in enumerate(zip(left, right))
        if a != b
    ]
    assert before == after, differences[:64]


def test_invalid_debug_profile_fails_closed_to_hoenn(session_factory):
    game = session_factory()
    quickstart_with_profile(game, 0xFF, 0xBAD50001)
    assert start_profile_status(game) == StartProfileStatus.ERROR
    _assert_profile(game, StartProfile.HOENN)
