import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"
GROUPS = ROOT / "data" / "maps" / "map_groups.json"
LAYOUTS = ROOT / "data" / "layouts" / "layouts.json"
MAPS = sorted((ROOT / "data" / "maps").glob("*/map.json"))


class ProductRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)
        cls.tempdir = tempfile.TemporaryDirectory(prefix="allregions-registry-")
        cls.output = Path(cls.tempdir.name) / "current"
        result = subprocess.run(
            [
                str(MAPJSON),
                "generate",
                "allregions",
                str(GROUPS),
                str(LAYOUTS),
                str(cls.output),
                *(str(path) for path in MAPS),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        if result.returncode:
            raise AssertionError(result.stderr)
        cls.manifest = json.loads((cls.output / "integrity-manifest.json").read_text())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_exact_reviewed_registry_boundary(self) -> None:
        self.assertEqual(
            self.manifest["counts"],
            {
                "groups": 75,
                "groupedMaps": 935,
                "reviewedMaps": 939,
                "layouts": 785,
                "regions": {"REGION_HOENN": 518, "REGION_KANTO": 421},
            },
        )
        self.assertEqual(len(self.manifest["groups"]), 75)
        self.assertEqual(len(self.manifest["maps"]), 935)
        self.assertEqual(len(self.manifest["layouts"]), 785)

    def test_only_four_reviewed_unused_houses_are_excluded(self) -> None:
        self.assertEqual(
            {entry["name"] for entry in self.manifest["exclusions"]},
            {
                "Route6_UnusedHouse_Frlg",
                "Route19_UnusedHouse_Frlg",
                "Route23_UnusedHouse",
                "SevenIsland_UnusedHouse",
            },
        )

    def test_product_pointer_tables_have_no_null_placeholders_and_are_aligned(
        self,
    ) -> None:
        groups = (self.output / "data/maps/groups.inc").read_text()
        layouts = (self.output / "data/layouts/layouts_table.inc").read_text()
        self.assertNotIn(".4byte NULL", groups)
        self.assertNotIn(".4byte NULL", layouts)
        self.assertIn("\t.align 2\ngMapGroups::", groups)
        self.assertIn("\t.align 2\ngMapLayouts::", layouts)

    def test_debug_map_names_are_generated_from_scoped_registry_names(self) -> None:
        names = (self.output / "src/data/debug_map_names.h").read_text()

        self.assertIn('_("Towns And Routes")', names)
        self.assertIn('_("Route 2")', names)
        self.assertIn('_("Pallet Town\\nProfessor Oaks Lab")', names)
        self.assertIn("static const u8 *const sDebugMapGroupNames[]", names)
        self.assertIn("static const u8 *const *const sDebugMapNames[]", names)

    def test_kanto_hidden_items_receive_stable_nonzero_saved_flags(self) -> None:
        allocated: dict[str, int] = {}
        for entry in self.manifest["maps"]:
            if entry["region"] != "REGION_KANTO":
                continue
            events = self.output / "data/maps" / entry["name"] / "events.inc"
            text = events.read_text()
            for value in re.findall(
                r"bg_hidden_item_event [^\n]*, (\d+), \d+, (?:TRUE|FALSE)$",
                text,
                re.MULTILINE,
            ):
                allocated[f"{entry['name']}:{len(allocated)}"] = int(value)
        values = list(allocated.values())
        self.assertEqual(len(values), 183)
        self.assertEqual(len(set(values)), 183)
        self.assertTrue(all(0x1F4 <= value < 0x8FE for value in values))


if __name__ == "__main__":
    unittest.main()
