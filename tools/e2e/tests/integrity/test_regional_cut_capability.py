from pathlib import Path

import pytest

from tools.e2e.generate_cut_oracle import load_reviewed_oracle
from tools.e2e.save_file import (
    SaveImage,
    is_strictly_newer_save_counter,
    with_saved_flags,
)
from tools.e2e.save_journey import (
    cold_restart_and_continue,
    probe_field_move,
    save_from_start_menu,
)


FIXTURES = Path(__file__).parents[2] / "fixtures"
ORACLE = load_reviewed_oracle(FIXTURES / "regional_cut_oracle.json")
BASE_FIXTURE = FIXTURES / ORACLE["source"]["baseFixture"]
FIELD_MOVE_CUT = 0
FLAG_REGIONAL_FACT_HOENN_STONE_BADGE = 0x20
FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE = 0x21
FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE = 0x22
FLAG_BADGE01_GET = 0x867
FLAG_BADGE02_GET = 0x868
REGIONAL_FACTS = (
    FLAG_REGIONAL_FACT_HOENN_STONE_BADGE,
    FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE,
    FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE,
)


def _continue_to_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("regional Cut fixture did not Continue")
    game.wait_for_controls_unlocked(max_frames=1_200)


def _quickstart_to_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("regional Cut Quickstart did not reach overworld")
    game.wait_for_controls_unlocked(max_frames=1_200)


def _assert_no_regional_facts(game) -> None:
    assert all(not game.read_flag(flag) for flag in REGIONAL_FACTS)


@pytest.mark.parametrize(
    "scenario", ORACLE["matrix"], ids=[item["name"] for item in ORACLE["matrix"]]
)
def test_historical_cut_matrix_matches_oracle_through_resave_and_restart(
    session_factory, tmp_path, scenario
):
    base = SaveImage.from_path(BASE_FIXTURE)
    assert base.sha256 == ORACLE["source"]["baseFixtureSha256"]
    scenario_index = ORACLE["matrix"].index(scenario)
    variant = with_saved_flags(
        base,
        {
            FLAG_BADGE01_GET: scenario["legacySlot1"],
            FLAG_BADGE02_GET: scenario["legacySlot2"],
            **{flag: False for flag in REGIONAL_FACTS},
        },
    )
    save = tmp_path / f"regional-cut-{scenario['name']}.sav"
    save.write_bytes(variant.data)
    game = session_factory(battery_save=save)

    _continue_to_overworld(game)
    _assert_no_regional_facts(game)
    assert (
        probe_field_move(game, FIELD_MOVE_CUT, 0x4E455700 + scenario_index)
        is scenario["cutUnlocked"]
    )

    rewritten = save_from_start_menu(game)
    assert is_strictly_newer_save_counter(
        rewritten.active_slot.counter, variant.active_slot.counter
    )
    assert all(not rewritten.active_slot.saved_flag(flag) for flag in REGIONAL_FACTS)
    assert rewritten.active_slot.saved_flag(FLAG_BADGE01_GET) is scenario["legacySlot1"]
    assert rewritten.active_slot.saved_flag(FLAG_BADGE02_GET) is scenario["legacySlot2"]

    cold_restart_and_continue(game)
    _assert_no_regional_facts(game)
    assert (
        probe_field_move(game, FIELD_MOVE_CUT, 0x434F4C00 + scenario_index)
        is scenario["cutUnlocked"]
    )


@pytest.mark.parametrize("regional_fact", REGIONAL_FACTS)
def test_each_regional_fact_unlocks_real_cut_consumer(integrity_game, regional_fact):
    _quickstart_to_overworld(integrity_game)
    for flag in REGIONAL_FACTS:
        integrity_game.set_flag(flag, False)
    integrity_game.set_flag(FLAG_BADGE01_GET, False)
    integrity_game.set_flag(FLAG_BADGE02_GET, False)
    integrity_game.set_flag(regional_fact)

    assert probe_field_move(integrity_game, FIELD_MOVE_CUT, 0x46524500 + regional_fact)
    assert integrity_game.read_flag(regional_fact)
    assert sum(integrity_game.read_flag(flag) for flag in REGIONAL_FACTS) == 1
