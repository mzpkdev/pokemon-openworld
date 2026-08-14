"""Verify the complete field-capability policy remains fail-closed and selector-free."""

from __future__ import annotations

import json
from pathlib import Path
import re

from tools.persistence.contract import ContractError


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SELECTOR = re.compile(
    r"\b(?:IS_(?:FRLG|EMERALD|FIRERED|LEAFGREEN)|"
    r"GAME_VERSION(?:_[A-Z0-9_]+)?|"
    r"VERSION_(?:RUBY|SAPPHIRE|EMERALD|FIRE_RED|LEAF_GREEN)|"
    r"EMERALD|FIRERED|LEAFGREEN|"
    r"gMapHeader|mapType|regionMapSectionId|"
    r"GetCurrentMap|current_?map|map_?selector|"
    r"GetCurrentRegion|current_?region|region_?selector|gGameVersion|game_?version|"
    r"current_?campaign|campaign_?selector)\b",
    re.IGNORECASE,
)

EXACT_STORY_PRODUCERS = (
    (
        "data/maps/RustboroCity_Gym/scripts.inc",
        "RustboroCity_Gym_EventScript_RoxanneDefeated",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        "FLAG_BADGE01_GET",
    ),
    (
        "data/maps/CeruleanCity_Gym_Frlg/scripts.inc",
        "CeruleanCity_Gym_EventScript_MistyDefeated",
        "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
        "FLAG_BADGE02_GET",
    ),
    (
        "data/maps/DewfordTown_Gym/scripts.inc",
        "DewfordTown_Gym_EventScript_BrawlyDefeated",
        "FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE",
        "FLAG_BADGE02_GET",
    ),
    (
        "data/maps/PewterCity_Gym_Frlg/scripts.inc",
        "PewterCity_Gym_EventScript_DefeatedBrock",
        "FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE",
        "FLAG_BADGE01_GET",
    ),
    (
        "data/maps/MauvilleCity_Gym/scripts.inc",
        "MauvilleCity_Gym_EventScript_WattsonDefeated",
        "FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE",
        "FLAG_BADGE03_GET",
    ),
    (
        "data/maps/VermilionCity_Gym_Frlg/scripts.inc",
        "VermilionCity_Gym_EventScript_DefeatedLtSurge",
        "FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE",
        "FLAG_BADGE03_GET",
    ),
    (
        "data/maps/LavaridgeTown_Gym_1F/scripts.inc",
        "LavaridgeTown_Gym_1F_EventScript_FlanneryDefeated",
        "FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE",
        "FLAG_BADGE04_GET",
    ),
    (
        "data/maps/CeladonCity_Gym_Frlg/scripts.inc",
        "CeladonCity_Gym_EventScript_DefeatedErika",
        "FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE",
        "FLAG_BADGE04_GET",
    ),
    (
        "data/maps/PetalburgCity_Gym/scripts.inc",
        "PetalburgCity_Gym_EventScript_NormanBattle",
        "FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE",
        "FLAG_BADGE05_GET",
    ),
    (
        "data/maps/FuchsiaCity_Gym_Frlg/scripts.inc",
        "FuchsiaCity_Gym_EventScript_DefeatedKoga",
        "FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE",
        "FLAG_BADGE05_GET",
    ),
    (
        "data/maps/FortreeCity_Gym/scripts.inc",
        "FortreeCity_Gym_EventScript_WinonaDefeated",
        "FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE",
        "FLAG_BADGE06_GET",
    ),
    (
        "data/maps/SaffronCity_Gym_Frlg/scripts.inc",
        "SaffronCity_Gym_EventScript_DefeatedSabrina",
        "FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE",
        "FLAG_BADGE06_GET",
    ),
    (
        "data/maps/MossdeepCity_Gym/scripts.inc",
        "MossdeepCity_Gym_EventScript_TateAndLizaDefeated",
        "FLAG_REGIONAL_FACT_HOENN_MIND_BADGE",
        "FLAG_BADGE07_GET",
    ),
    (
        "data/maps/SootopolisCity_Gym_1F/scripts.inc",
        "SootopolisCity_Gym_1F_EventScript_JuanDefeated",
        "FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE",
        "FLAG_BADGE08_GET",
    ),
    (
        "data/maps/CinnabarIsland_Gym_Frlg/scripts.inc",
        "CinnabarIsland_Gym_EventScript_DefeatedBlaine",
        "FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE",
        "FLAG_BADGE07_GET",
    ),
)

EXACT_STORY_READERS = (
    (
        "data/maps/RustboroCity_Gym/scripts.inc",
        "RustboroCity_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
    ),
    (
        "data/maps/RustboroCity_Gym/scripts.inc",
        "RustboroCity_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
    ),
    (
        "data/maps/RustboroCity/scripts.inc",
        "RustboroCity_EventScript_Man1",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
    ),
    (
        "data/maps/RustboroCity_PokemonSchool/scripts.inc",
        "RustboroCity_PokemonSchool_EventScript_Scott",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
    ),
    (
        "data/maps/RustboroCity_PokemonSchool/scripts.inc",
        "RustboroCity_PokemonSchool_EventScript_ScottSpokeAlready",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
    ),
    (
        "data/maps/CeruleanCity_Gym_Frlg/scripts.inc",
        "CeruleanCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckCascadeBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckCascadeBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
    ),
    (
        "data/maps/DewfordTown_Gym/scripts.inc",
        "DewfordTown_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE",
    ),
    (
        "data/maps/DewfordTown_Gym/scripts.inc",
        "DewfordTown_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_KNUCKLE_BADGE",
    ),
    (
        "data/maps/PewterCity_Gym_Frlg/scripts.inc",
        "PewterCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckBoulderBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckBoulderBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_BOULDER_BADGE",
    ),
    (
        "data/maps/MauvilleCity_Gym/scripts.inc",
        "MauvilleCity_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE",
    ),
    (
        "data/maps/MauvilleCity_Gym/scripts.inc",
        "MauvilleCity_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_DYNAMO_BADGE",
    ),
    (
        "data/maps/VermilionCity_Gym_Frlg/scripts.inc",
        "VermilionCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckThunderBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckThunderBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_THUNDER_BADGE",
    ),
    (
        "data/maps/LavaridgeTown_Gym_1F/scripts.inc",
        "LavaridgeTown_Gym_1F_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE",
    ),
    (
        "data/maps/LavaridgeTown_Gym_1F/scripts.inc",
        "LavaridgeTown_Gym_1F_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_HEAT_BADGE",
    ),
    (
        "data/maps/CeladonCity_Gym_Frlg/scripts.inc",
        "CeladonCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckRainbowBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckRainbowBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_RAINBOW_BADGE",
    ),
    (
        "data/maps/PetalburgCity_Gym/scripts.inc",
        "PetalburgCity_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE",
    ),
    (
        "data/maps/PetalburgCity_Gym/scripts.inc",
        "PetalburgCity_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE",
    ),
    (
        "data/scripts/players_house.inc",
        "PlayersHouse_1F_EventScript_CheckGiveAmuletCoin",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_BALANCE_BADGE",
    ),
    (
        "data/maps/FuchsiaCity_Gym_Frlg/scripts.inc",
        "FuchsiaCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckSoulBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckSoulBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_SOUL_BADGE",
    ),
    (
        "data/maps/FortreeCity_Gym/scripts.inc",
        "FortreeCity_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE",
    ),
    (
        "data/maps/FortreeCity_Gym/scripts.inc",
        "FortreeCity_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE",
    ),
    (
        "data/maps/SootopolisCity_Gym_1F/scripts.inc",
        "SootopolisCity_Gym_1F_EventScript_Juan",
        "goto_if_unset",
        "FLAG_REGIONAL_FACT_HOENN_FEATHER_BADGE",
    ),
    (
        "data/maps/SaffronCity_Gym_Frlg/scripts.inc",
        "SaffronCity_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckMarshBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckMarshBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_MARSH_BADGE",
    ),
    (
        "data/maps/MossdeepCity_Gym/scripts.inc",
        "MossdeepCity_Gym_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_MIND_BADGE",
    ),
    (
        "data/maps/MossdeepCity_Gym/scripts.inc",
        "MossdeepCity_Gym_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_MIND_BADGE",
    ),
    (
        "data/maps/SootopolisCity_Gym_1F/scripts.inc",
        "SootopolisCity_Gym_1F_EventScript_LeftGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE",
    ),
    (
        "data/maps/SootopolisCity_Gym_1F/scripts.inc",
        "SootopolisCity_Gym_1F_EventScript_RightGymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_HOENN_RAIN_BADGE",
    ),
    (
        "data/maps/CinnabarIsland_Gym_Frlg/scripts.inc",
        "CinnabarIsland_Gym_EventScript_GymStatue",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckVolcanoBadge",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE",
    ),
    (
        "data/scripts/route23.inc",
        "Route23_EventScript_CheckVolcanoBadgeTrigger",
        "goto_if_set",
        "FLAG_REGIONAL_FACT_KANTO_VOLCANO_BADGE",
    ),
)


def _without_comments(source: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.DOTALL)


def _compact(source: str) -> str:
    return re.sub(r"\s+", "", source)


def _braced_body(source: str, brace: int, description: str) -> str:
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise ContractError(f"field capability policy: unterminated {description}")


def _function_body(path: Path, name: str, root: Path) -> str:
    source = _without_comments(path.read_text(encoding="utf-8"))
    matches = list(re.finditer(rf"\b{name}\s*\([^;{{}}]*?\)\s*\{{", source))
    if not matches:
        raise ContractError(
            f"field capability policy: missing {name} in {path.relative_to(root)}"
        )
    if len(matches) != 1:
        raise ContractError(
            f"field capability policy: duplicate {name} in {path.relative_to(root)}"
        )
    return _braced_body(
        source,
        matches[0].end() - 1,
        f"{name} in {path.relative_to(root)}",
    )


def _script_block(path: Path, label: str, root: Path) -> str:
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"(?m)^{re.escape(label)}::\s*$", source)
    if match is None:
        raise ContractError(
            f"regional facts: missing {label} in {path.relative_to(root)}"
        )
    next_label = re.search(r"(?m)^[A-Za-z0-9_]+::\s*$", source[match.end() :])
    end = len(source) if next_label is None else match.end() + next_label.start()
    return source[match.start() : end]


def _field_move_array_body(path: Path, root: Path) -> str:
    source = _without_comments(path.read_text(encoding="utf-8"))
    matches = list(
        re.finditer(
            r"\bconst\s+struct\s+FieldMoveInfo\s+gFieldMoveInfo\s*"
            r"\[\s*FIELD_MOVES_COUNT\s*\]\s*=\s*\{",
            source,
        )
    )
    if len(matches) != 1:
        raise ContractError(
            "field capability policy: expected one live gFieldMoveInfo array"
        )
    return _braced_body(
        source,
        matches[0].end() - 1,
        f"gFieldMoveInfo in {path.relative_to(root)}",
    )


def _initializer_body(array: str, field_move: str) -> str:
    matches = list(re.finditer(rf"\[\s*FIELD_MOVE_{field_move}\s*\]\s*=\s*\{{", array))
    if not matches:
        raise ContractError(
            f"field capability policy: missing FIELD_MOVE_{field_move} initializer"
        )
    if len(matches) != 1:
        raise ContractError(
            f"field capability policy: duplicate FIELD_MOVE_{field_move} initializer"
        )
    return _braced_body(
        array, matches[0].end() - 1, f"FIELD_MOVE_{field_move} initializer"
    )


def _callback_suffix(capability: str) -> str:
    return "".join(part.title() for part in capability.split("_"))


def _load_bindings(root: Path) -> dict:
    path = root / "tools/persistence/regional_fact_bindings.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _reject_selector(body: str) -> None:
    match = FORBIDDEN_SELECTOR.search(body)
    if match is not None:
        raise ContractError(
            f"field capability policy: forbidden selector {match.group(0)}"
        )


def _validate_regional_fact_getter(root: Path, bindings: dict) -> None:
    body = _function_body(root / "src/regional_fact.c", "RegionalFact_Get", root)
    _reject_selector(body)
    expected = "switch(fact){"
    for entry in bindings["exact"]:
        fact = entry["fact"]
        expected += (
            f"case REGIONAL_FACT_{fact}:return FlagGet(FLAG_REGIONAL_FACT_{fact});"
        )
    expected += "default:return FALSE;}"
    if _compact(body) != _compact(expected):
        raise ContractError(
            "field capability policy: regional fact getter is not canonical and read-only"
        )


def _validate_resolver(root: Path, bindings: dict) -> None:
    source_path = root / "src/player_capability.c"
    resolver = _function_body(source_path, "PlayerHasCapability", root)
    _reject_selector(resolver)

    facts_by_capability: dict[str, list[str]] = {}
    for entry in bindings["exact"]:
        for capability in entry["grants"]:
            facts_by_capability.setdefault(capability, []).append(entry["fact"])

    legacy_by_capability: dict[str, list[str]] = {}
    for entry in bindings["ambiguous"]:
        for capability in entry["shippedCapabilities"]:
            legacy_by_capability.setdefault(capability, []).append(entry["symbol"])

    capabilities = list(facts_by_capability)
    if set(capabilities) != set(legacy_by_capability):
        raise ContractError(
            "field capability policy: exact and shipped capability sets differ"
        )

    header = (root / "include/player_capability.h").read_text(encoding="utf-8")
    enum_match = re.search(
        r"enum PlayerCapability\s*\{(.*?)PLAYER_CAPABILITY_COUNT", header, re.DOTALL
    )
    if enum_match is None:
        raise ContractError("field capability policy: missing PlayerCapability enum")
    enum_capabilities = re.findall(
        r"PLAYER_CAPABILITY_([A-Z0-9_]+)", enum_match.group(1)
    )
    if enum_capabilities != capabilities:
        raise ContractError(
            "field capability policy: PlayerCapability enum differs from bindings"
        )

    expected = "switch(capability){"
    for capability in capabilities:
        grants = [
            *(
                f"RegionalFact_Get(REGIONAL_FACT_{fact})"
                for fact in facts_by_capability[capability]
            ),
            *(f"FlagGet({flag})" for flag in legacy_by_capability[capability]),
        ]
        expected += f"case PLAYER_CAPABILITY_{capability}:return {' || '.join(grants)};"
    expected += "default:return FALSE;}"
    if _compact(resolver) != _compact(expected):
        raise ContractError(
            "field capability policy: resolver is not canonical and read-only"
        )


def _validate_field_move_routing(root: Path, bindings: dict) -> None:
    path = root / "src/field_move.c"
    array = _field_move_array_body(path, root)
    capabilities = list(
        dict.fromkeys(
            capability for entry in bindings["exact"] for capability in entry["grants"]
        )
    )
    for capability in capabilities:
        name = f"IsFieldMoveUnlocked_{_callback_suffix(capability)}"
        body = _function_body(path, name, root)
        _reject_selector(body)
        expected = f"return PlayerHasCapability(PLAYER_CAPABILITY_{capability});"
        if _compact(body) != _compact(expected):
            raise ContractError(
                f"field capability policy: {capability} wrapper is not canonical and read-only"
            )
        initializer = _initializer_body(array, capability)
        callbacks = re.findall(
            r"\.isUnlockedFunc\s*=\s*([A-Za-z0-9_]+)\s*,", initializer
        )
        if callbacks != [name]:
            raise ContractError(
                f"field capability policy: FIELD_MOVE_{capability} bypasses named wrapper"
            )

    config = (root / "include/config/overworld.h").read_text(encoding="utf-8")
    for move in bindings["unsupported"]:
        name = f"IsFieldMoveUnlocked_{_callback_suffix(move)}"
        body = _function_body(path, name, root)
        _reject_selector(body)
        macro = f"OW_{move}_FIELD_MOVE"
        if _compact(body) != _compact(f"return {macro};"):
            raise ContractError(
                f"field capability policy: unsupported {move} routing changed"
            )
        initializer = _initializer_body(array, move)
        callbacks = re.findall(
            r"\.isUnlockedFunc\s*=\s*([A-Za-z0-9_]+)\s*,", initializer
        )
        if callbacks != [name]:
            raise ContractError(
                f"field capability policy: FIELD_MOVE_{move} bypasses named wrapper"
            )
        if re.search(rf"(?m)^#define\s+{macro}\s+FALSE(?:\s|$)", config) is None:
            raise ContractError(
                f"field capability policy: unsupported {move} is not disabled"
            )

    for move in (
        "TELEPORT",
        "DIG",
        "SECRET_POWER",
        "MILK_DRINK",
        "SOFT_BOILED",
        "SWEET_SCENT",
    ):
        name = f"IsFieldMoveUnlocked_{_callback_suffix(move)}"
        body = _function_body(path, name, root)
        _reject_selector(body)
        if _compact(body) != _compact("return TRUE;"):
            raise ContractError(
                f"field capability policy: utility {move} is not always available"
            )
        initializer = _initializer_body(array, move)
        callbacks = re.findall(
            r"\.isUnlockedFunc\s*=\s*([A-Za-z0-9_]+)\s*,", initializer
        )
        if callbacks != [name]:
            raise ContractError(
                f"field capability policy: FIELD_MOVE_{move} bypasses named wrapper"
            )


def _validate_regional_badge_story_compatibility(root: Path, bindings: dict) -> None:
    exact_facts = {entry["symbol"] for entry in bindings["exact"]}
    admitted_facts = {
        entry["symbol"]
        for entry in bindings["exact"]
        if entry["fact"].startswith(("HOENN_", "KANTO_"))
    }
    inventoried_producers = {
        semantic_fact for _, _, semantic_fact, _ in EXACT_STORY_PRODUCERS
    }
    if inventoried_producers != admitted_facts:
        raise ContractError(
            "regional facts: producer inventory differs from admitted Hoenn/Kanto facts"
        )
    inventoried_readers = {
        semantic_fact for _, _, _, semantic_fact in EXACT_STORY_READERS
    }
    if inventoried_readers != admitted_facts:
        raise ContractError(
            "regional facts: reader inventory differs from admitted Hoenn/Kanto facts"
        )
    if len(EXACT_STORY_PRODUCERS) != len(
        {(path, label) for path, label, _, _ in EXACT_STORY_PRODUCERS}
    ):
        raise ContractError("regional facts: duplicate producer inventory entry")
    if len(EXACT_STORY_READERS) != len(
        {(path, label) for path, label, _, _ in EXACT_STORY_READERS}
    ):
        raise ContractError("regional facts: duplicate reader inventory entry")

    ambiguous_flags = {entry["symbol"] for entry in bindings["ambiguous"]}
    for path, label, command, expected_fact in EXACT_STORY_READERS:
        block = _script_block(root / path, label, root)
        _reject_selector(block)
        if any(flag in block for flag in ambiguous_flags):
            raise ContractError(f"regional facts: ambiguous exact reader {label}")
        if f"{command} {expected_fact}," not in block:
            raise ContractError(f"regional facts: {label} omits {expected_fact}")
        if any(fact in block for fact in exact_facts - {expected_fact}):
            raise ContractError(f"regional facts: wrong exact fact in {label}")

    for path, label, semantic_fact, flat_badge in EXACT_STORY_PRODUCERS:
        block = _script_block(root / path, label, root)
        _reject_selector(block)
        for flag in (semantic_fact, flat_badge):
            if block.count(f"setflag {flag}") != 1:
                raise ContractError(f"regional facts: {label} omits dual-write {flag}")
        if any(fact in block for fact in exact_facts - {semantic_fact}):
            raise ContractError(f"regional facts: wrong exact fact in {label}")


def validate(root: Path = ROOT) -> None:
    bindings = _load_bindings(root)
    _validate_regional_fact_getter(root, bindings)
    _validate_resolver(root, bindings)
    _validate_field_move_routing(root, bindings)

    _validate_regional_badge_story_compatibility(root, bindings)


if __name__ == "__main__":
    validate()
