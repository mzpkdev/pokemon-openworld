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
    "data/maps/RustboroCity_Gym/scripts.inc",
    "data/maps/RustboroCity/scripts.inc",
    "data/maps/RustboroCity_PokemonSchool/scripts.inc",
    "data/maps/CeruleanCity_Gym_Frlg/scripts.inc",
    "data/scripts/route23.inc",
)


class CutPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in POLICY_FILES:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)

    def tearDown(self):
        self.temp.cleanup()

    def replace(self, relative: str, old: str, new: str) -> None:
        path = self.root / relative
        source = path.read_text(encoding="utf-8")
        self.assertIn(old, source)
        path.write_text(source.replace(old, new, 1), encoding="utf-8")

    def test_current_policy_passes(self):
        validate(self.root)

    def test_exact_reader_requires_correct_regional_fact(self):
        path = "data/maps/RustboroCity/scripts.inc"
        fact = "FLAG_REGIONAL_FACT_HOENN_STONE_BADGE"
        self.replace(path, f"\tgoto_if_set {fact},", "\tgoto_if_set FLAG_BADGE03_GET,")
        with self.assertRaisesRegex(ContractError, "omits.*HOENN_STONE"):
            validate(self.root)

        self.tearDown()
        self.setUp()
        self.replace(path, fact, "FLAG_REGIONAL_FACT_KANTO_CASCADE_BADGE")
        with self.assertRaisesRegex(ContractError, "omits.*HOENN_STONE"):
            validate(self.root)

        self.tearDown()
        self.setUp()
        self.replace(path, fact, "FLAG_BADGE01_GET")
        with self.assertRaisesRegex(ContractError, "ambiguous exact reader"):
            validate(self.root)

    def test_exact_producer_requires_both_writes(self):
        path = "data/maps/RustboroCity_Gym/scripts.inc"
        for flag in ("FLAG_REGIONAL_FACT_HOENN_STONE_BADGE", "FLAG_BADGE01_GET"):
            with self.subTest(flag=flag):
                self.replace(path, f"\tsetflag {flag}\n", "")
                with self.assertRaisesRegex(ContractError, "omits dual-write"):
                    validate(self.root)
                self.tearDown()
                self.setUp()

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
            "GetCurrentRegion()",
            "gGameVersion",
            "currentRegion",
            "current_region",
            "gameVersion",
            "game_version",
        ):
            with self.subTest(selector=selector):
                self.replace(
                    path,
                    "bool32 PlayerHasCapability",
                    f"/* {selector} */\nbool32 PlayerHasCapability",
                )
                with self.assertRaisesRegex(ContractError, "forbidden selector"):
                    validate(self.root)
                self.tearDown()
                self.setUp()


if __name__ == "__main__":
    unittest.main()
