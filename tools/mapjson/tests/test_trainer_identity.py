from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
OPPONENTS = ROOT / "include" / "constants" / "opponents.h"
FRLG_OPPONENTS = ROOT / "include" / "constants" / "opponents_frlg.h"
HOENN_PARTIES = ROOT / "src" / "data" / "trainers.party"
FRLG_PARTIES = ROOT / "src" / "data" / "trainers_frlg.party"
TRAINERPROC = ROOT / "tools" / "trainerproc" / "trainerproc"

NUMERIC_DEFINE = re.compile(
    r"(?m)^#define[ \t]+(?P<name>TRAINER_[A-Z0-9_]+)[ \t]+"
    r"(?P<value>[0-9]+)[ \t]*$"
)
PARTY_SECTION = re.compile(r"(?m)^=== (TRAINER_[A-Z0-9_]+) ===$")
TRAINER_TOKEN = re.compile(r"\bTRAINER_[A-Z0-9_]+\b")
EXECUTABLE_SUFFIXES = {".c", ".h", ".inc", ".party", ".s"}


def numeric_definitions(path: Path) -> dict[str, int]:
    definitions: dict[str, int] = {}
    for match in NUMERIC_DEFINE.finditer(path.read_text()):
        name = match.group("name")
        if name in definitions:
            raise AssertionError(f"duplicate numeric trainer definition: {name}")
        definitions[name] = int(match.group("value"))
    return definitions


class GlobalTrainerIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.frlg_definitions = numeric_definitions(FRLG_OPPONENTS)
        cls.legacy = {
            name: value
            for name, value in cls.frlg_definitions.items()
            if name != "TRAINER_NONE" and not name.startswith("TRAINER_FRLG_")
        }
        cls.live = {
            name: value
            for name, value in cls.frlg_definitions.items()
            if name.startswith("TRAINER_FRLG_")
        }

        subprocess.run(
            ["make", "-C", "tools/trainerproc", "trainerproc"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.tempdir = tempfile.TemporaryDirectory(prefix="frlg-trainers-")
        cls.generated_frlg = Path(cls.tempdir.name) / "trainers_frlg.h"
        subprocess.run(
            [str(TRAINERPROC), "-o", str(cls.generated_frlg), str(FRLG_PARTIES)],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_legacy_to_live_frlg_identity_is_a_literal_bijection(self) -> None:
        self.assertEqual(len(self.legacy), 623)
        self.assertEqual(len(self.live), 623)
        self.assertEqual(set(self.legacy.values()), set(range(1, 624)))
        self.assertEqual(set(self.live.values()), set(range(858, 1481)))
        self.assertEqual(
            self.live,
            {
                f"TRAINER_FRLG_{legacy.removeprefix('TRAINER_')}": value + 857
                for legacy, value in self.legacy.items()
            },
        )

    def test_global_bounds_and_reserved_samuel_identity_are_literal(self) -> None:
        opponents = OPPONENTS.read_text()
        definitions = numeric_definitions(OPPONENTS)
        hoenn = {name: value for name, value in definitions.items() if value <= 857}
        self.assertEqual(len(hoenn), 858)
        self.assertEqual(set(hoenn.values()), set(range(858)))
        self.assertEqual(definitions["TRAINER_YOUNGSTER_SAMUEL_JOHTO"], 1481)
        self.assertRegex(opponents, r"(?m)^#define TRAINERS_COUNT\s+1482$")
        self.assertRegex(opponents, r"(?m)^#define MAX_TRAINERS_COUNT\s+1536$")

    def test_every_live_frlg_party_is_generated_and_nonempty(self) -> None:
        party_symbols = PARTY_SECTION.findall(FRLG_PARTIES.read_text())
        self.assertEqual(len(party_symbols), 623)
        self.assertEqual(set(party_symbols), set(self.live))

        generated = self.generated_frlg.read_text()
        generated_symbols = re.findall(
            r"(?m)^\s*\[DIFFICULTY_[A-Z0-9_]+\]\[(TRAINER_FRLG_[A-Z0-9_]+)\] =",
            generated,
        )
        party_sizes = [
            int(value)
            for value in re.findall(r"(?m)^\s*\.partySize = ([0-9]+),$", generated)
        ]
        self.assertEqual(generated_symbols, party_symbols)
        self.assertEqual(len(party_sizes), 623)
        self.assertTrue(all(size > 0 for size in party_sizes))

    def test_emerald_trainer_table_composes_both_generated_party_sources(self) -> None:
        data_source = (ROOT / "src" / "data.c").read_text()
        table = re.search(
            r"const struct Trainer gTrainers\[DIFFICULTY_COUNT\]\[TRAINERS_COUNT\] =\n"
            r"\{\n(?P<body>.*?)\n\};",
            data_source,
            re.DOTALL,
        )
        self.assertIsNotNone(table)
        body = table.group("body")
        self.assertEqual(
            re.findall(r'^#include "([^"]+)"$', body, re.MULTILINE),
            ["data/trainers.h", "data/trainers_frlg.h"],
        )
        self.assertNotIn("IS_FRLG", body)
        self.assertEqual(len(PARTY_SECTION.findall(HOENN_PARTIES.read_text())), 858)

    def test_executable_sources_never_use_legacy_frlg_tombstones(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout.split(b"\0")
        stale: dict[str, list[str]] = {}
        unknown_live: dict[str, list[str]] = {}
        for raw_path in tracked:
            if not raw_path:
                continue
            relative = Path(raw_path.decode())
            if relative == Path("include/constants/opponents_frlg.h"):
                continue
            if relative.parts[:3] == ("src", "data", "persistence"):
                continue
            if relative.suffix not in EXECUTABLE_SUFFIXES:
                continue
            tokens = set(TRAINER_TOKEN.findall((ROOT / relative).read_text()))
            tombstones = sorted(tokens & self.legacy.keys())
            unresolved = sorted(
                token
                for token in tokens
                if token.startswith("TRAINER_FRLG_") and token not in self.live
            )
            if tombstones:
                stale[str(relative)] = tombstones
            if unresolved:
                unknown_live[str(relative)] = unresolved
        self.assertEqual(stale, {})
        self.assertEqual(unknown_live, {})


if __name__ == "__main__":
    unittest.main()
