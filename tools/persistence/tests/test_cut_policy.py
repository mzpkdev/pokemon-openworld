from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from tools.persistence.contract import ContractError
from tools.persistence.cut_policy import ROOT, validate


POLICY_FILES = (
    "src/field_move.c",
    "src/player_capability.c",
    "src/regional_fact.c",
    "include/player_capability.h",
    "include/regional_fact.h",
    "include/config/overworld.h",
    "tools/persistence/regional_fact_bindings.json",
    "data/maps/RustboroCity_Gym/scripts.inc",
    "data/maps/RustboroCity/scripts.inc",
    "data/maps/RustboroCity_PokemonSchool/scripts.inc",
    "data/maps/CeruleanCity_Gym_Frlg/scripts.inc",
    "data/scripts/route23.inc",
)


class FieldCapabilityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.copy_policy()

    def tearDown(self):
        self.temp.cleanup()

    def copy_policy(self) -> None:
        for relative in POLICY_FILES:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)

    def reset_policy(self) -> None:
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.copy_policy()

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.root / relative
        source = path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        path.write_text(source.replace(old, new, 1), encoding="utf-8")

    def test_current_policy_passes(self):
        validate(self.root)

    def test_resolver_requires_every_and_only_authoritative_facts(self):
        path = "src/player_capability.c"
        mutations = (
            (
                "RegionalFact_Get(REGIONAL_FACT_HOENN_KNUCKLE_BADGE)",
                "FALSE",
            ),
            (
                "|| FlagGet(FLAG_BADGE02_GET);",
                "|| RegionalFact_Get(REGIONAL_FACT_HOENN_STONE_BADGE)\n"
                "            || FlagGet(FLAG_BADGE02_GET);",
            ),
        )
        for old, new in mutations:
            with self.subTest(mutation=old):
                self.replace(path, old, new)
                with self.assertRaisesRegex(ContractError, "resolver is not canonical"):
                    validate(self.root)
                self.reset_policy()

    def test_resolver_requires_exactly_the_shipped_legacy_grant(self):
        self.replace(
            "src/player_capability.c",
            "FlagGet(FLAG_BADGE06_GET)",
            "FlagGet(FLAG_BADGE03_GET)",
        )
        with self.assertRaisesRegex(ContractError, "resolver is not canonical"):
            validate(self.root)

        self.reset_policy()
        self.replace(
            "src/player_capability.c",
            "|| FlagGet(FLAG_BADGE06_GET);",
            "|| FlagGet(FLAG_UNUSED_0x035)\n            || FlagGet(FLAG_BADGE06_GET);",
        )
        with self.assertRaisesRegex(ContractError, "resolver is not canonical"):
            validate(self.root)

    def test_capability_enum_is_frozen_to_binding_authority(self):
        self.replace(
            "include/player_capability.h",
            "    PLAYER_CAPABILITY_DIVE,\n",
            "",
        )
        with self.assertRaisesRegex(ContractError, "enum differs from bindings"):
            validate(self.root)

    def test_supported_callback_must_route_through_named_capability(self):
        self.replace(
            "src/field_move.c",
            "return PlayerHasCapability(PLAYER_CAPABILITY_SURF);",
            "return TRUE;",
        )
        with self.assertRaisesRegex(ContractError, "SURF wrapper is not canonical"):
            validate(self.root)

    def test_regional_fact_getter_rejects_aliased_fact(self):
        self.replace(
            "src/regional_fact.c",
            "return FlagGet(FLAG_REGIONAL_FACT_JOHTO_HIVE_BADGE);",
            "return FlagGet(FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE);",
        )
        with self.assertRaisesRegex(
            ContractError, "regional fact getter is not canonical"
        ):
            validate(self.root)

    def test_resolver_and_wrapper_reject_unreachable_approved_return(self):
        mutations = (
            (
                "src/player_capability.c",
                "case PLAYER_CAPABILITY_CUT:\n        return RegionalFact_Get",
                "case PLAYER_CAPABILITY_CUT:\n        return TRUE;\n        return RegionalFact_Get",
                "resolver is not canonical",
            ),
            (
                "src/field_move.c",
                "{\n    return PlayerHasCapability(PLAYER_CAPABILITY_CUT);\n}",
                "{\n    return TRUE;\n    return PlayerHasCapability(PLAYER_CAPABILITY_CUT);\n}",
                "CUT wrapper is not canonical",
            ),
        )
        for path, old, new, error in mutations:
            with self.subTest(path=path):
                self.replace(path, old, new)
                with self.assertRaisesRegex(ContractError, error):
                    validate(self.root)
                self.reset_policy()

    def test_policy_bodies_reject_side_effect_calls(self):
        self.replace(
            "src/player_capability.c",
            "switch (capability)\n    {",
            "FlagSet(FLAG_UNUSED_0x035);\n    switch (capability)\n    {",
        )
        with self.assertRaisesRegex(ContractError, "resolver is not canonical"):
            validate(self.root)

    def test_field_move_initializer_must_use_named_wrapper(self):
        self.replace(
            "src/field_move.c",
            ".isUnlockedFunc = IsFieldMoveUnlocked_Flash,",
            ".isUnlockedFunc = IsFieldMoveUnlocked_Teleport,",
        )
        with self.assertRaisesRegex(
            ContractError, "FIELD_MOVE_FLASH bypasses named wrapper"
        ):
            validate(self.root)

    def test_disabled_decoy_initializer_does_not_hide_live_callback_swap(self):
        original = """[FIELD_MOVE_FLASH] =
    {
        .fieldMoveFunc = SetUpFieldMove_Flash,
        .isUnlockedFunc = IsFieldMoveUnlocked_Flash,
        .moveID = MOVE_FLASH,
        .partyMsgID = PARTY_MSG_CANT_USE_HERE,
    },"""
        swapped = original.replace(
            ".isUnlockedFunc = IsFieldMoveUnlocked_Flash,",
            ".isUnlockedFunc = IsFieldMoveUnlocked_Teleport,",
        )
        self.replace(
            "src/field_move.c",
            original,
            f"#if 0\n{original}\n#endif\n\n    {swapped}",
        )
        with self.assertRaisesRegex(
            ContractError, "duplicate FIELD_MOVE_FLASH initializer"
        ):
            validate(self.root)

    def test_unsupported_moves_remain_config_disabled(self):
        for move in ("ROCK_CLIMB", "DEFOG"):
            with self.subTest(move=move, mutation="config"):
                self.replace(
                    "include/config/overworld.h",
                    f"#define OW_{move}_FIELD_MOVE",
                    f"#define OW_{move}_FIELD_MOVE_CHANGED",
                )
                with self.assertRaisesRegex(
                    ContractError, f"unsupported {move} is not disabled"
                ):
                    validate(self.root)
                self.reset_policy()

            with self.subTest(move=move, mutation="callback"):
                self.replace(
                    "src/field_move.c",
                    f"return OW_{move}_FIELD_MOVE;",
                    "return TRUE;",
                )
                with self.assertRaisesRegex(
                    ContractError, f"unsupported {move} routing changed"
                ):
                    validate(self.root)
                self.reset_policy()

    def test_utility_moves_remain_always_available(self):
        for move, suffix in (
            ("TELEPORT", "Teleport"),
            ("DIG", "Dig"),
            ("SECRET_POWER", "SecretPower"),
            ("MILK_DRINK", "MilkDrink"),
            ("SOFT_BOILED", "SoftBoiled"),
            ("SWEET_SCENT", "SweetScent"),
        ):
            with self.subTest(move=move):
                marker = f"static bool32 IsFieldMoveUnlocked_{suffix}(void)\n{{\n    return TRUE;\n}}"
                replacement = marker.replace("return TRUE;", "return FALSE;")
                self.replace("src/field_move.c", marker, replacement)
                with self.assertRaisesRegex(
                    ContractError, f"utility {move} is not always available"
                ):
                    validate(self.root)
                self.reset_policy()

    def test_selector_variants_fail_closed(self):
        path = "src/player_capability.c"
        for selector in (
            "GAME_VERSION",
            "VERSION_RUBY",
            "VERSION_SAPPHIRE",
            "VERSION_EMERALD",
            "VERSION_FIRE_RED",
            "VERSION_LEAF_GREEN",
            "IS_FRLG",
            "GetCurrentMap()",
            "currentMap",
            "current_map",
            "mapSelector",
            "map_selector",
            "GetCurrentRegion()",
            "currentRegion",
            "current_region",
            "regionSelector",
            "gGameVersion",
            "gameVersion",
            "game_version",
            "currentCampaign",
            "campaign_selector",
            "gMapHeader.mapType",
            "gMapHeader.regionMapSectionId",
            "mapType",
            "regionMapSectionId",
        ):
            with self.subTest(selector=selector):
                self.replace(
                    path,
                    "switch (capability)\n    {",
                    f"if ({selector})\n        return TRUE;\n    switch (capability)\n    {{",
                )
                with self.assertRaisesRegex(ContractError, "forbidden selector"):
                    validate(self.root)
                self.reset_policy()

    def test_exact_reader_requires_correct_regional_fact(self):
        path = "data/maps/RustboroCity/scripts.inc"
        fact = "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE"
        for replacement, error in (
            ("FLAG_BADGE03_GET", "omits.*HOENN_STONE"),
            ("FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE", "omits.*HOENN_STONE"),
            ("FLAG_BADGE01_GET", "ambiguous exact reader"),
        ):
            with self.subTest(replacement=replacement):
                self.replace(path, fact, replacement)
                with self.assertRaisesRegex(ContractError, error):
                    validate(self.root)
                self.reset_policy()

    def test_exact_producer_requires_both_writes(self):
        path = "data/maps/RustboroCity_Gym/scripts.inc"
        for flag in ("FLAG_REGIONAL_FACT_HOENN_STONE_BADGE", "FLAG_BADGE01_GET"):
            with self.subTest(flag=flag):
                self.replace(path, f"\tsetflag {flag}\n", "")
                with self.assertRaisesRegex(ContractError, "omits dual-write"):
                    validate(self.root)
                self.reset_policy()


if __name__ == "__main__":
    unittest.main()
