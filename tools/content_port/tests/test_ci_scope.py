from __future__ import annotations

import unittest

from tools.content_port.ci_scope import requires_donor_contracts


class CiScopeTests(unittest.TestCase):
    def test_runs_for_donor_contract_implementation_and_configuration(self) -> None:
        for path in (
            ".github/workflows/ci.yml",
            "Makefile",
            "tools/content_port/sources.py",
            "tools/content_port/ports/johto/port.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(requires_donor_contracts([path]))

    def test_runs_for_production_inputs_validated_by_donor_contracts(self) -> None:
        for path in (
            "CREDITS.md",
            "data/maps/OlivineCity_PortInside/scripts.inc",
            "data/layouts/OlivineCity_PortInside/map.bin",
            "data/tilesets/primary/JohtoMetatiles.bin",
            "include/constants/items.h",
            "src/data/persistence/persistent_ids.json",
            "src/data/trainers.h",
            "src/data/wild_encounters.json",
        ):
            with self.subTest(path=path):
                self.assertTrue(requires_donor_contracts([path]))

    def test_skips_unrelated_changes(self) -> None:
        self.assertFalse(
            requires_donor_contracts(
                [
                    ".github/ISSUE_TEMPLATE/bug.yml",
                    "README.md",
                    "database/maps/example.json",
                    "tools/content_portable/example.py",
                    "tools/e2e/tests/core/test_new_game.py",
                ]
            )
        )

    def test_runs_when_any_changed_path_is_in_scope(self) -> None:
        self.assertTrue(
            requires_donor_contracts(
                [
                    "README.md",
                    "data/maps/OlivineCity_PortInside/scripts.inc",
                ]
            )
        )
