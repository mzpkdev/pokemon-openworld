import copy
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.foundation.manifest import ManifestError, validate_manifest
from tools.foundation.validate_artifact import (
    ROM_BASE,
    ValidationError,
    load_capacity_policy,
    validate_group_slots,
    validate_layouts,
)


ROOT = Path(__file__).resolve().parents[3]
CAPACITY = ROOT / "tools/foundation/capacity_policy.json"


class FoundationToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)
        cls.tempdir = tempfile.TemporaryDirectory(prefix="foundation-tools-")
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
        manifest = json.loads((self.generated / "foundation-manifest.json").read_text())
        manifest["counts"]["groupedMaps"] -= 1
        with self.assertRaisesRegex(ManifestError, "wrong registry counts"):
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
                }
            ]
        }
        with self.assertRaisesRegex(
            ValidationError, "PetalburgCity_Layout.primaryTileset points outside ROM"
        ):
            validate_layouts(rom, manifest, symbols, ROM_BASE + len(rom))


if __name__ == "__main__":
    unittest.main()
