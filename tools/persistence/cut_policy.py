"""Verify that Cut's complete policy path is selector-free."""

from __future__ import annotations

from pathlib import Path
import re

from tools.persistence.contract import ContractError


ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN_SELECTOR = re.compile(
    r"\b(?:IS_(?:FRLG|EMERALD|FIRERED|LEAFGREEN)|"
    r"GAME_VERSION(?:_[A-Z0-9_]+)?|"
    r"VERSION_(?:RUBY|SAPPHIRE|EMERALD|FIRE_RED|LEAF_GREEN)|"
    r"EMERALD|FIRERED|LEAFGREEN|"
    r"GetCurrentRegion|current_?region|gGameVersion|game_?version|"
    r"current_?campaign|campaign_?selector)\b",
    re.IGNORECASE,
)


def _function_body(path: Path, name: str, root: Path) -> str:
    source = path.read_text(encoding="utf-8")
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.DOTALL)
    if match is None:
        raise ContractError(f"Cut policy: missing {name} in {path.relative_to(root)}")
    start = match.start()
    brace = match.end() - 1
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise ContractError(f"Cut policy: unterminated {name} in {path.relative_to(root)}")


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


def validate(root: Path = ROOT) -> None:
    field_move = _function_body(
        root / "src/field_move.c", "IsFieldMoveUnlocked_Cut", root
    )
    capability = (root / "src/player_capability.c").read_text(encoding="utf-8")
    regional_fact = (root / "src/regional_fact.c").read_text(encoding="utf-8")
    public_headers = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in ("include/player_capability.h", "include/regional_fact.h")
    )
    policy = "\n".join((field_move, capability, regional_fact, public_headers))

    if "PlayerHasCapability(PLAYER_CAPABILITY_CUT)" not in field_move:
        raise ContractError(
            "Cut policy: field-move consumer bypasses capability resolver"
        )
    for fact in (
        "REGIONAL_FACT_HOENN_STONE_BADGE",
        "REGIONAL_FACT_KANTO_CASCADE_BADGE",
        "REGIONAL_FACT_JOHTO_HIVE_BADGE",
    ):
        if f"RegionalFact_Get({fact})" not in capability:
            raise ContractError(f"Cut policy: resolver omits {fact}")
    match = FORBIDDEN_SELECTOR.search(policy)
    if match is not None:
        raise ContractError(f"Cut policy: forbidden selector {match.group(0)}")

    exact_story_readers = (
        (
            "data/maps/RustboroCity_Gym/scripts.inc",
            "RustboroCity_Gym_EventScript_LeftGymStatue",
            "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        ),
        (
            "data/maps/RustboroCity_Gym/scripts.inc",
            "RustboroCity_Gym_EventScript_RightGymStatue",
            "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        ),
        (
            "data/maps/RustboroCity/scripts.inc",
            "RustboroCity_EventScript_Man1",
            "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        ),
        (
            "data/maps/RustboroCity_PokemonSchool/scripts.inc",
            "RustboroCity_PokemonSchool_EventScript_Scott",
            "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        ),
        (
            "data/maps/RustboroCity_PokemonSchool/scripts.inc",
            "RustboroCity_PokemonSchool_EventScript_ScottSpokeAlready",
            "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        ),
        (
            "data/maps/CeruleanCity_Gym_Frlg/scripts.inc",
            "CeruleanCity_Gym_EventScript_GymStatue",
            "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
        ),
        (
            "data/scripts/route23.inc",
            "Route23_EventScript_CheckCascadeBadge",
            "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
        ),
        (
            "data/scripts/route23.inc",
            "Route23_EventScript_CheckCascadeBadgeTrigger",
            "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
        ),
    )
    exact_facts = {
        "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE",
        "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE",
    }
    for path, label, expected_fact in exact_story_readers:
        block = _script_block(root / path, label, root)
        if "FLAG_BADGE01_GET" in block or "FLAG_BADGE02_GET" in block:
            raise ContractError(f"regional facts: ambiguous exact reader {label}")
        if f"goto_if_set {expected_fact}," not in block:
            raise ContractError(f"regional facts: {label} omits {expected_fact}")
        wrong_facts = exact_facts - {expected_fact}
        if any(fact in block for fact in wrong_facts):
            raise ContractError(f"regional facts: wrong exact fact in {label}")

    exact_story_producers = (
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
    )
    for path, label, semantic_fact, flat_badge in exact_story_producers:
        block = _script_block(root / path, label, root)
        for flag in (semantic_fact, flat_badge):
            if f"setflag {flag}" not in block:
                raise ContractError(f"regional facts: {label} omits dual-write {flag}")


if __name__ == "__main__":
    validate()
