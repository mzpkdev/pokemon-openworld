import struct
from pathlib import Path

from tools.e2e.generate_populated_fixture import (
    INSTRUMENTATION_PATCH_SHA256,
    instrumentation_overlay,
    overlay_sha256,
)

from tools.e2e.save_journey import (
    SAVE_SCENARIO_SIZE,
    SAVE_SCENARIO_STATUS_OFFSET,
    SaveScenarioRequest,
    SaveScenarioStatus,
    run_save_scenario,
)


def _request():
    return SaveScenarioRequest(0x12345678, 25, 133, 132, 133, 273, 135, 1, 20, 0, 0, 64)


def test_request_layout_keeps_status_as_last_commit_byte():
    payload = _request().pack_idle()
    assert len(payload) == SAVE_SCENARIO_SIZE
    assert payload[SAVE_SCENARIO_STATUS_OFFSET] == SaveScenarioStatus.IDLE
    assert struct.unpack_from("<I", payload, 0)[0] == 0x12345678
    assert struct.unpack_from("<H", payload, 22)[0] == 64


def test_host_commits_status_last_and_correlates_result():
    class Game:
        def __init__(self):
            self.writes = []
            self.result = bytes(SAVE_SCENARIO_SIZE)

        def address(self, symbol):
            return {"gSaveScenarioRequest": 0x1000, "gSaveScenarioResult": 0x2000}[
                symbol
            ]

        def pause(self):
            self.writes.append(("pause",))

        def resume(self):
            self.writes.append(("resume",))

        def write(self, address, payload):
            self.writes.append((address, payload))

        def write_u8(self, address, value):
            self.writes.append((address, value))

        def read(self, address, size):
            return self.result

        def step(self):
            request = _request()
            self.result = struct.pack(
                "<I7H4BHIIHH",
                request.request_id,
                0,
                0,
                0,
                133,
                1,
                request.reward_item,
                request.checkpoint_id,
                request.facility_id,
                1,
                1,
                SaveScenarioStatus.SUCCESS,
                request.trainer_id,
                request.rng_seed,
                request.player_trainer_id,
                request.abi_version,
                0xE2E,
            )

    game = Game()
    result = run_save_scenario(game, _request())
    assert game.writes[0] == ("pause",)
    assert game.writes[1][0] == 0x1000
    assert game.writes[2] == (
        0x1000 + SAVE_SCENARIO_STATUS_OFFSET,
        SaveScenarioStatus.PENDING,
    )
    assert game.writes[3] == ("resume",)
    assert result.trainer_flag == 64


def test_historical_instrumentation_digest_is_tracked_and_mutation_sensitive():
    root = Path(__file__).parents[4]
    bases, overlay = instrumentation_overlay(root)
    assert overlay_sha256(bases, overlay) == INSTRUMENTATION_PATCH_SHA256

    mutated = dict(overlay)
    path = "src/debug_save_scenario.c"
    mutated[path] = mutated[path].replace(b"requestId", b"requestID", 1)
    assert overlay_sha256(bases, mutated) != INSTRUMENTATION_PATCH_SHA256
