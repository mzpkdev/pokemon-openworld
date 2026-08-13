from __future__ import annotations

import copy
import contextlib
import errno
import hashlib
import io
import json
from pathlib import Path
import re
import tempfile
import subprocess
import unittest

from tools.persistence.contract import ContractError, canonical_bytes
from tools.persistence.historical_flags import (
    FLASH_SIZE,
    SECTOR_SIZE,
    inspect_historical_flags,
)
from tools.persistence.ledger import (
    RESIDENT_STORY_SELECTOR,
    _windows_byte_lock,
    main,
    render,
    seed_ledger,
    validate_consumer_references,
    validate_frozen_bindings,
    validate_ledger,
    validate_location_codecs,
    validate_published_allocation_history,
    validate_published_allocations,
    validate_regional_fact_policy,
    validate_regional_variable_policy,
    validate_resident_story_admission,
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
        cls.regional_fact_policy = json.loads(
            (ROOT / "tools/persistence/regional_fact_bindings.json").read_text()
        )
        cls.regional_variable_policy = json.loads(
            (ROOT / "tools/persistence/regional_variable_bindings.json").read_text()
        )

    def mutated(self):
        return copy.deepcopy(self.ledger)

    def test_windows_generation_lock_retries_contention_and_unlocks_once(self):
        class FakeLock:
            def __init__(self):
                self.seeks = 0

            def seek(self, offset):
                self.seeks += 1

            def fileno(self):
                return 17

        lock = FakeLock()
        calls = []
        sleeps = []

        def locking(fd, mode, size):
            calls.append((fd, mode, size))
            if len(calls) < 3:
                raise OSError(errno.EACCES, "contended")

        with _windows_byte_lock(
            lock,
            locking,
            nonblocking_mode=1,
            unlock_mode=2,
            sleep=sleeps.append,
        ):
            self.assertEqual(calls, [(17, 1, 1)] * 3)

        self.assertEqual(calls, [(17, 1, 1)] * 3 + [(17, 2, 1)])
        self.assertEqual(sleeps, [0.01, 0.01])
        self.assertEqual(lock.seeks, 4)

    def test_windows_generation_lock_does_not_retry_unexpected_errors(self):
        class FakeLock:
            def seek(self, offset):
                pass

            def fileno(self):
                return 17

        def locking(fd, mode, size):
            raise OSError(errno.EPERM, "unexpected")

        with self.assertRaisesRegex(OSError, "unexpected"):
            with _windows_byte_lock(
                FakeLock(),
                locking,
                nonblocking_mode=1,
                unlock_mode=2,
                sleep=lambda delay: None,
            ):
                self.fail("unexpected lock acquisition")

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
                "src/data/persistence/trainer_defeat_bindings.inc.c",
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

    def test_regional_fact_classification_and_fixture_evidence_is_valid(self):
        validate_regional_fact_policy(self.ledger["entries"], self.sources, ROOT)
        self.assertEqual(
            {item["fact"] for item in self.regional_fact_policy["exact"]},
            {
                "HOENN_STONE_BADGE",
                "KANTO_CASCADE_BADGE",
                "JOHTO_HIVE_BADGE",
                "HOENN_KNUCKLE_BADGE",
                "KANTO_BOULDER_BADGE",
                "JOHTO_ZEPHYR_BADGE",
                "HOENN_DYNAMO_BADGE",
                "KANTO_MARSH_BADGE",
                "HOENN_HEAT_BADGE",
                "KANTO_RAINBOW_BADGE",
                "JOHTO_PLAIN_BADGE",
                "HOENN_BALANCE_BADGE",
                "KANTO_SOUL_BADGE",
                "JOHTO_FOG_BADGE",
                "HOENN_FEATHER_BADGE",
                "KANTO_THUNDER_BADGE",
                "JOHTO_STORM_BADGE",
                "HOENN_MIND_BADGE",
                "HOENN_RAIN_BADGE",
                "KANTO_VOLCANO_BADGE",
                "JOHTO_RISING_BADGE",
                "SEVII_DETOUR_FINISHED",
            },
        )
        self.assertEqual(
            {
                item["symbol"]: item["shippedCapabilities"]
                for item in self.regional_fact_policy["ambiguous"]
            },
            {
                "FLAG_BADGE01_GET": ["CUT"],
                "FLAG_BADGE02_GET": ["FLASH"],
                "FLAG_BADGE03_GET": ["ROCK_SMASH"],
                "FLAG_BADGE04_GET": ["STRENGTH"],
                "FLAG_BADGE05_GET": ["SURF"],
                "FLAG_BADGE06_GET": ["FLY"],
                "FLAG_BADGE07_GET": ["DIVE"],
                "FLAG_BADGE08_GET": ["WATERFALL"],
            },
        )
        self.assertEqual(
            {item["value"] for item in self.regional_fact_policy["unused"]},
            {*range(0x20, 0x35), 0x2A1},
        )
        self.assertEqual(
            set(self.regional_fact_policy["unsupported"]), {"DEFOG", "ROCK_CLIMB"}
        )

    def test_regional_variable_and_story_admission_policies_are_valid(self):
        validate_regional_variable_policy(self.ledger["entries"], self.sources, ROOT)
        validate_resident_story_admission(self.sources, ROOT)
        admitted = [
            item
            for item in self.regional_variable_policy["entries"]
            if item["status"] == "admitted"
        ]
        self.assertEqual(
            {item["region"] for item in admitted},
            {"HOENN", "KANTO", "SEVII", "JOHTO"},
        )
        self.assertTrue(all(item["value"] > 0 for item in admitted))

    def test_story_selector_recognizes_runtime_product_and_region_dispatch(self):
        self.assertIsNotNone(RESIDENT_STORY_SELECTOR.search("if (IS_FRLG) story();"))
        self.assertIsNotNone(
            RESIDENT_STORY_SELECTOR.search(
                "if (GetCurrentRegion() == REGION_KANTO) story();"
            )
        )

    def test_regional_variable_policy_rejects_moved_binding(self):
        entries = self.mutated()["entries"]
        binding = next(
            item
            for item in entries
            if item["domain"] == "vars"
            and item["symbol"] == "VAR_CHERRYGROVE_CITY_STATE"
        )
        binding["value"] += 1
        with self.assertRaisesRegex(ContractError, "published binding moved"):
            validate_regional_variable_policy(entries, self.sources, ROOT)

    def test_regional_fact_fixture_digest_mutation_fails_closed(self):
        fixture = self.regional_fact_policy["historicalFixtures"][0]
        data = bytearray((ROOT / fixture["path"]).read_bytes())
        data[-1] ^= 1
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mutated.sav"
            path.write_bytes(data)
            with self.assertRaisesRegex(ContractError, "fixture digest changed"):
                inspect_historical_flags(
                    path,
                    fixture["sha256"],
                    {item["value"] for item in self.regional_fact_policy["exact"]},
                )

    def test_regional_fact_fixture_checksum_mutation_fails_closed(self):
        fixture = self.regional_fact_policy["historicalFixtures"][0]
        data = bytearray((ROOT / fixture["path"]).read_bytes())
        self.assertEqual(len(data), FLASH_SIZE)
        for sector_start in range(0, 2 * 14 * SECTOR_SIZE, SECTOR_SIZE):
            sector = data[sector_start : sector_start + SECTOR_SIZE]
            if sector != b"\xff" * SECTOR_SIZE:
                data[sector_start] ^= 1
                break
        else:
            self.fail("historical fixture has no populated normal-save sector")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-checksum.sav"
            path.write_bytes(data)
            with self.assertRaisesRegex(ContractError, "invalid slot"):
                inspect_historical_flags(
                    path,
                    hashlib.sha256(data).hexdigest(),
                    {item["value"] for item in self.regional_fact_policy["exact"]},
                )

    def test_regional_fact_policy_fixtures_are_make_prerequisites(self):
        expected = {
            item["path"] for item in self.regional_fact_policy["historicalFixtures"]
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "generated"
            target = output / "include/constants/persistent_bindings.h"
            database = subprocess.run(
                [
                    "make",
                    "-f",
                    "persistent_id_rules.mk",
                    "-pn",
                    f"GENERATED_ROOT={output}",
                    str(target),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout
        target_rule = next(
            line for line in database.splitlines() if line.startswith(f"{target}:")
        )
        self.assertTrue(expected)
        for fixture in expected:
            with self.subTest(fixture=fixture):
                self.assertIn(fixture, target_rule.split())

    def test_regional_fact_flags_are_distinct_generated_public_bindings(self):
        exact = self.regional_fact_policy["exact"]
        self.assertEqual(len({item["symbol"] for item in exact}), len(exact))
        self.assertEqual({item["value"] for item in exact}, {*range(0x20, 0x35), 0x2A1})
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            facade = (output / "include/constants/persistent_flags.inc.h").read_text()
            bindings = (output / "include/constants/persistent_bindings.h").read_text()
        for item in exact:
            macro = f"PERSISTENT_FLAGS_{item['symbol']}"
            with self.subTest(symbol=item["symbol"]):
                self.assertIn(
                    f"#undef {item['symbol']}\n#define {item['symbol']} {macro}\n",
                    facade,
                )
                self.assertIn(f"#define {macro} {item['value']}\n", bindings)

    def test_live_regional_trainer_facades_are_ledger_owned(self):
        cases = {
            "TRAINER_FRLG_YOUNGSTER_BEN": 858,
            "TRAINER_FRLG_CUE_BALL_PAXTON": 1480,
            "TRAINER_YOUNGSTER_SAMUEL_JOHTO": 1481,
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            facade = (
                output / "include/constants/persistent_opponents.inc.h"
            ).read_text()
            bindings = (output / "include/constants/persistent_bindings.h").read_text()
        for symbol, value in cases.items():
            macro = f"PERSISTENT_TRAINER_IDS_{symbol}"
            self.assertIn(f"#undef {symbol}\n#define {symbol} {macro}\n", facade)
            self.assertIn(f"#define {macro} {value}\n", bindings)

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
                "published-tombstone",
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

    def test_every_bitmap_trainer_binding_is_published(self):
        live = [
            item
            for item in self.ledger["entries"]
            if item["state"]["kind"] == "trainer-defeat-bitmap"
        ]
        published = [
            item
            for item in self.published_allocations["entries"]
            if "physicalBinding" in item
        ]
        self.assertEqual(len(live), 624)
        self.assertEqual(len(published), 624)
        self.assertEqual(
            {
                (item["symbol"], item["value"], item["state"]["bitIndex"])
                for item in live
            },
            {
                (
                    item["symbol"],
                    item["value"],
                    item["physicalBinding"]["bitIndex"],
                )
                for item in published
            },
        )

    def test_coordinated_bitmap_trainer_move_is_rejected_by_publication(self):
        ledger = self.mutated()
        sources = copy.deepcopy(self.sources)
        sources["trainerIdentityProjection"]["liveValueOffset"] += 1
        sources["trainerIdentityProjection"]["additional"][0]["value"] += 1
        for item in ledger["entries"]:
            if item["state"]["kind"] == "trainer-defeat-bitmap":
                item["value"] += 1
        self.assertEqual(
            next(
                item["value"]
                for item in ledger["entries"]
                if item["symbol"] == "TRAINER_YOUNGSTER_SAMUEL_JOHTO"
            ),
            sources["trainerIdentityProjection"]["additional"][0]["value"],
        )
        with self.assertRaisesRegex(
            ContractError, "published allocations moved/deleted/unreviewed"
        ):
            validate_published_allocations(
                ledger["entries"], self.published_allocations
            )

    def test_coordinated_bitmap_trainer_deletion_is_rejected_by_publication(self):
        ledger = self.mutated()
        sources = copy.deepcopy(self.sources)
        deleted = sources["trainerIdentityProjection"]["additional"].pop()
        ledger["entries"] = [
            item for item in ledger["entries"] if item["symbol"] != deleted["symbol"]
        ]
        self.assertNotIn(
            deleted["symbol"],
            {item["symbol"] for item in ledger["entries"]},
        )
        with self.assertRaisesRegex(
            ContractError, "published allocations moved/deleted/unreviewed"
        ):
            validate_published_allocations(
                ledger["entries"], self.published_allocations
            )

    def test_coordinated_bitmap_physical_rewrite_is_rejected_by_publication(self):
        ledger = self.mutated()
        sources = copy.deepcopy(self.sources)
        bitmap = sources["trainerDefeat"]["bitmapStorage"]
        bitmap["firstTrainerId"] -= 1
        bitmap["bitCount"] += 1
        bitmap["byteCount"] = (bitmap["bitCount"] + 7) // 8
        sources["trainerDefeat"]["publishedCount"] -= 1
        for item in ledger["entries"]:
            if item["state"]["kind"] == "trainer-defeat-bitmap":
                item["state"]["bitIndex"] += 1
                self.assertEqual(
                    item["state"]["bitIndex"],
                    item["value"] - bitmap["firstTrainerId"],
                )
        with self.assertRaisesRegex(
            ContractError, "published allocations moved/deleted/unreviewed"
        ):
            validate_published_allocations(
                ledger["entries"], self.published_allocations
            )

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
        for trainer_id in range(858, 1482):
            with self.subTest(trainer_id=trainer_id):
                self.assertIn(f"[{trainer_id}] = 0xFFFF,", table)

    def test_typed_trainer_table_reproduces_every_published_flag_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            render(self.ledger, self.sources, output)
            table = (
                output / "src/data/persistence/trainer_defeat_bindings.inc.c"
            ).read_text()
        for trainer_id in range(858):
            with self.subTest(trainer_id=trainer_id):
                self.assertIn(
                    f"[{trainer_id}] = {{.id = 0x{0x500 + trainer_id:04X}, "
                    ".storage = TRAINER_DEFEAT_STORAGE_FLAG, .bit = 0},",
                    table,
                )
        for trainer_id in range(858, 1482):
            bit_index = trainer_id - 858
            with self.subTest(trainer_id=trainer_id):
                self.assertIn(
                    f"[{trainer_id}] = {{.id = 0x{bit_index // 8:04X}, "
                    ".storage = TRAINER_DEFEAT_STORAGE_BITMAP, "
                    f".bit = {bit_index % 8}}},",
                    table,
                )

    def test_live_and_tombstone_trainer_projection_is_exact(self):
        trainer_entries = [
            item for item in self.ledger["entries"] if item["domain"] == "trainerIds"
        ]
        tombstones = [
            item
            for item in trainer_entries
            if item["state"]["kind"] == "published-tombstone"
        ]
        live = [
            item
            for item in trainer_entries
            if item["state"]["kind"] == "trainer-defeat-bitmap"
        ]
        self.assertEqual(len(tombstones), 623)
        self.assertEqual(len(live), 624)
        self.assertEqual({item["value"] for item in live}, set(range(858, 1482)))
        self.assertEqual({item["state"]["bitIndex"] for item in live}, set(range(624)))
        for item in live:
            self.assertEqual(item["state"]["bitIndex"], item["value"] - 858)

    def test_bitmap_binding_mutations_fail_without_generating_output(self):
        cases = {
            "moved bitmap binding": lambda item: item["state"].__setitem__(
                "bitIndex", item["state"]["bitIndex"] + 1
            ),
            "out-of-range bitmap bit": lambda item: item["state"].__setitem__(
                "bitIndex", 624
            ),
            "live trainer identity projection moved/deleted": lambda item: (
                item.__setitem__("symbol", item["symbol"] + "_MOVED")
            ),
        }
        for error, mutate in cases.items():
            ledger = self.mutated()
            item = next(
                entry
                for entry in ledger["entries"]
                if entry["state"]["kind"] == "trainer-defeat-bitmap"
            )
            mutate(item)
            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "generated"
                output.mkdir()
                marker = output / "marker"
                marker.write_bytes(b"unchanged")
                with self.assertRaisesRegex(ContractError, error):
                    validate_ledger(
                        ledger,
                        self.contract,
                        self.sources,
                        self.published_allocations,
                        ROOT,
                    )
                self.assertEqual(list(output.iterdir()), [marker])

    def test_tombstoned_trainer_battle_operand_is_rejected(self):
        tombstone = next(
            item
            for item in self.ledger["entries"]
            if item["state"]["kind"] == "published-tombstone"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            script = repo / "data/maps/Test/scripts.inc"
            script.parent.mkdir(parents=True)
            script.write_text(
                f"\ttrainerbattle_single {tombstone['symbol']}, Intro, Defeat\n"
            )
            schema = {
                "domain": "trainerIds",
                "paths": ["data/**/*.inc"],
                "patterns": [
                    r"^\s*trainerbattle(?:_[A-Za-z0-9_]+)?\s+"
                    r"(?P<symbol>TRAINER_[A-Za-z0-9_]+)\b"
                ],
                "scriptTokens": {
                    "paths": ["data/**/*.inc"],
                    "prefixes": ["TRAINER_"],
                    "opcodePrefixes": ["trainerbattle"],
                },
            }
            with self.assertRaisesRegex(ContractError, "tombstoned trainerIds"):
                validate_consumer_references(
                    [
                        item
                        for item in self.ledger["entries"]
                        if item["domain"] == "trainerIds"
                    ],
                    [schema],
                    repo,
                )

    def test_rejected_trainer_bindings_leave_generated_output_unchanged(self):
        flag_owner = next(
            item["value"]
            for item in self.ledger["entries"]
            if item["storage"] == "flag-id"
            and 31 < item["value"] < 0x920
            and item["value"] not in (0x8FE, 0x8FF)
        )
        variable_owner = next(
            item["value"]
            for item in self.ledger["entries"]
            if item["domain"] == "vars"
            and 0x400F < item["value"] <= 0x40FF
            and item["value"] not in range(0x40E6, 0x40EC)
            and item["value"] != 0x40F1
        )
        cases = {
            "malformed": (
                "malformed",
                lambda state: state.__setitem__("unexpected", 0),
            ),
            "moved": ("moved", lambda state: state.__setitem__("value", 0x85F)),
            "duplicate": ("duplicate", lambda state: state.__setitem__("value", 0x500)),
            "daily": ("daily", lambda state: state.__setitem__("value", 0x920)),
            "transient": ("transient", lambda state: state.__setitem__("value", 1)),
            "special": ("special", lambda state: state.__setitem__("value", 0x4000)),
            "debug-reserved": (
                "debug-reserved",
                lambda state: state.__setitem__("value", 0x8FE),
            ),
            "out-of-range": (
                "out-of-range",
                lambda state: state.__setitem__("value", 0x960),
            ),
            "external-flag-owner": (
                "published owner",
                lambda state: state.__setitem__("value", flag_owner),
            ),
            "external-variable-owner": (
                "published owner",
                lambda state: (
                    state.clear(),
                    state.update(
                        {
                            "bit": 7,
                            "kind": "trainer-defeat-variable-bit",
                            "value": variable_owner,
                        }
                    ),
                ),
            ),
        }
        trainer_entries = [
            item
            for item in self.ledger["entries"]
            if item["domain"] == "trainerIds"
            and item["value"] == 1
            and item["state"]["kind"] == "trainer-defeat-flag"
        ]
        self.assertTrue(trainer_entries)

        for label, (error, mutate) in cases.items():
            ledger = self.mutated()
            states = [
                item["state"]
                for item in ledger["entries"]
                if item["domain"] == "trainerIds"
                and item["value"] == 1
                and item["state"]["kind"] == "trainer-defeat-flag"
            ]
            for state in states:
                mutate(state)
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ledger_path = root / "persistent_ids.json"
                output = root / "generated"
                marker = output / "marker"
                output.mkdir()
                marker.write_bytes(b"unchanged")
                ledger_path.write_text(json.dumps(ledger))
                stderr = io.StringIO()
                with self.subTest(case=label):
                    with contextlib.redirect_stderr(stderr):
                        self.assertEqual(
                            main(
                                [
                                    "generate",
                                    "--ledger",
                                    str(ledger_path),
                                    "--output-root",
                                    str(output),
                                ]
                            ),
                            1,
                        )
                    self.assertIn(error, stderr.getvalue())
                    self.assertEqual(marker.read_bytes(), b"unchanged")
                    self.assertEqual(list(output.iterdir()), [marker])


if __name__ == "__main__":
    unittest.main()
