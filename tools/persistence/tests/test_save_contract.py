from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest import mock

from tools.persistence.contract import (
    ABI_PURPOSES,
    CONTRACT_METADATA_KEYS,
    ContractError,
    canonical_bytes,
    compare,
    abi_evidence_values,
    export_baseline,
    render_abi_evidence,
    seed_budgets,
    seed_from_commit,
    validate_budgets,
    validate_contract,
    validate_abi,
    _source_evidence,
    _purpose_defines,
)


def minimal_contract():
    roots = __import__("tools.persistence.contract", fromlist=["ROOT_TYPES"]).ROOT_TYPES
    contract = {
        "schemaVersion": 1, "baselineCommit": "a" * 40,
        "structs": {name: {"kind": "struct", "size": 0, "alignment": 1, "members": []} for name in roots},
        "checksums": {"sourceEvidence": {"fixture": {"source": "src/save.c", "sha256": "0" * 64}}},
        "publishedBindings": {"flags": [{"symbol": "FLAG_X", "value": 7}]},
    }
    evidence = [{"path": path, "value": value} for path, value in abi_evidence_values(contract)]
    contract["purposeAbiEvidence"] = {purpose: copy.deepcopy(evidence) for purpose in ABI_PURPOSES}
    return contract


def scalar_paths(value, path="$", result=None):
    result = [] if result is None else result
    if isinstance(value, dict):
        for key, child in value.items():
            scalar_paths(child, f"{path}.{key}", result)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            scalar_paths(child, f"{path}[{index}]", result)
    else:
        result.append((path, value))
    return result


def set_path(value, path, replacement):
    tokens = []
    for part in path[2:].split(".") if path.startswith("$.") else []:
        while "[" in part:
            name, rest = part.split("[", 1)
            if name:
                tokens.append(name)
            index, part = rest.split("]", 1)
            tokens.append(int(index))
            part = part.removeprefix(".")
        if part:
            tokens.append(part)
    target = value
    for token in tokens[:-1]:
        target = target[token]
    target[tokens[-1]] = replacement


class SaveContractTests(unittest.TestCase):
    def test_arm_compile_defines_are_purpose_specific(self):
        expected = {
            "normal": {"-DTESTING=0"},
            "debug": {"-DTESTING=0", "-DDEBUG=1"},
            "release": {"-DTESTING=0", "-DRELEASE=1"},
            "test-runner": {"-DTESTING=1"},
            "headless-test": {"-DTESTING=1"},
        }
        for purpose, required in expected.items():
            defines = set(_purpose_defines(purpose))
            with self.subTest(purpose=purpose):
                self.assertTrue(required <= defines)
                self.assertEqual("-DDEBUG=1" in defines, purpose == "debug")
                self.assertEqual("-DRELEASE=1" in defines, purpose == "release")

    def test_purpose_budgets_are_contract_metadata_not_live_abi(self):
        expected = {"baselineCommit": "a" * 40, "purposeBudgets": {"flags": 12}, "physical": {"size": 1}}
        actual = {"physical": {"size": 1}}
        projected = {key: value for key, value in expected.items() if key not in CONTRACT_METADATA_KEYS}
        compare(projected, actual)

    def test_purpose_budget_schema_is_enforced(self):
        contract = minimal_contract()
        contract["purposeBudgets"] = {
                "schemaVersion": 1,
                "limits": {"romBytes": 33554432, "ewramBytes": 262144, "iwramBytes": 32768,
                           "releaseHeadroomBytes": 2708917},
                "baselines": {
                    name: {"artifact": f"{name}.elf", "romBytes": 1, "ewramBytes": 2, "iwramBytes": 3}
                    for name in ("normal", "debug", "release", "test-runner", "headless-test")
                },
            }
        validate_contract(contract)
        broken = copy.deepcopy(contract)
        broken["purposeBudgets"]["baselines"]["normal"]["romBytes"] = -1
        with self.assertRaisesRegex(ContractError, r"purposeBudgets\.baselines\.normal\.romBytes"):
            validate_contract(broken)

    def test_every_recorded_leaf_is_enforced(self):
        actual = {
            "structs": {"Save": {"size": 8, "members": [{"name": "field", "offset": 4}]}},
            "physical": {"sectorSize": 4096},
            "checksums": {"main": {"coverage": 3968}},
            "publishedBindings": {"flags": [{"symbol": "FLAG_X", "value": 7}]},
        }
        for path, leaf in scalar_paths(actual):
            changed = copy.deepcopy(actual)
            replacement = leaf + 1 if isinstance(leaf, int) else leaf + "_changed"
            set_path(changed, path, replacement)
            with self.subTest(path=path), self.assertRaisesRegex(ContractError, re.escape(path)):
                compare(actual, changed)

    def test_every_checked_contract_leaf_is_enforced(self):
        contract_path = Path(__file__).parents[2] / "integrity/save_contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        for path, leaf in scalar_paths(contract):
            replacement = leaf + 1 if isinstance(leaf, int) else leaf + "_changed"
            with self.subTest(path=path), self.assertRaisesRegex(ContractError, re.escape(path)):
                compare(leaf, replacement, path)

    def test_canonical_json_is_byte_identical(self):
        left = canonical_bytes({"z": 1, "a": [3, 2, 1]})
        right = canonical_bytes({"a": [3, 2, 1], "z": 1})
        self.assertEqual(left, right)

    def test_complete_linked_evidence_covers_private_nested_member(self):
        contract_path = Path(__file__).parents[2] / "integrity/save_contract.json"
        abi = json.loads(contract_path.read_text(encoding="utf-8"))
        original = render_abi_evidence(abi)
        changed = copy.deepcopy(abi)
        members = changed["structs"]["PlayerRecordEmerald"]["members"]
        daycare = next(member for member in members if member["name"] == "daycareMail")
        daycare["offset"] += 1
        mutated = render_abi_evidence(changed)
        self.assertNotEqual(original, mutated)
        path = "$.structs.PlayerRecordEmerald.members[5].offset"
        self.assertIn(path.encode(), original)
        self.assertEqual(len(abi_evidence_values(abi)), original.count(b"SAVE_ABI_VALUE("))

    def test_every_purpose_rejects_a_conditional_layout_mutation(self):
        contract = minimal_contract()
        base = {key: copy.deepcopy(value) for key, value in contract.items()
                if key not in CONTRACT_METADATA_KEYS}
        purpose_actuals = {}
        for index, purpose in enumerate(ABI_PURPOSES):
            actual = copy.deepcopy(base)
            actual["structs"]["SaveBlock1"]["size"] = index
            purpose_actuals[purpose] = actual
            contract["purposeAbiEvidence"][purpose] = [
                {"path": path, "value": value} for path, value in abi_evidence_values(actual)]
        validate_contract(contract)
        for purpose, actual in purpose_actuals.items():
            validate_abi(contract, actual, purpose)
            changed = copy.deepcopy(actual)
            changed["structs"]["SaveBlock1"]["size"] += 100
            with self.subTest(purpose=purpose), self.assertRaises(ContractError):
                validate_abi(contract, changed, purpose)

    def test_source_mechanics_mutation_changes_evidence(self):
        root = Path(__file__).parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            for relative in ("src/save.c", "src/pokemon.c", "src/battle_tower.c",
                             "src/recorded_battle.c", "src/ereader_helpers.c"):
                destination = tree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((root / relative).read_bytes())
            before = _source_evidence(tree)
            save = tree / "src/save.c"
            save.write_text(save.read_text().replace("u32 checksum = 0;", "u32 checksum = 0; /* mutation */", 1))
            after = _source_evidence(tree)
            self.assertNotEqual(before["CalculateChecksum"], after["CalculateChecksum"])

    def test_validate_budgets_enforces_limits_not_baseline_growth(self):
        contract = minimal_contract()
        purposes = ("normal", "debug", "release", "test-runner", "headless-test")
        artifacts = {
            "normal": "pokemon-openworld.gba", "debug": "pokemon-openworld-debug.gba",
            "release": "pokemon-openworld-release.gba", "test-runner": "pokemon-openworld-test.elf",
            "headless-test": "pokemon-openworld-test-headless.elf"}
        contract["purposeBudgets"] = {"schemaVersion": 1,
            "limits": {"romBytes": 33554432, "ewramBytes": 262144, "iwramBytes": 32768,
                       "releaseHeadroomBytes": 2708917},
            "baselines": {name: {"artifact": artifacts[name], "romBytes": 1, "ewramBytes": 1, "iwramBytes": 1}
                          for name in purposes}}
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            for name in purposes:
                usage = {"romBytes": 2, "ewramBytes": 2, "iwramBytes": 2}
                (reports / f"{name}.json").write_text(json.dumps(
                    {"purpose": name, "artifact": artifacts[name], "usage": usage}))
            validate_budgets(contract, reports)
            report = json.loads((reports / "debug.json").read_text())
            report["usage"]["ewramBytes"] = 262145
            (reports / "debug.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(ContractError, "debug ewramBytes exceeds"):
                validate_budgets(contract, reports)
            (reports / "unrelated.json").write_text("{}")
            with self.assertRaisesRegex(ContractError, "expected exactly"):
                validate_budgets(contract, reports)

    def test_seed_budgets_builds_only_exported_baseline_tree(self):
        baseline = "b" * 40
        seen_trees = []
        def fake_export(repo, revision, destination):
            self.assertEqual(revision, baseline)
            self.assertNotEqual(repo, destination)
            return baseline
        def fake_run(args, cwd, **kwargs):
            seen_trees.append(cwd)
            target = args[-1]
            if target.endswith("pokemon-openworld-test.elf"):
                (cwd / target).touch()
            return b""
        with mock.patch("tools.persistence.contract.export_baseline", side_effect=fake_export), \
             mock.patch("tools.persistence.contract._run", side_effect=fake_run), \
             mock.patch("tools.persistence.contract._measure_elf_capacity",
                        return_value={"romBytes": 10, "ewramBytes": 20, "iwramBytes": 30}):
            result = seed_budgets(Path("/dirty/task"), baseline, rom_max=100,
                                  ewram_max=200, iwram_max=300, release_headroom=40)
        self.assertEqual(set(result["baselines"]),
                         {"normal", "debug", "release", "test-runner", "headless-test"})
        self.assertTrue(seen_trees)
        self.assertTrue(all(tree != Path("/dirty/task") for tree in seen_trees))

    def test_export_uses_committed_object_not_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            header = repo / "include/global.h"
            header.parent.mkdir()
            header.write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            baseline = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            header.write_text("mutated task tree\n", encoding="utf-8")
            snapshot = Path(tmp) / "snapshot"
            snapshot.mkdir()
            self.assertEqual(export_baseline(repo, baseline, snapshot), baseline)
            self.assertEqual((snapshot / "include/global.h").read_text(encoding="utf-8"), "baseline\n")

    def test_seed_measurement_receives_archived_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "include").mkdir(); (repo / "include/global.h").write_text("baseline\n")
            anchor = repo / "tools/persistence/abi_anchor.c"; anchor.parent.mkdir(parents=True); anchor.write_text("anchor\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
            (repo / "include/global.h").write_text("mutated\n")
            def fake_measure(tree, purpose="normal"):
                measured = {key: copy.deepcopy(value) for key, value in minimal_contract().items()
                            if key not in CONTRACT_METADATA_KEYS and key != "purposeAbiEvidence"}
                measured["measuredHeader"] = (tree / "include/global.h").read_text()
                return measured
            with mock.patch("tools.persistence.contract.measure_tree", side_effect=fake_measure):
                result = seed_from_commit(repo, sha)
            self.assertEqual(result["measuredHeader"], "baseline\n")

    def test_contract_rejects_empty_binding_domain(self):
        contract = minimal_contract()
        contract["publishedBindings"] = {"flags": []}
        with self.assertRaisesRegex(ContractError, r"\$\.publishedBindings\.flags"):
            validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
