import copy
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.integrity.manifest import EXPECTED_ABIS, ManifestError, validate_manifest
from tools.integrity.validate_artifact import (
    ROM_BASE,
    ValidationError,
    load_capacity_policy,
    validate_group_slots,
    validate_layouts,
    validate_map_headers,
    validate_section_metadata,
)


ROOT = Path(__file__).resolve().parents[3]
CAPACITY = ROOT / "tools/integrity/capacity_policy.json"


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
                    (manifest["maps"][0]["regionMapSectionValue"] + 1) % 209,
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
