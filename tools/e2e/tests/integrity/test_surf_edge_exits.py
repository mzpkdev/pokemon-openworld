from __future__ import annotations

from tools.e2e.save_journey import (
    cold_restart_and_continue,
    save_from_start_menu,
)
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)
from tools.e2e.tests.integrity.test_world_tier_encounters import (
    WILD_AREA_WATER,
    WILD_ENCOUNTER_FISHING_ROD_NONE,
    _probe_encounter,
)


FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE = 44
FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE = 45
FLAG_DEBUG_NO_WILD_ENCOUNTERS = 0x8FE
PLAYER_AVATAR_FLAG_SURFING = 1 << 3
DIR_SOUTH = 1
DIR_NORTH = 2
DIR_WEST = 3
DIR_EAST = 4
MUS_RG_ROUTE3 = 505
MUS_ROUTE119 = 402
WEATHER_SUNNY = 2
WEATHER_RAIN = 3
GENERATED_OBJECT_TEMPLATES_OFFSET = 0xC70
OBJECT_EVENT_TEMPLATE_SIZE = 0x18


def _settle_overworld(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach an unlocked overworld")


def _load_map(game, entry, position: tuple[int, int], request_id: int) -> None:
    result = game.request_map_load(
        IntegrityMapLoadRequest(
            request_id=request_id,
            map_group=entry.group,
            map_num=entry.number,
            x=position[0],
            y=position[1],
        ),
        max_frames=1_800,
    )
    assert result.status is IntegrityLoadStatus.SUCCESS
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert game.map_id() == entry.map_id
    assert game.position() == position
    game.wait_for_controls_unlocked(max_frames=1_200)


def _open_debug_menu(game) -> None:
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


def _clear_party(game) -> None:
    _open_debug_menu(game)
    for _ in range(16):
        game.press("Up", release_frames=1)
    for _ in range(2):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            game.read_u32(game.pointer("sDebugMenuListData") + 4)
            == game.address("sDebugMenu_Actions_Party")
        ),
        description="Party debug submenu",
        max_frames=300,
    )
    for _ in range(16):
        game.press("Up", release_frames=1)
    for _ in range(8):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == 0,
        description="cleared debug party",
        max_frames=300,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)


def _give_surf_mon(game) -> None:
    """Use the shipped debug UI to create a level-40 Tentacool that learns Surf."""
    _clear_party(game)
    _open_debug_menu(game)
    for _ in range(16):
        game.press("Up", release_frames=1)
    for _ in range(3):
        game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: (
            game.read_u32(game.pointer("sDebugMenuListData") + 4)
            == game.address("sDebugMenu_Actions_Give")
        ),
        description="Give debug submenu",
        max_frames=300,
    )
    game.press("Down", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectId"),
        description="debug Pokemon species picker",
        max_frames=300,
    )
    for _ in range(71):
        game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.task_active("DebugAction_Give_Pokemon_SelectLevel"),
        description="debug Pokemon level picker",
        max_frames=300,
    )
    for _ in range(39):
        game.press("Up", release_frames=2)
    game.press("A", release_frames=2)
    game.wait_until(
        lambda: game.read_u8(game.address("gPartiesCount")) == 1,
        description="debug-created Surf Pokemon",
        max_frames=1_200,
    )
    game.wait_for_controls_unlocked(max_frames=1_200)


def _use_surf_from_party_menu(game) -> None:
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
    pokemon_index = actions.index(1)
    cursor = game.read_u8(game.address("sStartMenuCursorPos"))
    for _ in range((pokemon_index - cursor) % len(actions)):
        game.press("Down", release_frames=3)
    game.press("A", release_frames=12)
    game.wait_until(
        lambda: game.task_active("Task_HandleChooseMonInput"),
        description="field party menu",
        max_frames=1_200,
    )
    # The party task is created before its entry fade completes and discards
    # input until that fade is done.
    game.step(60)
    game.press("A", release_frames=3)
    game.wait_until(
        lambda: game.task_active("Task_HandleSelectionMenuInput"),
        description="party actions",
        max_frames=300,
    )
    game.step(4)
    game.press("Down", release_frames=3)
    game.press("A", release_frames=12)
    game.advance_until(
        lambda: (
            game.read_u8(game.address("gPlayerAvatar")) & PLAYER_AVATAR_FLAG_SURFING
        ),
        description="party-menu Surf confirmation",
        max_pulses=300,
    )
    game.wait_for_controls_unlocked(max_frames=1_800)
    assert game.read_u8(game.address("gPlayerAvatar")) & PLAYER_AVATAR_FLAG_SURFING


def _assert_field_ready(game, entry, position: tuple[int, int], facing: int) -> None:
    game.wait_for_callback("CB2_Overworld", max_frames=1_200)
    game.wait_for_controls_unlocked(max_frames=1_200)
    assert game.map_id() == entry.map_id
    assert game.position() == position
    assert game.facing_direction() == facing
    assert not game.controls_locked()
    assert game.movement_idle()
    assert game.read_u8(game.address("gPlayerAvatar")) & PLAYER_AVATAR_FLAG_SURFING


def _assert_map_presentation(game, entry, music: int, weather: int) -> None:
    header = game.address("gMapHeader")
    assert game.read_u16(header + 0x10) == music
    assert game.read_u8(header + 0x17) == weather
    assert game.read_u16(header + 0x14) == entry.region_map_section_value
    metadata = game.address("gMapSectionMetadata") + entry.region_map_section_value * 4
    assert game.read_u8(metadata) == entry.section.region_value


def _cross_edge(game, direction: str, destination, position, facing: int) -> None:
    game.press(direction, hold_frames=3, release_frames=1)
    game.step(20)
    if game.map_id() != destination.map_id:
        game.wait_until(
            game.movement_idle,
            description="edge-turn movement idle",
            max_frames=120,
            step_frames=2,
        )
        game.press(direction, hold_frames=3, release_frames=1)
    game.wait_for_map(destination.map_id, max_frames=1_800)
    _assert_field_ready(game, destination, position, facing)


def _traverse_generated_ocean(
    game, direction: str, destination, position, facing: int
) -> None:
    for _ in range(60):
        game.press(direction, hold_frames=2, release_frames=1)
        game.step(20)
        # Crossing the endpoint starts a normal DoWarp fade: movement stays
        # non-idle until the destination avatar is rebuilt, so wait for that
        # map transition instead of requiring an impossible intermediate idle.
        if game.map_id() == destination.map_id or game.controls_locked():
            break
        game.wait_until(
            game.movement_idle,
            description="generated-ocean movement idle",
            max_frames=120,
            step_frames=2,
        )
    game.wait_for_map(destination.map_id, max_frames=1_800)
    _assert_field_ready(game, destination, position, facing)


def _generated_trainer_position(game) -> tuple[int, int]:
    templates = game.save_block1() + GENERATED_OBJECT_TEMPLATES_OFFSET
    matches = []
    for index in range(4):
        template = templates + index * OBJECT_EVENT_TEMPLATE_SIZE
        if 1 <= game.read_u8(template) <= 4:
            matches.append(
                (
                    game.read_u16(template + 4),
                    game.read_u16(template + 6),
                )
            )
    assert matches, "generated ocean did not publish a live swimmer trainer"
    return matches[0]


def test_surf_edges_cross_kanto_and_johto_and_survive_cold_restart(integrity_game):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    route19 = maps["Route19_Frlg"]
    route40 = maps["Route40"]
    generated_ocean = maps["AquaHideout_UnusedRubyMap2"]

    _settle_overworld(integrity_game)
    _give_surf_mon(integrity_game)
    for fact in (
        FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
        FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
    ):
        integrity_game.set_flag(fact)
    # The shell retains ordinary water encounters; disable only debug-ROM RNG
    # here so this route-ownership journey reaches its recorded endpoints.
    integrity_game.set_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)

    _load_map(integrity_game, route19, (16, 8), 0x53454601)
    integrity_game.face("Down")
    _use_surf_from_party_menu(integrity_game)
    assert integrity_game.position() == (16, 9)
    integrity_game.move_path(
        (16, 14),
        (7, 14),
        (7, 20),
        (5, 20),
        (5, 22),
        (3, 22),
        (3, 25),
        (4, 25),
        (4, 31),
        (11, 31),
        (11, 38),
        (16, 38),
        (16, 40),
        (17, 40),
        (17, 53),
        (21, 53),
        (21, 56),
        (20, 56),
        (20, 59),
    )
    _cross_edge(integrity_game, "Down", generated_ocean, (2, 12), DIR_SOUTH)
    _assert_map_presentation(
        integrity_game, generated_ocean, MUS_ROUTE119, WEATHER_SUNNY
    )
    saved = save_from_start_menu(integrity_game)
    cold_restart_and_continue(integrity_game)
    _assert_field_ready(integrity_game, generated_ocean, (2, 12), DIR_SOUTH)
    _traverse_generated_ocean(integrity_game, "Right", route40, (0, 30), DIR_EAST)
    _assert_map_presentation(integrity_game, route40, MUS_ROUTE119, WEATHER_RAIN)
    assert all(
        integrity_game.read_flag(fact)
        for fact in (
            FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
            FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
        )
    )

    _cross_edge(integrity_game, "Left", generated_ocean, (2, 12), DIR_WEST)
    _traverse_generated_ocean(integrity_game, "Right", route19, (20, 59), DIR_NORTH)
    _assert_map_presentation(integrity_game, route19, MUS_RG_ROUTE3, WEATHER_SUNNY)

    saved = save_from_start_menu(integrity_game)
    assert all(
        saved.active_slot.saved_flag(fact)
        for fact in (
            FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
            FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
        )
    )
    cold_restart_and_continue(integrity_game)
    _assert_field_ready(integrity_game, route19, (20, 59), DIR_NORTH)
    _assert_map_presentation(integrity_game, route19, MUS_RG_ROUTE3, WEATHER_SUNNY)


def test_generated_ocean_uses_normal_water_encounters_and_real_trainers(integrity_game):
    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    route19 = maps["Route19_Frlg"]
    generated_ocean = maps["AquaHideout_UnusedRubyMap2"]

    _settle_overworld(integrity_game)
    for fact in (
        FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE,
        FLAG_REGIONAL_FACT_JOHTO_FOG_BADGE,
    ):
        integrity_game.set_flag(fact)
    integrity_game.set_flag(FLAG_DEBUG_NO_WILD_ENCOUNTERS)

    _load_map(integrity_game, route19, (20, 59), 0x53454102)
    avatar = integrity_game.address("gPlayerAvatar")
    integrity_game.write_u8(
        avatar, integrity_game.read_u8(avatar) | PLAYER_AVATAR_FLAG_SURFING
    )
    _cross_edge(integrity_game, "Down", generated_ocean, (2, 12), DIR_SOUTH)
    encounter = _probe_encounter(
        integrity_game,
        request_id=0x53454103,
        area=WILD_AREA_WATER,
        fishing_rod=WILD_ENCOUNTER_FISHING_ROD_NONE,
        entry_index=0,
    )
    assert encounter.area == WILD_AREA_WATER
    assert encounter.entry_count > 0
    trainer_x, trainer_y = _generated_trainer_position(integrity_game)
    assert 0 < trainer_x < 61
    assert trainer_y not in range(9, 16)
