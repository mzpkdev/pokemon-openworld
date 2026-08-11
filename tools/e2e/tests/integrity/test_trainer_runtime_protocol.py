import struct

from tools.e2e.trainer_battle_journey import (
    TRAINER_BATTLE_SCENARIO_REQUEST_SIZE,
    TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET,
    TRAINER_BATTLE_SCENARIO_RESULT_SIZE,
    TrainerBattleScenarioPhase,
    TrainerBattleScenarioRequest,
    TrainerBattleScenarioResult,
    TrainerBattleScenarioStatus,
    TrainerDefeatStorage,
    TrainerRematchBindingKind,
    submit_trainer_battle_request,
)


def test_trainer_battle_request_layout_has_one_status_commit_byte():
    request = TrainerBattleScenarioRequest(0xD6000001, 858)
    payload = request.pack_idle()

    assert len(payload) == TRAINER_BATTLE_SCENARIO_REQUEST_SIZE
    assert payload[TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET] == (
        TrainerBattleScenarioStatus.IDLE
    )
    assert struct.unpack_from("<I", payload, 0)[0] == request.request_id
    assert struct.unpack_from("<H", payload, 4)[0] == request.trainer_id
    assert payload[6] == request.abi_version
    assert struct.unpack_from("<I", payload, 8)[0] == 0


def test_host_pauses_and_commits_request_status_last():
    class Game:
        def __init__(self):
            self.operations = []

        def address(self, symbol):
            assert symbol == "gTrainerBattleScenarioRequest"
            return 0x02001000

        def pause(self):
            self.operations.append(("pause",))

        def write(self, address, payload):
            self.operations.append(("write", address, payload))

        def write_u8(self, address, value):
            self.operations.append(("write_u8", address, value))

        def resume(self):
            self.operations.append(("resume",))

    game = Game()
    request = TrainerBattleScenarioRequest(0xD6000001, 858)
    submit_trainer_battle_request(game, request)

    assert game.operations[0] == ("pause",)
    assert game.operations[1] == ("write", 0x02001000, request.pack_idle())
    assert game.operations[2] == (
        "write_u8",
        0x02001000 + TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET,
        TrainerBattleScenarioStatus.PENDING,
    )
    assert game.operations[3] == ("resume",)


def test_result_protocol_decodes_party_chain_and_terminal_proof():
    payload = struct.pack(
        "<III5H6H6H6B12B",
        0xD6000002,
        8,
        0x080B9190,
        858,
        858,
        0,
        0,
        0,
        858,
        870,
        870,
        1241,
        1242,
        0xFFFF,
        19,
        23,
        0,
        0,
        0,
        0,
        11,
        11,
        0,
        0,
        0,
        0,
        0,
        TrainerBattleScenarioPhase.FIELD_READY,
        2,
        0,
        TrainerDefeatStorage.BITMAP,
        0,
        TrainerRematchBindingKind.CHAIN,
        1,
        0,
        0,
        1,
        TrainerBattleScenarioStatus.SUCCESS,
    )

    assert len(payload) == TRAINER_BATTLE_SCENARIO_RESULT_SIZE
    result = TrainerBattleScenarioResult.unpack(payload)
    assert result.authored_party == ((19, 11), (23, 11))
    assert result.end_callback == 0x080B9190
    assert result.resolved_rematch_stages == (858, 870, 870, 1241, 1242, None)
    assert result.rematch_kind is TrainerRematchBindingKind.CHAIN
    assert result.defeat_storage is TrainerDefeatStorage.BITMAP
    assert result.battle_outcome == 1
    assert result.defeated_after
    assert result.status is TrainerBattleScenarioStatus.SUCCESS
