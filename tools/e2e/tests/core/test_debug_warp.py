"""Core E2E coverage for settlement travel through the debug warp menu."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
MAP_GROUPS_PATH = ROOT / "data/maps/map_groups.json"
MAP_SECTIONS_PATH = ROOT / "src/data/region_map/region_map_sections.json"
REQUIRED_MAPS_PATH = ROOT / "tools/mapjson/required_map_defines.json"
DEBUG_NAMED_WARP_FORMAT = "named-warp-v1"

PRESENTATIONS = (
    "Hoenn",
    "Kanto",
    "Sevii 1-3",
    "Sevii 4-5",
    "Sevii 6-7",
    "Johto",
)
UI_REGION_NAMES = {
    "Hoenn": "Hoenn",
    "Kanto": "Kanto",
    "Sevii 1-3": "Sevii Islands 1-3",
    "Sevii 4-5": "Sevii Islands 4-5",
    "Sevii 6-7": "Sevii Islands 6-7",
    "Johto": "Johto",
}
SEVII_PRESENTATIONS = {
    "REGION_MAP_SEVII123": "Sevii 1-3",
    "REGION_MAP_SEVII45": "Sevii 4-5",
    "REGION_MAP_SEVII67": "Sevii 6-7",
}
EXPECTED_COUNTS = {
    "Hoenn": 16,
    "Kanto": 12,
    "Sevii 1-3": 3,
    "Sevii 4-5": 2,
    "Sevii 6-7": 2,
    "Johto": 14,
}
SETTLEMENT_TYPES = {"MAP_TYPE_TOWN", "MAP_TYPE_CITY"}

# This is deliberately independent of the generated registry.  The source JSON
# supplies ordinals, but it cannot silently redefine the product contract this
# test is meant to protect.
EXPECTED_SETTLEMENTS = (
    ("PetalburgCity", "Petalburg City", "Hoenn"),
    ("SlateportCity", "Slateport City", "Hoenn"),
    ("MauvilleCity", "Mauville City", "Hoenn"),
    ("RustboroCity", "Rustboro City", "Hoenn"),
    ("FortreeCity", "Fortree City", "Hoenn"),
    ("LilycoveCity", "Lilycove City", "Hoenn"),
    ("MossdeepCity", "Mossdeep City", "Hoenn"),
    ("SootopolisCity", "Sootopolis City", "Hoenn"),
    ("EverGrandeCity", "Ever Grande City", "Hoenn"),
    ("LittlerootTown", "Littleroot Town", "Hoenn"),
    ("OldaleTown", "Oldale Town", "Hoenn"),
    ("DewfordTown", "Dewford Town", "Hoenn"),
    ("LavaridgeTown", "Lavaridge Town", "Hoenn"),
    ("FallarborTown", "Fallarbor Town", "Hoenn"),
    ("VerdanturfTown", "Verdanturf Town", "Hoenn"),
    ("PacifidlogTown", "Pacifidlog Town", "Hoenn"),
    ("PalletTown_Frlg", "Pallet Town", "Kanto"),
    ("ViridianCity_Frlg", "Viridian City", "Kanto"),
    ("PewterCity_Frlg", "Pewter City", "Kanto"),
    ("CeruleanCity_Frlg", "Cerulean City", "Kanto"),
    ("LavenderTown_Frlg", "Lavender Town", "Kanto"),
    ("VermilionCity_Frlg", "Vermilion City", "Kanto"),
    ("CeladonCity_Frlg", "Celadon City", "Kanto"),
    ("FuchsiaCity_Frlg", "Fuchsia City", "Kanto"),
    ("CinnabarIsland_Frlg", "Cinnabar Island", "Kanto"),
    ("IndigoPlateau_Exterior_Frlg", "Indigo Plateau Exterior", "Kanto"),
    ("SaffronCity_Frlg", "Saffron City", "Kanto"),
    ("SaffronCity_Connection_Frlg", "Saffron City Connection", "Kanto"),
    ("OneIsland_Frlg", "One Island", "Sevii 1-3"),
    ("TwoIsland_Frlg", "Two Island", "Sevii 1-3"),
    ("ThreeIsland_Frlg", "Three Island", "Sevii 1-3"),
    ("FourIsland_Frlg", "Four Island", "Sevii 4-5"),
    ("FiveIsland_Frlg", "Five Island", "Sevii 4-5"),
    ("SevenIsland_Frlg", "Seven Island", "Sevii 6-7"),
    ("SixIsland_Frlg", "Six Island", "Sevii 6-7"),
    ("NewBarkTown", "New Bark Town", "Johto"),
    ("CherrygroveCity", "Cherrygrove City", "Johto"),
    ("VioletCity", "Violet City", "Johto"),
    ("MtSilver_Outside", "Mt Silver Outside", "Johto"),
    ("AzaleaTown", "Azalea Town", "Johto"),
    ("GoldenrodCity", "Goldenrod City", "Johto"),
    ("EcruteakCity", "Ecruteak City", "Johto"),
    ("OlivineCity", "Olivine City", "Johto"),
    ("CianwoodCity", "Cianwood City", "Johto"),
    ("Mahoganytown", "Mahoganytown", "Johto"),
    ("LakeOfRage", "Lake Of Rage", "Johto"),
    ("BlackthornCity", "Blackthorn City", "Johto"),
    ("SafariZoneGate", "Safari Zone Gate", "Johto"),
    ("JohtoIndigoPlateau", "Johto Indigo Plateau", "Johto"),
)

PINNED_GROUP_LABELS = {
    "gMapGroup_TownsAndRoutes": "Towns And Routes",
    "gMapGroup_IndoorPetalburg": "Indoor Petalburg",
    "gMapGroup_IndoorDynamic": "Indoor Dynamic",
}

NAMED_WARP_TASKS = (
    "DebugAction_Util_Warp_SelectRegion",
    "DebugAction_Util_Warp_SelectNamedMapGroup",
    "DebugAction_Util_Warp_SelectNamedMap",
    "DebugAction_Util_Warp_SelectNamedWarp",
)

TASK_SIZE = 0x28
TASK_DATA_OFFSET = 8
TASK_MAP_GROUP = 5
TASK_MAP_NUM = 6
TASK_WARP = 7
TASK_REGION = 8
PAGE_SIZE = 10


@dataclass(frozen=True)
class RegisteredMap:
    group: int
    number: int
    name: str
    display_name: str
    presentation: str | None
    map_type: str
    region_map_section: str
    map_id: str
    group_name: str
    group_display_name: str
    warp_events: tuple[dict, ...]


@dataclass(frozen=True)
class SettlementCase:
    map: RegisteredMap
    region_ordinal: int
    group_ordinal: int
    map_ordinal: int
    group_choices: tuple[int, ...]
    map_choices: tuple[int, ...]


def _humanize_component(identifier: str) -> str:
    display = ""
    for index, current in enumerate(identifier):
        previous = identifier[index - 1] if index else ""
        following = identifier[index + 1] if index + 1 < len(identifier) else ""
        starts_word = index > 0 and (
            (current.isupper() and previous.islower())
            or (current.isupper() and previous.isupper() and following.islower())
            or (current.isupper() and previous.isdigit())
            or (current.isdigit() and previous.islower())
        )
        if starts_word:
            display += " "
        display += current
    return display


def _debug_display_name(identifier: str) -> str:
    if identifier.endswith("_Frlg"):
        identifier = identifier.removesuffix("_Frlg")
    display = " ".join(_humanize_component(part) for part in identifier.split("_"))
    if len(display) <= 32:
        return display

    separators = (index for index, character in enumerate(display) if character == " ")
    fitting = [
        index for index in separators if index <= 32 and len(display) - index - 1 <= 32
    ]
    if not fitting:
        raise AssertionError(f"debug map name cannot fit in two lines: {identifier}")
    separator = min(fitting, key=lambda index: max(index, len(display) - index - 1))
    return display[:separator] + "\n" + display[separator + 1 :]


def _debug_group_display_name(identifier: str) -> str:
    identifier = identifier.removeprefix("gMapGroup_").removesuffix("_Frlg")
    return _humanize_component(identifier.replace("_", " "))


def _presentation(map_data: dict, sections: dict[str, dict]) -> str | None:
    declared_region = map_data.get("region")
    if declared_region == "REGION_HOENN":
        return "Hoenn"
    if declared_region == "REGION_JOHTO":
        return "Johto"
    if declared_region != "REGION_KANTO":
        return None
    section = sections[map_data["region_map_section"]]
    return SEVII_PRESENTATIONS.get(section.get("region_map_type"), "Kanto")


def _required_map_values() -> dict[str, tuple[int, int]]:
    values = {}
    previous_group = None
    number = 0
    for map_id, group in json.loads(REQUIRED_MAPS_PATH.read_text())["required_maps"]:
        number = number + 1 if group == previous_group else 0
        values[map_id] = (group, number)
        previous_group = group
    return values


REQUIRED_MAP_VALUES = _required_map_values()


def _load_registry() -> tuple[
    tuple[SettlementCase, ...],
    tuple[RegisteredMap, ...],
    dict[int, tuple[RegisteredMap, ...]],
    dict[str, RegisteredMap],
    dict[str, tuple[int, ...]],
    tuple[tuple[RegisteredMap, int, str, tuple[int, int] | None], ...],
]:
    groups = json.loads(MAP_GROUPS_PATH.read_text())
    section_document = json.loads(MAP_SECTIONS_PATH.read_text())
    sections = {section["id"]: section for section in section_document["map_sections"]}

    registered: list[RegisteredMap] = []
    by_group: dict[int, list[RegisteredMap]] = {}
    for group, group_name in enumerate(groups["group_order"]):
        group_maps = []
        for number, name in enumerate(groups[group_name]):
            map_data = json.loads((ROOT / "data/maps" / name / "map.json").read_text())
            entry = RegisteredMap(
                group=group,
                number=number,
                name=name,
                display_name=_debug_display_name(name),
                presentation=_presentation(map_data, sections),
                map_type=map_data["map_type"],
                region_map_section=map_data["region_map_section"],
                map_id=map_data["id"],
                group_name=group_name,
                group_display_name=_debug_group_display_name(group_name),
                warp_events=tuple(map_data.get("warp_events", ())),
            )
            registered.append(entry)
            group_maps.append(entry)
        by_group[group] = group_maps

    presentation_groups = {
        presentation: [
            group
            for group, maps in by_group.items()
            if any(entry.presentation == presentation for entry in maps)
        ]
        for presentation in PRESENTATIONS
    }
    settlements = [
        entry
        for entry in registered
        if entry.map_type in SETTLEMENT_TYPES and entry.presentation is not None
    ]
    counts = Counter(entry.presentation for entry in settlements)
    actual_settlements = tuple(
        (entry.name, entry.display_name, entry.presentation) for entry in settlements
    )
    if actual_settlements != EXPECTED_SETTLEMENTS:
        raise AssertionError(
            "named-warp settlement identities/labels/regions drifted:\n"
            f"expected={EXPECTED_SETTLEMENTS!r}\nactual={actual_settlements!r}"
        )
    if len(settlements) != 49 or dict(counts) != EXPECTED_COUNTS:
        raise AssertionError(
            "named-warp settlement registry drifted: "
            f"total={len(settlements)}, counts={dict(counts)}"
        )

    special_kanto_links = [
        entry
        for entry in registered
        if entry.region_map_section == "MAPSEC_SPECIAL_AREA"
        and entry.presentation == "Kanto"
    ]
    if len(special_kanto_links) != 5 or any(
        entry.map_type in SETTLEMENT_TYPES for entry in special_kanto_links
    ):
        raise AssertionError(
            "expected exactly five non-settlement Kanto MAPSEC_SPECIAL_AREA maps, "
            f"got {[entry.name for entry in special_kanto_links]}"
        )

    cases = []
    for settlement in settlements:
        presentation = settlement.presentation
        assert presentation is not None
        filtered_maps = [
            entry
            for entry in by_group[settlement.group]
            if entry.presentation == presentation
        ]
        cases.append(
            SettlementCase(
                map=settlement,
                region_ordinal=PRESENTATIONS.index(presentation),
                group_ordinal=presentation_groups[presentation].index(settlement.group),
                map_ordinal=filtered_maps.index(settlement),
                group_choices=tuple(presentation_groups[presentation]),
                map_choices=tuple(entry.number for entry in filtered_maps),
            )
        )
    by_name = {entry.name: entry for entry in registered}
    by_map_id = {entry.map_id: entry for entry in registered}
    invalid_warps = [
        (entry, index, warp["dest_map"], REQUIRED_MAP_VALUES.get(warp["dest_map"]))
        for entry in registered
        for index, warp in enumerate(entry.warp_events, start=1)
        if warp["dest_map"] != "MAP_DYNAMIC" and warp["dest_map"] not in by_map_id
    ]

    for group_name, expected_label in PINNED_GROUP_LABELS.items():
        actual_label = _debug_group_display_name(group_name)
        if actual_label != expected_label:
            raise AssertionError(
                f"pinned group label drifted for {group_name}: "
                f"expected={expected_label!r}, actual={actual_label!r}"
            )

    return (
        tuple(cases),
        tuple(registered),
        {group: tuple(maps) for group, maps in by_group.items()},
        by_name,
        {name: tuple(choices) for name, choices in presentation_groups.items()},
        tuple(invalid_warps),
    )


(
    CASES,
    REGISTERED_MAPS,
    MAPS_BY_GROUP,
    MAPS_BY_NAME,
    PRESENTATION_GROUPS,
    INVALID_WARPS,
) = _load_registry()


def _debug_named_warp_registry_identity() -> bytes:
    """Independently recompute the named-warp map-registry/content identity."""
    groups = json.loads(MAP_GROUPS_PATH.read_text())
    section_document = json.loads(MAP_SECTIONS_PATH.read_text())
    section_presentations = {
        section["id"]: section["region_map_type"]
        for section in section_document["map_sections"]
    }
    identity = 0xCBF29CE484222325

    def add(value: object) -> None:
        nonlocal identity
        encoded = str(value).encode()
        for byte in len(encoded).to_bytes(8, "little") + encoded:
            identity ^= byte
            identity = (identity * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF

    add(DEBUG_NAMED_WARP_FORMAT)
    for group_name in groups["group_order"]:
        add("group")
        add(group_name)
        for registry_name in groups[group_name]:
            map_data = json.loads(
                (ROOT / "data/maps" / registry_name / "map.json").read_text()
            )
            section_id = map_data["region_map_section"]
            add("map")
            add(registry_name)
            add(map_data["name"])
            add(map_data.get("id", ""))
            add(map_data.get("region", "<default>"))
            add(map_data["map_type"])
            add(section_id)
            add(section_presentations[section_id])
            warps = map_data.get("warp_events", [])
            add(len(warps))
            for warp in warps:
                add(warp["x"])
                add(warp["y"])
                add(warp["elevation"])
                add(warp["dest_map"])
                add(warp["dest_warp_id"])
    return identity.to_bytes(8, "little")


def _task_for_function(game, function: str) -> int | None:
    expected = game.address(function) | 1
    tasks = game.address("gTasks")
    for task_id in range(16):
        task = tasks + task_id * TASK_SIZE
        if game.read_u8(task + 4) and game.read_u32(task) == expected:
            return task_id
    return None


def _wait_for_task(game, function: str, description: str) -> int:
    game.wait_until(
        lambda: _task_for_function(game, function) is not None,
        description=description,
        max_frames=120,
    )
    task_id = _task_for_function(game, function)
    assert task_id is not None
    return task_id


def _task_data_s16(game, task_id: int, index: int) -> int:
    address = game.address("gTasks") + task_id * TASK_SIZE
    value = game.read_u16(address + TASK_DATA_OFFSET + index * 2)
    return value - 0x10000 if value & 0x8000 else value


def _assert_debug_artifacts_match_source(game) -> None:
    missing_runtime_symbols = []
    for symbol in (
        *NAMED_WARP_TASKS,
        "sDebugMenuListData",
        "CB2_Overworld",
        "gDebugNamedWarpRegistryIdentity",
    ):
        try:
            game.address(symbol)
        except KeyError:
            missing_runtime_symbols.append(symbol)
    assert not missing_runtime_symbols, (
        "debug ROM/symbol artifacts do not contain the named-warp implementation; "
        "rebuild pokemon-openworld-debug.gba and pokemon-openworld-debug.sym: "
        f"missing symbols={missing_runtime_symbols}"
    )
    expected = _debug_named_warp_registry_identity()
    actual = game.read(game.address("gDebugNamedWarpRegistryIdentity"), len(expected))
    assert actual == expected, (
        "debug ROM/SYM named-warp map-registry/content identity is stale relative "
        "to checked-in group, map, warp, region-section presentation, or "
        "generator-format inputs; rebuild "
        "pokemon-openworld-debug.gba and pokemon-openworld-debug.sym: "
        f"expected={expected.hex()}, embedded={actual.hex()}"
    )


def _select_ordinal(
    game,
    task_id: int,
    data_index: int,
    choices: tuple[int, ...],
    ordinal: int,
    context: str,
) -> None:
    assert _task_data_s16(game, task_id, data_index) == choices[0], (
        f"{context} picker did not start at its first registry choice"
    )
    current = 0
    pages, remainder = divmod(ordinal, PAGE_SIZE)
    for _ in range(pages):
        current = (current + PAGE_SIZE) % len(choices)
        game.advance_until(
            lambda: _task_data_s16(game, task_id, data_index) == choices[current],
            description=f"{context} Right page to ordinal {current}",
            max_pulses=20,
            button="Right",
        )
    for _ in range(remainder):
        current = (current + 1) % len(choices)
        game.advance_until(
            lambda: _task_data_s16(game, task_id, data_index) == choices[current],
            description=f"{context} Down to ordinal {current}",
            max_pulses=20,
            button="Down",
        )


def _advance_to_task(game, function: str, description: str) -> int:
    game.advance_until(
        lambda: _task_for_function(game, function) is not None,
        description=description,
        max_pulses=20,
        button="A",
    )
    task_id = _task_for_function(game, function)
    assert task_id is not None
    return task_id


def _encode_game_text(text: str) -> bytes:
    encoded = bytearray()
    for character in text:
        if "A" <= character <= "Z":
            encoded.append(0xBB + ord(character) - ord("A"))
        elif "a" <= character <= "z":
            encoded.append(0xD5 + ord(character) - ord("a"))
        elif "0" <= character <= "9":
            encoded.append(0xA1 + ord(character) - ord("0"))
        elif character == " ":
            encoded.append(0x00)
        elif character == ":":
            encoded.append(0xF0)
        elif character == "-":
            encoded.append(0xAE)
        elif character == "\n":
            encoded.append(0xFE)
        else:
            raise AssertionError(f"unsupported game-text character: {character!r}")
    encoded.append(0xFF)
    return bytes(encoded)


def _assert_visible_string(game, symbol: str, expected: str, context: str):
    encoded = _encode_game_text(expected)
    actual = game.read(game.address(symbol), len(encoded))
    assert actual == encoded, (
        f"{context} displayed the wrong {symbol}: "
        f"expected {expected!r}, bytes={actual.hex()}"
    )


def _assert_picker_task(game, function: str, task_id: int, context: str) -> None:
    assert _task_for_function(game, function) == task_id, (
        f"{context} left {function}; active task={_task_for_function(game, function)}"
    )


def _assert_region_picker(game, task_id: int, ordinal: int, context: str) -> None:
    _assert_picker_task(game, "DebugAction_Util_Warp_SelectRegion", task_id, context)
    assert _task_data_s16(game, task_id, TASK_REGION) == ordinal
    _assert_visible_string(
        game, "gStringVar1", UI_REGION_NAMES[PRESENTATIONS[ordinal]], context
    )


def _assert_group_picker(game, task_id: int, group: int, context: str) -> None:
    _assert_picker_task(
        game, "DebugAction_Util_Warp_SelectNamedMapGroup", task_id, context
    )
    assert _task_data_s16(game, task_id, TASK_MAP_GROUP) == group
    presentation = PRESENTATIONS[_task_data_s16(game, task_id, TASK_REGION)]
    _assert_visible_string(game, "gStringVar1", UI_REGION_NAMES[presentation], context)
    _assert_visible_string(
        game,
        "gStringVar2",
        MAPS_BY_GROUP[group][0].group_display_name,
        context,
    )


def _assert_map_picker(game, task_id: int, entry: RegisteredMap, context: str) -> None:
    _assert_picker_task(game, "DebugAction_Util_Warp_SelectNamedMap", task_id, context)
    assert _task_data_s16(game, task_id, TASK_MAP_GROUP) == entry.group
    assert _task_data_s16(game, task_id, TASK_MAP_NUM) == entry.number
    presentation = PRESENTATIONS[_task_data_s16(game, task_id, TASK_REGION)]
    _assert_visible_string(game, "gStringVar1", UI_REGION_NAMES[presentation], context)
    _assert_visible_string(game, "gStringVar2", entry.display_name, context)


def _entry_label(entry: RegisteredMap, ordinal: int) -> str:
    if ordinal == 0:
        return "Entry: Map center"
    warp = entry.warp_events[ordinal - 1]
    if warp["dest_map"] == "MAP_DYNAMIC":
        destination = "Dynamic destination"
    elif destination_maps := [
        candidate
        for candidate in REGISTERED_MAPS
        if candidate.map_id == warp["dest_map"]
    ]:
        destination = destination_maps[0].display_name
    else:
        numeric_destination = REQUIRED_MAP_VALUES.get(warp["dest_map"])
        if numeric_destination is None:
            raise AssertionError(
                f"invalid destination lacks a compiled numeric value: {warp['dest_map']}"
            )
        group, number = numeric_destination
        destination = f"Invalid destination {group}/{number}"
    return f"Entry: Warp {ordinal}\nTo: {destination}"


def _assert_entry_picker(
    game, task_id: int, entry: RegisteredMap, ordinal: int, context: str
) -> None:
    _assert_picker_task(game, "DebugAction_Util_Warp_SelectNamedWarp", task_id, context)
    assert _task_data_s16(game, task_id, TASK_MAP_GROUP) == entry.group
    assert _task_data_s16(game, task_id, TASK_MAP_NUM) == entry.number
    assert _task_data_s16(game, task_id, TASK_WARP) == ordinal
    presentation = PRESENTATIONS[_task_data_s16(game, task_id, TASK_REGION)]
    _assert_visible_string(game, "gStringVar1", UI_REGION_NAMES[presentation], context)
    _assert_visible_string(game, "gStringVar2", entry.display_name, context)
    _assert_visible_string(game, "gStringVar3", _entry_label(entry, ordinal), context)


def _current_debug_menu_is(game, menu_symbol: str, level: int) -> bool:
    menu_data = game.pointer("sDebugMenuListData")
    if menu_data == 0:
        return False
    return game.read_u32(menu_data + level * 4) == game.address(menu_symbol)


def _open_named_warp(game) -> int:
    game.set_buttons(R=True)
    game.step()
    game.set_buttons(R=True, Start=True)
    game.step()
    game.set_buttons(R=False, Start=False)
    game.step()
    _wait_for_task(game, "DebugTask_HandleMenuInput_General", "debug main menu")

    # Utilities is the first main-menu item. The input task exists one frame before
    # its list menu accepts input, so pulse until the menu-stack pointer proves the
    # submenu transition instead of relying on a blind delay.
    game.advance_until(
        lambda: _current_debug_menu_is(game, "sDebugMenu_Actions_Utilities", level=1),
        description="Utilities debug submenu",
        max_pulses=20,
        button="A",
    )
    game.step(2)
    game.press("Down", release_frames=2)  # Warp by name follows Fly to map.
    return _advance_to_task(
        game, "DebugAction_Util_Warp_SelectRegion", "named-warp region picker"
    )


def _pulse_to_value(
    game,
    task_id: int,
    data_index: int,
    expected: int,
    button: str,
    description: str,
) -> None:
    game.advance_until(
        lambda: _task_data_s16(game, task_id, data_index) == expected,
        description=description,
        max_pulses=20,
        button=button,
    )


def _hold_for_repeats(
    game, task_id: int, data_index: int, assert_current, context: str
):
    initial = _task_data_s16(game, task_id, data_index)
    observed = []
    game.set_buttons(Down=True)
    try:
        for _ in range(60):
            game.step()
            current = _task_data_s16(game, task_id, data_index)
            if current != initial and current not in observed:
                observed.append(current)
                assert_current(current, f"{context} held-repeat value {current}")
                if len(observed) == 2:
                    break
    finally:
        game.set_buttons(Down=False)
        game.step()
    assert len(observed) >= 2, (
        f"{context} did not produce two distinct JOY_REPEAT transitions; "
        f"initial={initial}, observed={observed}"
    )


def _navigate_to_map(game, entry: RegisteredMap, context: str) -> int:
    task_id = _open_named_warp(game)
    assert entry.presentation is not None
    region = PRESENTATIONS.index(entry.presentation)
    _select_ordinal(
        game,
        task_id,
        TASK_REGION,
        tuple(range(len(PRESENTATIONS))),
        region,
        f"{context} region",
    )
    _assert_region_picker(game, task_id, region, f"{context} region selected")
    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedMapGroup", f"{context} group picker"
    )
    groups = PRESENTATION_GROUPS[entry.presentation]
    _select_ordinal(
        game,
        task_id,
        TASK_MAP_GROUP,
        groups,
        groups.index(entry.group),
        f"{context} group",
    )
    _assert_group_picker(game, task_id, entry.group, f"{context} group selected")
    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedMap", f"{context} map picker"
    )
    maps = tuple(
        candidate.number
        for candidate in MAPS_BY_GROUP[entry.group]
        if candidate.presentation == entry.presentation
    )
    _select_ordinal(
        game,
        task_id,
        TASK_MAP_NUM,
        maps,
        maps.index(entry.number),
        f"{context} map",
    )
    _assert_map_picker(game, task_id, entry, f"{context} source map selected")
    return _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedWarp", f"{context} entry picker"
    )


def _assert_no_debug_residue(game, context: str) -> None:
    assert game.pointer("sDebugMenuListData") == 0, (
        f"{context} left debug menu/window allocation resident"
    )
    active = [
        symbol
        for symbol in (*NAMED_WARP_TASKS, "DebugTask_HandleMenuInput_General")
        if _task_for_function(game, symbol) is not None
    ]
    assert not active, f"{context} left named-warp tasks active: {active}"


def _assert_object_events_unfrozen(game, context: str) -> None:
    objects = game.address("gObjectEvents")
    frozen = [
        object_id
        for object_id in range(16)
        if game.read_u8(objects + object_id * 0x24) & 1
        and game.read_u8(objects + object_id * 0x24 + 1) & 1
    ]
    assert not frozen, f"{context} left active object events frozen: {frozen}"


def _assert_player_can_move(game, context: str) -> None:
    start_map = game.map_id()
    start = game.position()
    for button in ("Down", "Right", "Up", "Left"):
        game.press(button, hold_frames=8, release_frames=4)
        if game.position() != start:
            assert game.map_id() == start_map, f"{context} movement crossed maps"
            return
    raise AssertionError(f"{context} player did not move from {start}")


def _wait_for_field_ready(game, expected_map: tuple[int, int], context: str) -> None:
    game.wait_until(
        lambda: (
            game.map_id() == expected_map
            and game.callback_is("CB2_Overworld")
            and not game.controls_locked()
            and game.script_status() == 2
            and game.movement_idle()
            and game.pointer("sDebugMenuListData") == 0
            and all(
                _task_for_function(game, symbol) is None for symbol in NAMED_WARP_TASKS
            )
        ),
        description=f"{context} fully field-ready destination",
        max_frames=1_800,
        step_frames=2,
    )
    assert game.callback_is("CB2_Overworld"), f"{context} callback did not settle"
    assert not game.controls_locked(), f"{context} field controls remained locked"
    assert game.script_status() == 2, f"{context} scripts did not settle"
    assert game.movement_idle(), f"{context} player avatar did not become ready"
    _assert_no_debug_residue(game, context)


def test_debug_warp_reaches_every_settlement(game, tmp_path):
    _assert_debug_artifacts_match_source(game)
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            break
    else:
        raise AssertionError(
            "Quickstart did not reach CB2_Overworld after 3,000 SELECT pulses"
        )
    game.wait_for_controls_unlocked()

    clean_state = tmp_path / "clean-overworld.state"
    game.save_state(clean_state)

    # Drive every navigation branch through the actual debug menu.  Save states
    # return to a picker without creating another emulator process.
    navigation_region = tmp_path / "navigation-region.state"
    task_id = _open_named_warp(game)
    _assert_region_picker(game, task_id, 0, "initial region")
    game.save_state(navigation_region)
    _hold_for_repeats(
        game,
        task_id,
        TASK_REGION,
        lambda ordinal, context: _assert_region_picker(game, task_id, ordinal, context),
        "region picker",
    )
    game.load_state(navigation_region)
    game.press("Up", release_frames=2)
    _assert_region_picker(game, task_id, 5, "Hoenn-to-Johto reverse wrap")
    game.press("Down", release_frames=2)
    _assert_region_picker(game, task_id, 0, "Johto-to-Hoenn forward wrap")
    _pulse_to_value(game, task_id, TASK_REGION, 1, "Down", "region Down")
    _assert_region_picker(game, task_id, 1, "region Down")
    _pulse_to_value(game, task_id, TASK_REGION, 0, "Up", "region Up")
    _assert_region_picker(game, task_id, 0, "region Up")

    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedMapGroup", "navigation group picker"
    )
    hoenn_groups = PRESENTATION_GROUPS["Hoenn"]
    _assert_group_picker(game, task_id, hoenn_groups[0], "initial group")
    navigation_group = tmp_path / "navigation-group.state"
    game.save_state(navigation_group)
    _hold_for_repeats(
        game,
        task_id,
        TASK_MAP_GROUP,
        lambda group, context: _assert_group_picker(game, task_id, group, context),
        "group picker",
    )
    game.load_state(navigation_group)
    _pulse_to_value(
        game, task_id, TASK_MAP_GROUP, hoenn_groups[1], "Down", "group Down"
    )
    _assert_group_picker(game, task_id, hoenn_groups[1], "group Down")
    _pulse_to_value(game, task_id, TASK_MAP_GROUP, hoenn_groups[0], "Up", "group Up")
    _assert_group_picker(game, task_id, hoenn_groups[0], "group Up")
    _pulse_to_value(
        game, task_id, TASK_MAP_GROUP, hoenn_groups[-1], "Up", "group reverse wrap"
    )
    _assert_group_picker(game, task_id, hoenn_groups[-1], "group reverse wrap")
    _pulse_to_value(
        game, task_id, TASK_MAP_GROUP, hoenn_groups[0], "Down", "group forward wrap"
    )
    _assert_group_picker(game, task_id, hoenn_groups[0], "group forward wrap")
    _pulse_to_value(
        game, task_id, TASK_MAP_GROUP, hoenn_groups[10], "Right", "group Right page"
    )
    _assert_group_picker(game, task_id, hoenn_groups[10], "group Right page")
    _pulse_to_value(
        game, task_id, TASK_MAP_GROUP, hoenn_groups[0], "Left", "group Left page"
    )
    _assert_group_picker(game, task_id, hoenn_groups[0], "group Left page")

    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedMap", "navigation map picker"
    )
    hoenn_maps = tuple(
        entry
        for entry in MAPS_BY_GROUP[hoenn_groups[0]]
        if entry.presentation == "Hoenn"
    )
    _assert_map_picker(game, task_id, hoenn_maps[0], "initial map")
    navigation_map = tmp_path / "navigation-map.state"
    game.save_state(navigation_map)
    _hold_for_repeats(
        game,
        task_id,
        TASK_MAP_NUM,
        lambda number, context: _assert_map_picker(
            game,
            task_id,
            next(entry for entry in hoenn_maps if entry.number == number),
            context,
        ),
        "map picker",
    )
    game.load_state(navigation_map)
    for button, expected, context in (
        ("Down", hoenn_maps[1], "map Down"),
        ("Up", hoenn_maps[0], "map Up"),
        ("Up", hoenn_maps[-1], "map reverse wrap"),
        ("Down", hoenn_maps[0], "map forward wrap"),
        ("Right", hoenn_maps[10], "map Right page"),
        ("Left", hoenn_maps[0], "map Left page"),
    ):
        _pulse_to_value(game, task_id, TASK_MAP_NUM, expected.number, button, context)
        _assert_map_picker(game, task_id, expected, context)

    # Use the 38-warp Petalburg Gym for entry paging and both wrap directions.
    game.load_state(navigation_group)
    petalburg_gym = MAPS_BY_NAME["PetalburgCity_Gym"]
    _select_ordinal(
        game,
        task_id,
        TASK_MAP_GROUP,
        hoenn_groups,
        hoenn_groups.index(petalburg_gym.group),
        "entry-navigation group",
    )
    _assert_group_picker(game, task_id, petalburg_gym.group, "entry-navigation group")
    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedMap", "entry-navigation map picker"
    )
    petalburg_maps = tuple(
        entry
        for entry in MAPS_BY_GROUP[petalburg_gym.group]
        if entry.presentation == "Hoenn"
    )
    _select_ordinal(
        game,
        task_id,
        TASK_MAP_NUM,
        tuple(entry.number for entry in petalburg_maps),
        petalburg_maps.index(petalburg_gym),
        "Petalburg Gym map",
    )
    _assert_map_picker(game, task_id, petalburg_gym, "Petalburg Gym map")
    task_id = _advance_to_task(
        game, "DebugAction_Util_Warp_SelectNamedWarp", "navigation entry picker"
    )
    _assert_entry_picker(game, task_id, petalburg_gym, 0, "initial entry")
    navigation_entry = tmp_path / "navigation-entry.state"
    game.save_state(navigation_entry)
    _hold_for_repeats(
        game,
        task_id,
        TASK_WARP,
        lambda ordinal, context: _assert_entry_picker(
            game, task_id, petalburg_gym, ordinal, context
        ),
        "entry picker",
    )
    game.load_state(navigation_entry)
    for button, expected, context in (
        ("Down", 1, "entry Down"),
        ("Up", 0, "entry Up"),
        ("Up", 38, "entry reverse wrap"),
        ("Down", 0, "entry forward wrap"),
        ("Right", 10, "entry Right page"),
        ("Left", 0, "entry Left page"),
    ):
        _pulse_to_value(game, task_id, TASK_WARP, expected, button, context)
        _assert_entry_picker(game, task_id, petalburg_gym, expected, context)

    # Backtrack each level, checking retained selection and visible presentation.
    game.press("B", release_frames=2)
    _assert_map_picker(game, task_id, petalburg_gym, "B entry to map")
    game.press("B", release_frames=2)
    _assert_group_picker(game, task_id, petalburg_gym.group, "B map to group")
    game.press("B", release_frames=2)
    _assert_region_picker(game, task_id, 0, "B group to region")
    game.press("B", release_frames=2)
    game.wait_for_controls_unlocked()
    _assert_no_debug_residue(game, "B cancel from region")
    assert game.script_status() == 2, "B cancel did not restore idle script context"
    assert not game.controls_locked(), "B cancel left field controls locked"
    _assert_object_events_unfrozen(game, "B cancel from region")
    _assert_player_can_move(game, "B cancel from region")

    # Real non-center entries: one executable, coordinate-pinned valid warp and
    # one executable checked-in dynamic destination case.
    entry_scenarios = (
        {
            "map": petalburg_gym,
            "ordinal": 1,
            "expected_label": "Entry: Warp 1\nTo: Petalburg City",
            "expected_position": (4, 111),
            "execute": True,
        },
        {
            "map": MAPS_BY_NAME["BattleColosseum_2P"],
            "ordinal": 1,
            "expected_label": "Entry: Warp 1\nTo: Dynamic destination",
            "expected_position": (6, 8),
            "execute": True,
        },
    )
    assert petalburg_gym.display_name == "Petalburg City Gym"
    assert petalburg_gym.group_display_name == "Indoor Petalburg"
    dynamic_map = MAPS_BY_NAME["BattleColosseum_2P"]
    assert dynamic_map.display_name == "Battle Colosseum 2 P"
    assert dynamic_map.group_display_name == "Indoor Dynamic"
    for scenario in entry_scenarios:
        entry = scenario["map"]
        ordinal = scenario["ordinal"]
        context = f"non-center {entry.name} entry {ordinal}"
        game.load_state(clean_state)
        task_id = _navigate_to_map(game, entry, context)
        _pulse_to_value(game, task_id, TASK_WARP, ordinal, "Down", context)
        _assert_entry_picker(game, task_id, entry, ordinal, context)
        assert _entry_label(entry, ordinal) == scenario["expected_label"]
        assert (
            _task_data_s16(game, task_id, TASK_REGION),
            _task_data_s16(game, task_id, TASK_MAP_GROUP),
            _task_data_s16(game, task_id, TASK_MAP_NUM),
            _task_data_s16(game, task_id, TASK_WARP),
        ) == (
            PRESENTATIONS.index(entry.presentation),
            entry.group,
            entry.number,
            ordinal,
        )
        if scenario["execute"]:
            game.press("A", release_frames=2)
            _wait_for_field_ready(game, (entry.group, entry.number), context)
            assert game.map_id() == (entry.group, entry.number)
            assert game.position() == scenario["expected_position"], (
                f"{context} saved wrong player position: {game.position()}"
            )

    # Invalid destinations render a numeric fallback but still select the
    # checked-in source entry. There are currently no such product entries; the
    # zero-case assertion makes that branch explicit without aborting at import.
    if INVALID_WARPS:
        for entry, ordinal, destination, numeric_destination in INVALID_WARPS:
            context = f"invalid destination {entry.name} entry {ordinal}"
            game.load_state(clean_state)
            task_id = _navigate_to_map(game, entry, context)
            _select_ordinal(
                game,
                task_id,
                TASK_WARP,
                tuple(range(len(entry.warp_events) + 1)),
                ordinal,
                context,
            )
            _assert_entry_picker(game, task_id, entry, ordinal, context)
            assert numeric_destination is not None, (
                f"{destination} has no compiled invalid-destination numeric value"
            )
            group, number = numeric_destination
            assert _entry_label(entry, ordinal) == (
                f"Entry: Warp {ordinal}\nTo: Invalid destination {group}/{number}"
            ), destination
            game.press("B", release_frames=2)
            _assert_map_picker(game, task_id, entry, f"{context} B back")
    else:
        assert INVALID_WARPS == (), (
            "invalid-destination fallback coverage expected zero checked-in cases"
        )

    for case in CASES:
        context = f"{case.map.name} ({case.map.presentation})"
        game.load_state(clean_state)
        task_id = _open_named_warp(game)

        _select_ordinal(
            game,
            task_id,
            TASK_REGION,
            tuple(range(len(PRESENTATIONS))),
            case.region_ordinal,
            f"{context} region",
        )
        task_id = _advance_to_task(
            game,
            "DebugAction_Util_Warp_SelectNamedMapGroup",
            f"{context} group picker",
        )

        _select_ordinal(
            game,
            task_id,
            TASK_MAP_GROUP,
            case.group_choices,
            case.group_ordinal,
            f"{context} group",
        )
        task_id = _advance_to_task(
            game,
            "DebugAction_Util_Warp_SelectNamedMap",
            f"{context} map picker",
        )

        _select_ordinal(
            game,
            task_id,
            TASK_MAP_NUM,
            case.map_choices,
            case.map_ordinal,
            f"{context} map",
        )
        task_id = _advance_to_task(
            game,
            "DebugAction_Util_Warp_SelectNamedWarp",
            f"{context} entry picker",
        )

        selected = (
            _task_data_s16(game, task_id, TASK_REGION),
            _task_data_s16(game, task_id, TASK_MAP_GROUP),
            _task_data_s16(game, task_id, TASK_MAP_NUM),
            _task_data_s16(game, task_id, TASK_WARP),
        )
        expected_selection = (
            case.region_ordinal,
            case.map.group,
            case.map.number,
            0,
        )
        assert selected == expected_selection, (
            f"{context} selected wrong region/group/map/center state: "
            f"expected={expected_selection}, actual={selected}"
        )
        _assert_visible_string(
            game, "gStringVar1", UI_REGION_NAMES[case.map.presentation], context
        )
        _assert_visible_string(game, "gStringVar2", case.map.display_name, context)
        _assert_visible_string(game, "gStringVar3", "Entry: Map center", context)
        _assert_visible_string(
            game, "gStringVar2", case.map.display_name, f"{context} source map label"
        )

        expected_map = (case.map.group, case.map.number)
        game.press("A", release_frames=2)
        _wait_for_field_ready(game, expected_map, context)
        assert game.map_id() == expected_map, (
            f"{context} warped to {game.map_id()}, expected {expected_map}"
        )
