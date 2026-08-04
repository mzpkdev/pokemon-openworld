def test_quickstart_reaches_overworld(game):
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            return
    raise AssertionError("Quickstart did not reach CB2_Overworld after 3,000 SELECT pulses")
