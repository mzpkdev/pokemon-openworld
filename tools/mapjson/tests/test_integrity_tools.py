import copy
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.integrity.manifest import (
    EXPECTED_ABIS,
    EXPECTED_COUNTS,
    JOHTO_FORMAT_CLOSURE_MAPS,
    ManifestError,
    REVIEWED_CROSS_GEOGRAPHY_MAPS,
    validate_manifest,
)
from tools.integrity.validate_artifact import (
    ANIMATION_FRAME_SYMBOL_PREFIXES,
    ROM_BASE,
    ROM_LIMIT,
    ValidationError,
    expected_save_abi_values,
    enforce_purpose_usage,
    load_capacity_policy,
    parse_elf_sections,
    parse_elf_symbols,
    parse_symbol_records,
    validate_elf_linked_save_abi,
    validate_linked_save_abi,
    validate_linked_animation_contract,
    validate_group_slots,
    validate_layouts,
    validate_map_headers,
    validate_section_metadata,
    validate_surf_edge_exits,
    validate_surf_edge_route_profiles,
)


ROOT = Path(__file__).resolve().parents[3]
CAPACITY = ROOT / "tools/integrity/capacity_policy.json"
SAVE_CONTRACT = ROOT / "tools/integrity/save_contract.json"


class IntegrityToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)
        cls.tempdir = tempfile.TemporaryDirectory(prefix="integrity-tools-")
        cls.generated = Path(cls.tempdir.name) / "current"
        subprocess.run(
            [
                str(ROOT / "tools/mapjson/mapjson"),
                "generate",
                "allregions",
                str(ROOT / "data/maps/map_groups.json"),
                str(ROOT / "data/layouts/layouts.json"),
                str(cls.generated),
                *(
                    str(path)
                    for path in sorted((ROOT / "data/maps").glob("*/map.json"))
                ),
            ],
            cwd=ROOT,
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_manifest_rejects_count_drift(self) -> None:
        manifest = json.loads((self.generated / "integrity-manifest.json").read_text())
        manifest["counts"]["groupedMaps"] -= 1
        with self.assertRaisesRegex(ManifestError, "wrong registry counts"):
            validate_manifest(manifest)

    def manifest_with_surf_edge_exit(self):
        manifest = json.loads((self.generated / "integrity-manifest.json").read_text())
        source = manifest["maps"][0]
        layouts = {layout["id"]: layout for layout in manifest["layouts"]}
        target = next(
            entry
            for entry in manifest["maps"]
            if layouts[entry["layoutId"]]["width"] > 129
        )
        entry = {
            "sourceName": source["name"],
            "sourceId": source["id"],
            "sourceMapValue": source["number"] | (source["group"] << 8),
            "sourceGroup": source["group"],
            "sourceNumber": source["number"],
            "targetName": target["name"],
            "targetId": target["id"],
            "targetMapValue": target["number"] | (target["group"] << 8),
            "targetGroup": target["group"],
            "targetNumber": target["number"],
            "exitEdge": "east",
            "exitEdgeValue": 4,
            "targetFacing": "north",
            "targetFacingValue": 2,
            "targetX": 129,
            "targetY": 0,
        }
        manifest["edgeExits"] = [entry]
        manifest["counts"]["edgeExits"] = 1
        manifest["countSentinels"]["edgeExits"]["count"] = 1
        return manifest

    def test_manifest_validates_complete_surf_edge_exit_evidence(self) -> None:
        original = self.manifest_with_surf_edge_exit()
        validate_manifest(original)
        mutations = (
            (
                "extra field",
                lambda entry: entry.__setitem__("unexpected", 0),
                "invalid fields",
            ),
            (
                "boolean coordinate",
                lambda entry: entry.__setitem__("targetX", True),
                "invalid field types",
            ),
            (
                "direction encoding",
                lambda entry: entry.__setitem__("exitEdgeValue", 3),
                "name/value disagree",
            ),
            (
                "source identity",
                lambda entry: entry.__setitem__("sourceMapValue", 0xFFFF),
                "source map identity disagrees",
            ),
            (
                "target bounds",
                lambda entry: entry.__setitem__("targetX", 32767),
                "outside its layout",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                manifest = copy.deepcopy(original)
                mutate(manifest["edgeExits"][0])
                with self.assertRaisesRegex(ManifestError, message):
                    validate_manifest(manifest)

        duplicate = copy.deepcopy(original)
        duplicate["edgeExits"].append(copy.deepcopy(duplicate["edgeExits"][0]))
        duplicate["counts"]["edgeExits"] = 2
        duplicate["countSentinels"]["edgeExits"]["count"] = 2
        with self.assertRaisesRegex(ManifestError, "unique source edge"):
            validate_manifest(duplicate)

        noncanonical = copy.deepcopy(original)
        second = copy.deepcopy(noncanonical["edgeExits"][0])
        second_source = noncanonical["maps"][1]
        second.update(
            {
                "sourceName": second_source["name"],
                "sourceId": second_source["id"],
                "sourceMapValue": second_source["number"]
                | (second_source["group"] << 8),
                "sourceGroup": second_source["group"],
                "sourceNumber": second_source["number"],
            }
        )
        noncanonical["edgeExits"] = [second, noncanonical["edgeExits"][0]]
        noncanonical["counts"]["edgeExits"] = 2
        noncanonical["countSentinels"]["edgeExits"]["count"] = 2
        with self.assertRaisesRegex(ManifestError, "canonical order"):
            validate_manifest(noncanonical)

        count_mismatch = copy.deepcopy(original)
        count_mismatch["counts"]["edgeExits"] = 0
        count_mismatch["countSentinels"]["edgeExits"]["count"] = 0
        with self.assertRaisesRegex(ManifestError, "count sentinel"):
            validate_manifest(count_mismatch)

    def test_manifest_keeps_format_closure_distinct_from_geography(self) -> None:
        self.assertEqual(len(JOHTO_FORMAT_CLOSURE_MAPS), 254)
        self.assertEqual(
            REVIEWED_CROSS_GEOGRAPHY_MAPS,
            {"VermilionCity_PortInside": "REGION_KANTO"},
        )
        self.assertEqual(
            EXPECTED_COUNTS["regions"],
            {"REGION_HOENN": 518, "REGION_KANTO": 422, "REGION_JOHTO": 253},
        )
        self.assertEqual(sum(EXPECTED_COUNTS["regions"].values()), 1193)

    def test_manifest_rejects_missing_reviewed_animation_callback(self) -> None:
        manifest = json.loads((self.generated / "integrity-manifest.json").read_text())
        tileset = next(
            item
            for item in manifest["tilesets"]
            if item["name"] == "gTileset_NationalPark"
        )
        tileset["callback"] = None
        tileset["allowNullCallback"] = True
        with self.assertRaisesRegex(ManifestError, "reviewed animation callback"):
            validate_manifest(manifest)

    def test_linked_animation_evidence_rejects_missing_or_missized_symbols(
        self,
    ) -> None:
        policy_path = ROOT / "tools/content_port/ports/johto/animation_policy.json"
        policy = json.loads(policy_path.read_text())
        symbols = {
            schedule["callback"]: (0x08000100 + index * 4, 4)
            for index, schedule in enumerate(policy["schedules"])
        }
        for frame_set in policy["frameSets"]:
            if not frame_set["requiredFrames"]:
                continue
            prefix = ANIMATION_FRAME_SYMBOL_PREFIXES[frame_set["id"]]
            for frame in frame_set["requiredFrames"]:
                symbols[f"{prefix}{frame}"] = (
                    0x08001000 + len(symbols) * 4,
                    frame_set["sourceTilesPerFrame"] * 32,
                )
        report = validate_linked_animation_contract(symbols, policy_path)
        self.assertEqual(report["frames"], 111)
        self.assertLess(
            report["queue"]["peakEntries"], report["queue"]["capacityEntries"]
        )

        mutations = []
        without_callback = copy.deepcopy(symbols)
        without_callback.pop("InitTilesetAnim_NationalPark")
        mutations.append((without_callback, "symbol is missing"))
        without_frame = copy.deepcopy(symbols)
        without_frame.pop("sTilesetAnims_JohtoGeneral_Flower0")
        mutations.append((without_frame, "symbol is missing"))
        missized_frame = copy.deepcopy(symbols)
        address, size = missized_frame["sTilesetAnims_JohtoGeneral_Flower0"]
        missized_frame["sTilesetAnims_JohtoGeneral_Flower0"] = (address, size - 1)
        mutations.append((missized_frame, "bytes, expected"))
        for owner in (
            "InitTilesetAnim_NationalPark",
            "sTilesetAnims_JohtoGeneral_Flower0",
        ):
            _, size = symbols[owner]
            for label, address in (
                ("zero", 0),
                ("below ROM", ROM_BASE - 1),
                ("above ROM", ROM_BASE + ROM_LIMIT),
                (
                    "extent overflow",
                    ROM_BASE
                    + ROM_LIMIT
                    - size
                    + (2 if owner.startswith("InitTilesetAnim_") else 1),
                ),
            ):
                mutation = copy.deepcopy(symbols)
                mutation[owner] = (address, size)
                mutations.append((mutation, "outside ROM"))
        for mutation, message in mutations:
            with (
                self.subTest(message=message),
                self.assertRaisesRegex(ValidationError, message),
            ):
                validate_linked_animation_contract(mutation, policy_path)

        overflow = copy.deepcopy(policy)
        for schedule in overflow["schedules"]:
            schedule["transfers"] *= 11
        with tempfile.TemporaryDirectory(prefix="animation-overflow-") as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(overflow))
            with self.assertRaisesRegex(ValidationError, "exceeds capacity"):
                validate_linked_animation_contract(symbols, path)

    def test_sym_records_are_augmented_from_sibling_elf(self) -> None:
        with tempfile.TemporaryDirectory(prefix="linked-symbols-") as directory:
            sym = Path(directory) / "product.sym"
            sym.write_text("08000100 g 00000004 Existing\n")
            sym.with_suffix(".elf").touch()
            metadata = "   1: 08000200    32 OBJECT  GLOBAL HIDDEN     8 HiddenFrame\n"
            completed = subprocess.CompletedProcess(
                ["arm-none-eabi-readelf"], 0, stdout=metadata, stderr=""
            )
            with mock.patch("subprocess.run", return_value=completed) as run:
                records = parse_symbol_records(sym)
            self.assertEqual(records["Existing"], (0x08000100, 4))
            self.assertEqual(records["HiddenFrame"], (0x08000200, 32))
            run.assert_called_once_with(
                ["arm-none-eabi-readelf", "-Ws", str(sym.with_suffix(".elf"))],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

    def test_manifest_binds_section_identity_and_group_content_region(self) -> None:
        original = json.loads((self.generated / "integrity-manifest.json").read_text())
        validate_manifest(original)
        cross_region_maps = [
            entry["name"]
            for entry in original["maps"]
            if entry["region"]
            != original["mapSectionMetadata"][entry["regionMapSectionValue"]]["region"]
        ]
        self.assertEqual(
            cross_region_maps,
            [
                "BattleColosseum_2P_Frlg",
                "TradeCenter_Frlg",
                "RecordCorner_Frlg",
                "BattleColosseum_4P_Frlg",
                "UnionRoom_Frlg",
            ],
        )
        vermilion_drift = copy.deepcopy(original)
        vermilion = next(
            entry
            for entry in vermilion_drift["maps"]
            if entry["name"] == "VermilionCity_PortInside"
        )
        self.assertEqual(vermilion["region"], "REGION_KANTO")
        vermilion["region"] = "REGION_JOHTO"
        with self.assertRaisesRegex(
            ManifestError,
            "VermilionCity_PortInside.*disagrees.*REGION_KANTO",
        ):
            validate_manifest(vermilion_drift)
        mutations = (
            (
                "unknown name",
                lambda manifest: manifest["maps"][0].__setitem__(
                    "regionMapSection", "MAPSEC_DOES_NOT_EXIST"
                ),
                "names unknown map section",
            ),
            (
                "mismatched value",
                lambda manifest: manifest["maps"][0].__setitem__(
                    "regionMapSectionValue",
                    (manifest["maps"][0]["regionMapSectionValue"] + 1)
                    % len(manifest["mapSectionMetadata"]),
                ),
                "map-section name/value disagree",
            ),
            (
                "mismatched region",
                lambda manifest: manifest["maps"][0].__setitem__(
                    "region", "REGION_JOHTO"
                ),
                "region .* disagrees",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                manifest = copy.deepcopy(original)
                mutate(manifest)
                with self.assertRaisesRegex(ManifestError, message):
                    validate_manifest(manifest)

    def test_capacity_policy_rejects_bad_arithmetic_and_malformed_evidence_digest(
        self,
    ) -> None:
        policy = json.loads(CAPACITY.read_text())
        mutations = []
        wrong_headroom = copy.deepcopy(policy)
        wrong_headroom["requiredHeadroomBytes"] -= 1
        mutations.append(wrong_headroom)
        wrong_digest = copy.deepcopy(policy)
        wrong_digest["evidenceDigest"] = "0" * 63
        mutations.append(wrong_digest)

        with tempfile.TemporaryDirectory(prefix="capacity-policy-") as directory:
            for index, mutation in enumerate(mutations):
                path = Path(directory) / f"invalid-{index}.json"
                path.write_text(json.dumps(mutation))
                with self.subTest(index=index), self.assertRaises(ValidationError):
                    load_capacity_policy(path)

    def test_linked_save_abi_is_checked_value_by_value(self) -> None:
        contract = json.loads(SAVE_CONTRACT.read_text())
        expected = expected_save_abi_values(contract, "normal")
        by_path = dict(expected)
        self.assertEqual(
            by_path["$.structs.SaveBlock1.sizeAlignment"], (15736 << 8) | 4
        )
        self.assertEqual(
            by_path["$.structs.SaveBlock1.members[84].type.array.dimensions[0]"],
            103,
        )
        rom = bytearray(8 + len(expected) * 4)
        struct.pack_into("<II", rom, 0, 0x53414249, 1)
        struct.pack_into(
            f"<{len(expected)}I", rom, 8, *(value for _, value in expected)
        )
        evidence = validate_linked_save_abi(
            rom, {"gSaveAbiEvidence": ROM_BASE}, contract, "normal"
        )
        self.assertEqual(evidence["valueCount"], len(expected))
        rom[-1] ^= 1
        with self.assertRaisesRegex(ValidationError, "linked save ABI drift"):
            validate_linked_save_abi(
                rom, {"gSaveAbiEvidence": ROM_BASE}, contract, "normal"
            )

        nested_drift = copy.deepcopy(contract)
        nested_drift["structs"]["PlayerRecordEmerald"]["members"][3]["offset"] += 4
        with self.assertRaisesRegex(
            ValidationError, r"PlayerRecordEmerald\.members\[3\]\.offset"
        ):
            validate_linked_save_abi(
                bytearray(rom[:-1]) + bytes([rom[-1] ^ 1]),
                {"gSaveAbiEvidence": ROM_BASE},
                nested_drift,
                "normal",
            )

    def test_linked_save_abi_rejects_unreviewed_tail_extension(self) -> None:
        contract = json.loads(SAVE_CONTRACT.read_text())
        contract["compatibleTailExtension"]["currentBitmapBytes"] = 104

        with self.assertRaisesRegex(ValidationError, "unsupported evolution"):
            expected_save_abi_values(contract, "normal")

    def surf_edge_exit_fixture(self):
        rom = bytearray(0x60)
        symbols = {
            "gSurfEdgeExits": ROM_BASE,
            "gSurfEdgeExitCount": ROM_BASE + 0x40,
        }
        struct.pack_into("<HHhhBB", rom, 0, 0x0102, 0x0304, 129, 5, 4, 2)
        struct.pack_into("<H", rom, 0x40, 1)
        manifest = {
            "abis": {"surfEdgeExit": EXPECTED_ABIS["surfEdgeExit"]},
            "countSentinels": {
                "edgeExits": {
                    "registry": "gSurfEdgeExits",
                    "countSymbol": "gSurfEdgeExitCount",
                    "count": 1,
                }
            },
            "edgeExits": [
                {
                    "sourceMapValue": 0x0102,
                    "targetMapValue": 0x0304,
                    "targetX": 129,
                    "targetY": 5,
                    "exitEdgeValue": 4,
                    "targetFacingValue": 2,
                }
            ],
        }
        return rom, manifest, symbols

    def test_linked_surf_edge_exit_decodes_signed_16_bit_coordinates(self) -> None:
        rom, manifest, symbols = self.surf_edge_exit_fixture()
        report = validate_surf_edge_exits(rom, manifest, symbols, ROM_BASE + len(rom))
        self.assertEqual(report, {"count": 1, "bytes": 10})

        mutations = (
            (0, 0xFF, "sourceMapValue"),
            (2, 0xFF, "targetMapValue"),
            (4, 0xFF, "targetX"),
            (6, 0xFF, "targetY"),
            (8, 0x03, "exitEdgeValue"),
            (9, 0x04, "targetFacingValue"),
        )
        for offset, value, message in mutations:
            with self.subTest(message=message):
                changed = bytearray(rom)
                changed[offset] = value
                with self.assertRaisesRegex(ValidationError, message):
                    validate_surf_edge_exits(
                        changed, manifest, symbols, ROM_BASE + len(changed)
                    )

    def test_linked_surf_edge_exit_rejects_count_alignment_and_truncation(self) -> None:
        rom, manifest, symbols = self.surf_edge_exit_fixture()
        wrong_count = bytearray(rom)
        struct.pack_into("<H", wrong_count, 0x40, 2)
        with self.assertRaisesRegex(ValidationError, "count is 2, expected 1"):
            validate_surf_edge_exits(
                wrong_count, manifest, symbols, ROM_BASE + len(wrong_count)
            )

        for symbol, message in (
            ("gSurfEdgeExits", "registry violates ABI alignment"),
            ("gSurfEdgeExitCount", "count violates u16 alignment"),
        ):
            with self.subTest(symbol=symbol):
                misaligned = dict(symbols)
                misaligned[symbol] += 1
                with self.assertRaisesRegex(ValidationError, message):
                    validate_surf_edge_exits(
                        rom, manifest, misaligned, ROM_BASE + len(rom)
                    )

        with self.assertRaisesRegex(ValidationError, "registry is truncated"):
            truncated_symbols = dict(symbols)
            truncated_symbols["gSurfEdgeExits"] = ROM_BASE + len(rom) - 8
            validate_surf_edge_exits(
                rom, manifest, truncated_symbols, ROM_BASE + len(rom)
            )

    def test_linked_empty_surf_edge_exit_requires_ten_zero_bytes(self) -> None:
        rom, manifest, symbols = self.surf_edge_exit_fixture()
        manifest["edgeExits"] = []
        manifest["countSentinels"]["edgeExits"]["count"] = 0
        struct.pack_into("<H", rom, 0x40, 0)
        rom[:10] = bytes(10)
        self.assertEqual(
            validate_surf_edge_exits(rom, manifest, symbols, ROM_BASE + len(rom)),
            {"count": 0, "bytes": 10},
        )
        rom[9] = 1
        with self.assertRaisesRegex(ValidationError, "not zero-filled"):
            validate_surf_edge_exits(rom, manifest, symbols, ROM_BASE + len(rom))

    def test_linked_surf_edge_route_profiles_decode_and_require_zero_sentinel(self) -> None:
        rom = bytearray(0x60)
        symbols = {
            "gSurfEdgeRouteProfiles": ROM_BASE,
            "gSurfEdgeRouteProfileCount": ROM_BASE + 0x40,
        }
        struct.pack_into("<HBB", rom, 0, 0x0102, 4, 1)
        struct.pack_into("<H", rom, 0x40, 1)
        manifest = {
            "abis": {"surfEdgeRouteProfile": EXPECTED_ABIS["surfEdgeRouteProfile"]},
            "countSentinels": {
                "edgeRouteProfiles": {
                    "registry": "gSurfEdgeRouteProfiles",
                    "countSymbol": "gSurfEdgeRouteProfileCount",
                    "count": 1,
                }
            },
            "edgeRouteProfiles": [
                {"sourceMapValue": 0x0102, "exitEdgeValue": 4, "profileValue": 1}
            ],
        }
        self.assertEqual(
            validate_surf_edge_route_profiles(rom, manifest, symbols, ROM_BASE + len(rom)),
            {"count": 1, "bytes": 4},
        )
        rom[3] = 0
        with self.assertRaisesRegex(ValidationError, "profileValue"):
            validate_surf_edge_route_profiles(rom, manifest, symbols, ROM_BASE + len(rom))

        manifest["edgeRouteProfiles"] = []
        manifest["countSentinels"]["edgeRouteProfiles"]["count"] = 0
        struct.pack_into("<H", rom, 0x40, 0)
        rom[:4] = bytes(4)
        self.assertEqual(
            validate_surf_edge_route_profiles(rom, manifest, symbols, ROM_BASE + len(rom)),
            {"count": 0, "bytes": 4},
        )
        rom[3] = 1
        with self.assertRaisesRegex(ValidationError, "not zero-filled"):
            validate_surf_edge_route_profiles(rom, manifest, symbols, ROM_BASE + len(rom))

    def test_purpose_conditional_save_abi_drift_is_rejected(self) -> None:
        contract = json.loads(SAVE_CONTRACT.read_text())
        normal = expected_save_abi_values(contract, "normal")
        for purpose in ("debug", "release", "test-runner", "headless-test"):
            expected = expected_save_abi_values(contract, purpose)
            rom = bytearray(8 + len(normal) * 4)
            struct.pack_into("<II", rom, 0, 0x53414249, 1)
            struct.pack_into(
                f"<{len(normal)}I", rom, 8, *(value for _, value in normal)
            )
            if expected == normal:
                evidence = validate_linked_save_abi(
                    rom, {"gSaveAbiEvidence": ROM_BASE}, contract, purpose
                )
                self.assertEqual(evidence["valueCount"], len(expected))
            else:
                with self.assertRaisesRegex(
                    ValidationError, "linked save ABI (drift|evidence size)"
                ):
                    validate_linked_save_abi(
                        rom, {"gSaveAbiEvidence": ROM_BASE}, contract, purpose
                    )

        # A layout fact that changes under a purpose-only compiler define must
        # be compared with that purpose's frozen evidence, never normal's.
        conditional_drift = copy.deepcopy(contract)
        conditional_drift["purposeAbiEvidence"]["debug"][0]["value"] ^= 1
        with self.assertRaisesRegex(ValidationError, "linked save ABI drift"):
            validate_linked_save_abi(
                rom, {"gSaveAbiEvidence": ROM_BASE}, conditional_drift, "debug"
            )

    def test_elf_save_abi_evidence_is_checked_value_by_value(self) -> None:
        contract = json.loads(SAVE_CONTRACT.read_text())
        purpose = "test-runner"
        expected = expected_save_abi_values(contract, purpose)
        evidence = struct.pack(
            f"<II{len(expected)}I",
            0x53414249,
            1,
            *(value for _, value in expected),
        )
        address = ROM_BASE + 0x20
        section = {
            "name": ".text",
            "type": "PROGBITS",
            "address": ROM_BASE,
            "offset": 0x100,
            "size": 0x20 + len(evidence),
            "flags": "AX",
        }
        with tempfile.TemporaryDirectory(prefix="elf-save-abi-") as directory:
            path = Path(directory) / "test.elf"
            path.write_bytes(bytes(0x120) + evidence)
            symbols = {"gSaveAbiEvidence": (address, len(evidence))}
            result = validate_elf_linked_save_abi(
                path, [section], symbols, contract, purpose
            )
            self.assertEqual(result["valueCount"], len(expected))
            data = bytearray(path.read_bytes())
            data[-1] ^= 1
            path.write_bytes(data)
            with self.assertRaisesRegex(ValidationError, "linked save ABI drift"):
                validate_elf_linked_save_abi(
                    path, [section], symbols, contract, purpose
                )

    def test_elf_symbols_accept_decimal_and_hexadecimal_sizes(self) -> None:
        symbols = parse_elf_symbols(
            "   112: 08000100   132 OBJECT  GLOBAL DEFAULT   10 gDecimalEvidence\n"
            "404007: 08d4f010 0x2076c OBJECT  GLOBAL DEFAULT   10 gSaveAbiEvidence\n"
            "404008: 08d6f77c 0X20 OBJECT  LOCAL  HIDDEN    10 gUpperHexSize\n"
        )
        self.assertEqual(symbols["gDecimalEvidence"], (0x08000100, 132))
        self.assertEqual(symbols["gSaveAbiEvidence"], (0x08D4F010, 0x2076C))
        self.assertEqual(symbols["gUpperHexSize"], (0x08D6F77C, 0x20))

    def test_elf_symbols_reject_malformed_or_out_of_range_fields(self) -> None:
        symbols = parse_elf_symbols(
            "1: 08000100 -1 OBJECT GLOBAL DEFAULT 10 gNegativeSize\n"
            "2: 08000100 0x20z OBJECT GLOBAL DEFAULT 10 gMalformedSize\n"
            "3: 08000100 0x100000000 OBJECT GLOBAL DEFAULT 10 gOverflowSize\n"
            "4: 100000000 32 OBJECT GLOBAL DEFAULT 10 gOverflowAddress\n"
            "5: 08000100 32 OBJECT GLOBAL DEFAULT 10 extra gUnexpectedField\n"
            "6: 08000100 32 OBJECT GLOBAL DEFAULT 10 gValidSymbol\n"
            "7: 08000100 4294967296 OBJECT GLOBAL DEFAULT 10 gDecimalOverflow\n"
        )
        self.assertEqual(symbols, {"gValidSymbol": (0x08000100, 32)})

    def test_elf_sections_and_five_purpose_hardware_budgets(self) -> None:
        sections = parse_elf_sections(
            "  [ 1] .text PROGBITS 08000000 001000 000100 00  AX  0 0 4\n"
            "  [ 2] .ewram PROGBITS 02000000 001100 000020 00  WA  0 0 4\n"
            "  [ 3] .ewram.sbss NOBITS 02000020 001120 000010 00  WA  0 0 4\n"
            "  [ 4] .iwram PROGBITS 03000000 001130 000020 00  WA  0 0 4\n"
            "  [ 5] .iwram.bss NOBITS 03000020 001150 000010 00  WA  0 0 4\n"
        )
        self.assertEqual(
            [section["name"] for section in sections],
            [".text", ".ewram", ".ewram.sbss", ".iwram", ".iwram.bss"],
        )
        contract = json.loads(SAVE_CONTRACT.read_text())
        for purpose in ("normal", "debug", "release", "test-runner", "headless-test"):
            usage = {"romBytes": 1, "ewramBytes": 1, "iwramBytes": 1}
            self.assertEqual(
                enforce_purpose_usage(purpose, usage, contract)["purpose"], purpose
            )
            with self.assertRaisesRegex(ValidationError, "outside budget"):
                enforce_purpose_usage(
                    purpose,
                    {"romBytes": 33554433, "ewramBytes": 1, "iwramBytes": 1},
                    contract,
                )

    def test_wrong_map_slot_is_rejected_even_when_pointer_is_in_rom(self) -> None:
        rom = bytearray(0x100)
        symbols = {
            "gMapGroups": ROM_BASE,
            "gMapGroup_Test": ROM_BASE + 0x20,
            "PetalburgCity": ROM_BASE + 0x40,
            "WrongMap": ROM_BASE + 0x60,
        }
        struct.pack_into("<I", rom, 0, symbols["gMapGroup_Test"])
        struct.pack_into("<I", rom, 0x20, symbols["WrongMap"])
        manifest = {
            "groups": [{"name": "gMapGroup_Test", "number": 0, "mapCount": 1}],
            "maps": [
                {"name": "PetalburgCity", "group": 0, "number": 0},
            ],
        }
        with self.assertRaisesRegex(ValidationError, "expected PetalburgCity"):
            validate_group_slots(rom, manifest, symbols, ROM_BASE + len(rom))

    def test_zeroed_petalburg_primary_tileset_is_rejected(self) -> None:
        rom = bytearray(0x100)
        symbols = {
            "gMapLayouts": ROM_BASE,
            "PetalburgCity_Layout": ROM_BASE + 0x20,
            "PetalburgCity_Layout_Border": ROM_BASE + 0x60,
            "PetalburgCity_Layout_Blockdata": ROM_BASE + 0x64,
            "gTileset_General": ROM_BASE + 0x68,
            "gTileset_Petalburg": ROM_BASE + 0x80,
        }
        struct.pack_into("<I", rom, 0, symbols["PetalburgCity_Layout"])
        struct.pack_into("<ii", rom, 0x20, 30, 30)
        struct.pack_into("<I", rom, 0x28, symbols["PetalburgCity_Layout_Border"])
        struct.pack_into("<I", rom, 0x2C, symbols["PetalburgCity_Layout_Blockdata"])
        struct.pack_into("<I", rom, 0x30, 0)  # Mutated primaryTileset.
        struct.pack_into("<I", rom, 0x34, symbols["gTileset_Petalburg"])
        manifest = {
            "abis": {"mapLayout": EXPECTED_ABIS["mapLayout"]},
            "layouts": [
                {
                    "name": "PetalburgCity_Layout",
                    "number": 1,
                    "width": 30,
                    "height": 30,
                    "border": "PetalburgCity_Layout_Border",
                    "map": "PetalburgCity_Layout_Blockdata",
                    "primaryTileset": "gTileset_General",
                    "secondaryTileset": "gTileset_Petalburg",
                    "layoutFormatValue": 0,
                    "borderWidth": 0,
                    "borderHeight": 0,
                }
            ],
        }
        with self.assertRaisesRegex(
            ValidationError, "PetalburgCity_Layout.primaryTileset points outside ROM"
        ):
            validate_layouts(rom, manifest, symbols, ROM_BASE + len(rom))

    def map_header_fixture(self):
        rom = bytearray(0x180)
        symbols = {
            "FirstMap": ROM_BASE,
            "SecondMap": ROM_BASE + 0x20,
            "FirstLayout": ROM_BASE + 0x80,
            "SecondLayout": ROM_BASE + 0x84,
            "FirstEvents": ROM_BASE + 0x88,
            "SecondEvents": ROM_BASE + 0x8C,
            "FirstScripts": ROM_BASE + 0x90,
            "SecondScripts": ROM_BASE + 0x94,
        }
        maps = []
        section_values = (253, 256)
        for index, name in enumerate(("FirstMap", "SecondMap")):
            header = symbols[name] - ROM_BASE
            prefix = "First" if index == 0 else "Second"
            struct.pack_into(
                "<IIII",
                rom,
                header,
                symbols[f"{prefix}Layout"],
                symbols[f"{prefix}Events"],
                symbols[f"{prefix}Scripts"],
                0,
            )
            struct.pack_into("<H", rom, header + 0x14, section_values[index])
            rom[header + 0x1C] = 4 + index
            maps.append(
                {
                    "name": name,
                    "group": index,
                    "region": "REGION_HOENN" if index == 0 else "REGION_KANTO",
                    "regionMapSection": f"MAPSEC_{prefix.upper()}_FIXTURE",
                    "mapLayout": f"{prefix}Layout",
                    "mapEvents": f"{prefix}Events",
                    "mapScripts": f"{prefix}Scripts",
                    "mapConnections": None,
                    "regionMapSectionValue": section_values[index],
                    "battleType": 4 + index,
                }
            )
        manifest = {
            "abis": {
                "mapHeader": {
                    "size": 32,
                    "alignment": 4,
                    "regionMapSectionIdOffset": 20,
                    "battleTypeOffset": 28,
                    "paddingOffset": 29,
                    "paddingSize": 3,
                }
            },
            "maps": maps,
            "groups": [
                {"name": "gMapGroup_Fixture", "number": 0},
                {"name": "gMapGroup_Fixture_Frlg", "number": 1},
            ],
            "mapSectionMetadata": [
                {
                    "id": "MAPSEC_FIRST_FIXTURE",
                    "value": 253,
                    "region": "REGION_HOENN",
                },
                {
                    "id": "MAPSEC_SECOND_FIXTURE",
                    "value": 256,
                    "region": "REGION_HOENN",
                },
            ],
        }
        return rom, manifest, symbols

    def test_map_header_exact_offsets_values_stride_and_alignment(self) -> None:
        rom, manifest, symbols = self.map_header_fixture()
        self.assertEqual(
            struct.unpack_from("<H", rom, symbols["SecondMap"] - ROM_BASE + 0x14)[0],
            256,
        )
        validate_map_headers(rom, manifest, symbols, ROM_BASE + len(rom))

        mutations = (
            (0x14, 0xFF, "regionMapSectionId"),
            (0x1C, 0xFF, "battleType"),
            (0x1D, 0x01, "padding"),
        )
        for offset, value, message in mutations:
            with self.subTest(message=message):
                changed = bytearray(rom)
                changed[offset] = value
                with self.assertRaisesRegex(ValidationError, message):
                    validate_map_headers(
                        changed, manifest, symbols, ROM_BASE + len(changed)
                    )

        misaligned_symbols = dict(symbols)
        misaligned_symbols["FirstMap"] += 2
        with self.assertRaisesRegex(ValidationError, "not four-byte aligned"):
            validate_map_headers(rom, manifest, misaligned_symbols, ROM_BASE + len(rom))

        bad_stride_symbols = dict(symbols)
        bad_stride_symbols["SecondMap"] += 4
        with self.assertRaisesRegex(ValidationError, "32-byte stride"):
            validate_map_headers(rom, manifest, bad_stride_symbols, ROM_BASE + len(rom))

    def test_artifact_rejects_unbound_map_section_against_valid_rom(self) -> None:
        rom, original, symbols = self.map_header_fixture()
        mutations = (
            (
                "unknown name",
                "regionMapSection",
                "MAPSEC_DOES_NOT_EXIST",
                "names unknown map section",
            ),
            (
                "mismatched value",
                "regionMapSectionValue",
                256,
                "map-section name/value disagree",
            ),
            (
                "mismatched region",
                "region",
                "REGION_JOHTO",
                "region .* disagrees",
            ),
        )
        for label, field, value, message in mutations:
            with self.subTest(label=label):
                manifest = copy.deepcopy(original)
                manifest["maps"][0][field] = value
                with self.assertRaisesRegex(ValidationError, message):
                    validate_map_headers(rom, manifest, symbols, ROM_BASE + len(rom))

    def test_artifact_honors_reviewed_vermilion_geography(self) -> None:
        generated = json.loads((self.generated / "integrity-manifest.json").read_text())
        entry = copy.deepcopy(
            next(
                item
                for item in generated["maps"]
                if item["name"] == "VermilionCity_PortInside"
            )
        )
        group = copy.deepcopy(
            next(
                item for item in generated["groups"] if item["number"] == entry["group"]
            )
        )
        section = copy.deepcopy(
            next(
                item
                for item in generated["mapSectionMetadata"]
                if item["id"] == entry["regionMapSection"]
            )
        )
        manifest = {
            "abis": {"mapHeader": generated["abis"]["mapHeader"]},
            "maps": [entry],
            "groups": [group],
            "mapSectionMetadata": [section],
        }
        rom = bytearray(0x100)
        symbols = {entry["name"]: ROM_BASE}
        pointer_fields = ("mapLayout", "mapEvents", "mapScripts", "mapConnections")
        for index, field in enumerate(pointer_fields, start=1):
            if entry[field] is not None:
                symbols[entry[field]] = ROM_BASE + index * 4
        struct.pack_into(
            "<IIII",
            rom,
            0,
            *(symbols.get(entry[field], 0) for field in pointer_fields),
        )
        struct.pack_into("<H", rom, 0x14, entry["regionMapSectionValue"])
        rom[0x1C] = entry["battleType"]

        self.assertEqual(group["name"], "gMapGroup_IndoorSSAqua")
        self.assertEqual(entry["region"], "REGION_KANTO")
        validate_map_headers(rom, manifest, symbols, ROM_BASE + len(rom))

        entry["region"] = "REGION_JOHTO"
        with self.assertRaisesRegex(
            ValidationError,
            "VermilionCity_PortInside.*disagrees.*REGION_KANTO",
        ):
            validate_map_headers(rom, manifest, symbols, ROM_BASE + len(rom))

        entry["region"] = "REGION_KANTO"
        group["name"] = "IndoorSSAqua"
        with self.assertRaisesRegex(ValidationError, "invalid map-group metadata"):
            validate_map_headers(rom, manifest, symbols, ROM_BASE + len(rom))

    def test_map_section_metadata_byte_mutation_is_rejected(self) -> None:
        rom = bytearray((3, 0, 0, 0, 1, 1, 4, 0))
        manifest = {
            "mapSectionMetadata": [
                {
                    "id": "MAPSEC_HOENN_FIXTURE",
                    "value": 0,
                    "regionValue": 3,
                    "kindValue": 0,
                    "regionMapTypeValue": 0,
                },
                {
                    "id": "MAPSEC_SEVII_FIXTURE",
                    "value": 1,
                    "regionValue": 1,
                    "kindValue": 1,
                    "regionMapTypeValue": 4,
                },
            ]
        }
        symbols = {"gMapSectionMetadata": ROM_BASE}
        validate_section_metadata(rom, manifest, symbols, ROM_BASE + len(rom))
        rom[0] = 0
        with self.assertRaisesRegex(
            ValidationError, "MAPSEC_HOENN_FIXTURE.regionValue"
        ):
            validate_section_metadata(rom, manifest, symbols, ROM_BASE + len(rom))


if __name__ == "__main__":
    unittest.main()
