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
    NON_PERSISTENT_CONFIG_BINDINGS,
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
    _prepare_tree,
    _canonicalize_anonymous_layouts,
    _bindings,
    _parse_dwarf,
    DwarfLayouts,
)


def minimal_contract():
    roots = __import__("tools.persistence.contract", fromlist=["ROOT_TYPES"]).ROOT_TYPES
    contract = {
        "schemaVersion": 1,
        "target": "arm-none-eabi/armv4t/apcs-gnu",
        "baselineCommit": "a" * 40,
        "structs": {
            name: {"kind": "struct", "size": 0, "alignment": 1, "members": []}
            for name in roots
        },
        "checksums": {
            "sourceEvidence": {"fixture": {"source": "src/save.c", "sha256": "0" * 64}}
        },
        "physical": {},
        "publishedBindings": {
            domain: [{"symbol": f"{domain.upper()}_X", "value": 7}]
            for domain in (
                "trainerIds",
                "flags",
                "vars",
                "rewardState",
                "tradeState",
                "checkpoints",
                "destinations",
                "facilities",
                "savedLocations",
                "metLocations",
                "gameStats",
            )
        },
    }
    evidence = [
        {"path": path, "value": value} for path, value in abi_evidence_values(contract)
    ]
    contract["purposeAbiEvidence"] = {
        purpose: copy.deepcopy(evidence) for purpose in ABI_PURPOSES
    }
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
    def test_live_trainer_identities_do_not_rewrite_frozen_tombstone_evidence(self):
        bindings = _bindings(
            {
                "TRAINER_YOUNGSTER_BEN": 1,
                "TRAINER_FRLG_YOUNGSTER_BEN": 858,
                "TRAINER_YOUNGSTER_SAMUEL_JOHTO": 1481,
            }
        )
        self.assertIn(
            {"symbol": "TRAINER_YOUNGSTER_BEN", "value": 1},
            bindings["trainerIds"],
        )
        self.assertNotIn(
            {"symbol": "TRAINER_FRLG_YOUNGSTER_BEN", "value": 858},
            bindings["trainerIds"],
        )
        self.assertNotIn(
            {"symbol": "TRAINER_YOUNGSTER_SAMUEL_JOHTO", "value": 1481},
            bindings["trainerIds"],
        )

    @staticmethod
    def _saveblock_unit(*, leaf_size=1, bit_attribute=None, bit_value=0):
        member_attrs = {
            "DW_AT_name": "value",
            "DW_AT_type": "<0x40>",
            "DW_AT_data_member_location": "0",
        }
        if bit_attribute:
            member_attrs.update({"DW_AT_bit_size": "3", bit_attribute: str(bit_value)})
        return {
            0x10: {
                "offset": 0x10,
                "tag": "DW_TAG_structure_type",
                "attrs": {"DW_AT_name": "SaveBlock1", "DW_AT_byte_size": "1"},
                "children": [0x20],
            },
            0x20: {
                "offset": 0x20,
                "tag": "DW_TAG_member",
                "attrs": {
                    "DW_AT_name": "payload",
                    "DW_AT_type": "<0x30>",
                    "DW_AT_data_member_location": "0",
                },
                "children": [],
            },
            0x30: {
                "offset": 0x30,
                "tag": "DW_TAG_structure_type",
                "attrs": {"DW_AT_byte_size": "1"},
                "children": [0x35],
            },
            0x35: {
                "offset": 0x35,
                "tag": "DW_TAG_member",
                "attrs": member_attrs,
                "children": [],
            },
            0x40: {
                "offset": 0x40,
                "tag": "DW_TAG_base_type",
                "attrs": {
                    "DW_AT_name": "unsigned char",
                    "DW_AT_byte_size": str(leaf_size),
                    "DW_AT_encoding": "8",
                },
                "children": [],
            },
        }

    def test_duplicate_named_aggregate_is_cu_order_independent(self):
        first = self._saveblock_unit()
        second = self._saveblock_unit()
        with mock.patch("tools.persistence.contract.ROOT_TYPES", ("SaveBlock1",)):
            forward = DwarfLayouts([first, second]).collect()[0]
            reverse = DwarfLayouts([second, first]).collect()[0]
        self.assertEqual(canonical_bytes(forward), canonical_bytes(reverse))
        self.assertEqual(sum(name.startswith("anonymous::") for name in forward), 1)

    def test_duplicate_named_aggregate_conflict_is_fatal(self):
        first = self._saveblock_unit(leaf_size=1)
        second = self._saveblock_unit(leaf_size=2)
        with (
            mock.patch("tools.persistence.contract.ROOT_TYPES", ("SaveBlock1",)),
            self.assertRaisesRegex(ContractError, "disagrees across compilation units"),
        ):
            DwarfLayouts([first, second]).collect()

    def test_legacy_and_modern_bit_offsets_have_one_canonical_shape(self):
        modern = self._saveblock_unit(
            bit_attribute="DW_AT_data_bit_offset", bit_value=0
        )
        legacy = self._saveblock_unit(bit_attribute="DW_AT_bit_offset", bit_value=5)
        mutated = self._saveblock_unit(
            bit_attribute="DW_AT_data_bit_offset", bit_value=1
        )
        with mock.patch("tools.persistence.contract.ROOT_TYPES", ("SaveBlock1",)):
            modern_layout = DwarfLayouts([modern]).collect()[0]
            legacy_layout = DwarfLayouts([legacy]).collect()[0]
            mutated_layout = DwarfLayouts([mutated]).collect()[0]
        self.assertEqual(canonical_bytes(modern_layout), canonical_bytes(legacy_layout))
        member = next(
            layout["members"][0]
            for name, layout in modern_layout.items()
            if name.startswith("anonymous::")
        )
        self.assertEqual(member["bitOffset"], 0)
        self.assertNotEqual(
            canonical_bytes(modern_layout), canonical_bytes(mutated_layout)
        )

    def test_anonymous_layout_identity_ignores_all_dwarf_offsets_and_source_lines(self):
        def unit(offset_delta: int, line_delta: int):
            offsets = {
                "unit": 0x10 + offset_delta,
                "outer": 0x20 + offset_delta,
                "outer_member": 0x30 + offset_delta,
                "anonymous": 0x40 + offset_delta,
                "anonymous_member": 0x50 + offset_delta,
                "base": 0x60 + offset_delta,
            }
            text = f"""
 <0><{offsets["unit"]:x}>: Abbrev Number: 1 (DW_TAG_compile_unit)
    <{offsets["unit"] + 1:x}>   DW_AT_decl_line : {1 + line_delta}
 <1><{offsets["outer"]:x}>: Abbrev Number: 2 (DW_TAG_structure_type)
    <{offsets["outer"] + 1:x}>   DW_AT_name : Outer
    <{offsets["outer"] + 2:x}>   DW_AT_byte_size : 4
    <{offsets["outer"] + 3:x}>   DW_AT_decl_line : {10 + line_delta}
 <2><{offsets["outer_member"]:x}>: Abbrev Number: 3 (DW_TAG_member)
    <{offsets["outer_member"] + 1:x}>   DW_AT_name : payload
    <{offsets["outer_member"] + 2:x}>   DW_AT_type : <0x{offsets["anonymous"]:x}>
    <{offsets["outer_member"] + 3:x}>   DW_AT_data_member_location : 0
    <{offsets["outer_member"] + 4:x}>   DW_AT_decl_line : {11 + line_delta}
 <1><{offsets["anonymous"]:x}>: Abbrev Number: 4 (DW_TAG_structure_type)
    <{offsets["anonymous"] + 1:x}>   DW_AT_byte_size : 4
    <{offsets["anonymous"] + 2:x}>   DW_AT_decl_line : {20 + line_delta}
 <2><{offsets["anonymous_member"]:x}>: Abbrev Number: 3 (DW_TAG_member)
    <{offsets["anonymous_member"] + 1:x}>   DW_AT_name : value
    <{offsets["anonymous_member"] + 2:x}>   DW_AT_type : <0x{offsets["base"]:x}>
    <{offsets["anonymous_member"] + 3:x}>   DW_AT_data_member_location : 0
    <{offsets["anonymous_member"] + 4:x}>   DW_AT_decl_line : {21 + line_delta}
 <1><{offsets["base"]:x}>: Abbrev Number: 5 (DW_TAG_base_type)
    <{offsets["base"] + 1:x}>   DW_AT_name : unsigned int
    <{offsets["base"] + 2:x}>   DW_AT_byte_size : 4
    <{offsets["base"] + 3:x}>   DW_AT_encoding : 7 (unsigned)
"""
            return _parse_dwarf(text), offsets["outer"]

        def layout(*variants: tuple[int, int]):
            parsed = [unit(*variant) for variant in variants]
            layouts = DwarfLayouts([dies for dies, _ in parsed])
            for unit_index, (_, outer_offset) in enumerate(parsed):
                layouts._record(unit_index, outer_offset)
            return _canonicalize_anonymous_layouts(layouts.structs, ("Outer",))

        first = layout((0, 0))
        perturbed = layout((0x1000, 400))
        self.assertEqual(canonical_bytes(first), canonical_bytes(perturbed))
        self.assertEqual(
            canonical_bytes(first),
            canonical_bytes(layout((0, 0), (0x1000, 400))),
        )
        self.assertEqual(
            canonical_bytes(first),
            canonical_bytes(layout((0x1000, 400), (0, 0))),
        )
        anonymous = [name for name in first if name.startswith("anonymous::")]
        self.assertEqual(len(anonymous), 1)
        self.assertRegex(anonymous[0], r"^anonymous::[0-9a-f]{64}$")
        self.assertNotIn("anonymous@", canonical_bytes(first).decode())

    def test_anonymous_layout_identity_collision_is_fatal(self):
        structs = {
            "Outer": {
                "kind": "struct",
                "size": 4,
                "alignment": 4,
                "members": [
                    {
                        "name": "payload",
                        "offset": 0,
                        "type": {"kind": "struct", "name": "anonymous@0:10"},
                    }
                ],
            },
            "anonymous@0:10": {
                "kind": "struct",
                "size": 4,
                "alignment": 4,
                "members": [],
            },
        }
        canonical = next(
            name
            for name in _canonicalize_anonymous_layouts(
                copy.deepcopy(structs), ("Outer",)
            )
            if name.startswith("anonymous::")
        )
        structs[canonical] = {
            "kind": "struct",
            "size": 4,
            "alignment": 4,
            "members": [],
        }
        with self.assertRaisesRegex(ContractError, "collides with named layout"):
            _canonicalize_anonymous_layouts(structs, ("Outer",))

    def test_layout_graph_prunes_unrelated_and_pointer_target_types(self):
        structs = {
            "Outer": {
                "kind": "struct",
                "size": 8,
                "alignment": 4,
                "members": [
                    {
                        "name": "inline",
                        "offset": 0,
                        "type": {"kind": "struct", "name": "anonymous@0:10"},
                    },
                    {
                        "name": "pointer",
                        "offset": 4,
                        "type": {
                            "kind": "pointer",
                            "size": 4,
                            "target": {"kind": "struct", "name": "anonymous@0:20"},
                        },
                    },
                ],
            },
            "anonymous@0:10": {
                "kind": "struct",
                "size": 4,
                "alignment": 4,
                "members": [],
            },
            "anonymous@0:20": {
                "kind": "struct",
                "size": 4,
                "alignment": 4,
                "members": [],
            },
            "Unrelated": {
                "kind": "struct",
                "size": 4,
                "alignment": 4,
                "members": [],
            },
        }
        canonical = _canonicalize_anonymous_layouts(structs, ("Outer",))
        self.assertEqual(len(canonical), 2)
        self.assertIn("Outer", canonical)
        self.assertEqual(sum(name.startswith("anonymous::") for name in canonical), 1)
        pointer = canonical["Outer"]["members"][1]["type"]
        self.assertEqual(pointer["target"], {"kind": "void"})

    def test_shared_and_duplicated_anonymous_dies_are_identical(self):
        def graph(duplicate: bool):
            second = "anonymous@0:20" if duplicate else "anonymous@0:10"
            structs = {
                "Outer": {
                    "kind": "struct",
                    "size": 8,
                    "alignment": 4,
                    "members": [
                        {
                            "name": "first",
                            "offset": 0,
                            "type": {"kind": "struct", "name": "anonymous@0:10"},
                        },
                        {
                            "name": "second",
                            "offset": 4,
                            "type": {"kind": "struct", "name": second},
                        },
                    ],
                },
                "anonymous@0:10": {
                    "kind": "struct",
                    "size": 4,
                    "alignment": 4,
                    "members": [],
                },
            }
            if duplicate:
                structs["anonymous@0:20"] = copy.deepcopy(structs["anonymous@0:10"])
            return _canonicalize_anonymous_layouts(structs, ("Outer",))

        shared = graph(False)
        duplicated = graph(True)
        self.assertEqual(canonical_bytes(shared), canonical_bytes(duplicated))
        self.assertEqual(sum(name.startswith("anonymous::") for name in shared), 1)
        mutated = graph(False)
        anonymous = next(name for name in mutated if name.startswith("anonymous::"))
        mutated[anonymous]["size"] += 1
        self.assertNotEqual(canonical_bytes(shared), canonical_bytes(mutated))

    def test_readelf_form_presentations_canonicalize_names_and_encodings(self):
        def describe(name: str, size: str, encoding: str):
            die = {
                "offset": 1,
                "tag": "DW_TAG_base_type",
                "attrs": {
                    "DW_AT_name": name,
                    "DW_AT_byte_size": size,
                    "DW_AT_encoding": encoding,
                },
                "children": [],
            }
            return DwarfLayouts([{1: die}])._describe(0, 1)

        plain = describe("u8", "1", "8 (unsigned char)")
        annotated = describe("(string) u8", "(data1) 1", "(data1) 8\t(unsigned char)")
        indirect = describe(
            "(indirect string, offset: 0x12): u8",
            "(data1) 1",
            "(data1) 8 (unsigned char)",
        )
        nested_forms = describe(
            "(strp) (offset: 0x12): u8",
            "(data1) 1",
            "(data1) 8 (unsigned char)",
        )
        self.assertEqual(plain, annotated)
        self.assertEqual(plain, indirect)
        self.assertEqual(plain, nested_forms)
        self.assertEqual(plain, {"kind": "base", "size": 1, "encoding": 8})

    def test_scalar_typedef_wrappers_and_die_sharing_are_abi_transparent(self):
        def unit(size: int, encoding: int, form: str):
            dies = {
                0x10: {
                    "offset": 0x10,
                    "tag": "DW_TAG_structure_type",
                    "attrs": {
                        "DW_AT_name": "SaveBlock1",
                        "DW_AT_byte_size": str(size * 2),
                    },
                    "children": [0x20, 0x30],
                },
                0x20: {
                    "offset": 0x20,
                    "tag": "DW_TAG_member",
                    "attrs": {
                        "DW_AT_name": "first",
                        "DW_AT_data_member_location": "0",
                    },
                    "children": [],
                },
                0x30: {
                    "offset": 0x30,
                    "tag": "DW_TAG_member",
                    "attrs": {
                        "DW_AT_name": "second",
                        "DW_AT_data_member_location": str(size),
                    },
                    "children": [],
                },
            }

            def base(offset: int, spelling: str):
                dies[offset] = {
                    "offset": offset,
                    "tag": "DW_TAG_base_type",
                    "attrs": {
                        "DW_AT_name": spelling,
                        "DW_AT_byte_size": str(size),
                        "DW_AT_encoding": str(encoding),
                    },
                    "children": [],
                }

            def typedef(offset: int, name: str, target: int):
                dies[offset] = {
                    "offset": offset,
                    "tag": "DW_TAG_typedef",
                    "attrs": {"DW_AT_name": name, "DW_AT_type": f"<0x{target:x}>"},
                    "children": [],
                }

            if form == "direct":
                base(0x80, "producer scalar spelling")
                member_types = (0x80, 0x80)
            elif form == "public":
                base(0x80, "compiler base spelling")
                typedef(0x60, "PublicScalar", 0x80)
                member_types = (0x60, 0x60)
            elif form == "nested-shared":
                base(0x80, "__compiler_scalar")
                typedef(0x60, "__private_scalar_t", 0x80)
                typedef(0x50, "PublicScalar", 0x60)
                member_types = (0x50, 0x50)
            elif form == "nested-duplicated":
                base(0x80, "__compiler_scalar_a")
                typedef(0x60, "__private_scalar_a_t", 0x80)
                typedef(0x50, "PublicScalarA", 0x60)
                base(0x180, "__compiler_scalar_b")
                typedef(0x160, "__private_scalar_b_t", 0x180)
                typedef(0x150, "PublicScalarB", 0x160)
                member_types = (0x50, 0x150)
            else:
                self.fail(f"unknown scalar graph form: {form}")
            dies[0x20]["attrs"]["DW_AT_type"] = f"<0x{member_types[0]:x}>"
            dies[0x30]["attrs"]["DW_AT_type"] = f"<0x{member_types[1]:x}>"
            return dies

        forms = ("direct", "public", "nested-shared", "nested-duplicated")
        with mock.patch("tools.persistence.contract.ROOT_TYPES", ("SaveBlock1",)):
            for encoding in (5, 7):
                for size in (1, 2, 4, 8):
                    layouts = [
                        DwarfLayouts([unit(size, encoding, form)]).collect()[0]
                        for form in forms
                    ]
                    expected = canonical_bytes(layouts[0])
                    for form, layout in zip(forms[1:], layouts[1:]):
                        with self.subTest(size=size, encoding=encoding, form=form):
                            self.assertEqual(expected, canonical_bytes(layout))

                    frozen = minimal_contract()
                    frozen["structs"]["SaveBlock1"] = copy.deepcopy(
                        layouts[0]["SaveBlock1"]
                    )
                    evidence = [
                        {"path": path, "value": value}
                        for path, value in abi_evidence_values(frozen)
                    ]
                    frozen["purposeAbiEvidence"] = {
                        purpose: copy.deepcopy(evidence) for purpose in ABI_PURPOSES
                    }
                    for form, layout in zip(forms, layouts):
                        actual = {
                            key: copy.deepcopy(value)
                            for key, value in frozen.items()
                            if key not in CONTRACT_METADATA_KEYS
                        }
                        actual["structs"]["SaveBlock1"] = copy.deepcopy(
                            layout["SaveBlock1"]
                        )
                        for purpose in ABI_PURPOSES:
                            with self.subTest(
                                size=size,
                                encoding=encoding,
                                form=form,
                                purpose=purpose,
                            ):
                                validate_abi(frozen, actual, purpose)

                    changed_size = DwarfLayouts(
                        [unit(size + 1, encoding, "nested-shared")]
                    ).collect()[0]
                    changed_encoding = DwarfLayouts(
                        [unit(size, encoding + 1, "nested-shared")]
                    ).collect()[0]
                    self.assertNotEqual(expected, canonical_bytes(changed_size))
                    self.assertNotEqual(expected, canonical_bytes(changed_encoding))

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
        expected = {
            "baselineCommit": "a" * 40,
            "purposeBudgets": {"flags": 12},
            "physical": {"size": 1},
        }
        actual = {"physical": {"size": 1}}
        projected = {
            key: value
            for key, value in expected.items()
            if key not in CONTRACT_METADATA_KEYS
        }
        compare(projected, actual)

    def test_purpose_budget_schema_is_enforced(self):
        contract = minimal_contract()
        contract["purposeBudgets"] = {
            "schemaVersion": 1,
            "limits": {
                "romBytes": 33554432,
                "ewramBytes": 262144,
                "iwramBytes": 32768,
                "releaseHeadroomBytes": 2708917,
            },
            "baselines": {
                name: {
                    "artifact": f"{name}.elf",
                    "romBytes": 1,
                    "ewramBytes": 2,
                    "iwramBytes": 3,
                }
                for name in (
                    "normal",
                    "debug",
                    "release",
                    "test-runner",
                    "headless-test",
                )
            },
        }
        validate_contract(contract)
        broken = copy.deepcopy(contract)
        broken["purposeBudgets"]["baselines"]["normal"]["romBytes"] = -1
        with self.assertRaisesRegex(
            ContractError, r"purposeBudgets\.baselines\.normal\.romBytes"
        ):
            validate_contract(broken)

    def test_every_recorded_leaf_is_enforced(self):
        actual = {
            "structs": {
                "Save": {"size": 8, "members": [{"name": "field", "offset": 4}]}
            },
            "physical": {"sectorSize": 4096},
            "checksums": {"main": {"coverage": 3968}},
            "publishedBindings": {"flags": [{"symbol": "FLAG_X", "value": 7}]},
        }
        for path, leaf in scalar_paths(actual):
            changed = copy.deepcopy(actual)
            replacement = leaf + 1 if isinstance(leaf, int) else leaf + "_changed"
            set_path(changed, path, replacement)
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ContractError, re.escape(path)),
            ):
                compare(actual, changed)

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
        self.assertEqual(
            len(abi_evidence_values(abi)), original.count(b"SAVE_ABI_VALUE(")
        )

    def test_real_anonymous_nested_layout_mutation_changes_evidence(self):
        contract_path = Path(__file__).parents[2] / "integrity/save_contract.json"
        abi = json.loads(contract_path.read_text(encoding="utf-8"))
        anonymous = abi["structs"]["BoxPokemon"]["members"][18]["type"]["name"]
        self.assertTrue(anonymous.startswith("anonymous::"))
        before = render_abi_evidence(abi)
        changed = copy.deepcopy(abi)
        changed["structs"][anonymous]["members"][0]["offset"] += 1
        after = render_abi_evidence(changed)
        self.assertNotEqual(before, after)
        self.assertIn(f"$.structs.{anonymous}.members[0].offset".encode(), before)

    def test_known_sha32_offset_type_collision_is_rejected(self):
        contract = minimal_contract()
        first = {
            "name": "collision",
            "offset": 696,
            "type": {
                "kind": "array",
                "dimensions": [54, 2],
                "element": {"kind": "base", "size": 1, "encoding": 8},
            },
        }
        contract["structs"]["SaveBlock1"]["members"] = [first]
        expected = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(contract)
        ]
        contract["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(expected) for purpose in ABI_PURPOSES
        }
        actual = {
            key: copy.deepcopy(value)
            for key, value in contract.items()
            if key not in CONTRACT_METADATA_KEYS
        }
        actual["structs"]["SaveBlock1"]["members"][0]["offset"] = 1356

        self.assertIn(
            ("$.structs.SaveBlock1.members[0].offset", 696),
            abi_evidence_values(contract),
        )
        self.assertIn(
            ("$.structs.SaveBlock1.members[0].offset", 1356),
            abi_evidence_values(actual),
        )
        with self.assertRaises(ContractError):
            validate_abi(contract, actual, "normal")

    def test_every_type_leaf_and_member_offset_is_rejected(self):
        contract = minimal_contract()
        contract["structs"]["SaveBlock1"]["members"] = [
            {
                "name": "array",
                "offset": 4,
                "type": {
                    "kind": "array",
                    "dimensions": [3, 5],
                    "element": {"kind": "base", "size": 2, "encoding": 7},
                },
            },
            {
                "name": "enum",
                "offset": 8,
                "type": {"kind": "enum", "name": "Choice", "size": 4},
            },
            {
                "name": "pointer",
                "offset": 12,
                "type": {
                    "kind": "pointer",
                    "size": 4,
                    "target": {"kind": "void"},
                },
            },
        ]
        expected = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(contract)
        ]
        contract["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(expected) for purpose in ABI_PURPOSES
        }
        actual = {
            key: copy.deepcopy(value)
            for key, value in contract.items()
            if key not in CONTRACT_METADATA_KEYS
        }
        members = actual["structs"]["SaveBlock1"]["members"]
        mutations = [(member, "offset") for member in members] + [
            (members[0]["type"]["dimensions"], 0),
            (members[0]["type"]["dimensions"], 1),
            (members[0]["type"]["element"], "size"),
            (members[0]["type"]["element"], "encoding"),
            (members[1]["type"], "size"),
            (members[2]["type"], "size"),
        ]
        for target, field in mutations:
            original = target[field]
            target[field] = original + 1
            try:
                with self.subTest(field=field), self.assertRaises(ContractError):
                    validate_abi(contract, actual, "normal")
            finally:
                target[field] = original

    def test_real_scalar_leaf_mutations_are_rejected(self):
        contract_path = Path(__file__).parents[2] / "integrity/save_contract.json"
        frozen = json.loads(contract_path.read_text(encoding="utf-8"))
        normal_evidence = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(frozen)
        ]
        frozen["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(normal_evidence) for purpose in ABI_PURPOSES
        }
        actual = {
            key: copy.deepcopy(value)
            for key, value in frozen.items()
            if key not in CONTRACT_METADATA_KEYS
        }

        leaves = {}

        def find(desc):
            kind = desc.get("kind")
            if kind in ("base", "enum", "pointer"):
                leaves.setdefault(kind, desc)
            elif kind == "typedef":
                find(desc["target"])
            elif kind == "array":
                find(desc["element"])

        for layout in actual["structs"].values():
            for member in layout["members"]:
                find(member["type"])
        self.assertEqual(set(leaves), {"base", "enum", "pointer"})

        mutations = (
            ("base-size", leaves["base"], "size"),
            ("base-encoding", leaves["base"], "encoding"),
            ("enum-size", leaves["enum"], "size"),
            ("pointer-size", leaves["pointer"], "size"),
        )
        for mutation, leaf, field in mutations:
            original = leaf[field]
            leaf[field] = original + 1
            try:
                with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                    validate_abi(frozen, actual, "normal")
            finally:
                leaf[field] = original

    def test_real_modulo_collision_mutations_cannot_be_encoded(self):
        contract_path = Path(__file__).parents[2] / "integrity/save_contract.json"
        frozen = json.loads(contract_path.read_text(encoding="utf-8"))
        normal_evidence = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(frozen)
        ]
        frozen["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(normal_evidence) for purpose in ABI_PURPOSES
        }
        mutations = (
            ("SaveBlock1.size", ("SaveBlock1", None, "size"), -16761648),
            ("Apprentice.bitOffset", ("Apprentice", 0, "bitOffset"), -16777216),
        )
        for mutation, (layout_name, member_index, field), replacement in mutations:
            actual = {
                key: copy.deepcopy(value)
                for key, value in frozen.items()
                if key not in CONTRACT_METADATA_KEYS
            }
            target = actual["structs"][layout_name]
            if member_index is not None:
                target = target["members"][member_index]
            target[field] = replacement
            with (
                self.subTest(mutation=mutation, operation="render"),
                self.assertRaises(ContractError),
            ):
                render_abi_evidence(actual)
            with (
                self.subTest(mutation=mutation, operation="validate"),
                self.assertRaises(ContractError),
            ):
                validate_abi(frozen, actual, "normal")

    def test_retained_abi_fact_mutation_matrix_is_rejected(self):
        contract = minimal_contract()
        contract["structs"].update(
            {
                "Nested": {
                    "kind": "struct",
                    "size": 1,
                    "alignment": 1,
                    "members": [],
                },
                "ChoiceUnion": {
                    "kind": "union",
                    "size": 1,
                    "alignment": 1,
                    "members": [],
                },
            }
        )
        members = [
            {
                "name": "bits",
                "offset": 0,
                "bitOffset": 0,
                "bitSize": 1,
                "type": {"kind": "base", "size": 1, "encoding": 8},
            },
            {
                "name": "choices",
                "offset": 1,
                "type": {
                    "kind": "array",
                    "dimensions": [2, 3],
                    "element": {
                        "kind": "enum",
                        "name": "Choice",
                        "size": 2,
                    },
                },
            },
            {
                "name": "link",
                "offset": 8,
                "type": {
                    "kind": "pointer",
                    "size": 4,
                    "target": {"kind": "void"},
                },
            },
            {
                "name": "nested",
                "offset": 12,
                "type": {"kind": "struct", "name": "Nested"},
            },
            {
                "name": "variant",
                "offset": 13,
                "type": {"kind": "union", "name": "ChoiceUnion"},
            },
        ]
        save = contract["structs"]["SaveBlock1"]
        save.update({"size": 14, "alignment": 4, "members": members})
        expected = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(contract)
        ]
        contract["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(expected) for purpose in ABI_PURPOSES
        }

        def replace(path, value):
            def mutate(actual):
                set_path(actual, path, value)

            return mutate

        mutations = {
            "layout-kind": replace("$.structs.SaveBlock1.kind", "union"),
            "layout-size-negative": replace("$.structs.SaveBlock1.size", -1),
            "layout-size-too-large": replace("$.structs.SaveBlock1.size", 0x1000000),
            "alignment-negative": replace("$.structs.SaveBlock1.alignment", -1),
            "alignment-too-large": replace("$.structs.SaveBlock1.alignment", 0x100),
            "member-name": replace(
                "$.structs.SaveBlock1.members[0].name", "renamedBits"
            ),
            "offset-negative": replace("$.structs.SaveBlock1.members[0].offset", -1),
            "offset-too-large": replace(
                "$.structs.SaveBlock1.members[0].offset", 0x100000000
            ),
            "bit-offset-negative": replace(
                "$.structs.SaveBlock1.members[0].bitOffset", -1
            ),
            "bit-offset-too-large": replace(
                "$.structs.SaveBlock1.members[0].bitOffset", 0x1000000
            ),
            "bit-size-negative": replace("$.structs.SaveBlock1.members[0].bitSize", -1),
            "bit-size-too-large": replace(
                "$.structs.SaveBlock1.members[0].bitSize", 0x100
            ),
            "base-size-negative": replace(
                "$.structs.SaveBlock1.members[0].type.size", -1
            ),
            "base-size-too-large": replace(
                "$.structs.SaveBlock1.members[0].type.size", 0x10000
            ),
            "encoding-negative": replace(
                "$.structs.SaveBlock1.members[0].type.encoding", -1
            ),
            "encoding-too-large": replace(
                "$.structs.SaveBlock1.members[0].type.encoding", 0x10000
            ),
            "dimension-negative": replace(
                "$.structs.SaveBlock1.members[1].type.dimensions[0]", -1
            ),
            "dimension-too-large": replace(
                "$.structs.SaveBlock1.members[1].type.dimensions[0]", 0x100000000
            ),
            "cardinality-too-large": replace(
                "$.structs.SaveBlock1.members[1].type.dimensions[0]", 0x80000000
            ),
            "enum-name": replace(
                "$.structs.SaveBlock1.members[1].type.element.name", "OtherChoice"
            ),
            "enum-size-negative": replace(
                "$.structs.SaveBlock1.members[1].type.element.size", -1
            ),
            "enum-size-too-large": replace(
                "$.structs.SaveBlock1.members[1].type.element.size", 0x100000000
            ),
            "pointer-size-negative": replace(
                "$.structs.SaveBlock1.members[2].type.size", -1
            ),
            "pointer-size-too-large": replace(
                "$.structs.SaveBlock1.members[2].type.size", 0x100000000
            ),
            "pointer-target-kind": replace(
                "$.structs.SaveBlock1.members[2].type.target.kind", "function"
            ),
            "struct-name": replace(
                "$.structs.SaveBlock1.members[3].type.name", "ChoiceUnion"
            ),
            "union-name": replace(
                "$.structs.SaveBlock1.members[4].type.name", "Nested"
            ),
        }
        for mutation, mutate in mutations.items():
            actual = {
                key: copy.deepcopy(value)
                for key, value in contract.items()
                if key not in CONTRACT_METADATA_KEYS
            }
            mutate(actual)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_abi(contract, actual, "normal")

    def test_every_purpose_rejects_a_conditional_layout_mutation(self):
        contract = minimal_contract()
        base = {
            key: copy.deepcopy(value)
            for key, value in contract.items()
            if key not in CONTRACT_METADATA_KEYS
        }
        purpose_actuals = {}
        for index, purpose in enumerate(ABI_PURPOSES):
            actual = copy.deepcopy(base)
            actual["structs"]["SaveBlock1"]["size"] = index
            purpose_actuals[purpose] = actual
            contract["purposeAbiEvidence"][purpose] = [
                {"path": path, "value": value}
                for path, value in abi_evidence_values(actual)
            ]
        validate_contract(contract)
        for purpose, actual in purpose_actuals.items():
            validate_abi(contract, actual, purpose)
            changed = copy.deepcopy(actual)
            changed["structs"]["SaveBlock1"]["size"] += 100
            with self.subTest(purpose=purpose), self.assertRaises(ContractError):
                validate_abi(contract, changed, purpose)

    def test_live_schema_rejects_unexpected_keys_at_every_level(self):
        contract = self._schema_contract()

        def add(path, key):
            def mutate(actual):
                target = actual
                for token in path:
                    target = target[token]
                target[key] = 1

            return mutate

        descriptor_paths = self._schema_descriptor_paths()
        mutations = {
            "top-level": add((), "unexpected"),
            "layout": add(("structs", "SaveBlock1"), "unexpected"),
            "member": add(("structs", "SaveBlock1", "members", 0), "unexpected"),
            "binding-entry": add(("publishedBindings", "flags", 0), "unexpected"),
            **{
                f"{kind}-descriptor": add(path, "unexpected")
                for kind, path in descriptor_paths.items()
            },
        }
        self._assert_schema_mutations_fail(contract, mutations)

    def test_live_schema_rejects_deleted_required_keys(self):
        contract = self._schema_contract()

        def delete(path, key):
            def mutate(actual):
                target = actual
                for token in path:
                    target = target[token]
                del target[key]

            return mutate

        descriptor_paths = self._schema_descriptor_paths()
        required_by_kind = {
            "array": "dimensions",
            "base": "encoding",
            "enum": "size",
            "pointer": "target",
            "struct": "name",
            "union": "name",
            "void": "kind",
            "function": "kind",
        }
        mutations = {
            "top-level": delete((), "physical"),
            "layout": delete(("structs", "SaveBlock1"), "alignment"),
            "member": delete(("structs", "SaveBlock1", "members", 0), "offset"),
            "binding-domain": delete(("publishedBindings",), "flags"),
            "binding-entry": delete(("publishedBindings", "flags", 0), "value"),
            **{
                f"{kind}-descriptor": delete(path, required_by_kind[kind])
                for kind, path in descriptor_paths.items()
            },
        }
        self._assert_schema_mutations_fail(contract, mutations)

    def test_live_schema_rejects_malformed_values(self):
        contract = self._schema_contract()

        def replace(path, value):
            def mutate(actual):
                target = actual
                for token in path[:-1]:
                    target = target[token]
                target[path[-1]] = value

            return mutate

        base = ("structs", "SaveBlock1", "members")
        mutations = {
            "boolean-schema-version": replace(("schemaVersion",), True),
            "non-string-target": replace(("target",), 1),
            "non-mapping-structs": replace(("structs",), []),
            "negative-layout-size": replace(("structs", "SaveBlock1", "size"), -1),
            "non-list-members": replace(("structs", "SaveBlock1", "members"), {}),
            "non-string-member-name": replace((*base, 0, "name"), 1),
            "non-mapping-descriptor": replace((*base, 0, "type"), []),
            "non-string-kind": replace((*base, 0, "type", "kind"), []),
            "non-list-dimensions": replace((*base, 1, "type", "dimensions"), 2),
            "boolean-dimension": replace((*base, 1, "type", "dimensions", 0), True),
            "missing-graph-reference": replace((*base, 3, "type", "name"), "Missing"),
            "non-mapping-physical": replace(("physical",), []),
            "non-mapping-checksums": replace(("checksums",), []),
            "boolean-binding-value": replace(
                ("publishedBindings", "flags", 0, "value"), True
            ),
        }
        self._assert_schema_mutations_fail(contract, mutations)

    def test_published_binding_entries_are_exact(self):
        contract = minimal_contract()
        contract["publishedBindings"]["flags"] = [
            {"symbol": "FLAGS_X", "value": 7},
            {"symbol": "FLAGS_Y", "value": 9},
        ]
        mutations = {
            "value-drift": lambda entries: entries[0].update(value=8),
            "deleted-entry": lambda entries: entries.pop(),
            "added-entry": lambda entries: entries.append(
                {"symbol": "FLAGS_Z", "value": 11}
            ),
            "reordered-entries": lambda entries: entries.reverse(),
        }
        for mutation, mutate in mutations.items():
            actual = {
                key: copy.deepcopy(value)
                for key, value in contract.items()
                if key not in CONTRACT_METADATA_KEYS
            }
            mutate(actual["publishedBindings"]["flags"])
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_abi(contract, actual, "normal")

    @staticmethod
    def _schema_descriptor_paths():
        base = ("structs", "SaveBlock1", "members")
        return {
            "base": (*base, 0, "type"),
            "array": (*base, 1, "type"),
            "enum": (*base, 1, "type", "element"),
            "pointer": (*base, 2, "type"),
            "void": (*base, 2, "type", "target"),
            "struct": (*base, 3, "type"),
            "union": (*base, 4, "type"),
            "function": (*base, 5, "type"),
        }

    @staticmethod
    def _schema_contract():
        contract = minimal_contract()
        contract["structs"].update(
            {
                "Nested": {
                    "kind": "struct",
                    "size": 1,
                    "alignment": 1,
                    "members": [],
                },
                "ChoiceUnion": {
                    "kind": "union",
                    "size": 1,
                    "alignment": 1,
                    "members": [],
                },
            }
        )
        contract["structs"]["SaveBlock1"].update(
            {
                "size": 16,
                "alignment": 4,
                "members": [
                    {
                        "name": "scalar",
                        "offset": 0,
                        "type": {"kind": "base", "size": 1, "encoding": 8},
                    },
                    {
                        "name": "choices",
                        "offset": 1,
                        "type": {
                            "kind": "array",
                            "dimensions": [2],
                            "element": {"kind": "enum", "name": "Choice", "size": 2},
                        },
                    },
                    {
                        "name": "pointer",
                        "offset": 4,
                        "type": {
                            "kind": "pointer",
                            "size": 4,
                            "target": {"kind": "void"},
                        },
                    },
                    {
                        "name": "nested",
                        "offset": 8,
                        "type": {"kind": "struct", "name": "Nested"},
                    },
                    {
                        "name": "variant",
                        "offset": 9,
                        "type": {"kind": "union", "name": "ChoiceUnion"},
                    },
                    {
                        "name": "callback",
                        "offset": 12,
                        "type": {"kind": "function"},
                    },
                ],
            }
        )
        evidence = [
            {"path": path, "value": value}
            for path, value in abi_evidence_values(contract)
        ]
        contract["purposeAbiEvidence"] = {
            purpose: copy.deepcopy(evidence) for purpose in ABI_PURPOSES
        }
        return contract

    def _assert_schema_mutations_fail(self, contract, mutations):
        for mutation, mutate in mutations.items():
            actual = {
                key: copy.deepcopy(value)
                for key, value in contract.items()
                if key not in CONTRACT_METADATA_KEYS
            }
            mutate(actual)
            with self.subTest(mutation=mutation), self.assertRaises(ContractError):
                validate_abi(contract, actual, "normal")

    def test_source_mechanics_mutation_changes_evidence(self):
        root = Path(__file__).parents[3]
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            for relative in (
                "src/save.c",
                "src/pokemon.c",
                "src/battle_tower.c",
                "src/recorded_battle.c",
                "src/ereader_helpers.c",
            ):
                destination = tree / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((root / relative).read_bytes())
            before = _source_evidence(tree)
            save = tree / "src/save.c"
            save.write_text(
                save.read_text().replace(
                    "u32 checksum = 0;", "u32 checksum = 0; /* mutation */", 1
                )
            )
            after = _source_evidence(tree)
            self.assertNotEqual(before["CalculateChecksum"], after["CalculateChecksum"])

    def test_validate_budgets_enforces_limits_not_baseline_growth(self):
        contract = minimal_contract()
        purposes = ("normal", "debug", "release", "test-runner", "headless-test")
        artifacts = {
            "normal": "pokemon-openworld.gba",
            "debug": "pokemon-openworld-debug.gba",
            "release": "pokemon-openworld-release.gba",
            "test-runner": "pokemon-openworld-test.elf",
            "headless-test": "pokemon-openworld-test-headless.elf",
        }
        contract["purposeBudgets"] = {
            "schemaVersion": 1,
            "limits": {
                "romBytes": 33554432,
                "ewramBytes": 262144,
                "iwramBytes": 32768,
                "releaseHeadroomBytes": 2708917,
            },
            "baselines": {
                name: {
                    "artifact": artifacts[name],
                    "romBytes": 1,
                    "ewramBytes": 1,
                    "iwramBytes": 1,
                }
                for name in purposes
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            reports = Path(tmp)
            for name in purposes:
                usage = {"romBytes": 2, "ewramBytes": 2, "iwramBytes": 2}
                (reports / f"{name}.json").write_text(
                    json.dumps(
                        {"purpose": name, "artifact": artifacts[name], "usage": usage}
                    )
                )
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

        with (
            mock.patch(
                "tools.persistence.contract.export_baseline", side_effect=fake_export
            ),
            mock.patch("tools.persistence.contract._run", side_effect=fake_run),
            mock.patch(
                "tools.persistence.contract._measure_elf_capacity",
                return_value={"romBytes": 10, "ewramBytes": 20, "iwramBytes": 30},
            ),
        ):
            result = seed_budgets(
                Path("/dirty/task"),
                baseline,
                rom_max=100,
                ewram_max=200,
                iwram_max=300,
                release_headroom=40,
            )
        self.assertEqual(
            set(result["baselines"]),
            {"normal", "debug", "release", "test-runner", "headless-test"},
        )
        self.assertTrue(seen_trees)
        self.assertTrue(all(tree != Path("/dirty/task") for tree in seen_trees))

    def test_prepare_tree_publishes_map_root_before_aggregate_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            generated = tree / "build/generated/allregions/current"
            generation = generated.parent / ".generation-test"
            calls = []

            def fake_run(args, cwd, **kwargs):
                self.assertEqual(cwd, tree)
                calls.append(args)
                if args[-1].endswith("/.map-build-policy"):
                    generation.mkdir(parents=True)
                    (generation / ".map-build-policy").write_text("allregions\n")
                    generated.symlink_to(generation.name, target_is_directory=True)
                return b""

            with mock.patch("tools.persistence.contract._run", side_effect=fake_run):
                resolved = _prepare_tree(tree)

        self.assertEqual(resolved, generation)
        self.assertEqual(
            [args[-1] for args in calls],
            [
                "tools/mapjson",
                "build/generated/allregions/current/.map-build-policy",
                "generated",
            ],
        )

    def test_export_uses_committed_object_not_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            header = repo / "include/global.h"
            header.parent.mkdir()
            header.write_text("baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            baseline = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            header.write_text("mutated task tree\n", encoding="utf-8")
            snapshot = Path(tmp) / "snapshot"
            snapshot.mkdir()
            self.assertEqual(export_baseline(repo, baseline, snapshot), baseline)
            self.assertEqual(
                (snapshot / "include/global.h").read_text(encoding="utf-8"),
                "baseline\n",
            )

    def test_seed_measurement_receives_archived_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.invalid"],
                cwd=repo,
                check=True,
            )
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "include").mkdir()
            (repo / "include/global.h").write_text("baseline\n")
            anchor = repo / "tools/persistence/abi_anchor.c"
            anchor.parent.mkdir(parents=True)
            anchor.write_text("anchor\n")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=repo, check=True)
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip()
            (repo / "include/global.h").write_text("mutated\n")

            def fake_measure(tree, purpose="normal"):
                measured = {
                    key: copy.deepcopy(value)
                    for key, value in minimal_contract().items()
                    if key not in CONTRACT_METADATA_KEYS and key != "purposeAbiEvidence"
                }
                measured["measuredHeader"] = (tree / "include/global.h").read_text()
                return measured

            with mock.patch(
                "tools.persistence.contract.measure_tree", side_effect=fake_measure
            ):
                result = seed_from_commit(repo, sha)
            self.assertEqual(result["measuredHeader"], "baseline\n")

    def test_seed_rejects_purpose_specific_published_binding_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            anchor = repo / "tools/persistence/abi_anchor.c"
            anchor.parent.mkdir(parents=True)
            anchor.write_text("anchor\n")

            def fake_measure(_tree, purpose="normal"):
                measured = {
                    key: copy.deepcopy(value)
                    for key, value in minimal_contract().items()
                    if key not in CONTRACT_METADATA_KEYS and key != "purposeAbiEvidence"
                }
                if purpose == "debug":
                    measured["publishedBindings"]["flags"][0]["value"] += 1
                return measured

            with (
                mock.patch(
                    "tools.persistence.contract.export_baseline",
                    return_value="a" * 40,
                ),
                mock.patch(
                    "tools.persistence.contract.measure_tree", side_effect=fake_measure
                ),
                self.assertRaisesRegex(
                    ContractError, r"\$\.purposeInvariant\.debug\.publishedBindings"
                ),
            ):
                seed_from_commit(repo, "baseline")

    def test_debug_configuration_flags_are_not_published_bindings(self):
        normal = {
            "FLAG_REAL_SAVE_STATE": 7,
            "FLAG_DEBUG_NO_WILD_ENCOUNTERS": 0,
            "FLAG_DEBUG_NO_TRAINER_SIGHT": 0,
        }
        debug = {
            **normal,
            "FLAG_DEBUG_NO_WILD_ENCOUNTERS": 0x8FE,
            "FLAG_DEBUG_NO_TRAINER_SIGHT": 0x8FF,
        }
        self.assertEqual(_bindings(normal), _bindings(debug))
        symbols = {item["symbol"] for item in _bindings(debug)["flags"]}
        self.assertEqual(symbols, {"FLAG_REAL_SAVE_STATE"})

    def test_contract_rejects_debug_configuration_flags_as_persistent(self):
        for symbol in NON_PERSISTENT_CONFIG_BINDINGS:
            contract = minimal_contract()
            contract["publishedBindings"]["flags"].append(
                {"symbol": symbol, "value": 0}
            )
            contract["publishedBindings"]["flags"].sort(
                key=lambda item: (item["value"], item["symbol"])
            )
            with (
                self.subTest(symbol=symbol),
                self.assertRaisesRegex(ContractError, "compile-configuration control"),
            ):
                validate_contract(contract)

    def test_contract_rejects_empty_binding_domain(self):
        contract = minimal_contract()
        contract["publishedBindings"]["flags"] = []
        with self.assertRaisesRegex(ContractError, r"\$\.publishedBindings\.flags"):
            validate_contract(contract)


if __name__ == "__main__":
    unittest.main()
