import struct

from tools.e2e.trainer_battle_journey import (
    BattleInputPhase,
    BattleInputTransaction,
    BATTLE_MON_STATUS1_OFFSET,
    TRAINER_BATTLE_SCENARIO_REQUEST_SIZE,
    TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET,
    TRAINER_BATTLE_SCENARIO_RESULT_SIZE,
    TrainerBattleScenarioPhase,
    TrainerBattleScenarioRequest,
    TrainerBattleScenarioResult,
    TrainerBattleScenarioStatus,
    TrainerDefeatStorage,
    TrainerRematchBindingKind,
    battle_mon_is_asleep,
    grant_full_obedience_through_debug_menu,
    select_ordinary_fight_action,
    submit_trainer_battle_request,
)


def test_move_input_is_one_transaction_while_handler_and_pp_stay_live():
    transaction = BattleInputTransaction(
        pending_move=214,
        pending_move_index=1,
        pending_pp=10,
    )

    for _ in range(78):
        transaction.observe(
            action_handler_active=False,
            move_handler_active=True,
            controller_active=True,
            attacker=1,
            current_move=0,
            current_pp=10,
        )
        assert transaction.phase is BattleInputPhase.EXECUTION

    transaction.observe(
        action_handler_active=False,
        move_handler_active=True,
        controller_active=True,
        attacker=0,
        current_move=214,
        current_pp=9,
    )
    assert transaction.phase is BattleInputPhase.ACTION

    transaction.observe(
        action_handler_active=False,
        move_handler_active=True,
        controller_active=True,
        attacker=0,
        current_move=0,
        current_pp=9,
    )
    assert transaction.phase is BattleInputPhase.ACTION

    transaction.observe(
        action_handler_active=True,
        move_handler_active=False,
        controller_active=True,
        attacker=0,
        current_move=0,
        current_pp=9,
    )
    transaction.accept_action()
    assert transaction.phase is BattleInputPhase.MOVE

    transaction.accept_move(move_index=1, move_id=214, pp=9)
    assert transaction.phase is BattleInputPhase.EXECUTION


def test_sleep_status_uses_status1_not_adjacent_personality_word():
    class Game:
        def __init__(self, values):
            self.values = values

        def read_u32(self, address):
            return self.values.get(address, 0)

    battle_mon = 0x02001000
    game = Game(
        {
            battle_mon + 76: 7,
            battle_mon + BATTLE_MON_STATUS1_OFFSET: 0,
        }
    )
    assert not battle_mon_is_asleep(game, battle_mon)

    game.values[battle_mon + BATTLE_MON_STATUS1_OFFSET] = 3
    assert battle_mon_is_asleep(game, battle_mon)


def test_full_obedience_is_granted_through_shipped_debug_menu():
    class Game:
        def __init__(self):
            self.badge = False
            self.a_presses = 0
            self.presses = []

        def address(self, symbol):
            return {
                "gBadgeFlags": 0x08001000,
                "sDebugMenu_Actions_Flags": 0x08002000,
            }[symbol]

        def read_u16(self, address):
            assert address == 0x0800100E
            return 0x807

        def read_flag(self, flag):
            assert flag == 0x807
            return self.badge

        def set_buttons(self, **_buttons):
            pass

        def step(self, _frames=1):
            pass

        def wait_until(self, predicate, **_kwargs):
            assert predicate()

        def task_active(self, task):
            assert task == "DebugTask_HandleMenuInput_General"
            return True

        def pointer(self, symbol):
            assert symbol == "sDebugMenuListData"
            return 0x02001000

        def read_u32(self, address):
            assert address == 0x02001004
            return 0x08002000

        def press(self, button, **_frames):
            self.presses.append(button)
            if button == "A":
                self.a_presses += 1
                if self.a_presses == 2:
                    self.badge = True

        def wait_for_controls_unlocked(self, **_kwargs):
            pass

    game = Game()
    grant_full_obedience_through_debug_menu(game)

    assert game.badge
    assert game.presses == ["Down"] * 7 + ["A"] + ["Down"] * 10 + ["A", "B", "B"]


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


def test_fight_selection_normalizes_every_live_action_cursor():
    class Game:
        def __init__(self, cursor):
            self.cursor = cursor
            self.presses = []

        def address(self, symbol):
            assert symbol == "gActionSelectionCursor"
            return 0x02001000

        def read_u8(self, address):
            assert address == 0x02001000
            return self.cursor

        def press(self, button, **frames):
            self.presses.append((button, frames))
            if button == "Left":
                self.cursor &= ~1
            elif button == "Up":
                self.cursor &= ~2

    for initial_cursor in range(4):
        game = Game(initial_cursor)
        select_ordinary_fight_action(game)
        assert game.cursor == 0
        assert [button for button, _ in game.presses] == ["Left", "Up", "A"]
