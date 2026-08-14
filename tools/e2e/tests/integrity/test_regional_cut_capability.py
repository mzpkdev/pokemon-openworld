import json
from pathlib import Path

import pytest

from tools.e2e.generate_cut_oracle import (
    CAPABILITIES,
    LEGACY_FLAGS,
    load_reviewed_oracle,
)
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
POLICY = json.loads(
    (
        Path(__file__).parents[4] / "tools/persistence/regional_fact_bindings.json"
    ).read_text()
)
REGIONAL_FACT_GRANTS = tuple(
    (item["value"], item["grants"][0]) for item in POLICY["exact"] if item["grants"]
)
REGIONAL_FACTS = tuple(item["value"] for item in POLICY["exact"])


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


def _probe_capabilities(game, request_base: int) -> list[str]:
    return [
        capability
        for index, (capability, field_move, _) in enumerate(CAPABILITIES)
        if probe_field_move(game, field_move, request_base + index)
    ]


@pytest.mark.parametrize(
    "scenario", ORACLE["matrix"], ids=[item["name"] for item in ORACLE["matrix"]]
)
def test_historical_capability_matrix_matches_oracle_through_resave_and_restart(
    session_factory, tmp_path, scenario
):
    base = SaveImage.from_path(BASE_FIXTURE)
    assert base.sha256 == ORACLE["source"]["baseFixtureSha256"]
    scenario_index = ORACLE["matrix"].index(scenario)
    legacy_flags = dict(zip(LEGACY_FLAGS, scenario["legacySlots"], strict=True))
    variant = with_saved_flags(
        base,
        {
            **legacy_flags,
            **{flag: False for flag in REGIONAL_FACTS},
        },
    )
    save = tmp_path / f"regional-capability-{scenario['name']}.sav"
    save.write_bytes(variant.data)
    game = session_factory(battery_save=save)

    _continue_to_overworld(game)
    _assert_no_regional_facts(game)
    assert (
        _probe_capabilities(game, 0x4E450000 + scenario_index * len(CAPABILITIES))
        == scenario["unlockedCapabilities"]
    )

    rewritten = save_from_start_menu(game)
    assert is_strictly_newer_save_counter(
        rewritten.active_slot.counter, variant.active_slot.counter
    )
    assert all(not rewritten.active_slot.saved_flag(flag) for flag in REGIONAL_FACTS)
    for flag, enabled in legacy_flags.items():
        assert rewritten.active_slot.saved_flag(flag) is enabled

    cold_restart_and_continue(game)
    _assert_no_regional_facts(game)
    for flag, enabled in legacy_flags.items():
        assert game.read_flag(flag) is enabled
    assert (
        _probe_capabilities(game, 0x434F0000 + scenario_index * len(CAPABILITIES))
        == scenario["unlockedCapabilities"]
    )


def test_each_regional_fact_unlocks_only_its_real_field_move_consumer(integrity_game):
    _quickstart_to_overworld(integrity_game)
    for flag in REGIONAL_FACTS:
        integrity_game.set_flag(flag, False)
    for flag in LEGACY_FLAGS:
        integrity_game.set_flag(flag, False)

    previous_fact = None
    for index, (regional_fact, capability) in enumerate(REGIONAL_FACT_GRANTS):
        if previous_fact is not None:
            integrity_game.set_flag(previous_fact, False)
        integrity_game.set_flag(regional_fact)

        assert _probe_capabilities(
            integrity_game, 0x46410000 + index * len(CAPABILITIES)
        ) == [capability]
        assert integrity_game.read_flag(regional_fact)
        assert sum(integrity_game.read_flag(flag) for flag in REGIONAL_FACTS) == 1
        previous_fact = regional_fact
