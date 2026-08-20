import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPS_ROOT = ROOT / "data" / "maps"
MAP_GROUPS = MAPS_ROOT / "map_groups.json"
HEAL_LOCATIONS = ROOT / "src" / "data" / "heal_locations.json"
GLOBAL_POKEMON_CENTER_SCRIPTS = ROOT / "data" / "scripts" / "pokemon_center.inc"
NURSE_SCRIPT = ROOT / "data" / "scripts" / "pkmn_center_nurse.inc"
EVENT_SCRIPTS = ROOT / "data" / "event_scripts.s"
FIELD_SCREEN_EFFECT = ROOT / "src" / "field_screen_effect.c"
EVENT_SCRIPTS_HEADER = ROOT / "include" / "event_scripts.h"
FLAGS = ROOT / "include" / "constants" / "flags.h"
REGION_MAP = ROOT / "src" / "region_map.c"
MAP_MACROS = ROOT / "asm" / "macros" / "map.inc"
OBJECT_EVENT_GRAPHICS = ROOT / "src" / "data" / "object_events"
NURSE_FRLG_ASSET = (
    ROOT / "graphics" / "object_events" / "pics" / "people" / "nurse_frlg.png"
)
FIXTURE = Path(__file__).with_name("fixtures") / "pokecenter_contract.json"
EMPTY_SEMANTIC_SHA256 = hashlib.sha256(b"").hexdigest()
APPROVED_NURSE_GRAPHICS_ID = "OBJ_EVENT_GFX_NURSE"
APPROVED_SHARED_2F_OWNERS = {"PokemonCenter_2F", "PokemonCenter_2F_Frlg"}
EXPECTED_FLOOR_PAIRS = {
    "BattleFrontier_PokemonCenter_1F": "BattleFrontier_PokemonCenter_2F",
    "CeladonCity_PokemonCenter_1F_Frlg": "CeladonCity_PokemonCenter_2F_Frlg",
    "CeruleanCity_PokemonCenter_1F_Frlg": "CeruleanCity_PokemonCenter_2F_Frlg",
    "CinnabarIsland_PokemonCenter_1F_Frlg": "CinnabarIsland_PokemonCenter_2F_Frlg",
    "DewfordTown_PokemonCenter_1F": "DewfordTown_PokemonCenter_2F",
    "EverGrandeCity_PokemonCenter_1F": "EverGrandeCity_PokemonCenter_2F",
    "EverGrandeCity_PokemonLeague_1F": "EverGrandeCity_PokemonLeague_2F",
    "FallarborTown_PokemonCenter_1F": "FallarborTown_PokemonCenter_2F",
    "FiveIsland_PokemonCenter_1F_Frlg": "FiveIsland_PokemonCenter_2F_Frlg",
    "FortreeCity_PokemonCenter_1F": "FortreeCity_PokemonCenter_2F",
    "FourIsland_PokemonCenter_1F_Frlg": "FourIsland_PokemonCenter_2F_Frlg",
    "FuchsiaCity_PokemonCenter_1F_Frlg": "FuchsiaCity_PokemonCenter_2F_Frlg",
    "IndigoPlateau_PokemonCenter_1F_Frlg": "IndigoPlateau_PokemonCenter_2F_Frlg",
    "LavaridgeTown_PokemonCenter_1F": "LavaridgeTown_PokemonCenter_2F",
    "LavenderTown_PokemonCenter_1F_Frlg": "LavenderTown_PokemonCenter_2F_Frlg",
    "LilycoveCity_PokemonCenter_1F": "LilycoveCity_PokemonCenter_2F",
    "MauvilleCity_PokemonCenter_1F": "MauvilleCity_PokemonCenter_2F",
    "MossdeepCity_PokemonCenter_1F": "MossdeepCity_PokemonCenter_2F",
    "OldaleTown_PokemonCenter_1F": "OldaleTown_PokemonCenter_2F",
    "OneIsland_PokemonCenter_1F_Frlg": "OneIsland_PokemonCenter_2F_Frlg",
    "PacifidlogTown_PokemonCenter_1F": "PacifidlogTown_PokemonCenter_2F",
    "PetalburgCity_PokemonCenter_1F": "PetalburgCity_PokemonCenter_2F",
    "PewterCity_PokemonCenter_1F_Frlg": "PewterCity_PokemonCenter_2F_Frlg",
    "Route10_PokemonCenter_1F_Frlg": "Route10_PokemonCenter_2F_Frlg",
    "Route4_PokemonCenter_1F_Frlg": "Route4_PokemonCenter_2F_Frlg",
    "RustboroCity_PokemonCenter_1F": "RustboroCity_PokemonCenter_2F",
    "SaffronCity_PokemonCenter_1F_Frlg": "SaffronCity_PokemonCenter_2F_Frlg",
    "SevenIsland_PokemonCenter_1F_Frlg": "SevenIsland_PokemonCenter_2F_Frlg",
    "SixIsland_PokemonCenter_1F_Frlg": "SixIsland_PokemonCenter_2F_Frlg",
    "SlateportCity_PokemonCenter_1F": "SlateportCity_PokemonCenter_2F",
    "SootopolisCity_PokemonCenter_1F": "SootopolisCity_PokemonCenter_2F",
    "ThreeIsland_PokemonCenter_1F_Frlg": "ThreeIsland_PokemonCenter_2F_Frlg",
    "TwoIsland_PokemonCenter_1F_Frlg": "TwoIsland_PokemonCenter_2F_Frlg",
    "VerdanturfTown_PokemonCenter_1F": "VerdanturfTown_PokemonCenter_2F",
    "VermilionCity_PokemonCenter_1F_Frlg": "VermilionCity_PokemonCenter_2F_Frlg",
    "ViridianCity_PokemonCenter_1F_Frlg": "ViridianCity_PokemonCenter_2F_Frlg",
}
EXPECTED_PAIRS = len(EXPECTED_FLOOR_PAIRS)
EXPECTED_SHARED_2F_OWNERS = {
    second_floor: (
        "PokemonCenter_2F_Frlg"
        if second_floor.endswith("_Frlg")
        else "PokemonCenter_2F"
    )
    for second_floor in EXPECTED_FLOOR_PAIRS.values()
}
FACILITY_NURSE_MAPS = {
    "TrainerHill_Entrance",
    "TrainerTower_Lobby_Frlg",
}
IMPORTED_FRLG_NURSE_MAPS = {
    name for name in EXPECTED_FLOOR_PAIRS if name.endswith("_Frlg")
} | {"TrainerTower_Lobby_Frlg"}
EMERALD_CABLE_HOOKS = (
    "CableClub_OnFrame",
    "CableClub_OnWarp",
    "CableClub_OnLoad",
    "CableClub_OnTransition",
)
FRLG_CABLE_HOOKS = tuple(f"{hook}_Frlg" for hook in EMERALD_CABLE_HOOKS)
CABLE_TABLE_KINDS = (
    "MAP_SCRIPT_ON_FRAME_TABLE",
    "MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE",
    "MAP_SCRIPT_ON_LOAD",
    "MAP_SCRIPT_ON_TRANSITION",
)

# These are deliberately source-level names. They make local story behavior visible
# even though the map-table and respawn boilerplate is omitted from the digest.
SPECIAL_CENTER_TOKENS = {
    "OneIsland_PokemonCenter_1F_Frlg": (
        "map_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad",
        "map_script MAP_SCRIPT_ON_FRAME_TABLE, OneIsland_PokemonCenter_1F_OnFrame",
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 6, OneIsland_PokemonCenter_1F_EventScript_SetCelioQuestDone",
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 0, OneIsland_PokemonCenter_1F_EventScript_SetBillCelioFirstMeetingPos",
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 2, OneIsland_PokemonCenter_1F_EventScript_SetBillCelioReadyToLeavePos",
    ),
    "SixIsland_PokemonCenter_1F_Frlg": (
        "map_script MAP_SCRIPT_ON_FRAME_TABLE, SixIsland_PokemonCenter_1F_OnFrame",
        "call_if_eq VAR_MAP_SCENE_SIX_ISLAND_POKEMON_CENTER_1F, 0, SixIsland_PokemonCenter_1F_EventScript_ShowRival",
        "map_script_2 VAR_MAP_SCENE_SIX_ISLAND_POKEMON_CENTER_1F, 0, SixIsland_PokemonCenter_1F_EventScript_RivalScene",
    ),
    "Route4_PokemonCenter_1F_Frlg": (
        "setworldmapflag FLAG_WORLD_MAP_ROUTE4_POKEMON_CENTER_1F",
        "Route4_PokemonCenter_1F_EventScript_MagikarpSalesman",
    ),
    "Route10_PokemonCenter_1F_Frlg": (
        "setworldmapflag FLAG_WORLD_MAP_ROUTE10_POKEMON_CENTER_1F",
        "Route10_PokemonCenter_1F_EventScript_GetAideRequestInfo",
    ),
    "IndigoPlateau_PokemonCenter_1F_Frlg": (
        "specialvar VAR_RESULT, IsNationalPokedexEnabled",
        "call_if_eq VAR_RESULT, TRUE, IndigoPlateau_PokemonCenter_1F_EventScript_CheckBlockDoor",
    ),
    "LilycoveCity_PokemonCenter_1F": (
        "goto LilycoveCity_PokemonCenter_1F_EventScript_SetLilycoveLadyGfx",
        "special SetLilycoveLadyGfx",
    ),
    "MauvilleCity_PokemonCenter_1F": (
        "call Common_EventScript_UpdateBrineyLocation",
        "goto MauvilleCity_PokemonCenter_1F_EventScript_SetMauvilleOldManGfx",
    ),
    "LavaridgeTown_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "EverGrandeCity_PokemonCenter_1F": (
        "call_if_unset FLAG_MET_SCOTT_IN_EVERGRANDE, EverGrandeCity_PokemonCenter_1F_EventScript_TryShowScott",
    ),
    "EverGrandeCity_PokemonLeague_1F": (
        "setflag FLAG_LANDMARK_POKEMON_LEAGUE",
        "call_if_unset FLAG_ENTERED_ELITE_FOUR, EverGrandeCity_PokemonLeague_1F_EventScript_GuardsBlockDoor",
    ),
}

SPECIAL_1F_TABLE_ROWS = {
    "OneIsland_PokemonCenter_1F_Frlg": (
        "map_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad",
        "map_script MAP_SCRIPT_ON_FRAME_TABLE, OneIsland_PokemonCenter_1F_OnFrame",
    ),
    "SixIsland_PokemonCenter_1F_Frlg": (
        "map_script MAP_SCRIPT_ON_FRAME_TABLE, SixIsland_PokemonCenter_1F_OnFrame",
    ),
}

SPECIAL_1F_TRANSITION_ROWS = {
    "DewfordTown_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "EverGrandeCity_PokemonCenter_1F": (
        "call_if_unset FLAG_MET_SCOTT_IN_EVERGRANDE, EverGrandeCity_PokemonCenter_1F_EventScript_TryShowScott",
    ),
    "EverGrandeCity_PokemonLeague_1F": (
        "setflag FLAG_LANDMARK_POKEMON_LEAGUE",
        "call_if_unset FLAG_ENTERED_ELITE_FOUR, EverGrandeCity_PokemonLeague_1F_EventScript_GuardsBlockDoor",
    ),
    "FallarborTown_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "IndigoPlateau_PokemonCenter_1F_Frlg": (
        "specialvar VAR_RESULT, IsNationalPokedexEnabled",
        "call_if_eq VAR_RESULT, TRUE, IndigoPlateau_PokemonCenter_1F_EventScript_CheckBlockDoor",
    ),
    "LavaridgeTown_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "LilycoveCity_PokemonCenter_1F": (
        "goto LilycoveCity_PokemonCenter_1F_EventScript_SetLilycoveLadyGfx",
    ),
    "MauvilleCity_PokemonCenter_1F": (
        "call Common_EventScript_UpdateBrineyLocation",
        "goto MauvilleCity_PokemonCenter_1F_EventScript_SetMauvilleOldManGfx",
    ),
    "OldaleTown_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "OneIsland_PokemonCenter_1F_Frlg": (
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 6, OneIsland_PokemonCenter_1F_EventScript_SetCelioQuestDone",
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 0, OneIsland_PokemonCenter_1F_EventScript_SetBillCelioFirstMeetingPos",
        "call_if_eq VAR_MAP_SCENE_ONE_ISLAND_POKEMON_CENTER_1F, 2, OneIsland_PokemonCenter_1F_EventScript_SetBillCelioReadyToLeavePos",
    ),
    "PetalburgCity_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "Route10_PokemonCenter_1F_Frlg": (
        "setworldmapflag FLAG_WORLD_MAP_ROUTE10_POKEMON_CENTER_1F",
    ),
    "Route4_PokemonCenter_1F_Frlg": (
        "setworldmapflag FLAG_WORLD_MAP_ROUTE4_POKEMON_CENTER_1F",
    ),
    "RustboroCity_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "SixIsland_PokemonCenter_1F_Frlg": (
        "call_if_eq VAR_MAP_SCENE_SIX_ISLAND_POKEMON_CENTER_1F, 0, SixIsland_PokemonCenter_1F_EventScript_ShowRival",
    ),
    "SlateportCity_PokemonCenter_1F": ("call Common_EventScript_UpdateBrineyLocation",),
    "VerdanturfTown_PokemonCenter_1F": (
        "call Common_EventScript_UpdateBrineyLocation",
    ),
}

# This clerk is local non-Pokecenter behavior covered by the semantic digest. Its
# source was migrated to the byte-equivalent standard mart macro, so retain the
# reviewed expanded command stream rather than accepting arbitrary macro changes.
APPROVED_STANDARD_MART_CLERKS = {
    "EverGrandeCity_PokemonLeague_1F": (
        "EverGrandeCity_PokemonLeague_1F_EventScript_Clerk",
        "EverGrandeCity_PokemonLeague_1F_Pokemart",
        "msgbox gText_PleaseComeAgain, MSGBOX_DEFAULT",
    ),
    "IndigoPlateau_PokemonCenter_1F_Frlg": (
        "IndigoPlateau_PokemonCenter_1F_EventScript_Clerk",
        "IndigoPlateau_PokemonCenter_1F_Items",
        "msgbox gText_PleaseComeAgain",
    ),
}


def _reviewed_maps():
    groups = json.loads(MAP_GROUPS.read_text(encoding="utf-8"))
    reviewed_names = {name for group in groups["group_order"] for name in groups[group]}
    maps = {}
    paths = {}
    for path in sorted(MAPS_ROOT.glob("*/map.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["name"] in reviewed_names:
            maps[data["name"]] = data
            paths[data["name"]] = path
    return maps, paths


def _discover_pairs(maps):
    by_id = {data["id"]: name for name, data in maps.items()}
    pairs = {}
    for name, data in maps.items():
        if not ("PokemonCenter_1F" in name or "PokemonLeague_1F" in name):
            continue
        destinations = {
            by_id[warp["dest_map"]]
            for warp in data.get("warp_events", [])
            if warp["dest_map"] in by_id
        }
        second_floors = sorted(
            destination
            for destination in destinations
            if "PokemonCenter_2F" in destination or "PokemonLeague_2F" in destination
        )
        if second_floors:
            if len(second_floors) != 1:
                raise AssertionError(f"{name} links to multiple second floors")
            pairs[name] = second_floors[0]
    return dict(sorted(pairs.items()))


def _is_nurse_object(obj):
    return "NURSE" in obj.get("graphics_id", "") or "NURSE" in obj.get("local_id", "")


def _authoritative_nurse_local_id(map_name):
    data = json.loads((MAPS_ROOT / map_name / "map.json").read_text(encoding="utf-8"))
    nurses = [obj for obj in data.get("object_events", []) if _is_nurse_object(obj)]
    if len(nurses) != 1 or "local_id" not in nurses[0]:
        raise AssertionError(f"{map_name}: expected one nurse object with a local_id")
    return nurses[0]["local_id"]


def _full_map_semantic_digest(data, baseline_nurse_graphics_id):
    """Hash the complete map, masking only approved Pokecenter migrations."""
    approved_nurse_graphics_ids = {
        baseline_nurse_graphics_id,
        APPROVED_NURSE_GRAPHICS_ID,
    }
    for obj in data.get("object_events", []):
        if (
            _is_nurse_object(obj)
            and obj.get("graphics_id") not in approved_nurse_graphics_ids
        ):
            raise AssertionError(
                f"{data['name']}: unapproved nurse graphics_id "
                f"{obj.get('graphics_id')!r}"
            )

    normalized = dict(data)
    if "_2F" in data["name"]:
        normalized.pop("shared_scripts_map", None)
    if "object_events" in data:
        normalized["object_events"] = [
            {
                key: (
                    f"<normalized nurse {key}>"
                    if _is_nurse_object(obj) and key in {"graphics_id", "script"}
                    else value
                )
                for key, value in obj.items()
            }
            for obj in data["object_events"]
        ]
    semantic_json = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(semantic_json.encode("utf-8")).hexdigest()


def _script_path(map_name):
    return MAPS_ROOT / map_name / "scripts.inc"


def _resolve_2f_sources(
    map_name, shared_owner, local_source, global_source, baseline_local_digest
):
    """Select the exact 2F table owner while enforcing local-content retention."""
    if shared_owner and shared_owner not in APPROVED_SHARED_2F_OWNERS:
        raise AssertionError(f"{map_name}: unapproved shared scripts owner")
    if local_source is None and (
        not shared_owner or baseline_local_digest != EMPTY_SEMANTIC_SHA256
    ):
        raise AssertionError(f"{map_name}: required local scripts.inc is missing")
    if shared_owner:
        if global_source is None:
            raise AssertionError(f"{map_name}: global pokemon_center.inc is missing")
        return local_source or "", global_source, f"{shared_owner}_MapScripts"
    return local_source, local_source, f"{map_name}_MapScripts"


def _valid_shared_2f_tables(source):
    expected = []
    for owner, hooks in (
        ("PokemonCenter_2F", EMERALD_CABLE_HOOKS),
        ("PokemonCenter_2F_Frlg", FRLG_CABLE_HOOKS),
    ):
        expected.append(f"{owner}_MapScripts::")
        expected.extend(
            f"map_script {kind}, {hook}" for kind, hook in zip(CABLE_TABLE_KINDS, hooks)
        )
        expected.append(".byte 0")
    active_lines = tuple(
        _canonical_line(line)
        for line in _active_source(source).splitlines()
        if line.strip()
    )
    return active_lines == tuple(expected)


def _valid_shared_2f_owners(shared_owners):
    return shared_owners == EXPECTED_SHARED_2F_OWNERS


def _active_source(source):
    """Return assembler source with comments removed, preserving quoted '@'."""
    active = []
    for raw_line in source.splitlines():
        quoted = False
        escaped = False
        chars = []
        for char in raw_line:
            if char == "@" and not quoted:
                break
            chars.append(char)
            if char == '"' and not escaped:
                quoted = not quoted
            escaped = char == "\\" and not escaped
            if char != "\\":
                escaped = False
        active.append("".join(chars).rstrip())
    return "\n".join(active) + "\n"


def _has_directive(source, directive):
    return re.search(rf"(?m)^\s*{re.escape(directive)}\s*$", _active_source(source))


def _label_section_span(source, label):
    label_match = re.search(rf"(?m)^{re.escape(label)}::?\s*$", source)
    if not label_match:
        return None
    next_label = re.search(
        r"(?m)^[A-Za-z_][A-Za-z0-9_]*::?\s*$", source[label_match.end() :]
    )
    end = label_match.end() + next_label.start() if next_label else len(source)
    return label_match.start(), end


def _canonical_line(line):
    line = re.sub(r"\s*,\s*", ", ", line.strip())
    return re.sub(r"\s+", " ", line)


def _section_lines(source, label):
    span = _label_section_span(source, label)
    if not span:
        return None
    return tuple(
        _canonical_line(line)
        for line in source[span[0] : span[1]].splitlines()[1:]
        if line.strip()
    )


def _expected_1f_table(map_name):
    symbol = map_name.removesuffix("_Frlg")
    return (
        f"map_script MAP_SCRIPT_ON_TRANSITION, {symbol}_OnTransition",
        "map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume",
        *SPECIAL_1F_TABLE_ROWS.get(map_name, ()),
        ".byte 0",
    )


def _expected_1f_transition(map_name, heal_location):
    callbacks = SPECIAL_1F_TRANSITION_ROWS.get(map_name, ())
    if map_name.startswith(("Route4_", "Route10_")):
        return (*callbacks, f"setrespawn {heal_location}", "end")
    return (f"setrespawn {heal_location}", *callbacks, "end")


def _valid_1f_macro_definition(source):
    definition = _macro_definition(source, "pokemon_center_1f_scripts")
    if not definition:
        return False
    return tuple(
        _canonical_line(line) for line in definition.splitlines() if line.strip()
    ) == (
        ".macro pokemon_center_1f_scripts transition:req, heal_location:req, transition_hook=, on_load=, on_frame=",
        "map_script MAP_SCRIPT_ON_TRANSITION, \\transition",
        "map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume",
        ".ifnb \\on_load",
        "map_script MAP_SCRIPT_ON_LOAD, \\on_load",
        ".endif",
        ".ifnb \\on_frame",
        "map_script MAP_SCRIPT_ON_FRAME_TABLE, \\on_frame",
        ".endif",
        ".byte 0",
        ".global \\transition",
        "\\transition\\():",
        "setrespawn \\heal_location",
        ".ifnb \\transition_hook",
        "call \\transition_hook",
        ".endif",
        "end",
        ".endm",
    )


def _macro_invocation_details(map_name, source, macro_source):
    active = _active_source(source)
    all_invocations = re.findall(r"(?m)^\s*pokemon_center_1f_scripts(?:\s|$)", active)
    invocation_pattern = re.compile(
        rf"(?m)^{re.escape(map_name)}_MapScripts::\s*\n"
        r"\s*pokemon_center_1f_scripts\s+([^\n]+?)\s*$"
    )
    invocations = invocation_pattern.findall(active)
    any_owner_invocations = re.findall(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)_MapScripts::\s*\n"
        r"\s*pokemon_center_1f_scripts\s+([^\n]+?)\s*$",
        active,
    )
    if not invocations:
        return False if all_invocations else None
    if (
        len(invocations) != 1
        or len(all_invocations) != 1
        or len(any_owner_invocations) != 1
        or not _valid_1f_macro_definition(macro_source)
    ):
        return False
    args = tuple(part.strip() for part in invocations[0].split(","))
    if not 2 <= len(args) <= 5:
        return False
    transition, heal_location, *optional = args
    symbol = map_name.removesuffix("_Frlg")
    if transition != f"{symbol}_OnTransition" or not re.fullmatch(
        r"HEAL_LOCATION_[A-Z0-9_]+", heal_location
    ):
        return False

    callbacks = SPECIAL_1F_TRANSITION_ROWS.get(map_name, ())
    table_rows = SPECIAL_1F_TABLE_ROWS.get(map_name, ())
    on_load = next(
        (
            row.removeprefix("map_script MAP_SCRIPT_ON_LOAD, ")
            for row in table_rows
            if row.startswith("map_script MAP_SCRIPT_ON_LOAD, ")
        ),
        "",
    )
    on_frame = next(
        (
            row.removeprefix("map_script MAP_SCRIPT_ON_FRAME_TABLE, ")
            for row in table_rows
            if row.startswith("map_script MAP_SCRIPT_ON_FRAME_TABLE, ")
        ),
        "",
    )
    required_optional_count = 3 if on_frame else 2 if on_load else 1 if callbacks else 0
    if len(optional) != required_optional_count:
        return False
    supplied_optional = [*optional, *([""] * (3 - len(optional)))]
    transition_hook, supplied_on_load, supplied_on_frame = supplied_optional
    if supplied_on_load != on_load or supplied_on_frame != on_frame:
        return False
    for callback in (supplied_on_load, supplied_on_frame):
        if callback and _label_section_span(active, callback) is None:
            return False

    hook_span = None
    if callbacks:
        direct_hook = (
            len(callbacks) == 1
            and callbacks[0].startswith("call ")
            and transition_hook == callbacks[0].removeprefix("call ")
        )
        if not direct_hook:
            hook_span = _label_section_span(active, transition_hook)
            if not hook_span:
                return False
            hook_lines = _section_lines(active, transition_hook)
            if hook_lines != (*callbacks, "return"):
                return False
    elif transition_hook:
        return False

    return {"callbacks": callbacks, "hook_span": hook_span}


def _macro_invocation(map_name, source, macro_source):
    details = _macro_invocation_details(map_name, source, macro_source)
    return details if details is None or details is False else True


def _validate_excluded_sections(map_name, source, macro_source="", shared_owner=None):
    active = _active_source(source)
    invocation = _macro_invocation_details(map_name, active, macro_source)
    if invocation is not None:
        if invocation is False:
            raise AssertionError(
                f"{map_name}: invalid pokemon_center_1f_scripts contract"
            )
        symbol = map_name.removesuffix("_Frlg")
        transition_span = _label_section_span(active, f"{symbol}_OnTransition")
        if transition_span:
            raise AssertionError(f"{map_name}: macro invocation duplicates transition")
    elif "_2F" not in map_name and _label_section_span(
        active, f"{map_name}_MapScripts"
    ):
        table_label = f"{map_name}_MapScripts"
        if _section_lines(active, table_label) != _expected_1f_table(map_name):
            raise AssertionError(f"{map_name}: unexpected active 1F map-script table")
        symbol = map_name.removesuffix("_Frlg")
        transition_lines = _section_lines(active, f"{symbol}_OnTransition")
        if not transition_lines:
            raise AssertionError(f"{map_name}: missing 1F transition script")
        respawns = [
            line.removeprefix("setrespawn ")
            for line in transition_lines
            if line.startswith("setrespawn ")
        ]
        if len(respawns) != 1 or transition_lines != _expected_1f_transition(
            map_name, respawns[0]
        ):
            raise AssertionError(f"{map_name}: unexpected active 1F transition script")

    nurse_labels = re.findall(
        r"(?m)^([A-Za-z0-9_]+_(?:PokemonCenter|PokemonLeague)_1F_EventScript_Nurse)::?\s*$",
        active,
    )
    if nurse_labels:
        raise AssertionError(f"{map_name}: unexpected active nurse wrapper")

    if "_2F" in map_name and shared_owner:
        if shared_owner not in APPROVED_SHARED_2F_OWNERS:
            raise AssertionError(f"{map_name}: unapproved shared scripts owner")
        if _label_section_span(active, f"{map_name}_MapScripts"):
            raise AssertionError(f"{map_name}: retained shared 2F table")
        symbol = map_name.removesuffix("_Frlg")
        for suffix in ("Colosseum", "TradeCenter", "RecordCorner"):
            if _label_section_span(active, f"{symbol}_EventScript_{suffix}"):
                raise AssertionError(f"{map_name}: retained shared 2F {suffix} wrapper")
    elif "_2F" in map_name:
        hooks = FRLG_CABLE_HOOKS if map_name.endswith("_Frlg") else EMERALD_CABLE_HOOKS
        expected_table = (
            *(
                f"map_script {kind}, {hook}"
                for kind, hook in zip(
                    (
                        "MAP_SCRIPT_ON_FRAME_TABLE",
                        "MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE",
                        "MAP_SCRIPT_ON_LOAD",
                        "MAP_SCRIPT_ON_TRANSITION",
                    ),
                    hooks,
                )
            ),
            ".byte 0",
        )
        if _section_lines(active, f"{map_name}_MapScripts") != expected_table:
            raise AssertionError(f"{map_name}: unexpected active 2F map-script table")
        symbol = map_name.removesuffix("_Frlg")
        family_suffix = "_Frlg" if map_name.endswith("_Frlg") else ""
        for suffix in ("Colosseum", "TradeCenter", "RecordCorner"):
            label = f"{symbol}_EventScript_{suffix}"
            expected = (f"call CableClub_EventScript_{suffix}{family_suffix}", "end")
            if _section_lines(active, label) != expected:
                raise AssertionError(
                    f"{map_name}: unexpected active 2F {suffix} wrapper"
                )
    return invocation


def _expand_approved_standard_mart_clerk(map_name, source):
    approved = APPROVED_STANDARD_MART_CLERKS.get(map_name)
    if not approved:
        return source
    label, products, farewell = approved
    span = _label_section_span(source, label)
    invocation = f"standard_mart_clerk {products}"
    if not span or _section_lines(source, label) != (invocation, ".align 2"):
        return source

    section = source[span[0] : span[1]]
    expanded = "\n".join(
        (
            "lock",
            "faceplayer",
            "message gText_HowMayIServeYou",
            "waitmessage",
            f"pokemart {products}",
            farewell,
            "release",
            "end",
        )
    )
    section = re.sub(
        rf"(?m)^\s*{re.escape(invocation)}\s*$",
        expanded,
        section,
        count=1,
    )
    return source[: span[0]] + section + source[span[1] :]


def _normalize_local_script(map_name, source, macro_source="", shared_owner=None):
    """Build a formatting- and dialogue-insensitive semantic local contract."""
    invocation = _validate_excluded_sections(
        map_name, source, macro_source, shared_owner
    )
    source = _expand_approved_standard_mart_clerk(map_name, _active_source(source))
    table_label = f"{map_name}_MapScripts"
    table_span = _label_section_span(source, table_label)
    transition_label = None
    if table_span:
        table = source[table_span[0] : table_span[1]]
        match = re.search(
            r"map_script\s+MAP_SCRIPT_ON_TRANSITION,\s*([A-Za-z0-9_]+)", table
        )
        transition_label = match.group(1) if match else None

    removals = []
    macro_callbacks = ()
    if invocation not in (None, False):
        macro_callbacks = invocation["callbacks"]
        if invocation["hook_span"]:
            removals.append(invocation["hook_span"])
    if table_span:
        replacement = ""
        if macro_callbacks:
            callback_source = "\n".join(macro_callbacks) + "\n"
            callback_targets = [
                match.group(1)
                for callback in macro_callbacks
                if (
                    match := re.search(
                        rf"\b({re.escape(map_name.removesuffix('_Frlg'))}_[A-Za-z0-9_]+)$",
                        callback,
                    )
                )
            ]
            target_spans = [
                span
                for target in callback_targets
                if (span := _label_section_span(source, target))
            ]
            if SPECIAL_1F_TABLE_ROWS.get(map_name, ()) and target_spans:
                callback_position = min(span[0] for span in target_spans)
                removals.append((callback_position, callback_position, callback_source))
            else:
                replacement = callback_source
        removals.append((*table_span, replacement))

    if transition_label:
        span = _label_section_span(source, transition_label)
        if span:
            section = source[span[0] : span[1]]
            lines = section.splitlines(keepends=True)[1:]
            retained = []
            for line in lines:
                stripped = line.strip()
                if re.fullmatch(r"setrespawn\s+HEAL_LOCATION_[A-Z0-9_]+", stripped):
                    continue
                if stripped == "end":
                    continue
                retained.append(line)
            removals.append((span[0], span[1], "".join(retained)))

    removable_labels = re.findall(
        rf"(?m)^({re.escape(map_name.removesuffix('_Frlg'))}_EventScript_Nurse)::?\s*$",
        source,
    )
    # FRLG directory names include _Frlg, while their local symbols do not.
    removable_labels += re.findall(
        r"(?m)^([A-Za-z0-9_]+_PokemonCenter_1F_EventScript_Nurse)::?\s*$",
        source,
    )
    if "PokemonLeague_1F" in map_name:
        removable_labels += re.findall(
            r"(?m)^([A-Za-z0-9_]+_PokemonLeague_1F_EventScript_Nurse)::?\s*$",
            source,
        )
    for label in sorted(set(removable_labels)):
        span = _label_section_span(source, label)
        if span:
            removals.append(span)

    if "_2F" in map_name:
        for suffix in ("Colosseum", "TradeCenter", "RecordCorner"):
            match = re.search(
                rf"(?m)^([A-Za-z0-9_]+_EventScript_{suffix})::?\s*$", source
            )
            if match and (span := _label_section_span(source, match.group(1))):
                removals.append(span)

    normalized = source
    normalized_removals = [
        removal if len(removal) == 3 else (*removal, "") for removal in removals
    ]
    for start, end, replacement in sorted(normalized_removals, reverse=True):
        normalized = normalized[:start] + replacement + normalized[end:]
    semantic_lines = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped or re.match(r"pokemon_center_1f_scripts(?:\s|$)", stripped):
            continue
        if stripped.startswith(".string"):
            stripped = ".string"
        # Whitespace and comma style are presentation; tokens and their order are ABI.
        stripped = re.sub(r"\s*,\s*", ",", stripped)
        stripped = re.sub(r"\s+", " ", stripped)
        semantic_lines.append(stripped)
    return "\n".join(semantic_lines)


def _macro_definition(source, name):
    active = _active_source(source)
    start = re.search(rf"(?m)^\s*\.macro\s+{re.escape(name)}(?:\s|$)", active)
    if not start:
        return None
    end = re.search(r"(?m)^\s*\.endm\s*$", active[start.end() :])
    if not end:
        return None
    return active[start.start() : start.end() + end.end()]


def _has_1f_shell(source, macro_source=""):
    active = _active_source(source)
    transition = re.search(
        r"(?m)^\s*map_script\s+MAP_SCRIPT_ON_TRANSITION,\s*([A-Za-z0-9_]+)\s*$",
        active,
    )
    resume = re.search(
        r"(?m)^\s*map_script\s+MAP_SCRIPT_ON_RESUME,\s*CableClub_OnResume\s*$",
        active,
    )
    if transition and resume:
        span = _label_section_span(active, transition.group(1))
        table_label = re.search(r"(?m)^([A-Za-z0-9_]+_MapScripts)::?\s*$", active)
        if span and table_label:
            map_name = table_label.group(1).removesuffix("_MapScripts")
            try:
                _validate_excluded_sections(map_name, active)
            except AssertionError:
                return False
            return True
    invocation = re.search(
        r"(?m)^([A-Za-z_][A-Za-z0-9_]*)_MapScripts::\s*\n"
        r"\s*pokemon_center_1f_scripts(?:\s|$)",
        active,
    )
    if not invocation:
        return False
    map_name = invocation.group(1)
    return _macro_invocation(map_name, active, macro_source) is True


def _has_nurse_target(source, script, nurse_local_id=None):
    active = _active_source(source)
    if script == "Common_EventScript_PkmnCenterNurse_Interact":
        return _section_lines(
            _active_source(NURSE_SCRIPT.read_text(encoding="utf-8")), script
        ) == (
            "copyvar VAR_0x800B, VAR_LAST_TALKED",
            "call Common_EventScript_PkmnCenterNurse",
            "waitmessage",
            "waitbuttonpress",
            "release",
            "end",
        )
    span = _label_section_span(active, script)
    if not span:
        return False
    lines = _section_lines(active, script)
    emerald = (
        f"setvar VAR_0x800B, {nurse_local_id}",
        "call Common_EventScript_PkmnCenterNurse",
        "waitmessage",
        "waitbuttonpress",
        "release",
        "end",
    )
    return (
        lines is not None
        and len(lines) == len(emerald)
        and all(
            item.fullmatch(actual) is not None
            if hasattr(item, "fullmatch")
            else item == actual
            for item, actual in zip(emerald, lines)
        )
    )


def _respawn_ids(source):
    active = _active_source(source)
    transition = re.search(
        r"(?m)^\s*map_script\s+MAP_SCRIPT_ON_TRANSITION,\s*([A-Za-z0-9_]+)\s*$",
        active,
    )
    if transition and (span := _label_section_span(active, transition.group(1))):
        direct = re.findall(
            r"(?m)^\s*setrespawn\s+(HEAL_LOCATION_[A-Z0-9_]+)\s*$",
            active[span[0] : span[1]],
        )
        if direct:
            return direct
    invocation = re.search(r"(?m)^\s*pokemon_center_1f_scripts\s+([^@\n]+)\s*$", active)
    return (
        re.findall(r"\bHEAL_LOCATION_[A-Z0-9_]+\b", invocation.group(1))
        if invocation
        else []
    )


def _cable_table(source, table_label=None):
    active = _active_source(source)
    if table_label:
        lines = _section_lines(active, table_label)
        if lines is None:
            return []
        table_source = "\n".join(lines)
    else:
        table_source = active
    rows = re.findall(
        r"(?m)^\s*map_script\s+(MAP_SCRIPT_[A-Z_]+),\s*([A-Za-z0-9_]+)\s*$",
        table_source,
    )
    if not rows:
        return []
    expected_lines = tuple(f"map_script {kind}, {hook}" for kind, hook in rows) + (
        ".byte 0",
    )
    if table_label:
        return rows if lines == expected_lines else []
    discovered_label = re.search(r"(?m)^([A-Za-z0-9_]+_MapScripts)::?\s*$", active)
    if discovered_label:
        lines = _section_lines(active, discovered_label.group(1))
    else:
        lines = tuple(
            _canonical_line(line) for line in active.splitlines() if line.strip()
        )
        expected_lines = expected_lines[:-1]
    return rows if lines == expected_lines else []


def _has_facility_exclusion(source, predicate):
    active = _active_source(source)
    if predicate not in {
        "PlayerNotAtTrainerHillEntrance",
        "IsPlayerNotInTrainerTowerLobby",
    }:
        return False
    label = "EventScript_PkmnCenterNurse_CheckTrainerHillAndUnionRoom"
    expected = (
        "specialvar VAR_RESULT, PlayerNotAtTrainerHillEntrance",
        "goto_if_eq VAR_RESULT, 0, EventScript_PkmnCenterNurse_ReturnPkmn",
        "specialvar VAR_RESULT, IsPlayerNotInTrainerTowerLobby",
        "goto_if_eq VAR_RESULT, FALSE, EventScript_PkmnCenterNurse_ReturnPkmn",
        "specialvar VAR_RESULT, BufferUnionRoomPlayerName",
        "copyvar VAR_0x8008, VAR_RESULT",
        "goto_if_eq VAR_0x8008, 0, EventScript_PkmnCenterNurse_ReturnPkmn",
        "goto_if_eq VAR_0x8008, 1, EventScript_PkmnCenterNurse_PlayerWaitingInUnionRoom",
        "end",
    )
    return _section_lines(active, label) == expected


def _has_active_token(source, token):
    active = _active_source(source)
    if " " not in token:
        return _label_section_span(active, token) is not None
    return _has_directive(active, token) is not None


def _has_preserved_special_token(map_name, source, token, macro_source):
    if _has_active_token(source, token):
        return True
    invocation = _macro_invocation_details(map_name, source, macro_source)
    if invocation is None or invocation is False:
        return False
    if token in SPECIAL_1F_TABLE_ROWS.get(map_name, ()):
        return True
    return (
        token.startswith("call ")
        and invocation["callbacks"] == (token,)
        and invocation["hook_span"] is None
    )


def _repository_macro_source(name):
    declaration = re.compile(rf"(?m)^\s*\.macro\s+{re.escape(name)}(?:\s|$)")
    source = MAP_MACROS.read_text(encoding="utf-8")
    return source if declaration.search(_active_source(source)) else ""


def _test_1f_macro_source():
    return r""".macro pokemon_center_1f_scripts transition:req, heal_location:req, transition_hook=, on_load=, on_frame=
	map_script MAP_SCRIPT_ON_TRANSITION, \transition
	map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
	.ifnb \on_load
	map_script MAP_SCRIPT_ON_LOAD, \on_load
	.endif
	.ifnb \on_frame
	map_script MAP_SCRIPT_ON_FRAME_TABLE, \on_frame
	.endif
	.byte 0
	.global \transition
\transition\():
	setrespawn \heal_location
	.ifnb \transition_hook
	call \transition_hook
	.endif
	end
.endm
"""


def _contract(maps, pairs, baseline_contract, macro_source=""):
    names = sorted({*pairs, *pairs.values()})
    contract_maps = {}
    for name in names:
        data = maps[name]
        script_path = _script_path(name)
        source = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
        normalized = (
            _normalize_local_script(
                name, source, macro_source, data.get("shared_scripts_map")
            )
            if source.strip()
            else ""
        )
        if not normalized.strip():
            normalized = ""
        baseline_nurse_graphics_id = baseline_contract["maps"][name][
            "baselineNurseGraphicsId"
        ]
        contract_maps[name] = {
            "layout": data["layout"],
            "music": data["music"],
            "baselineNurseGraphicsId": baseline_nurse_graphics_id,
            "warps": data.get("warp_events", []),
            "nonNurseObjects": [
                obj
                for obj in data.get("object_events", [])
                if not _is_nurse_object(obj)
            ],
            "localSemanticSha256": hashlib.sha256(
                normalized.encode("utf-8")
            ).hexdigest(),
            "fullMapSemanticSha256": _full_map_semantic_digest(
                data, baseline_nurse_graphics_id
            ),
        }
    return {
        "expectedPairs": EXPECTED_PAIRS,
        "includesEverGrandePokemonLeague": ("EverGrandeCity_PokemonLeague_1F" in pairs),
        "maps": contract_maps,
    }


class PokeCenterScriptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.maps, cls.map_paths = _reviewed_maps()
        cls.pairs = _discover_pairs(cls.maps)
        cls.one_floor_macro_source = _repository_macro_source(
            "pokemon_center_1f_scripts"
        )
        cls.expected_contract = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.actual_contract = _contract(
            cls.maps,
            cls.pairs,
            cls.expected_contract,
            cls.one_floor_macro_source,
        )
        cls.heal_locations = {
            entry["id"]: entry
            for entry in json.loads(HEAL_LOCATIONS.read_text(encoding="utf-8"))[
                "heal_locations"
            ]
        }

    def test_every_center_has_nurse_respawn_and_floor_contract(self):
        self.assertEqual(self.pairs, EXPECTED_FLOOR_PAIRS)

        for first_floor, second_floor in self.pairs.items():
            first = self.maps[first_floor]
            second = self.maps[second_floor]
            first_source = _script_path(first_floor).read_text(encoding="utf-8")
            second_path = _script_path(second_floor)
            second_source = (
                second_path.read_text(encoding="utf-8")
                if second_path.exists()
                else None
            )
            nurses = [
                obj for obj in first.get("object_events", []) if _is_nurse_object(obj)
            ]
            self.assertEqual(len(nurses), 1, first_floor)
            nurse = nurses[0]
            self.assertIn("local_id", nurse, first_floor)
            self.assertTrue(
                _has_nurse_target(first_source, nurse["script"], nurse["local_id"]),
                f"{first_floor}: inactive/unverified nurse script {nurse['script']}",
            )
            self.assertTrue(
                _has_1f_shell(first_source, self.one_floor_macro_source), first_floor
            )

            respawns = _respawn_ids(first_source)
            self.assertEqual(len(respawns), 1, first_floor)
            heal = self.heal_locations[respawns[0]]
            self.assertEqual(heal["respawn_map"], first["id"], first_floor)
            self.assertEqual(heal["respawn_npc"], nurse["local_id"], first_floor)
            self.assertIn(
                heal["map"],
                {warp["dest_map"] for warp in first["warp_events"]},
                first_floor,
            )

            first_to_second = [
                warp
                for warp in first["warp_events"]
                if warp["dest_map"] == second["id"]
            ]
            second_to_first = [
                warp
                for warp in second["warp_events"]
                if warp["dest_map"] == first["id"]
            ]
            self.assertEqual(len(first_to_second), 1, first_floor)
            self.assertEqual(len(second_to_first), 1, second_floor)
            self.assertEqual(
                int(second_to_first[0]["dest_warp_id"]),
                first["warp_events"].index(first_to_second[0]),
                second_floor,
            )

            # One Island has its own FRLG layout id, so the reviewed map family
            # name is the reliable cable-engine discriminator.
            frlg = second_floor.endswith("_Frlg")
            union_map = "MAP_UNION_ROOM_FRLG" if frlg else "MAP_UNION_ROOM"
            trade_map = "MAP_TRADE_CENTER_FRLG" if frlg else "MAP_TRADE_CENTER"
            self.assertEqual(
                [warp["dest_map"] for warp in second["warp_events"]].count(union_map),
                1,
                second_floor,
            )
            self.assertEqual(
                [warp["dest_map"] for warp in second["warp_events"]].count(trade_map),
                1,
                second_floor,
            )
            hooks = FRLG_CABLE_HOOKS if frlg else EMERALD_CABLE_HOOKS
            scripts_owner = second.get("shared_scripts_map")
            global_source = (
                GLOBAL_POKEMON_CENTER_SCRIPTS.read_text(encoding="utf-8")
                if scripts_owner and GLOBAL_POKEMON_CENTER_SCRIPTS.exists()
                else None
            )
            _, cable_source, cable_label = _resolve_2f_sources(
                second_floor,
                scripts_owner,
                second_source,
                global_source,
                self.expected_contract["maps"][second_floor]["localSemanticSha256"],
            )
            cable_table = _cable_table(cable_source, cable_label)
            self.assertEqual(
                cable_table,
                list(
                    zip(
                        (
                            "MAP_SCRIPT_ON_FRAME_TABLE",
                            "MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE",
                            "MAP_SCRIPT_ON_LOAD",
                            "MAP_SCRIPT_ON_TRANSITION",
                        ),
                        hooks,
                    )
                ),
                second_floor,
            )

    def test_shared_2f_owners_and_global_tables_are_exact(self):
        expected_owners = EXPECTED_SHARED_2F_OWNERS
        self.assertEqual(
            sum(owner == "PokemonCenter_2F" for owner in expected_owners.values()),
            17,
        )
        self.assertEqual(
            sum(owner == "PokemonCenter_2F_Frlg" for owner in expected_owners.values()),
            19,
        )
        actual_owners = {
            second_floor: self.maps[second_floor].get("shared_scripts_map")
            for second_floor in EXPECTED_FLOOR_PAIRS.values()
        }
        self.assertTrue(_valid_shared_2f_owners(actual_owners))

        global_source = GLOBAL_POKEMON_CENTER_SCRIPTS.read_text(encoding="utf-8")
        self.assertTrue(_valid_shared_2f_tables(global_source))

        generic_map = next(
            name
            for name, owner in expected_owners.items()
            if owner == "PokemonCenter_2F"
        )
        frlg_map = next(
            name
            for name, owner in expected_owners.items()
            if owner == "PokemonCenter_2F_Frlg"
        )
        swapped_owners = dict(actual_owners)
        swapped_owners[generic_map], swapped_owners[frlg_map] = (
            swapped_owners[frlg_map],
            swapped_owners[generic_map],
        )
        self.assertFalse(_valid_shared_2f_owners(swapped_owners))

        swapped_bodies = (
            global_source.replace("CableClub_OnFrame_Frlg", "__FRLG_FRAME__")
            .replace("CableClub_OnFrame", "CableClub_OnFrame_Frlg")
            .replace("__FRLG_FRAME__", "CableClub_OnFrame")
        )
        self.assertFalse(_valid_shared_2f_tables(swapped_bodies))
        self.assertFalse(_valid_shared_2f_tables(global_source + "\n.byte 0\n"))

        reformatted = "@ retained heading\n" + global_source.replace(
            "\t", "    "
        ).replace(", ", " ,   ")
        self.assertTrue(_valid_shared_2f_tables(reformatted))

    def test_every_owned_nurse_uses_the_shared_interaction_contract(self):
        owned_maps = set(EXPECTED_FLOOR_PAIRS) | FACILITY_NURSE_MAPS
        self.assertEqual(len(IMPORTED_FRLG_NURSE_MAPS), 20)

        for map_name in sorted(owned_maps):
            nurses = [
                obj
                for obj in self.maps[map_name].get("object_events", [])
                if _is_nurse_object(obj)
            ]
            self.assertEqual(len(nurses), 1, map_name)
            self.assertEqual(
                nurses[0]["script"],
                "Common_EventScript_PkmnCenterNurse_Interact",
                map_name,
            )
            if map_name in IMPORTED_FRLG_NURSE_MAPS:
                self.assertEqual(
                    nurses[0]["graphics_id"], APPROVED_NURSE_GRAPHICS_ID, map_name
                )

            script_path = _script_path(map_name)
            source = (
                script_path.read_text(encoding="utf-8") if script_path.exists() else ""
            )
            self.assertNotRegex(
                _active_source(source),
                r"(?m)^[A-Za-z0-9_]+_EventScript_Nurse::?\s*$",
                map_name,
            )

        cherrygrove = self.maps["CherrygroveCity_PokemonCenter"]
        cherrygrove_nurses = [
            obj for obj in cherrygrove.get("object_events", []) if _is_nurse_object(obj)
        ]
        self.assertEqual(len(cherrygrove_nurses), 1)
        self.assertEqual(
            cherrygrove_nurses[0]["script"],
            "Common_EventScript_PkmnCenterNurse_Interact",
        )
        self.assertNotEqual(
            cherrygrove_nurses[0]["script"],
            "OldaleTown_PokemonCenter_1F_EventScript_Nurse",
        )

    def test_no_legacy_frlg_nurse_adapter_include_or_symbols_remain(self):
        legacy_adapter = ROOT / "data" / "scripts" / "pkmn_center_nurse_frlg.inc"
        self.assertFalse(legacy_adapter.exists())

        production_paths = [
            EVENT_SCRIPTS_HEADER,
            FIELD_SCREEN_EFFECT,
            *sorted((ROOT / "data").rglob("*.inc")),
            *sorted((ROOT / "data").rglob("*.s")),
        ]
        production_source = "\n".join(
            path.read_text(encoding="utf-8") for path in production_paths
        )
        self.assertNotIn("pkmn_center_nurse_frlg.inc", production_source)
        for symbol in (
            "EventScript_AfterWhiteOutHeal_Frlg",
            "EventScript_PkmnCenterNurse_Frlg",
            "EventScript_PkmnCenterNurse_HealPkmn_Frlg",
            "EventScript_PkmnCenterNurse_TakeAndHealPkmn_Frlg",
            "EventScript_PkmnCenterNurse_CheckTrainerTowerAndUnionRoom_Frlg",
            "EventScript_PkmnCenterNurse_ReturnPkmn_Frlg",
            "EventScript_PkmnCenterNurse_PlayerWaitingInUnionRoom_Frlg",
            "EventScript_PkmnCenterNurse_Goodbye_Frlg",
            "Text_WelcomeWantToHealPkmn_Frlg",
            "Text_TakeYourPkmnForFewSeconds_Frlg",
            "Text_WeHopeToSeeYouAgain_Frlg",
            "Text_RestoredPkmnToFullHealth_Frlg",
        ):
            self.assertNotIn(symbol, production_source, symbol)

    def test_legacy_frlg_nurse_graphics_slot_uses_surviving_asset(self):
        self.assertFalse(NURSE_FRLG_ASSET.exists())

        graphics_sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in OBJECT_EVENT_GRAPHICS.glob("*.h")
        }
        combined_source = "\n".join(graphics_sources.values())
        for symbol in (
            "gObjectEventPic_NurseFrlg",
            "sPicTable_NurseFrlg",
            "gObjectEventGraphicsInfo_NurseFrlg",
        ):
            self.assertNotIn(symbol, combined_source, symbol)

        pointer_source = graphics_sources["object_event_graphics_info_pointers.h"]
        self.assertRegex(
            pointer_source,
            r"(?m)^STATIC_ASSERT\(OBJ_EVENT_GFX_NURSE_FRLG == 333, "
            r"NurseFrlgGraphicsIdAbi\);$",
        )
        self.assertRegex(
            pointer_source,
            r"(?m)^\s*\[OBJ_EVENT_GFX_NURSE_FRLG\]\s*=\s*"
            r"&gObjectEventGraphicsInfo_Nurse,\s*$",
        )

    def test_shared_nurse_checks_both_facilities_before_union_room(self):
        source = NURSE_SCRIPT.read_text(encoding="utf-8")
        for predicate in (
            "PlayerNotAtTrainerHillEntrance",
            "IsPlayerNotInTrainerTowerLobby",
        ):
            self.assertTrue(_has_facility_exclusion(source, predicate), predicate)

    def test_one_nurse_state_machine_preserves_all_shared_behavior(self):
        nurse_source = NURSE_SCRIPT.read_text(encoding="utf-8")
        active_nurse = _active_source(nurse_source)

        self.assertEqual(
            _section_lines(active_nurse, "Common_EventScript_PkmnCenterNurse_Interact"),
            (
                "copyvar VAR_0x800B, VAR_LAST_TALKED",
                "call Common_EventScript_PkmnCenterNurse",
                "waitmessage",
                "waitbuttonpress",
                "release",
                "end",
            ),
        )
        for state_machine_directive in (
            "incrementgamestat GAME_STAT_USED_POKECENTER",
            "special HealPlayerParty",
            "specialvar VAR_RESULT, BufferUnionRoomPlayerName",
        ):
            self.assertEqual(
                active_nurse.count(state_machine_directive), 1, state_machine_directive
            )
        for preserved_feature in (
            "specialvar VAR_RESULT, CountPlayerTrainerStars",
            "specialvar VAR_RESULT, IsPokerusInParty",
            "goto_if_set FLAG_NURSE_UNION_ROOM_REMINDER",
        ):
            self.assertIn(preserved_feature, active_nurse)

    def test_non_house_whiteout_flow_is_exact_and_region_neutral(self):
        event_source = _active_source(EVENT_SCRIPTS.read_text(encoding="utf-8"))
        self.assertEqual(
            _section_lines(event_source, "EventScript_AfterWhiteOutHeal"),
            (
                "lockall",
                "msgbox gText_FirstShouldRestoreMonsHealth",
                "call EventScript_PkmnCenterNurse_TakeAndHealPkmn",
                "msgbox gText_MonsHealed",
                "applymovement VAR_LAST_TALKED, Movement_PkmnCenterNurse_Bow",
                "waitmovement 0",
                "fadedefaultbgm",
                "releaseall",
                "end",
            ),
        )
        self.assertEqual(
            _section_lines(event_source, "EventScript_AfterWhiteOutMomHeal"),
            (
                "lockall",
                "textcolor NPC_TEXT_COLOR_FEMALE",
                "applymovement LOCALID_PLAYERS_HOUSE_1F_MOM, Common_Movement_WalkInPlaceFasterDown",
                "waitmovement 0",
                "msgbox gText_HadQuiteAnExperienceTakeRest",
                "call Common_EventScript_OutOfCenterPartyHeal",
                "msgbox gText_MomExplainHPGetPotions",
                "fadedefaultbgm",
                "releaseall",
                "end",
            ),
        )
        self.assertIsNone(
            _label_section_span(
                event_source, "EventScript_AfterWhiteOutHealMsgPreFirstBoss"
            )
        )

        header = EVENT_SCRIPTS_HEADER.read_text(encoding="utf-8")
        field_source = FIELD_SCREEN_EFFECT.read_text(encoding="utf-8")
        self.assertNotIn("EventScript_AfterWhiteOutHeal_Frlg", header)
        self.assertNotIn("EventScript_AfterWhiteOutHeal_Frlg", field_source)
        self.assertNotIn("else if (IS_FRLG)", field_source)
        self.assertRegex(
            field_source,
            r"if \(gTasks\[taskId\]\.tIsPlayerHouse\)\s*\{[\s\S]*?"
            r"ScriptContext_SetupScript\(EventScript_AfterWhiteOutMomHeal\);\s*\}"
            r"\s*else\s*\{\s*"
            r"ScriptContext_SetupScript\(EventScript_AfterWhiteOutHeal\);\s*\}",
        )

    def test_special_center_callbacks_are_preserved(self):
        for map_name, tokens in SPECIAL_CENTER_TOKENS.items():
            source = _script_path(map_name).read_text(encoding="utf-8")
            for token in tokens:
                self.assertTrue(
                    _has_preserved_special_token(
                        map_name, source, token, self.one_floor_macro_source
                    ),
                    f"{map_name}: {token}",
                )

    def test_no_generated_artifact_is_a_reviewed_input(self):
        reviewed_inputs = [MAP_GROUPS, HEAL_LOCATIONS, FIXTURE]
        for name in {*self.pairs, *self.pairs.values()}:
            reviewed_inputs.extend((self.map_paths[name], _script_path(name)))
        for path in reviewed_inputs:
            self.assertNotIn("build/generated", path.as_posix(), str(path))

    def test_fixture_shape_is_complete(self):
        self.assertEqual(self.expected_contract["expectedPairs"], EXPECTED_PAIRS)
        self.assertTrue(self.expected_contract["includesEverGrandePokemonLeague"])
        self.assertEqual(len(self.expected_contract["maps"]), EXPECTED_PAIRS * 2)
        self.assertEqual(
            set(self.expected_contract["maps"]), set(self.actual_contract["maps"])
        )
        for name, entry in self.expected_contract["maps"].items():
            baseline_graphics_id = entry["baselineNurseGraphicsId"]
            if "_1F" in name:
                self.assertRegex(baseline_graphics_id, r"^OBJ_EVENT_GFX_NURSE", name)
            else:
                self.assertIsNone(baseline_graphics_id, name)
            self.assertRegex(entry["localSemanticSha256"], r"^[0-9a-f]{64}$", name)
            self.assertRegex(entry["fullMapSemanticSha256"], r"^[0-9a-f]{64}$", name)

    def test_layout_and_music_match_reviewed_contract(self):
        for name, expected in self.expected_contract["maps"].items():
            actual = self.actual_contract["maps"][name]
            self.assertEqual(actual["layout"], expected["layout"], name)
            self.assertEqual(actual["music"], expected["music"], name)

    def test_all_warps_match_reviewed_contract(self):
        for name, expected in self.expected_contract["maps"].items():
            self.assertEqual(
                self.actual_contract["maps"][name]["warps"], expected["warps"], name
            )

    def test_non_nurse_objects_match_reviewed_contract(self):
        for name, expected in self.expected_contract["maps"].items():
            self.assertEqual(
                self.actual_contract["maps"][name]["nonNurseObjects"],
                expected["nonNurseObjects"],
                name,
            )

    def test_local_script_content_matches_reviewed_contract(self):
        for name, expected in self.expected_contract["maps"].items():
            self.assertEqual(
                self.actual_contract["maps"][name]["localSemanticSha256"],
                expected["localSemanticSha256"],
                name,
            )

    def test_full_map_content_matches_reviewed_contract(self):
        for name, expected in self.expected_contract["maps"].items():
            self.assertEqual(
                self.actual_contract["maps"][name]["fullMapSemanticSha256"],
                expected["fullMapSemanticSha256"],
                name,
            )

    def test_full_map_digest_rejects_unapproved_event_and_nurse_changes(self):
        battle_frontier = self.maps["BattleFrontier_PokemonCenter_1F"]
        baseline_graphics_id = self.expected_contract["maps"][
            "BattleFrontier_PokemonCenter_1F"
        ]["baselineNurseGraphicsId"]
        baseline = _full_map_semantic_digest(battle_frontier, baseline_graphics_id)

        added_coord_event = json.loads(json.dumps(battle_frontier))
        added_coord_event["coord_events"].append(
            {
                "type": "trigger",
                "x": 0,
                "y": 0,
                "elevation": 0,
                "var": "VAR_TEMP_0",
                "var_value": "0",
                "script": "EventScript_Test",
            }
        )
        self.assertNotEqual(
            _full_map_semantic_digest(added_coord_event, baseline_graphics_id), baseline
        )

        moved_nurse = json.loads(json.dumps(battle_frontier))
        nurse = next(filter(_is_nurse_object, moved_nurse["object_events"]))
        nurse["x"] += 1
        self.assertNotEqual(
            _full_map_semantic_digest(moved_nurse, baseline_graphics_id), baseline
        )

    def test_full_map_digest_accepts_only_approved_map_migrations(self):
        frlg_map_name = "CeladonCity_PokemonCenter_1F_Frlg"
        first_floor = json.loads(json.dumps(self.maps[frlg_map_name]))
        baseline_graphics_id = self.expected_contract["maps"][frlg_map_name][
            "baselineNurseGraphicsId"
        ]
        baseline = _full_map_semantic_digest(first_floor, baseline_graphics_id)
        nurse = next(filter(_is_nurse_object, first_floor["object_events"]))
        nurse["script"] = "Common_EventScript_PkmnCenterNurse_Interact"
        nurse["graphics_id"] = APPROVED_NURSE_GRAPHICS_ID
        self.assertEqual(
            _full_map_semantic_digest(first_floor, baseline_graphics_id), baseline
        )

        battle_frontier_name = "BattleFrontier_PokemonCenter_1F"
        battle_frontier = json.loads(json.dumps(self.maps[battle_frontier_name]))
        baseline_graphics_id = self.expected_contract["maps"][battle_frontier_name][
            "baselineNurseGraphicsId"
        ]
        nurse = next(filter(_is_nurse_object, battle_frontier["object_events"]))
        nurse["graphics_id"] = "OBJ_EVENT_GFX_NURSE_FRLG"
        with self.assertRaisesRegex(AssertionError, "unapproved nurse graphics_id"):
            _full_map_semantic_digest(battle_frontier, baseline_graphics_id)

        nurse["graphics_id"] = "OBJ_EVENT_GFX_NURSE_JOY"
        with self.assertRaisesRegex(AssertionError, "unapproved nurse graphics_id"):
            _full_map_semantic_digest(battle_frontier, baseline_graphics_id)

        second_floor = json.loads(
            json.dumps(self.maps["BattleFrontier_PokemonCenter_2F"])
        )
        baseline = _full_map_semantic_digest(second_floor, None)
        second_floor["shared_scripts_map"] = "PokemonCenter_2F"
        self.assertEqual(_full_map_semantic_digest(second_floor, None), baseline)

    def test_active_code_parser_rejects_commented_contract_lines(self):
        wrapper = """Nurse::
\tsetvar VAR_0x800B, LOCALID_TEST_NURSE
\tcall Common_EventScript_PkmnCenterNurse
\twaitmessage
\twaitbuttonpress
\trelease
\tend
"""
        self.assertTrue(_has_nurse_target(wrapper, "Nurse", "LOCALID_TEST_NURSE"))
        self.assertFalse(
            _has_nurse_target(
                wrapper.replace("\tcall", "@\tcall"),
                "Nurse",
                "LOCALID_TEST_NURSE",
            )
        )
        shell = """Map_MapScripts::
\tmap_script MAP_SCRIPT_ON_TRANSITION, Map_OnTransition
\tmap_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
\t.byte 0
Map_OnTransition::
\tsetrespawn HEAL_LOCATION_TEST
\tend
"""
        self.assertTrue(_has_1f_shell(shell))
        self.assertFalse(
            _has_1f_shell(
                shell.replace(
                    "\tmap_script MAP_SCRIPT_ON_RESUME",
                    "@\tmap_script MAP_SCRIPT_ON_RESUME",
                )
            )
        )
        one_island_row = (
            "\tmap_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad\n"
        )
        self.assertTrue(
            _has_active_token(
                one_island_row,
                "map_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad",
            )
        )
        self.assertFalse(
            _has_active_token(
                "@" + one_island_row,
                "map_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad",
            )
        )

    def test_approved_target_forms_are_accepted(self):
        self.assertTrue(
            _has_nurse_target("", "Common_EventScript_PkmnCenterNurse_Interact")
        )
        macro = """.macro pokemon_center_1f_scripts transition:req, heal_location:req, transition_hook=, on_load=, on_frame=
\tmap_script MAP_SCRIPT_ON_TRANSITION, \\transition
\tmap_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
\t.ifnb \\on_load
\tmap_script MAP_SCRIPT_ON_LOAD, \\on_load
\t.endif
\t.ifnb \\on_frame
\tmap_script MAP_SCRIPT_ON_FRAME_TABLE, \\on_frame
\t.endif
\t.byte 0
\t.global \\transition
\\transition\\():
\tsetrespawn \\heal_location
\t.ifnb \\transition_hook
\tcall \\transition_hook
\t.endif
\tend
.endm
"""
        oldale = """OldaleTown_PokemonCenter_1F_MapScripts::
\tpokemon_center_1f_scripts OldaleTown_PokemonCenter_1F_OnTransition, HEAL_LOCATION_OLDALE_TOWN, Common_EventScript_UpdateBrineyLocation
"""
        self.assertTrue(_has_1f_shell(oldale, macro))
        generated_owner_only = (
            "pokemon_center_1f_scripts OldaleTown_PokemonCenter_1F_OnTransition, "
            "HEAL_LOCATION_OLDALE_TOWN, Common_EventScript_UpdateBrineyLocation\n"
        )
        self.assertFalse(_has_1f_shell(generated_owner_only, macro))
        with self.assertRaisesRegex(AssertionError, "pokemon_center_1f_scripts"):
            _normalize_local_script(
                "OldaleTown_PokemonCenter_1F", generated_owner_only, macro
            )

        shared_global = """PokemonCenter_2F_MapScripts::
\tmap_script MAP_SCRIPT_ON_FRAME_TABLE, CableClub_OnFrame
\tmap_script MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE, CableClub_OnWarp
\tmap_script MAP_SCRIPT_ON_LOAD, CableClub_OnLoad
\tmap_script MAP_SCRIPT_ON_TRANSITION, CableClub_OnTransition
\t.byte 0
"""
        local, cable_source, cable_label = _resolve_2f_sources(
            "OldaleTown_PokemonCenter_2F",
            "PokemonCenter_2F",
            None,
            shared_global,
            EMPTY_SEMANTIC_SHA256,
        )
        self.assertEqual(local, "")
        self.assertEqual(
            _cable_table(cable_source, cable_label),
            list(
                zip(
                    (
                        "MAP_SCRIPT_ON_FRAME_TABLE",
                        "MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE",
                        "MAP_SCRIPT_ON_LOAD",
                        "MAP_SCRIPT_ON_TRANSITION",
                    ),
                    EMERALD_CABLE_HOOKS,
                )
            ),
        )
        with self.assertRaisesRegex(AssertionError, "required local scripts.inc"):
            _resolve_2f_sources(
                "Ordinary_PokemonCenter_2F",
                None,
                None,
                shared_global,
                EMPTY_SEMANTIC_SHA256,
            )
        with self.assertRaisesRegex(AssertionError, "required local scripts.inc"):
            _resolve_2f_sources(
                "MauvilleCity_PokemonCenter_2F",
                "PokemonCenter_2F",
                None,
                shared_global,
                "1" * 64,
            )
        hooks = list(
            zip(
                (
                    "MAP_SCRIPT_ON_FRAME_TABLE",
                    "MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE",
                    "MAP_SCRIPT_ON_LOAD",
                    "MAP_SCRIPT_ON_TRANSITION",
                ),
                EMERALD_CABLE_HOOKS,
            )
        )
        shared = "\n".join(f"map_script {kind}, {hook}" for kind, hook in hooks)
        self.assertEqual(_cable_table(shared), hooks)
        self.assertEqual(_cable_table(f"{shared}\nsetflag FLAG_TEST\n"), [])

    def test_emerald_nurse_wrapper_requires_maps_exact_local_id(self):
        map_name = "MauvilleCity_PokemonCenter_1F"
        script = "MauvilleCity_PokemonCenter_1F_EventScript_Nurse"
        nurse_local_id = _authoritative_nurse_local_id(map_name)
        source = f"""{script}::
\tsetvar VAR_0x800B, {nurse_local_id}
\tcall Common_EventScript_PkmnCenterNurse
\twaitmessage
\twaitbuttonpress
\trelease
\tend
"""

        self.assertEqual(nurse_local_id, "LOCALID_MAUVILLE_NURSE")
        self.assertTrue(_has_nurse_target(source, script, nurse_local_id))

        for other_local_id in (
            "LOCALID_DEWFORD_BRINEY",
            "LOCALID_MAUVILLE_SCOTT",
            "LOCALID_TEST_NURSE",
        ):
            mutated = source.replace(nurse_local_id, other_local_id)
            self.assertFalse(_has_nurse_target(mutated, script, nurse_local_id))

        self.assertTrue(
            _has_nurse_target("", "Common_EventScript_PkmnCenterNurse_Interact")
        )

    def test_oldale_direct_macro_hook_matches_baseline_digest(self):
        baseline = """OldaleTown_PokemonCenter_1F_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, OldaleTown_PokemonCenter_1F_OnTransition
	map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
	.byte 0
OldaleTown_PokemonCenter_1F_OnTransition::
	setrespawn HEAL_LOCATION_OLDALE_TOWN
	call Common_EventScript_UpdateBrineyLocation
	end
OldaleTown_PokemonCenter_1F_EventScript_Gentleman::
	msgbox OldaleTown_PokemonCenter_1F_Text_Test, MSGBOX_NPC
	end
OldaleTown_PokemonCenter_1F_Text_Test:
	.string "Test$"
"""
        migrated = """OldaleTown_PokemonCenter_1F_MapScripts::
	pokemon_center_1f_scripts OldaleTown_PokemonCenter_1F_OnTransition, HEAL_LOCATION_OLDALE_TOWN, Common_EventScript_UpdateBrineyLocation
OldaleTown_PokemonCenter_1F_EventScript_Gentleman::
	msgbox OldaleTown_PokemonCenter_1F_Text_Test, MSGBOX_NPC
	end
OldaleTown_PokemonCenter_1F_Text_Test:
	.string "Test$"
"""
        callback = "call Common_EventScript_UpdateBrineyLocation"
        macro_source = _test_1f_macro_source()
        self.assertTrue(
            _has_preserved_special_token(
                "OldaleTown_PokemonCenter_1F", migrated, callback, macro_source
            )
        )
        self.assertFalse(
            _has_preserved_special_token(
                "OldaleTown_PokemonCenter_1F",
                migrated.replace(
                    "Common_EventScript_UpdateBrineyLocation", "EventScript_Test"
                ),
                callback,
                macro_source,
            )
        )
        self.assertEqual(
            _normalize_local_script("OldaleTown_PokemonCenter_1F", baseline),
            _normalize_local_script(
                "OldaleTown_PokemonCenter_1F",
                migrated,
                macro_source,
            ),
        )

    def test_lilycove_named_transition_hook_matches_baseline_digest(self):
        callbacks = SPECIAL_1F_TRANSITION_ROWS["LilycoveCity_PokemonCenter_1F"]
        baseline = f"""LilycoveCity_PokemonCenter_1F_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, LilycoveCity_PokemonCenter_1F_OnTransition
	map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
	.byte 0
LilycoveCity_PokemonCenter_1F_OnTransition::
	setrespawn HEAL_LOCATION_LILYCOVE_CITY
	{callbacks[0]}
	end
LilycoveCity_PokemonCenter_1F_EventScript_SetLilycoveLadyGfx::
	special SetLilycoveLadyGfx
	end
"""
        migrated = f"""LilycoveCity_PokemonCenter_1F_MapScripts::
	pokemon_center_1f_scripts LilycoveCity_PokemonCenter_1F_OnTransition, HEAL_LOCATION_LILYCOVE_CITY, LilycoveCity_PokemonCenter_1F_TransitionHook
LilycoveCity_PokemonCenter_1F_TransitionHook::
	{callbacks[0]}
	return
LilycoveCity_PokemonCenter_1F_EventScript_SetLilycoveLadyGfx::
	special SetLilycoveLadyGfx
	end
"""
        self.assertEqual(
            _normalize_local_script("LilycoveCity_PokemonCenter_1F", baseline),
            _normalize_local_script(
                "LilycoveCity_PokemonCenter_1F",
                migrated,
                _test_1f_macro_source(),
            ),
        )
        with self.assertRaisesRegex(AssertionError, "pokemon_center_1f_scripts"):
            _normalize_local_script(
                "LilycoveCity_PokemonCenter_1F",
                migrated.replace(
                    f"\t{callbacks[0]}", f"\tsetflag FLAG_TEST\n\t{callbacks[0]}"
                ),
                _test_1f_macro_source(),
            )

    def test_one_island_five_argument_macro_matches_baseline_digest(self):
        callbacks = SPECIAL_1F_TRANSITION_ROWS["OneIsland_PokemonCenter_1F_Frlg"]
        callback_source = "\n".join(f"\t{line}" for line in callbacks)
        common_tail = """OneIsland_PokemonCenter_1F_OnLoad::
	call_if_set FLAG_IS_CHAMPION, EventScript_Test
	end
OneIsland_PokemonCenter_1F_OnFrame::
	map_script_2 VAR_TEST, 0, EventScript_Test
	.2byte 0
"""
        baseline = f"""OneIsland_PokemonCenter_1F_Frlg_MapScripts::
	map_script MAP_SCRIPT_ON_TRANSITION, OneIsland_PokemonCenter_1F_OnTransition
	map_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
	map_script MAP_SCRIPT_ON_LOAD, OneIsland_PokemonCenter_1F_OnLoad
	map_script MAP_SCRIPT_ON_FRAME_TABLE, OneIsland_PokemonCenter_1F_OnFrame
	.byte 0
OneIsland_PokemonCenter_1F_OnTransition::
	setrespawn HEAL_LOCATION_ONE_ISLAND
{callback_source}
	end
{common_tail}"""
        migrated = f"""OneIsland_PokemonCenter_1F_Frlg_MapScripts::
	pokemon_center_1f_scripts OneIsland_PokemonCenter_1F_OnTransition, HEAL_LOCATION_ONE_ISLAND, OneIsland_PokemonCenter_1F_TransitionHook, OneIsland_PokemonCenter_1F_OnLoad, OneIsland_PokemonCenter_1F_OnFrame
OneIsland_PokemonCenter_1F_TransitionHook::
{callback_source}
	return
{common_tail}"""
        self.assertTrue(_has_1f_shell(migrated, _test_1f_macro_source()))
        self.assertEqual(
            _normalize_local_script("OneIsland_PokemonCenter_1F_Frlg", baseline),
            _normalize_local_script(
                "OneIsland_PokemonCenter_1F_Frlg",
                migrated,
                _test_1f_macro_source(),
            ),
        )
        missing_hook_return = migrated.replace("\treturn\n", "", 1)
        self.assertFalse(_has_1f_shell(missing_hook_return, _test_1f_macro_source()))
        with self.assertRaisesRegex(AssertionError, "pokemon_center_1f_scripts"):
            _normalize_local_script(
                "OneIsland_PokemonCenter_1F_Frlg",
                missing_hook_return,
                _test_1f_macro_source(),
            )
        missing_on_frame = migrated.replace(
            "OneIsland_PokemonCenter_1F_OnFrame::",
            "Missing_OneIsland_OnFrame::",
        )
        self.assertFalse(_has_1f_shell(missing_on_frame, _test_1f_macro_source()))

    def test_shared_2f_retained_local_tail_matches_baseline_digest(self):
        table_and_wrappers = """MauvilleCity_PokemonCenter_2F_MapScripts::
	map_script MAP_SCRIPT_ON_FRAME_TABLE, CableClub_OnFrame
	map_script MAP_SCRIPT_ON_WARP_INTO_MAP_TABLE, CableClub_OnWarp
	map_script MAP_SCRIPT_ON_LOAD, CableClub_OnLoad
	map_script MAP_SCRIPT_ON_TRANSITION, CableClub_OnTransition
	.byte 0
MauvilleCity_PokemonCenter_2F_EventScript_Colosseum::
	call CableClub_EventScript_Colosseum
	end
MauvilleCity_PokemonCenter_2F_EventScript_TradeCenter::
	call CableClub_EventScript_TradeCenter
	end
MauvilleCity_PokemonCenter_2F_EventScript_RecordCorner::
	call CableClub_EventScript_RecordCorner
	end
"""
        tail = """MauvilleCity_PokemonCenter_2F_EventScript_Youngster::
	msgbox MauvilleCity_PokemonCenter_2F_Text_Youngster, MSGBOX_NPC
	end
MauvilleCity_PokemonCenter_2F_Text_Youngster:
	.string "Retained dialogue$"
"""
        baseline = _normalize_local_script(
            "MauvilleCity_PokemonCenter_2F", table_and_wrappers + tail
        )
        migrated = _normalize_local_script(
            "MauvilleCity_PokemonCenter_2F",
            tail,
            shared_owner="PokemonCenter_2F",
        )
        self.assertEqual(migrated, baseline)
        self.assertIn("MauvilleCity_PokemonCenter_2F_EventScript_Youngster::", migrated)
        self.assertIn(
            "msgbox MauvilleCity_PokemonCenter_2F_Text_Youngster,MSGBOX_NPC",
            migrated,
        )
        with self.assertRaisesRegex(AssertionError, "retained shared 2F table"):
            _normalize_local_script(
                "MauvilleCity_PokemonCenter_2F",
                table_and_wrappers + tail,
                shared_owner="PokemonCenter_2F",
            )

    def test_extra_nurse_wrapper_behavior_is_rejected(self):
        wrapper = """Nurse::
\tsetvar VAR_0x800B, LOCALID_TEST_NURSE
\tcall Common_EventScript_PkmnCenterNurse
\twaitmessage
\twaitbuttonpress
\trelease
\tend
"""
        self.assertTrue(_has_nurse_target(wrapper, "Nurse", "LOCALID_TEST_NURSE"))
        self.assertFalse(
            _has_nurse_target(
                wrapper.replace("\twaitmessage", "\tsetflag FLAG_TEST\n\twaitmessage"),
                "Nurse",
                "LOCALID_TEST_NURSE",
            )
        )

    def test_extra_ordinary_map_table_callback_is_rejected(self):
        shell = """Map_MapScripts::
\tmap_script MAP_SCRIPT_ON_TRANSITION, Map_OnTransition
\tmap_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
\t.byte 0
Map_OnTransition::
\tsetrespawn HEAL_LOCATION_TEST
\tend
"""
        self.assertEqual(_normalize_local_script("Map", shell), "")
        mutated = shell.replace(
            "\t.byte 0",
            "\tmap_script MAP_SCRIPT_ON_LOAD, Map_OnLoad\n\t.byte 0",
        )
        with self.assertRaisesRegex(AssertionError, "map-script table"):
            _normalize_local_script("Map", mutated)

    def test_commented_facility_predicate_is_rejected(self):
        source = """EventScript_PkmnCenterNurse_CheckTrainerHillAndUnionRoom::
\tspecialvar VAR_RESULT, PlayerNotAtTrainerHillEntrance
\tgoto_if_eq VAR_RESULT, 0, EventScript_PkmnCenterNurse_ReturnPkmn
\tspecialvar VAR_RESULT, IsPlayerNotInTrainerTowerLobby
\tgoto_if_eq VAR_RESULT, FALSE, EventScript_PkmnCenterNurse_ReturnPkmn
\tspecialvar VAR_RESULT, BufferUnionRoomPlayerName
\tcopyvar VAR_0x8008, VAR_RESULT
\tgoto_if_eq VAR_0x8008, 0, EventScript_PkmnCenterNurse_ReturnPkmn
\tgoto_if_eq VAR_0x8008, 1, EventScript_PkmnCenterNurse_PlayerWaitingInUnionRoom
\tend
"""
        self.assertTrue(
            _has_facility_exclusion(source, "PlayerNotAtTrainerHillEntrance")
        )
        mutated = source.replace(
            "\tspecialvar VAR_RESULT, PlayerNotAtTrainerHillEntrance",
            "\tsetvar VAR_RESULT, 0 @ specialvar VAR_RESULT, PlayerNotAtTrainerHillEntrance",
        )
        self.assertFalse(
            _has_facility_exclusion(mutated, "PlayerNotAtTrainerHillEntrance")
        )

    def test_extra_macro_behavior_is_rejected(self):
        macro = """.macro pokemon_center_1f_scripts transition:req, heal_location:req, transition_hook=, on_load=, on_frame=
\tmap_script MAP_SCRIPT_ON_TRANSITION, \\transition
\tmap_script MAP_SCRIPT_ON_RESUME, CableClub_OnResume
\t.ifnb \\on_load
\tmap_script MAP_SCRIPT_ON_LOAD, \\on_load
\t.endif
\t.ifnb \\on_frame
\tmap_script MAP_SCRIPT_ON_FRAME_TABLE, \\on_frame
\t.endif
\t.byte 0
\t.global \\transition
\\transition\\():
\tsetrespawn \\heal_location
\t.ifnb \\transition_hook
\tcall \\transition_hook
\t.endif
\tend
.endm
"""
        invocation = """TEST_MAP_MapScripts::
\tpokemon_center_1f_scripts TEST_MAP_OnTransition, HEAL_LOCATION_TEST
"""
        self.assertTrue(_has_1f_shell(invocation, macro))
        duplicate_invocation = (
            invocation
            + "\tpokemon_center_1f_scripts ROGUE_OnTransition, HEAL_LOCATION_TEST\n"
        )
        self.assertFalse(_has_1f_shell(duplicate_invocation, macro))
        with self.assertRaisesRegex(AssertionError, "pokemon_center_1f_scripts"):
            _normalize_local_script("TEST_MAP", duplicate_invocation, macro)
        mutated = macro.replace("\tsetrespawn", "\tsetflag FLAG_TEST\n\tsetrespawn")
        self.assertFalse(_has_1f_shell(invocation, mutated))
        with self.assertRaisesRegex(AssertionError, "pokemon_center_1f_scripts"):
            _normalize_local_script("TEST_MAP", invocation, mutated)

    def test_approved_standard_mart_macro_matches_expanded_clerk_digest(self):
        map_name = "EverGrandeCity_PokemonLeague_1F"
        label = "EverGrandeCity_PokemonLeague_1F_EventScript_Clerk"
        products = "EverGrandeCity_PokemonLeague_1F_Pokemart"
        expanded = f"""{label}::
\tlock
\tfaceplayer
\tmessage gText_HowMayIServeYou
\twaitmessage
\tpokemart {products}
\tmsgbox gText_PleaseComeAgain, MSGBOX_DEFAULT
\trelease
\tend

\t.align 2
{products}:
\t.2byte ITEM_ULTRA_BALL
\tpokemartlistend
"""
        migrated = expanded.replace(
            "\tlock\n\tfaceplayer\n\tmessage gText_HowMayIServeYou\n"
            "\twaitmessage\n\t"
            f"pokemart {products}\n"
            "\tmsgbox gText_PleaseComeAgain, MSGBOX_DEFAULT\n\trelease\n\tend",
            f"\tstandard_mart_clerk {products}",
        )

        self.assertEqual(
            _normalize_local_script(map_name, expanded),
            _normalize_local_script(map_name, migrated),
        )
        self.assertNotEqual(
            _normalize_local_script(map_name, expanded),
            _normalize_local_script(
                map_name,
                migrated.replace(
                    f"standard_mart_clerk {products}",
                    f"standard_mart_clerk {products}, custom_mart",
                ),
            ),
        )
        self.assertNotEqual(
            _normalize_local_script(map_name, expanded),
            _normalize_local_script("Unapproved_PokemonCenter_1F", migrated),
        )

    def test_semantic_digest_ignores_dialogue_only_changes(self):
        before = """OldaleTown_PokemonCenter_1F_EventScript_Gentleman::
\tsetflag FLAG_REWARD_RECEIVED
OldaleTown_PokemonCenter_1F_Text_Test:
\t.string "Original dialogue$"
"""
        after = before.replace("Original dialogue", "Completely rewritten dialogue")
        self.assertEqual(
            _normalize_local_script("OldaleTown_PokemonCenter_1F", before),
            _normalize_local_script("OldaleTown_PokemonCenter_1F", after),
        )
        injected = before.replace(
            "\tsetflag FLAG_REWARD_RECEIVED",
            '\tsetflag FLAG_REWARD_RECEIVED\n\t.string "Injected into code$"',
        )
        self.assertNotEqual(
            _normalize_local_script("OldaleTown_PokemonCenter_1F", before),
            _normalize_local_script("OldaleTown_PokemonCenter_1F", injected),
        )

    def test_route_center_fly_flags_are_unique_persistent_flags(self):
        flags = FLAGS.read_text(encoding="utf-8")
        offsets = []
        for name in (
            "FLAG_WORLD_MAP_ROUTE4_POKEMON_CENTER_1F",
            "FLAG_WORLD_MAP_ROUTE10_POKEMON_CENTER_1F",
        ):
            match = re.search(
                rf"^#define {name}\s+\(SYSTEM_FLAGS \+ (0x[0-9A-F]+)\)$",
                flags,
                re.MULTILINE,
            )
            self.assertIsNotNone(match, name)
            offsets.append(int(match.group(1), 16))
            self.assertEqual(flags.count(f"#define {name}"), 1, name)
            self.assertIn(f"FlagGet({name})", REGION_MAP.read_text(encoding="utf-8"))
        self.assertEqual(len(set(offsets)), len(offsets))
        for offset in offsets:
            self.assertNotRegex(
                flags,
                rf"FLAG_UNUSED_0x[0-9A-F]+\s+\(SYSTEM_FLAGS \+ 0x{offset:X}\)",
            )

    def test_hns_pewter_fly_reuses_the_next_unclaimed_persistent_slot(self):
        flags = FLAGS.read_text(encoding="utf-8")
        self.assertRegex(
            flags,
            r"^#define FLAG_WORLD_MAP_PEWTER_CITY\s+FLAG_UNUSED_0x90B$",
        )
        self.assertRegex(
            flags,
            r"^#define FLAG_UNUSED_0x90B\s+\(SYSTEM_FLAGS \+ 0xAB\)",
        )
        self.assertIn(
            "FlagGet(FLAG_WORLD_MAP_PEWTER_CITY)",
            REGION_MAP.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
