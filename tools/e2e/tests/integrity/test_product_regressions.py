def test_product_boots_to_title(game):
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)


def test_new_game_initialization_reaches_unlocked_overworld(game):
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not initialize a new game")

    game.wait_for_controls_unlocked(max_frames=1_200)
    assert not game.controls_locked()


def test_existing_hoenn_save_continues(game_from_hoenn_save):
    game_from_hoenn_save.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game_from_hoenn_save.press("A")
        if game_from_hoenn_save.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Continue did not reach the overworld from the Hoenn save")

    game_from_hoenn_save.wait_for_controls_unlocked(max_frames=1_200)
    assert game_from_hoenn_save.map_id() == (0, 9)
    assert not game_from_hoenn_save.controls_locked()
