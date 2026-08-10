from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import tempfile
import subprocess
import unittest

from tools.persistence.contract import ContractError, canonical_bytes
from tools.persistence.ledger import (
    render,
    seed_ledger,
    validate_consumer_references,
    validate_frozen_bindings,
    validate_ledger,
    validate_location_codecs,
    validate_published_allocation_history,
    validate_published_allocations,
)


ROOT = Path(__file__).parents[3]


def _numeric_macro_match(text: str, symbol: str) -> re.Match[str]:
    pattern = re.compile(
        rf"(?m)^[ \t]*#define[ \t]+{re.escape(symbol)}[ \t]+"
        r"(?P<value>0[xX][0-9A-Fa-f]+|[0-9]+)[ \t]*(?://[^\r\n]*)?$"
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one numeric macro for {symbol}")
    return matches[0]


def _numeric_macro_value(text: str, symbol: str) -> int:
    return int(_numeric_macro_match(text, symbol).group("value"), 0)


def _replace_numeric_macro(
    text: str, symbol: str, *, expected: int, replacement: int
) -> str:
    match = _numeric_macro_match(text, symbol)
    if int(match.group("value"), 0) != expected:
        raise AssertionError(f"expected {symbol} to equal {expected}")
    start, end = match.span("value")
    return f"{text[:start]}{replacement}{text[end:]}"


class PersistentIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(
            (ROOT / "tools/integrity/save_contract.json").read_text()
        )
        cls.sources = json.loads(
            (ROOT / "tools/persistence/persistent_sources.json").read_text()
        )
        cls.ledger = json.loads(
            (ROOT / "src/data/persistence/persistent_ids.json").read_text()
        )
        cls.published_allocations = json.loads(
            (ROOT / "tools/persistence/published_allocations.json").read_text()
        )

    def mutated(self):
        return copy.deepcopy(self.ledger)

    def test_seed_and_generation_are_byte_identical(self):
        first = seed_ledger(self.contract, self.sources, ROOT)
        second = seed_ledger(self.contract, self.sources, ROOT)
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertEqual(
            canonical_bytes(first),
            (ROOT / "src/data/persistence/persistent_ids.json").read_bytes(),
        )
        with (
            tempfile.TemporaryDirectory() as left_tmp,
            tempfile.TemporaryDirectory() as right_tmp,
        ):
            left, right = Path(left_tmp), Path(right_tmp)
            render(first, self.sources, left)
            render(second, self.sources, right)
            for relative in (
                "src/data/persistence/trainer_defeat_flags.inc.c",
                "src/data/persistence/location_codecs.inc.c",
                "include/constants/heal_locations.h",
                "include/constants/persistent_bindings.h",
                "include/constants/persistent_flags.inc.h",
                "include/constants/persistent_vars.inc.h",
                "include/constants/persistent_game_stats.inc.h",
                "include/constants/persistent_maps.inc.h",
                "include/constants/persistent_facilities.inc.h",
                "include/constants/persistent_locations.inc.h",
                "include/constants/persistent_opponents.inc.h",
                "include/constants/persistent_trainer_special.inc.h",
                "include/constants/persistent_trainer_hill.inc.h",
            ):
                self.assertEqual(
                    (left / relative).read_bytes(), (right / relative).read_bytes()
                )

    def test_public_constant_facades_resolve_through_ledger_values(self):
        cases = {
            "persistent_flags.inc.h": ("flags", "FLAG_RECEIVED_FIRST_POTION"),
            "persistent_vars.inc.h": ("vars", "VAR_TRAINER_BATTLE_OPPONENT_A"),
            "persistent_game_stats.inc.h": ("gameStats", "GAME_STAT_SAVED_GAME"),
            "persistent_maps.inc.h": ("checkpoints", "WARP_ID_DYNAMIC"),
            "persistent_facilities.inc.h": ("facilities", "FRONTIER_FACILITY_TOWER"),
            "persistent_locations.inc.h": ("savedLocations", "MAPSEC_LITTLEROOT_TOWN"),
            "persistent_opponents.inc.h": ("trainerIds", "TRAINER_RIVAL_TOTODILE_1"),
            "persistent_trainer_special.inc.h": ("trainerIds", "TRAINER_UNION_ROOM"),
            "persistent_trainer_hill.inc.h": ("facilities", "HILL_MODE_EXPERT"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            bindings = (output / "include/constants/persistent_bindings.h").read_text()
            for filename, (domain, symbol) in cases.items():
                facade = (output / "include/constants" / filename).read_text()
                domain_macro = (
                    __import__("re").sub(r"(?<!^)(?=[A-Z])", "_", domain).upper()
                )
                macro = f"PERSISTENT_{domain_macro}_{symbol}"
                entry = next(
                    item
                    for item in self.ledger["entries"]
                    if item["domain"] == domain and item["symbol"] == symbol
                )
                with self.subTest(filename=filename, symbol=symbol):
                    self.assertIn(
                        f"#undef {symbol}\n#define {symbol} {macro}\n", facade
                    )
                    self.assertIn(f"#define {macro} {entry['value']}\n", bindings)

    def test_debug_configuration_flags_survive_generated_overlay(self):
        debug_symbols = {
            "FLAG_DEBUG_NO_WILD_ENCOUNTERS": "0x8FE",
            "FLAG_DEBUG_NO_TRAINER_SIGHT": "0x8FF",
        }
        self.assertTrue(
            debug_symbols.keys().isdisjoint(
                item["symbol"] for item in self.ledger["entries"]
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            overlay = (output / "include/constants/persistent_flags.inc.h").read_text()
            for symbol in debug_symbols:
                self.assertNotIn(symbol, overlay)

            for debug, expected in (
                (False, {key: "0" for key in debug_symbols}),
                (True, debug_symbols),
            ):
                command = [
                    "arm-none-eabi-gcc",
                    "-dM",
                    "-E",
                    "-x",
                    "c",
                    "-DTESTING=0",
                    "-I",
                    str(output / "include"),
                    "-I",
                    str(ROOT / "include"),
                ]
                if debug:
                    command.append("-DDEBUG=1")
                macros = subprocess.run(
                    command + ["-"],
                    cwd=ROOT,
                    input='#include "constants/flags.h"\n',
                    text=True,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                ).stdout
                definitions = dict(
                    line.removeprefix("#define ").split(maxsplit=1)
                    for line in macros.splitlines()
                    if line.startswith("#define ") and len(line.split()) == 3
                )
                with self.subTest(debug=debug):
                    for symbol, value in expected.items():
                        self.assertEqual(definitions[symbol], value)

    def test_grouped_generation_recovers_a_missing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "generated"
            target = output / "src/data/persistence/location_codecs.inc.c"
            command = [
                "make",
                "-f",
                "persistent_id_rules.mk",
                f"GENERATED_ROOT={output}",
                str(target),
            ]
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            target.unlink()
            subprocess.run(
                command,
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self.assertTrue(target.is_file())

    def test_heal_header_is_preprocessor_only_for_assembler(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            header = (output / "include/constants/heal_locations.h").read_text()
        self.assertNotIn("enum", header)
        self.assertNotIn("{", header)
        self.assertNotIn("}", header)
        for item in (
            item
            for item in self.ledger["entries"]
            if item["source"] == "heal-locations"
        ):
            self.assertIn(f"#define {item['symbol']} {item['value']}\n", header)

    def test_every_frozen_binding_rejects_a_value_mutation(self):
        # Exercise every published symbol without thousands of deep copies. Each
        # in-place mutation is restored before the next subtest.
        entries = self.ledger["entries"]
        for item in entries:
            if item["state"]["kind"] not in {
                "published-binding",
                "trainer-defeat-flag",
            }:
                continue
            old = item["value"]
            item["value"] = old + 1
            with (
                self.subTest(domain=item["domain"], symbol=item["symbol"]),
                self.assertRaises(ContractError),
            ):
                validate_frozen_bindings(entries, self.contract)
            item["value"] = old

    def test_every_allocated_binding_is_bound_to_the_published_baseline(self):
        validate_published_allocations(
            self.ledger["entries"], self.published_allocations
        )
        entries = self.ledger["entries"]
        for item in entries:
            if item["state"]["kind"] != "allocated-binding":
                continue
            old = item["value"]
            item["value"] = old + 1
            with (
                self.subTest(domain=item["domain"], symbol=item["symbol"]),
                self.assertRaisesRegex(
                    ContractError, "published allocations moved/deleted/unreviewed"
                ),
            ):
                validate_published_allocations(entries, self.published_allocations)
            item["value"] = old

    def test_coordinated_berry_source_and_ledger_renumber_is_rejected(self):
        ledger = self.mutated()
        sources = copy.deepcopy(self.sources)
        berry_symbol = "BERRY_TREE_ROUTE_29_ORAN_1"
        berry_entry = next(
            item for item in ledger["entries"] if item["symbol"] == berry_symbol
        )
        berry_source = next(
            item
            for item in sources["explicitAllocations"]
            if item["symbol"] == berry_symbol
        )
        berry_entry["value"] = 91
        berry_source["value"] = 91
        header = _replace_numeric_macro(
            (ROOT / "include/constants/berry.h").read_text(),
            berry_symbol,
            expected=90,
            replacement=91,
        )
        self.assertEqual(_numeric_macro_value(header, berry_symbol), 91)
        self.assertEqual(berry_entry["value"], berry_source["value"])

        with self.assertRaisesRegex(
            ContractError, "published allocations moved/deleted/unreviewed"
        ):
            validate_published_allocations(
                ledger["entries"], self.published_allocations
            )

    def test_changing_current_policy_cannot_rewrite_published_history(self):
        current = copy.deepcopy(self.published_allocations)
        ledger = self.mutated()
        sources = copy.deepcopy(self.sources)
        berry_symbol = "BERRY_TREE_ROUTE_29_ORAN_1"
        berry = next(
            item for item in current["entries"] if item["symbol"] == berry_symbol
        )
        berry["value"] = 91
        next(item for item in ledger["entries"] if item["symbol"] == berry_symbol)[
            "value"
        ] = 91
        next(
            item
            for item in sources["explicitAllocations"]
            if item["symbol"] == berry_symbol
        )["value"] = 91
        header = _replace_numeric_macro(
            (ROOT / "include/constants/berry.h").read_text(),
            berry_symbol,
            expected=90,
            replacement=91,
        )
        self.assertEqual(_numeric_macro_value(header, berry_symbol), 91)
        validate_published_allocations(ledger["entries"], current)
        with self.assertRaisesRegex(
            ContractError, r"entries\[1\]: published allocation history changed"
        ):
            validate_published_allocation_history(current, self.published_allocations)

    def test_berry_macro_mutation_is_independent_of_rendered_spacing(self):
        symbol = "BERRY_TREE_ROUTE_29_ORAN_1"
        installed = (ROOT / "include/constants/berry.h").read_text()
        compiler_rendered = f"#define {symbol:<40} 90\n"
        for label, header in (
            ("installed", installed),
            ("compiler-rendered", compiler_rendered),
        ):
            with self.subTest(header=label):
                self.assertEqual(_numeric_macro_value(header, symbol), 90)
                mutated = _replace_numeric_macro(
                    header, symbol, expected=90, replacement=91
                )
                self.assertEqual(_numeric_macro_value(mutated, symbol), 91)

    def test_published_allocation_history_is_append_only(self):
        previous = self.published_allocations
        current = copy.deepcopy(previous)
        allocation = {
            "domain": "berryTrees",
            "source": "berry-trees",
            "storage": "u8-id",
            "symbol": "BERRY_TREE_FUTURE_REVIEWED",
            "value": 91,
        }
        current["entries"].append(allocation)
        validate_published_allocation_history(current, previous)

        ledger_entries = copy.deepcopy(self.ledger["entries"])
        ledger_entries.append(
            {
                "alias": None,
                **allocation,
                "state": {"kind": "allocated-binding"},
            }
        )
        validate_published_allocations(ledger_entries, current)

        truncated = copy.deepcopy(previous)
        truncated["entries"].pop()
        with self.assertRaisesRegex(ContractError, "history was truncated"):
            validate_published_allocation_history(truncated, previous)

        reused = copy.deepcopy(previous)
        reused["entries"].append(
            {
                **allocation,
                "symbol": "BERRY_TREE_REUSED_FORBIDDEN",
                "value": 90,
            }
        )
        with self.assertRaisesRegex(ContractError, "reuses published allocation"):
            validate_published_allocation_history(reused, previous)

    def test_every_domain_rejects_an_unallocated_live_consumer(self):
        entries = self.ledger["entries"]
        for schema in self.sources["consumerSchemas"]:
            referenced = None
            for glob in schema["paths"]:
                for path in ROOT.glob(glob):
                    if not path.is_file():
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                    for pattern in schema["patterns"]:
                        match = __import__("re").search(
                            pattern, text, __import__("re").MULTILINE
                        )
                        if match is not None:
                            referenced = match.group("symbol")
                            break
                    if referenced is not None:
                        break
                if referenced is not None:
                    break
            with self.subTest(domain=schema["domain"]):
                self.assertIsNotNone(
                    referenced, "consumer schema did not scan a real reference"
                )
                reduced = [
                    item
                    for item in entries
                    if item["domain"] == schema["domain"]
                    and item["symbol"] != referenced
                ]
                with self.assertRaisesRegex(ContractError, "unallocated"):
                    validate_consumer_references(reduced, [schema], ROOT)

    def test_script_opcodes_reject_unallocated_persistent_tokens(self):
        cases = {
            "flags": "FLAG_TUTOR_DOUBLE_EDGE",  # setflag
            "vars": "VAR_0x8005",  # setvar/copyvar
            "gameStats": "GAME_STAT_WATCHED_TV",  # incrementgamestat
            "facilities": "FACILITY_BATTLE_DOME",  # dofacilitytrainerbattle
            "trainerIds": "TRAINER_JOSH",  # settrainerflag
        }
        for domain, symbol in cases.items():
            schema = next(
                item
                for item in self.sources["consumerSchemas"]
                if item["domain"] == domain
            )
            reduced = [
                item
                for item in self.ledger["entries"]
                if item["domain"] == domain and item["symbol"] != symbol
            ]
            with (
                self.subTest(domain=domain, symbol=symbol),
                self.assertRaisesRegex(ContractError, "unallocated"),
            ):
                validate_consumer_references(reduced, [schema], ROOT)

    def test_all_saved_and_met_code_bindings_reject_mutation(self):
        for codec in ("saved", "met"):
            for record in self.ledger["locationCodecs"][codec]:
                ledger = self.mutated()
                ledger["locationCodecs"][codec][record["code"]]["sectionValue"] ^= 1
                with (
                    self.subTest(codec=codec, code=record["code"]),
                    self.assertRaisesRegex(ContractError, "locationCodecs"),
                ):
                    validate_location_codecs(
                        ledger["locationCodecs"], self.sources, ROOT
                    )

    def test_duplicate_symbol_is_rejected(self):
        ledger = self.mutated()
        first, second = ledger["entries"][:2]
        second["domain"], second["symbol"] = first["domain"], first["symbol"]
        with self.assertRaisesRegex(ContractError, "duplicate symbol"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_duplicate_value_without_alias_is_rejected(self):
        ledger = self.mutated()
        group = next(item for item in ledger["entries"] if item["alias"] is not None)
        group["alias"] = None
        with self.assertRaisesRegex(ContractError, "canonical owner"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_unauthorized_alias_is_rejected(self):
        ledger = self.mutated()
        item = next(item for item in ledger["entries"] if item["alias"] is not None)
        item["alias"]["owner"] = "contract-vars"
        with self.assertRaisesRegex(ContractError, "unauthorized alias"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_deleted_published_binding_is_rejected(self):
        ledger = self.mutated()
        index = next(
            i
            for i, item in enumerate(ledger["entries"])
            if item["state"]["kind"] == "published-binding" and item["alias"] is None
        )
        ledger["entries"].pop(index)
        with self.assertRaises(ContractError):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_sentinel_collision_is_rejected(self):
        ledger = self.mutated()
        item = next(item for item in ledger["entries"] if item["storage"] == "flag-id")
        item["value"] = 0xFFFF
        with self.assertRaisesRegex(ContractError, "sentinel collision"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_storage_overflow_is_rejected(self):
        ledger = self.mutated()
        item = next(item for item in ledger["entries"] if item["storage"] == "u8-id")
        item["value"] = 256
        with self.assertRaisesRegex(ContractError, "width/storage overflow"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_unallocated_source_reference_is_rejected(self):
        ledger = self.mutated()
        ledger["entries"][0]["source"] = "missing-source"
        with self.assertRaisesRegex(ContractError, "unallocated source reference"):
            validate_ledger(
                ledger,
                self.contract,
                self.sources,
                self.published_allocations,
                ROOT,
            )

    def test_trainer_table_preserves_every_old_defeat_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            table = (
                output / "src/data/persistence/trainer_defeat_flags.inc.c"
            ).read_text()
        for trainer_id in range(858):
            with self.subTest(trainer_id=trainer_id):
                self.assertIn(f"[{trainer_id}] = 0x{0x500 + trainer_id:04X},", table)


if __name__ == "__main__":
    unittest.main()
