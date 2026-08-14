from pathlib import Path
import json

from tools.e2e.save_file import SaveImage, load_fixture_manifest
from tools.e2e.save_journey import (
    SaveScenarioRequest,
    SaveScenarioResult,
    SaveScenarioStatus,
    assert_runtime_semantics,
    cold_restart_and_continue,
    representative_runtime_semantics,
    representative_saved_semantics,
    run_save_scenario,
    save_from_start_menu,
)


FIXTURE_MANIFEST = Path(__file__).parents[2] / "fixtures" / "hoenn_continue.json"
POPULATED_FIXTURE_MANIFEST = (
    Path(__file__).parents[2] / "fixtures" / "hoenn_populated.json"
)
FLAG_DEBUG_NO_WILD_ENCOUNTERS = 0x8FE
FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED = 0x8E3
VAR_E2E_PERSISTENCE_SENTINEL = 0x40FF
SPECIES_PIKACHU = 25
SPECIES_DITTO = 132
SPECIES_EEVEE = 133
SPECIES_SEEDOT = 273
ITEM_NUGGET = 135
HEAL_LOCATION_LITTLEROOT_BRENDAN_2F = 1
TRAINER_RICKY_1 = 64
REGIONAL_STORY_MIGRATION_MARKER_OFFSET = 0x9C2
REGIONAL_STORY_MIGRATION_MARKER = bytes((0x53, 2))


def _migration_marker(image) -> bytes:
    offset = REGIONAL_STORY_MIGRATION_MARKER_OFFSET
    return image.active_slot.save_block1[offset : offset + 2]


def test_existing_hoenn_save_continues(game_from_hoenn_save):
    document, original = load_fixture_manifest(FIXTURE_MANIFEST)
    expected = document["semanticExpectations"]
    assert _migration_marker(original) == bytes(2)
    assert original.active_slot.trainer_defeated_bitmap == bytes(79)
    assert original.semantics() == expected

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
    assert_runtime_semantics(game_from_hoenn_save, expected)
    assert game_from_hoenn_save.read_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)

    rewritten = save_from_start_menu(game_from_hoenn_save)
    assert _migration_marker(rewritten) == REGIONAL_STORY_MIGRATION_MARKER
    assert rewritten.active_slot.saved_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    assert rewritten.active_slot.trainer_defeated_bitmap == bytes(79)
    assert rewritten.semantics() == expected
    cold_restart_and_continue(game_from_hoenn_save)
    assert_runtime_semantics(game_from_hoenn_save, expected)
    assert game_from_hoenn_save.read_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    restarted = game_from_hoenn_save.battery_snapshot()
    assert _migration_marker(restarted) == REGIONAL_STORY_MIGRATION_MARKER
    assert restarted.active_slot.saved_flag(FLAG_VERMILION_FAST_SHIP_TERMINAL_LOCKED)
    assert restarted.semantics() == expected


def test_populated_historical_save_preserves_reviewed_state(
    game_from_populated_hoenn_save,
):
    document = json.loads(POPULATED_FIXTURE_MANIFEST.read_text())
    image = SaveImage.from_path(
        POPULATED_FIXTURE_MANIFEST.parent / document["fixture"]["file"]
    )
    assert image.sha256 == document["fixture"]["sha256"]
    assert image.active_slot.trainer_defeated_bitmap == bytes(79)
    result_fields = document["generation"]["result"]
    result_fields["status"] = SaveScenarioStatus(result_fields["status"])
    result = SaveScenarioResult(**result_fields)
    expected = document["semanticExpectations"]
    assert representative_saved_semantics(image, result) == expected

    game = game_from_populated_hoenn_save
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(1_500):
        game.press("A")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("populated historical fixture did not Continue")
    game.wait_for_controls_unlocked(max_frames=1_200)
    before_resave = representative_runtime_semantics(game, result)
    assert {k: v for k, v in before_resave.items() if k != "facilitySession"} == {
        k: v for k, v in expected.items() if k != "facilitySession"
    }
    assert before_resave["facilitySession"] == {
        **expected["facilitySession"],
        "challengeStatus": 1,
    }

    # Continue resumes a PAUSED tower challenge as active in RAM. The field
    # save retains the reviewed paused record so another cold Continue can
    # perform the same documented transition.
    rewritten = save_from_start_menu(game)
    assert rewritten.active_slot.trainer_defeated_bitmap == bytes(79)
    assert representative_saved_semantics(rewritten, result) == expected
    cold_restart_and_continue(game)
    after_restart = representative_runtime_semantics(game, result)
    assert {k: v for k, v in after_restart.items() if k != "facilitySession"} == {
        k: v for k, v in expected.items() if k != "facilitySession"
    }
    assert after_restart["facilitySession"] == {
        **expected["facilitySession"],
        "challengeStatus": 1,
    }
    assert representative_saved_semantics(game.battery_snapshot(), result) == expected


def test_fresh_save_persists_representative_state_after_cold_restart(game):
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError("Quickstart did not initialize a fresh game")
    game.wait_for_controls_unlocked(max_frames=1_200)

    game.set_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)
    game.set_var(VAR_E2E_PERSISTENCE_SENTINEL, 0xA55A)
    result = run_save_scenario(
        game,
        SaveScenarioRequest(
            request_id=0x53415645,
            party_species=SPECIES_PIKACHU,
            box_species=SPECIES_EEVEE,
            daycare_species_1=SPECIES_DITTO,
            daycare_species_2=SPECIES_EEVEE,
            trade_species=SPECIES_SEEDOT,
            reward_item=ITEM_NUGGET,
            checkpoint_id=HEAL_LOCATION_LITTLEROOT_BRENDAN_2F,
            level=20,
            facility_id=0,
            facility_level_mode=0,
            trainer_id=TRAINER_RICKY_1,
        ),
    )
    expected = representative_runtime_semantics(game, result)
    assert expected["party"]["createdPokemon"] is not None, expected
    assert expected["party"]["createdPokemon"]["species"] == SPECIES_PIKACHU
    assert expected["party"]["tradedPokemon"]["species"] == SPECIES_SEEDOT
    assert expected["party"]["tradedPokemon"]["metLocation"] == 254
    assert expected["box"]["pokemon"]["species"] == SPECIES_EEVEE
    assert {
        expected["daycare"]["parent1"]["species"],
        expected["daycare"]["parent2"]["species"],
    } == {
        SPECIES_DITTO,
        SPECIES_EEVEE,
    }
    assert expected["daycare"]["pendingEgg"]
    assert expected["daycare"]["eggSpecies"] == SPECIES_EEVEE
    assert expected["facilitySession"]["challengeStatus"] != 0
    assert expected["facilitySession"]["paused"]
    assert expected["reward"] == {"item": ITEM_NUGGET, "quantity": 1}
    assert expected["checkpoint"]["id"] == HEAL_LOCATION_LITTLEROOT_BRENDAN_2F
    assert expected["trainer"] == {"id": TRAINER_RICKY_1, "defeated": True}
    saved = save_from_start_menu(game)
    assert representative_saved_semantics(saved, result) == expected

    cold_restart_and_continue(game)
    after_restart = representative_runtime_semantics(game, result)
    assert {
        key: value for key, value in after_restart.items() if key != "facilitySession"
    } == {key: value for key, value in expected.items() if key != "facilitySession"}
    # Continue resumes the serialized PAUSED tower challenge as active while
    # retaining its pause marker and level mode.
    assert after_restart["facilitySession"] == {
        **expected["facilitySession"],
        "challengeStatus": 1,
    }
    assert representative_saved_semantics(game.battery_snapshot(), result) == expected
    assert game.read_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)
    assert game.read_var(VAR_E2E_PERSISTENCE_SENTINEL) == 0xA55A
