from tools.e2e.save_file import decode_box_pokemon


TRUCK = (25, 40)
LITTLEROOT = (0, 9)
OLDALE = (0, 10)
ROUTE_101 = (0, 16)
ROUTE_103 = (0, 18)
BRENDAN_HOUSE_1F = (1, 0)
BRENDAN_HOUSE_2F = (1, 1)
MAY_HOUSE_1F = (1, 2)
MAY_HOUSE_2F = (1, 3)
BIRCH_LAB = (1, 4)

VAR_LITTLEROOT_TOWN_STATE = 0x4050
VAR_OLDALE_TOWN_STATE = 0x4051
VAR_ROUTE101_STATE = 0x4060
VAR_LITTLEROOT_HOUSES_STATE_MAY = 0x4082
VAR_BIRCH_LAB_STATE = 0x4084
VAR_LITTLEROOT_HOUSES_STATE_BRENDAN = 0x408C
VAR_LITTLEROOT_RIVAL_STATE = 0x408D
VAR_LITTLEROOT_INTRO_STATE = 0x4092
VAR_OLDALE_RIVAL_STATE = 0x40C7
VAR_CABLE_CLUB_TUTORIAL_STATE = 0x40CD

FLAG_RESCUED_BIRCH = 0x52
FLAG_ADVENTURE_STARTED = 0x74
FLAG_DEFEATED_RIVAL_ROUTE103 = 0x82
FLAG_SYS_POKEMON_GET = 0x860
FLAG_SYS_POKEDEX_GET = 0x861
FLAG_RECEIVED_POKEDEX_FROM_BIRCH = 0x8E4
FLAG_DEBUG_NO_WILD_ENCOUNTERS = 0x8FE

SPECIES_MEW = 151
HOENN_STARTERS = {252, 255, 258}
PARTY_MON_SIZE = 100


def player_party(game):
    count = game.read_u8(game.address("gPartiesCount"))
    mons = game.read(game.address("gParties"), count * PARTY_MON_SIZE)
    return count, [
        mons[offset : offset + PARTY_MON_SIZE]
        for offset in range(0, len(mons), PARTY_MON_SIZE)
    ]


def dismiss_until_var(game, var_id, value, description, max_pulses=800):
    game.advance_until(
        lambda: game.read_var(var_id) == value,
        description=description,
        max_pulses=max_pulses,
    )


def finish_started_battle_with_debug_victory(game, victory_condition, description):
    """Complete a proven live battle through its normal post-battle callback."""
    game.wait_for_callback("BattleMainCB2", max_frames=1_500)
    assert game.callback_is("BattleMainCB2")

    player_controller = game.address("SetControllerToPlayer")
    partner_controller = game.address("SetControllerToPlayerPartner")
    action_handlers = [
        address
        for address in game.symbols.addresses("HandleInputChooseAction")
        if player_controller < address < partner_controller
    ]
    assert len(action_handlers) == 1
    game.advance_until(
        lambda: game.battler_controller_is(action_handlers[0]),
        description=f"{description} action menu",
        max_pulses=1_500,
        button="B",
    )

    # This is reached only after the live battle's action controller is active.
    game.advance_until(
        lambda: game.callback_is("CB2_BattleDebugMenu"),
        description=f"{description} debug menu",
        max_pulses=600,
        button="Select",
    )
    game.wait_until(
        lambda: game.task_active("Task_DebugMenuProcessInput"),
        description=f"{description} debug menu input",
        max_frames=600,
        step_frames=2,
    )
    for _ in range(16):
        game.press("Down")
    game.press("A")
    game.advance_until(
        victory_condition,
        description=description,
        max_pulses=2_000,
    )


def finish_littleroot_intro_and_meet_rival(game, female):
    game.wait_for_map(TRUCK)
    game.wait_until(
        lambda: not game.controls_locked(),
        description="moving truck controls",
        max_frames=1_500,
        step_frames=4,
    )
    game.move_to(x=4, y=2)
    for _ in range(30):
        if game.map_id() != TRUCK:
            break
        game.press("Right", hold_frames=3, release_frames=1)
    home_1f = MAY_HOUSE_1F if female else BRENDAN_HOUSE_1F
    game.advance_until(
        lambda: game.map_id() == home_1f,
        description="arrival cutscene and home entry",
        max_pulses=1_000,
    )

    dismiss_until_var(game, VAR_LITTLEROOT_INTRO_STATE, 4, "arrival conversation")
    game.wait_for_controls_unlocked(max_frames=1_500)
    stair_x = 2 if female else 8
    game.move_to(x=stair_x, y=2)
    game.wait_for_map(MAY_HOUSE_2F if female else BRENDAN_HOUSE_2F)
    game.wait_for_controls_unlocked()

    clock_x = 3 if female else 5
    game.move_to(x=clock_x, y=2)
    game.face("Up")
    game.press("A")
    game.advance_until(
        lambda: game.callback_is("CB2_WallClock"),
        description="clock UI",
        max_pulses=200,
        pulse_frames=4,
    )
    game.step(60)
    for _ in range(200):
        if game.read_var(VAR_LITTLEROOT_INTRO_STATE) == 6:
            break
        game.press("A", release_frames=10)
        game.press("Up", release_frames=4)
        game.press("A", release_frames=10)
    else:
        raise AssertionError("clock confirmation did not set intro state 6")
    game.step(120)
    game.advance_until(
        lambda: not game.controls_locked() and game.script_status() == 2,
        description="post-clock conversation",
        max_pulses=300,
    )

    game.move_to(x=1 if female else 7, y=2)
    downstairs = MAY_HOUSE_1F if female else BRENDAN_HOUSE_1F
    for _ in range(30):
        if game.map_id() == downstairs:
            break
        game.press("Up", hold_frames=3, release_frames=1)
    else:
        raise AssertionError("player-home stairs did not reach 1F")
    dismiss_until_var(game, VAR_LITTLEROOT_INTRO_STATE, 7, "home TV scene")
    game.wait_for_controls_unlocked(max_frames=1_500)
    game.move_to(x=2 if female else 8, y=8)
    game.press("Down", hold_frames=3, release_frames=1)
    game.wait_for_map(LITTLEROOT)

    rival_door_x = 5 if female else 14
    game.move_to(x=rival_door_x, y=9)
    game.move_to(y=8)
    game.wait_for_map(BRENDAN_HOUSE_1F if female else MAY_HOUSE_1F)
    rival_house_state = (
        VAR_LITTLEROOT_HOUSES_STATE_MAY
        if female
        else VAR_LITTLEROOT_HOUSES_STATE_BRENDAN
    )
    game.advance_until(
        lambda: game.read_var(rival_house_state) >= 2,
        description="rival's mother introduction",
    )
    game.wait_for_controls_unlocked()
    game.move_to(x=8 if female else 2, y=2)
    game.wait_for_map(BRENDAN_HOUSE_2F if female else MAY_HOUSE_2F)
    game.move_to(x=4, y=4)
    game.face("Left" if female else "Right")
    game.press("A")
    dismiss_until_var(game, VAR_LITTLEROOT_RIVAL_STATE, 3, "rival introduction")
    assert game.read_var(VAR_LITTLEROOT_TOWN_STATE) == 1

    game.move_to(x=7 if female else 1, y=2)
    downstairs = BRENDAN_HOUSE_1F if female else MAY_HOUSE_1F
    for _ in range(30):
        if game.map_id() == downstairs:
            break
        game.press("Up", hold_frames=3, release_frames=1)
    else:
        raise AssertionError("rival-home stairs did not reach 1F")
    game.wait_for_controls_unlocked()
    game.move_to(x=8 if female else 2, y=8)
    game.press("Down", hold_frames=3, release_frames=1)
    game.wait_for_map(LITTLEROOT)


def rescue_birch_and_receive_starter(game):
    game.move_to(x=11)
    game.move_to(y=1)
    dismiss_until_var(game, VAR_LITTLEROOT_TOWN_STATE, 2, "Littleroot north-gate scene")
    game.advance_until(
        lambda: game.map_id() == ROUTE_101,
        description="Route 101 transition",
        button="Up",
    )
    game.move_to(x=11)
    game.move_to(y=19)
    dismiss_until_var(game, VAR_ROUTE101_STATE, 2, "Birch rescue scene")
    assert game.position() == (11, 15)

    game.move_path((8, 15), (8, 14))
    game.face("Left")
    game.press("A")
    game.wait_for_callback("CB2_ChooseStarter", max_frames=600)
    party_count, party = player_party(game)
    assert party_count == 1
    assert party[0][84] == 100
    assert decode_box_pokemon(party[0])["species"] == SPECIES_MEW
    assert game.read_flag(FLAG_SYS_POKEMON_GET)
    assert game.read_flag(FLAG_RESCUED_BIRCH)

    game.press("A")
    game.advance_until(
        lambda: game.callback_is("CB2_InitBattle") or game.callback_is("BattleMainCB2"),
        description="first battle",
        max_pulses=1_000,
    )
    finish_started_battle_with_debug_victory(
        game,
        lambda: game.map_id() == BIRCH_LAB and game.read_var(VAR_BIRCH_LAB_STATE) >= 2,
        "first battle victory and lab return",
    )
    party_count, party = player_party(game)
    assert party_count == 2
    assert party[0][84] == 100
    assert decode_box_pokemon(party[0])["species"] == SPECIES_MEW
    assert party[1][84] == 5
    assert decode_box_pokemon(party[1])["species"] in HOENN_STARTERS

    # Nickname defaults to Yes; stop on its menu and choose No.
    game.advance_until(
        lambda: game.task_active("Task_HandleYesNoInput"),
        description="starter nickname prompt",
        max_pulses=2_000,
    )
    game.step(30)
    game.press("Down", release_frames=8)
    game.press("A", release_frames=8)
    game.wait_until(
        lambda: not game.task_active("Task_HandleYesNoInput"),
        description="nickname choice accepted",
        max_frames=120,
    )
    # The following travel prompt defaults to Yes.
    game.advance_until(
        lambda: game.task_active("Task_HandleYesNoInput"),
        description="go see rival prompt",
        max_pulses=2_000,
    )
    game.step(30)
    game.press("A", release_frames=8)
    dismiss_until_var(game, VAR_BIRCH_LAB_STATE, 3, "first lab scene")
    game.wait_for_controls_unlocked(max_frames=1_500)


def walk_to_route103_rival(game):
    game.move_to(x=7, y=11)
    game.advance_until(
        lambda: game.map_id() == LITTLEROOT,
        description="lab exit",
        button="Down",
    )
    game.wait_for_controls_unlocked()
    game.move_path((11, None), (11, 2))
    game.advance_until(
        lambda: game.map_id() == ROUTE_101,
        description="Littleroot to Route 101",
        button="Up",
    )
    game.wait_for_controls_unlocked()
    game.move_path(
        (10, 17), (7, 17), (7, 12), (16, 12), (17, 12), (17, 4), (10, 4), (10, 2)
    )
    game.advance_until(
        lambda: game.map_id() == OLDALE,
        description="Route 101 to Oldale",
        button="Up",
    )
    game.wait_for_controls_unlocked()
    game.move_path((10, None), (10, 2))
    game.advance_until(
        lambda: game.map_id() == ROUTE_103,
        description="Oldale to Route 103",
        button="Up",
    )
    game.wait_for_controls_unlocked()
    game.move_path((10, 13), (16, 13), (16, 7), (5, 7), (5, 2), (10, 2))


def defeat_route103_rival_and_receive_pokedex(game):
    walk_to_route103_rival(game)
    game.face("Down")
    game.press("A")
    game.advance_until(
        lambda: game.callback_is("BattleMainCB2"),
        description="Route 103 rival battle",
        max_pulses=1_500,
    )
    assert game.callback_is("BattleMainCB2")
    finish_started_battle_with_debug_victory(
        game,
        lambda: game.read_flag(FLAG_DEFEATED_RIVAL_ROUTE103),
        "Route 103 rival victory",
    )
    assert game.read_var(VAR_BIRCH_LAB_STATE) == 4

    game.wait_for_controls_unlocked(max_frames=1_500)
    game.move_path((10, 4), (5, 4), (5, 7), (16, 7), (16, 13), (10, 13), (10, 17))
    game.advance_until(
        lambda: game.map_id() == OLDALE,
        description="Route 103 return to Oldale",
        button="Down",
    )
    game.move_to(x=10, y=19)
    game.advance_until(
        lambda: game.read_var(VAR_OLDALE_RIVAL_STATE) >= 2,
        description="Oldale rival return scene",
    )
    game.wait_for_controls_unlocked()
    game.advance_until(
        lambda: game.map_id() == ROUTE_101,
        description="Oldale return to Route 101",
        button="Down",
    )
    for _ in range(800):
        if game.map_id() != ROUTE_101:
            break
        game.press("Down", hold_frames=3, release_frames=1)
    else:
        raise AssertionError("Route 101 south exit did not reach Littleroot")
    game.wait_for_map(LITTLEROOT)
    game.move_path((10, 17), (7, 17))
    game.advance_until(
        lambda: game.map_id() == BIRCH_LAB,
        description="final Birch lab entry",
        button="Up",
    )

    game.advance_until(
        lambda: game.read_flag(FLAG_ADVENTURE_STARTED),
        description="Pokédex and Poké Ball presentation",
        max_pulses=2_000,
    )
    assert game.read_flag(FLAG_SYS_POKEDEX_GET)
    assert game.read_flag(FLAG_RECEIVED_POKEDEX_FROM_BIRCH)
    assert game.read_var(VAR_BIRCH_LAB_STATE) == 5
    assert game.read_var(VAR_LITTLEROOT_TOWN_STATE) == 3
    assert game.read_var(VAR_OLDALE_TOWN_STATE) == 1
    assert game.read_var(VAR_LITTLEROOT_RIVAL_STATE) == 4
    assert game.read_var(VAR_CABLE_CLUB_TUTORIAL_STATE) == 1
    assert game.read_u32(game.save_block2() + 0xA8) == 0x803F
    party_count, party = player_party(game)
    assert party_count == 2
    assert party[0][84] == 100
    assert decode_box_pokemon(party[0])["species"] == SPECIES_MEW
    assert party[1][84] == 5
    assert decode_box_pokemon(party[1])["species"] in HOENN_STARTERS


def test_quickstart_to_pokedex(game):
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not reach CB2_Overworld")

    gender = game.read_u8(game.save_block2() + 8)
    assert gender in (0, 1)
    female = gender == 1
    game.set_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)
    assert game.read_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)

    finish_littleroot_intro_and_meet_rival(game, female)
    rescue_birch_and_receive_starter(game)
    defeat_route103_rival_and_receive_pokedex(game)
