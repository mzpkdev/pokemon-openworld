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
FONTS_SOURCE = ROOT / "src" / "fonts.c"
DEBUG_WARP_WINDOW_WIDTH_PX = 28 * 8


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
        cls.groups = json.loads(GROUPS.read_text())
        cls.maps_by_name = {
            data["name"]: data
            for path in MAPS
            if (data := json.loads(path.read_text()))
        }
        cls.debug_names = (cls.output / "src/data/debug_map_names.h").read_text()

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

    def test_debug_map_tables_exhaustively_match_scoped_registry(self) -> None:
        names = self.debug_names
        group_order = self.groups["group_order"]

        for group_index, group_name in enumerate(group_order):
            expected_maps = self.groups[group_name]
            group_match = re.search(
                rf'sDebugMapGroupName_{group_index}\[\] = _\("([^"]*)"\);',
                names,
            )
            self.assertIsNotNone(group_match, group_name)
            self.assertTrue(group_match.group(1), group_name)

            definitions = re.findall(
                rf'sDebugMapName_{group_index}_(\d+)\[\] = _\("([^"]*)"\);',
                names,
            )
            self.assertEqual(
                [index for index, _label in definitions],
                [str(map_index) for map_index in range(len(expected_maps))],
                group_name,
            )
            self.assertTrue(all(label for _index, label in definitions), group_name)

            name_table = re.search(
                rf"sDebugMapNames_{group_index}\[\] =\n\{{\n(.*?)\n\}};",
                names,
                re.DOTALL,
            )
            region_table = re.search(
                rf"sDebugMapRegions_{group_index}\[\] =\n\{{\n(.*?)\n\}};",
                names,
                re.DOTALL,
            )
            self.assertIsNotNone(name_table, group_name)
            self.assertIsNotNone(region_table, group_name)
            self.assertEqual(
                re.findall(r"sDebugMapName_\d+_\d+", name_table.group(1)),
                [
                    f"sDebugMapName_{group_index}_{map_index}"
                    for map_index in range(len(expected_maps))
                ],
                group_name,
            )
            self.assertEqual(
                re.findall(r"REGION_[A-Z]+", region_table.group(1)),
                [self.maps_by_name[map_name]["region"] for map_name in expected_maps],
                group_name,
            )

        self.assertEqual(
            re.findall(
                r"sDebugMapGroupName_\d+",
                re.search(
                    r"sDebugMapGroupNames\[\] =\n\{\n(.*?)\n\};", names, re.DOTALL
                ).group(1),
            ),
            [f"sDebugMapGroupName_{index}" for index in range(len(group_order))],
        )
        for table_name, entry_prefix in (
            ("sDebugMapNames", "sDebugMapNames_"),
            ("sDebugMapRegions", "sDebugMapRegions_"),
        ):
            table = re.search(
                rf"{table_name}\[\] =\n\{{\n(.*?)\n\}};", names, re.DOTALL
            ).group(1)
            self.assertEqual(
                re.findall(rf"{entry_prefix}\d+|NULL", table),
                [f"{entry_prefix}{index}" for index in range(len(group_order))],
            )

    def debug_label_for_map(self, map_name: str) -> str:
        for group_index, group_name in enumerate(self.groups["group_order"]):
            if map_name in self.groups[group_name]:
                map_index = self.groups[group_name].index(map_name)
                match = re.search(
                    rf'sDebugMapName_{group_index}_{map_index}\[\] = _\("([^"]*)"\);',
                    self.debug_names,
                )
                self.assertIsNotNone(match, map_name)
                return match.group(1)
        self.fail(f"{map_name} is absent from the scoped group registry")

    def debug_label_for_group(self, group_name: str) -> str:
        group_index = self.groups["group_order"].index(group_name)
        match = re.search(
            rf'sDebugMapGroupName_{group_index}\[\] = _\("([^"]*)"\);',
            self.debug_names,
        )
        self.assertIsNotNone(match, group_name)
        return match.group(1)

    def test_debug_labels_have_independent_exact_examples(self) -> None:
        self.assertEqual(
            self.debug_label_for_group("gMapGroup_IndoorRoute104Prototype"),
            "Indoor Route 104 Prototype",
        )
        self.assertEqual(
            self.debug_label_for_map("PalletTown_ProfessorOaksLab_Frlg"),
            "Pallet Town Professor Oaks Lab",
        )
        self.assertEqual(
            self.debug_label_for_map("CinnabarIsland_PokemonLab_ExperimentRoom_Frlg"),
            r"Cinnabar Island Pokemon\nLab Experiment Room",
        )
        self.assertEqual(
            self.debug_label_for_map("Route104_PrototypePrettyPetalFlowerShop"),
            r"Route 104 Prototype\nPretty Petal Flower Shop",
        )

    def test_debug_labels_prove_every_warp_state_fits_the_window(self) -> None:
        group_labels = re.findall(
            r'sDebugMapGroupName_\d+\[\] = _\("([^"]*)"\);', self.debug_names
        )
        map_labels = re.findall(
            r'sDebugMapName_\d+_\d+\[\] = _\("([^"]*)"\);', self.debug_names
        )

        self.assertEqual(len(group_labels), 75)
        self.assertEqual(len(map_labels), 935)
        self.assertTrue(all(r"\n" not in label for label in group_labels))
        for label in map_labels:
            lines = label.split(r"\n")
            self.assertLessEqual(len(lines), 2, label)
            self.assertTrue(all(lines), label)
            self.assertLessEqual(max(map(len, lines)), 32, label)

        max_name_lines = max(label.count(r"\n") + 1 for label in map_labels)
        state_line_counts = {
            "region": 5,
            "group": 8,
            "map": 6 + max_name_lines,
            "entry_center": 5 + max_name_lines,
            "entry_warp": 5 + 2 * max_name_lines,
        }
        self.assertEqual(state_line_counts["entry_warp"], 9)
        self.assertTrue(
            all(lines <= 9 for lines in state_line_counts.values()),
            state_line_counts,
        )

    def test_every_group_label_fits_debug_font_window_horizontally(self) -> None:
        font_source = FONTS_SOURCE.read_text()
        widths_text = re.search(
            r"gFontNormalLatinGlyphWidths\[\] = \{(.*?)\n\};",
            font_source,
            re.DOTALL,
        )
        self.assertIsNotNone(widths_text)
        glyph_widths = [
            int(value) for value in re.findall(r"\d+", widths_text.group(1))
        ]
        self.assertGreaterEqual(len(glyph_widths), 256)

        def char_code(character: str) -> int:
            if character == " ":
                return 0x00
            if "0" <= character <= "9":
                return 0xA1 + ord(character) - ord("0")
            if "A" <= character <= "Z":
                return 0xBB + ord(character) - ord("A")
            if "a" <= character <= "z":
                return 0xD5 + ord(character) - ord("a")
            if character == "-":
                return 0xAE
            self.fail(f"unsupported debug group-label character: {character!r}")

        group_labels = re.findall(
            r'sDebugMapGroupName_\d+\[\] = _\("([^"]*)"\);', self.debug_names
        )
        measured = [
            (label, sum(glyph_widths[char_code(character)] for character in label))
            for label in group_labels
        ]
        overflowing = {
            label: width
            for label, width in measured
            if width > DEBUG_WARP_WINDOW_WIDTH_PX
        }
        self.assertFalse(
            overflowing,
            "FONT_NORMAL group labels exceed the 28-tile debug warp window",
        )
        self.assertEqual(len(measured), 75)

    def test_frlg_link_maps_keep_declared_kanto_debug_region(self) -> None:
        names = (self.output / "src/data/debug_map_names.h").read_text()
        link_maps = {
            "BattleColosseum_2P_Frlg",
            "BattleColosseum_4P_Frlg",
            "TradeCenter_Frlg",
            "RecordCorner_Frlg",
            "UnionRoom_Frlg",
        }

        for map_name in link_maps:
            self.assertEqual(self.maps_by_name[map_name]["region"], "REGION_KANTO")
            self.assertEqual(
                self.maps_by_name[map_name]["region_map_section"],
                "MAPSEC_SPECIAL_AREA",
            )
            for group_index, group_name in enumerate(self.groups["group_order"]):
                if map_name in self.groups[group_name]:
                    map_index = self.groups[group_name].index(map_name)
                    break
            else:
                self.fail(f"{map_name} is absent from the scoped group registry")
            region_table = re.search(
                rf"sDebugMapRegions_{group_index}\[\] =\n\{{\n(.*?)\n\}};",
                names,
                re.DOTALL,
            ).group(1)
            self.assertEqual(
                re.findall(r"REGION_[A-Z]+", region_table)[map_index],
                "REGION_KANTO",
            )

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
