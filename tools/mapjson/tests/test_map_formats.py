import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"


class MapFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["make", "-C", "tools/mapjson"], cwd=ROOT, check=True)

    def generate_layout(self, format_name, primary, secondary, include_format=True):
        layout = {
            "id": "LAYOUT_FORMAT_FIXTURE",
            "name": "FormatFixture_Layout",
            "width": 2,
            "height": 2,
            "primary_tileset": primary,
            "secondary_tileset": secondary,
            "border_filepath": "data/layouts/PetalburgCity/border.bin",
            "blockdata_filepath": "data/layouts/PetalburgCity/map.bin",
            "border_width": 2,
            "border_height": 2,
        }
        if include_format:
            layout["format"] = format_name

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            layouts = temporary_path / "layouts.json"
            output = temporary_path / "output"
            output.mkdir()
            layouts.write_text(
                json.dumps({"layouts_table_label": "gMapLayouts", "layouts": [layout]}),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    str(MAPJSON),
                    "layouts",
                    "allregions",
                    str(layouts),
                    f"{output}/",
                    f"{output}/",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            generated = (
                (output / "layouts.inc").read_text(encoding="utf-8")
                if result.returncode == 0
                else ""
            )
            return result, generated

    def test_synthetic_johto_layout_accepts_mixed_attribute_widths(self):
        result, generated = self.generate_layout(
            "johto", "gTileset_General", "gTileset_PalletTown"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".byte 2 @ MAP_LAYOUT_FORMAT_JOHTO", generated)

    def test_synthetic_johto_layout_accepts_reverse_mixed_attribute_widths(self):
        result, generated = self.generate_layout(
            "johto", "gTileset_General_Frlg", "gTileset_Petalburg"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".byte 2 @ MAP_LAYOUT_FORMAT_JOHTO", generated)

    def test_emerald_layout_rejects_u32_tileset(self):
        result, _ = self.generate_layout(
            "emerald", "gTileset_General_Frlg", "gTileset_PalletTown"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatches primary tileset attribute width", result.stderr)

    def test_frlg_layout_rejects_u16_tileset(self):
        result, _ = self.generate_layout(
            "frlg", "gTileset_General", "gTileset_Petalburg"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mismatches primary tileset attribute width", result.stderr)

    def test_layout_format_is_required(self):
        result, _ = self.generate_layout(
            "emerald", "gTileset_General", "gTileset_Petalburg", include_format=False
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("format", result.stderr)

    def test_unknown_layout_format_is_rejected(self):
        result, _ = self.generate_layout(
            "sinnoh", "gTileset_General", "gTileset_Petalburg"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown layout format 'sinnoh'", result.stderr)


if __name__ == "__main__":
    unittest.main()
