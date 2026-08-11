from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
import struct


TRAINER_BATTLE_SCENARIO_ABI_VERSION = 1
TRAINER_BATTLE_SCENARIO_REQUEST_SIZE = 12
TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET = 7
TRAINER_BATTLE_SCENARIO_RESULT_SIZE = 64
BATTLE_TYPE_TRAINER = 1 << 3
TRAINER_NONE = 0
REMATCH_STAGE_SKIP = 0xFFFF
MOVE_WATER_SPOUT = 323
MOVE_SLEEP_TALK = 214
SPECIES_SWAMPERT = 260
ABILITY_DAMP = 6


class TrainerBattleScenarioStatus(IntEnum):
    IDLE = 0
    PENDING = 1
    RUNNING = 2
    SUCCESS = 3
    ERROR = 4


class TrainerBattleScenarioPhase(IntEnum):
    NONE = 0
    VALIDATE = 1
    START = 2
    BATTLE_READY = 3
    POST_BATTLE = 4
    FIELD_READY = 5


class TrainerBattleScenarioError(IntEnum):
    NONE = 0
    NOT_READY = 1
    REQUEST = 2
    ALREADY_DEFEATED = 3
    RESOLVE = 4
    PERSISTENCE_BINDING = 5
    REMATCH_BINDING = 6
    PREFLIGHT = 7
    CONFIGURATION = 8
    OUTCOME = 9
    PERSISTENCE = 10


class TrainerRematchBindingKind(IntEnum):
    INVALID = 0
    NONE = 1
    MATCH_CALL = 2
    CHAIN = 3


class TrainerDefeatStorage(IntEnum):
    FLAG = 0
    VARIABLE_BIT = 1
    BITMAP = 2


@dataclass(frozen=True)
class TrainerBattleScenarioRequest:
    request_id: int
    trainer_id: int
    abi_version: int = TRAINER_BATTLE_SCENARIO_ABI_VERSION
    reserved: int = 0

    def pack_idle(self) -> bytes:
        payload = struct.pack(
            "<IHBBI",
            self.request_id,
            self.trainer_id,
            self.abi_version,
            TrainerBattleScenarioStatus.IDLE,
            self.reserved,
        )
        assert len(payload) == TRAINER_BATTLE_SCENARIO_REQUEST_SIZE
        return payload


@dataclass(frozen=True)
class TrainerBattleScenarioResult:
    request_id: int
    battle_type_flags: int
    end_callback: int
    trainer_id: int
    opponent_a: int
    opponent_b: int
    defeat_id: int
    rematch_index: int
    rematch_stages: tuple[int, ...]
    party_species: tuple[int, ...]
    party_levels: tuple[int, ...]
    error: TrainerBattleScenarioError
    phase: TrainerBattleScenarioPhase
    party_size: int
    difficulty: int
    defeat_storage: TrainerDefeatStorage
    defeat_bit: int
    rematch_kind: TrainerRematchBindingKind
    battle_outcome: int
    is_debug_battle: bool
    defeated_before: bool
    defeated_after: bool
    status: TrainerBattleScenarioStatus

    @classmethod
    def unpack(cls, payload: bytes) -> "TrainerBattleScenarioResult":
        if len(payload) != TRAINER_BATTLE_SCENARIO_RESULT_SIZE:
            raise ValueError(
                f"trainer battle result is {len(payload)} bytes; "
                f"expected {TRAINER_BATTLE_SCENARIO_RESULT_SIZE}"
            )
        fields = struct.unpack("<III5H6H6H6B12B", payload)
        return cls(
            request_id=fields[0],
            battle_type_flags=fields[1],
            end_callback=fields[2],
            trainer_id=fields[3],
            opponent_a=fields[4],
            opponent_b=fields[5],
            defeat_id=fields[6],
            rematch_index=fields[7],
            rematch_stages=tuple(fields[8:14]),
            party_species=tuple(fields[14:20]),
            party_levels=tuple(fields[20:26]),
            error=TrainerBattleScenarioError(fields[26]),
            phase=TrainerBattleScenarioPhase(fields[27]),
            party_size=fields[28],
            difficulty=fields[29],
            defeat_storage=TrainerDefeatStorage(fields[30]),
            defeat_bit=fields[31],
            rematch_kind=TrainerRematchBindingKind(fields[32]),
            battle_outcome=fields[33],
            is_debug_battle=bool(fields[34]),
            defeated_before=bool(fields[35]),
            defeated_after=bool(fields[36]),
            status=TrainerBattleScenarioStatus(fields[37]),
        )

    @property
    def authored_party(self) -> tuple[tuple[int, int], ...]:
        return tuple(
            zip(
                self.party_species[: self.party_size],
                self.party_levels[: self.party_size],
            )
        )

    @property
    def resolved_rematch_stages(self) -> tuple[int | None, ...]:
        return tuple(
            None if trainer_id == REMATCH_STAGE_SKIP else trainer_id
            for trainer_id in self.rematch_stages
        )


def read_trainer_battle_result(game) -> TrainerBattleScenarioResult:
    return TrainerBattleScenarioResult.unpack(
        game.read(
            game.address("gTrainerBattleScenarioResult"),
            TRAINER_BATTLE_SCENARIO_RESULT_SIZE,
        )
    )


def submit_trainer_battle_request(game, request: TrainerBattleScenarioRequest) -> None:
    submit_raw_trainer_battle_request(
        game,
        request,
        TrainerBattleScenarioStatus.PENDING,
    )


def submit_raw_trainer_battle_request(
    game,
    request: TrainerBattleScenarioRequest,
    commit_status: int,
) -> None:
    address = game.address("gTrainerBattleScenarioRequest")
    game.pause()
    game.write(address, request.pack_idle())
    # Status is the request commit byte; the hook cannot see a partial payload.
    game.write_u8(
        address + TRAINER_BATTLE_SCENARIO_REQUEST_STATUS_OFFSET,
        commit_status,
    )
    game.resume()


def _raise_scenario_error(result: TrainerBattleScenarioResult) -> None:
    raise AssertionError(
        f"trainer battle request {result.request_id:#x} failed: "
        f"phase={result.phase.name}, error={result.error.name}"
    )


def wait_for_battle_ready(
    game,
    request: TrainerBattleScenarioRequest,
    *,
    max_frames: int = 2_400,
) -> TrainerBattleScenarioResult:
    for _ in range(max_frames):
        result = read_trainer_battle_result(game)
        if result.request_id == request.request_id:
            if result.status is TrainerBattleScenarioStatus.ERROR:
                _raise_scenario_error(result)
            if result.phase is TrainerBattleScenarioPhase.BATTLE_READY:
                if result.status is not TrainerBattleScenarioStatus.RUNNING:
                    raise AssertionError("battle-ready result is not RUNNING")
                return result
        game.step()
    raise TimeoutError(
        f"trainer battle request {request.request_id:#x} did not reach BATTLE_READY"
    )


def wait_for_scenario_terminal(
    game,
    request: TrainerBattleScenarioRequest,
    *,
    action_handler: int,
    move_handler: int,
    target_handler: int,
    message_handler: int,
    status_handler: int,
    move_index: int,
    sleep_move_index: int,
    move_id: int,
    selected_pp: int,
    max_pulses: int = 5_000,
) -> TrainerBattleScenarioResult:
    move_selections = 0
    party_switches = 0
    observed_move_execution = False
    selected_target_index = game.read_u8(game.address("gBattlerPartyIndexes") + 1)
    selected_target_species = game.read_u16(game.address("gBattleMons") + 140)
    selected_target_fainted = False
    for _ in range(max_pulses):
        result = read_trainer_battle_result(game)
        if result.request_id == request.request_id:
            if result.status is TrainerBattleScenarioStatus.ERROR:
                _raise_scenario_error(result)
            if result.status is TrainerBattleScenarioStatus.SUCCESS:
                if not observed_move_execution:
                    raise AssertionError("ordinary move execution was not observed")
                return result
        if (
            game.read_u8(game.address("gBattlerAttacker")) == 0
            and game.read_u16(game.address("gCurrentMove")) == move_id
            and game.read_u8(game.address("gBattleMons") + 37 + move_index)
            < selected_pp
        ):
            observed_move_execution = True
        if game.task_active("Task_HandleChooseMonInput"):
            party_switches += 1
            game.step(60)
            for _ in range(party_switches):
                game.press("Down", hold_frames=3, release_frames=3)
            selected_slot = game.read_u8(game.address("gPartyMenu") + 9)
            if selected_slot != party_switches:
                raise AssertionError(
                    f"party cursor is on slot {selected_slot}, expected {party_switches}"
                )
            game.press("A", release_frames=4)
            continue
        if game.task_active("Task_HandleSelectionMenuInput"):
            game.press("A", release_frames=8)
            continue
        if game.callback_is("BattleMainCB2"):
            battle_mons = game.address("gBattleMons")
            opponent_hp = game.read_u16(battle_mons + 140 + 42)
            opponent_index = game.read_u8(game.address("gBattlerPartyIndexes") + 1)
            opponent_species = game.read_u16(battle_mons + 140)
            if opponent_hp == 0:
                selected_target_fainted = True
            elif (
                opponent_index != selected_target_index
                or opponent_species != selected_target_species
            ):
                selected_target_fainted = False
            if any(
                game.battler_controller_is(message_handler, battler=battler)
                for battler in range(4)
            ):
                game.press("A", hold_frames=2, release_frames=4)
                continue
            if any(
                game.battler_controller_is(status_handler, battler=battler)
                for battler in range(4)
            ):
                game.step(16)
                continue
            if game.battler_controller_is(target_handler):
                game.press("A", hold_frames=2, release_frames=8)
                continue
            if (
                game.read_u16(battle_mons + 42) == 0
                or opponent_hp == 0
                or selected_target_fainted
            ):
                game.step(16)
                continue
            if game.battler_controller_is(action_handler):
                select_ordinary_fight_action(game)
                continue
            if game.battler_controller_is(move_handler):
                is_asleep = game.read_u32(battle_mons + 80) & 7
                selected_index = sleep_move_index if is_asleep else move_index
                selected_move = MOVE_SLEEP_TALK if is_asleep else move_id
                selected_pp = game.read_u8(battle_mons + 37 + selected_index)
                selected_target_index = opponent_index
                selected_target_species = opponent_species
                select_ordinary_move(game, selected_index, selected_move)
                move_selections += 1
                continue
        game.step(16)
    battle_mons = game.address("gBattleMons")
    raise TimeoutError(
        f"trainer battle request {request.request_id:#x} did not finish; "
        f"callback2={game.read_u32(game.address('gMain') + 4):#x}, "
        f"controllers={tuple(hex(game.read_u32(game.address('gBattlerControllerFuncs') + battler * 4)) for battler in range(4))}, "
        f"player_hp={game.read_u16(battle_mons + 42)}, "
        f"opponent_hp={game.read_u16(battle_mons + 140 + 42)}, "
        f"chosen_move={game.read_u16(game.address('gChosenMoveByBattler'))}, "
        f"pp={tuple(game.read(battle_mons + 37, 4))}, "
        f"move_selections={move_selections}, "
        f"party_switches={party_switches}, "
        f"battle_script={game.read_u32(game.address('gBattlescriptCurrInstr')):#x}, "
        f"controller_flags={game.read_u32(game.address('gBattleControllerExecFlags')):#x}, "
        f"outcome={game.read_u8(game.address('gBattleOutcome'))}"
    )


def wait_for_raw_scenario_terminal(
    game,
    request_id: int,
    *,
    max_frames: int = 600,
) -> TrainerBattleScenarioResult:
    for _ in range(max_frames + 1):
        result = read_trainer_battle_result(game)
        if result.request_id == request_id and result.status in (
            TrainerBattleScenarioStatus.SUCCESS,
            TrainerBattleScenarioStatus.ERROR,
        ):
            return result
        game.step()
    raise TimeoutError(f"trainer battle request {request_id:#x} did not terminate")


def set_battle_party_through_debug_menu(game, *, _remaining: int = 6) -> None:
    """Give six level-100 Damp Swampert through the shipped debug menu."""
    game.set_buttons(R=True)
    game.step()
    game.set_buttons(R=True, Start=True)
    game.step()
    game.set_buttons(R=False, Start=False)
    game.step()
    game.wait_until(
        lambda: game.task_active("DebugTask_HandleMenuInput_General"),
        description="debug main menu",
        max_frames=300,
    )
    game.step(4)

    for _ in range(3):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            (menu_data := game.pointer("sDebugMenuListData"))
            and game.read_u32(menu_data + 4) == game.address("sDebugMenu_Actions_Give")
        ),
        description="Give debug submenu",
        max_frames=300,
    )
    game.step(4)
    for _ in range(2):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectId"),
        description="basic Pokémon species selector",
        max_frames=300,
    )
    game.step(4)

    game.press("Right", release_frames=2)
    game.press("Right", release_frames=2)
    for _ in range(2):
        game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    for _ in range(6):
        game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectLevel"),
        description="basic Pokémon level selector",
        max_frames=300,
    )
    game.step(4)
    game.press("Right", release_frames=2)
    for _ in range(9):
        game.press("Up", release_frames=2)
    game.press("Right", release_frames=2)
    game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectShiny"),
        description="complex Pokémon shiny selector",
        max_frames=300,
    )
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectNature"),
        description="complex Pokémon nature selector",
        max_frames=300,
    )
    for _ in range(4):
        game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectAbility"),
        description="complex Pokémon ability selector",
        max_frames=300,
    )
    game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    for task_name in (
        "DebugAction_Give_Pokemon_SelectTeraType",
        "DebugAction_Give_Pokemon_SelectDynamaxLevel",
        "DebugAction_Give_Pokemon_SelectGigantamaxFactor",
    ):
        game.wait_until(
            lambda task_name=task_name: game.task_active(task_name),
            description=task_name,
            max_frames=300,
        )
        game.press("A", release_frames=2)
    for stat in range(6):
        game.wait_until(
            lambda: game.task_active("DebugAction_Give_Pokemon_SelectIVs"),
            description="complex Pokémon IV selector",
            max_frames=300,
        )
        game.press("Right", release_frames=2)
        for _ in range(3):
            game.press("Up", release_frames=2)
        game.press("Left", release_frames=2)
        game.press("Up", release_frames=2)
        if stat in (0, 1):
            game.press("Right", release_frames=2)
            game.press("Right", release_frames=2)
            for _ in range(2):
                game.press("Up", release_frames=2)
            game.press("Left", release_frames=2)
            for _ in range(5):
                game.press("Up", release_frames=2)
            game.press("Left", release_frames=2)
            for _ in range(2):
                game.press("Up", release_frames=2)
        game.press("A", release_frames=2)
    for _ in range(6):
        game.wait_until(
            lambda: game.task_active("DebugAction_Give_Pokemon_SelectEVs"),
            description="complex Pokémon EV selector",
            max_frames=300,
        )
        game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_Move"),
        description="complex Pokémon move selector",
        max_frames=300,
    )
    game.press("Right", release_frames=2)
    game.press("Right", release_frames=2)
    for _ in range(3):
        game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    for _ in range(2):
        game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    for _ in range(3):
        game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_Move"),
        description="complex Pokémon second move selector",
        max_frames=300,
    )
    game.press("Right", release_frames=2)
    game.press("Right", release_frames=2)
    for _ in range(2):
        game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    game.press("Up", release_frames=2)
    game.press("Left", release_frames=2)
    for _ in range(4):
        game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_Move"),
        description="complex Pokémon third move selector",
        max_frames=300,
    )
    game.press("A", release_frames=2)
    game.wait_for_controls_unlocked(max_frames=600)
    if not any(game.read(game.address("gParties"), 100)):
        raise AssertionError("shipped debug battle party was not installed")
    if _remaining > 1:
        set_battle_party_through_debug_menu(game, _remaining=_remaining - 1)
    if _remaining == 6:
        party_count = game.read_u8(game.address("gPartiesCount"))
        if party_count != 6:
            raise AssertionError(
                f"shipped debug battle party has {party_count} mons, expected 6"
            )


def heal_party_through_debug_menu(game) -> None:
    """Use the shipped Party > Heal party action between ordinary battles."""
    game.set_buttons(R=True)
    game.step()
    game.set_buttons(R=True, Start=True)
    game.step()
    game.set_buttons(R=False, Start=False)
    game.step()
    game.wait_until(
        lambda: game.task_active("DebugTask_HandleMenuInput_General"),
        description="debug main menu",
        max_frames=300,
    )
    game.step(4)
    for _ in range(2):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            (menu_data := game.pointer("sDebugMenuListData"))
            and game.read_u32(menu_data + 4) == game.address("sDebugMenu_Actions_Party")
        ),
        description="Party debug submenu",
        max_frames=300,
    )
    game.step(4)
    for _ in range(2):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_for_controls_unlocked(max_frames=600)


def disable_battle_animations_through_options(game) -> None:
    """Turn Battle Scene off through the shipped Options UI."""
    game.press("Start", release_frames=20)
    game.wait_until(
        lambda: game.read_u8(game.address("sNumStartMenuActions")) > 0,
        description="start menu",
        max_frames=300,
    )
    actions = game.read(
        game.address("sCurrentStartMenuActions"),
        game.read_u8(game.address("sNumStartMenuActions")),
    )
    options_index = actions.index(6)
    cursor = game.read_u8(game.address("sStartMenuCursorPos"))
    for _ in range((options_index - cursor) % len(actions)):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: game.task_active("Task_OptionMenuProcessInput"),
        description="options menu",
        max_frames=600,
    )
    game.press("Down", release_frames=3)
    game.press("Right", release_frames=3)
    game.press("Down", release_frames=3)
    game.press("Right", release_frames=3)
    game.press("B", release_frames=8)
    game.wait_until(
        lambda: (
            game.read_u32(game.address("gMenuCallback"))
            == (game.address("HandleStartMenuInput") | 1)
        ),
        description="returned start menu",
        max_frames=1_200,
        step_frames=4,
    )
    game.press("B", release_frames=8)
    game.wait_for_controls_unlocked(max_frames=600)


def select_ordinary_move(game, move_index: int, move_id: int) -> None:
    game.press("Left", release_frames=4)
    game.press("Up", release_frames=4)
    if move_index in (1, 3):
        game.press("Right", release_frames=4)
    if move_index in (2, 3):
        game.press("Down", release_frames=4)
    selected_move = game.read_u8(game.address("gMoveSelectionCursor"))
    if selected_move != move_index:
        raise AssertionError(
            f"ordinary move cursor is {selected_move}, expected {move_index}"
        )
    game.press("A", hold_frames=2, release_frames=8)
    chosen_move = game.read_u16(game.address("gChosenMoveByBattler"))
    if chosen_move != move_id:
        raise AssertionError(
            f"production chosen move is {chosen_move}, expected {move_id}"
        )


def select_ordinary_fight_action(game) -> None:
    """Select Fight through the production action-menu input handler."""
    game.press("Left", release_frames=4)
    game.press("Up", release_frames=4)
    selected_action = game.read_u8(game.address("gActionSelectionCursor"))
    if selected_action != 0:
        raise AssertionError(
            f"ordinary action cursor is {selected_action}, expected Fight"
        )
    game.press("A", release_frames=8)


def win_battle_through_normal_input(
    game, move_id: int
) -> tuple[int, int, int, int, int, int, int, int]:
    """Choose Fight and a live move through the production input handlers."""
    player_controller = game.address("SetControllerToPlayer")
    partner_controller = game.address("SetControllerToPlayerPartner")
    action_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseAction")
        if player_controller < address < partner_controller
    ]
    if len(action_handlers) != 1:
        raise AssertionError(
            f"expected one player action handler, found {action_handlers!r}"
        )
    move_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseMove")
        if player_controller < address < partner_controller
    ]
    if len(move_handlers) != 1:
        raise AssertionError(
            f"expected one player move handler, found {move_handlers!r}"
        )

    message_handler = game.address("Controller_WaitForString")
    status_handler = game.address("Controller_WaitForStatusAnimation")
    target_handler = game.address("HandleInputChooseTarget")
    for _ in range(1_500):
        if game.battler_controller_is(action_handlers[0]):
            break
        if game.battler_controller_is(message_handler):
            game.press("A", hold_frames=2, release_frames=4)
        else:
            game.step(16)
    else:
        actual = game.read_u32(game.address("gBattlerControllerFuncs"))
        raise AssertionError(
            f"ordinary trainer battle action menu not reached; controller={actual:#x}"
        )
    moves = struct.unpack("<4H", game.read(game.address("gBattleMons") + 12, 8))
    battle_mon = game.address("gBattleMons")
    species = game.read_u16(battle_mon)
    ability = game.read_u16(battle_mon + 32)
    level = game.read_u8(battle_mon + 44)
    hp = game.read_u16(battle_mon + 42)
    pp = tuple(game.read(battle_mon + 37, 4))
    if (species, ability, level) != (SPECIES_SWAMPERT, ABILITY_DAMP, 100):
        raise AssertionError(
            "ordinary battle fixture is not live Damp Swampert: "
            f"species={species}, ability={ability}, level={level}"
        )
    if move_id not in moves:
        raise AssertionError(
            f"level-100 Swampert is missing requested move {move_id}: {moves!r}"
        )
    move_index = moves.index(move_id)
    if MOVE_SLEEP_TALK not in moves:
        raise AssertionError(f"level-100 Swampert is missing Sleep Talk: {moves!r}")
    sleep_move_index = moves.index(MOVE_SLEEP_TALK)
    if hp == 0 or pp[move_index] == 0:
        raise AssertionError(f"ordinary battle fixture is not ready: hp={hp}, pp={pp}")
    select_ordinary_fight_action(game)
    game.wait_until(
        lambda: game.battler_controller_is(move_handlers[0]),
        description="ordinary trainer battle move menu",
        max_frames=2_400,
        step_frames=8,
    )
    select_ordinary_move(game, move_index, move_id)
    return (
        action_handlers[0],
        move_handlers[0],
        target_handler,
        message_handler,
        status_handler,
        move_index,
        sleep_move_index,
        pp[move_index],
    )


def run_ordinary_trainer_battle(
    game,
    request: TrainerBattleScenarioRequest,
    *,
    move_id: int = MOVE_WATER_SPOUT,
) -> tuple[TrainerBattleScenarioResult, TrainerBattleScenarioResult]:
    submit_trainer_battle_request(game, request)
    ready = wait_for_battle_ready(game, request)
    # The hook captures the party at the end of CB2_InitBattle, before the
    # normal battle callback becomes visible on the following frames.
    game.wait_for_callback("BattleMainCB2", max_frames=1_500)
    if not game.callback_is("BattleMainCB2"):
        raise AssertionError("hook did not enter BattleMainCB2")
    if ready.battle_type_flags != BATTLE_TYPE_TRAINER:
        raise AssertionError(
            f"battle flags are {ready.battle_type_flags:#x}, expected "
            f"BATTLE_TYPE_TRAINER ({BATTLE_TYPE_TRAINER:#x})"
        )
    expected_end_callback = game.address("CB2_EndTrainerBattle")
    # MainCallback values carry the Thumb-state bit; the linked symbol does not.
    if ready.end_callback & ~1 != expected_end_callback:
        raise AssertionError(
            f"saved callback is {ready.end_callback:#x}, expected production "
            f"CB2_EndTrainerBattle ({expected_end_callback:#x})"
        )
    if ready.opponent_a != request.trainer_id or ready.opponent_b != TRAINER_NONE:
        raise AssertionError(
            f"wrong opponents: A={ready.opponent_a}, B={ready.opponent_b}"
        )
    if ready.is_debug_battle:
        raise AssertionError("ordinary battle was marked as a debug battle")
    (
        action_handler,
        move_handler,
        target_handler,
        message_handler,
        status_handler,
        move_index,
        sleep_move_index,
        selected_pp,
    ) = win_battle_through_normal_input(game, move_id)
    finished = wait_for_scenario_terminal(
        game,
        request,
        action_handler=action_handler,
        move_handler=move_handler,
        target_handler=target_handler,
        message_handler=message_handler,
        status_handler=status_handler,
        move_index=move_index,
        sleep_move_index=sleep_move_index,
        move_id=move_id,
        selected_pp=selected_pp,
    )
    if finished.battle_outcome != 1 or not finished.defeated_after:
        raise AssertionError(
            f"victory did not persist through the production callback: {finished!r}"
        )
    # The result commits as soon as the overworld callback is restored. Let the
    # normal post-battle field script finish unlocking controls before the next
    # request (or the real start-menu save) begins.
    game.wait_for_controls_unlocked(max_frames=1_500)
    return ready, finished
