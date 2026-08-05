import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"
REGISTRY = ROOT / "src" / "data" / "region_map" / "region_map_sections.json"
COMPATIBILITY = ROOT / "src" / "data" / "region_map" / "map_section_compatibility.json"


class MapSectionIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson"], cwd=ROOT, check=True)
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.compatibility = json.loads(COMPATIBILITY.read_text(encoding="utf-8"))

    def validate(self, registry=None, compatibility=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path = root / "registry.json"
            compatibility_path = root / "compatibility.json"
            registry_path.write_text(
                json.dumps(registry or self.registry), encoding="utf-8"
            )
            compatibility_path.write_text(
                json.dumps(compatibility or self.compatibility), encoding="utf-8"
            )
            return subprocess.run(
                [
                    str(MAPJSON),
                    "sections",
                    "allregions",
                    str(registry_path),
                    str(compatibility_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

    def mutated_registry(self):
        return copy.deepcopy(self.registry)

    def test_reviewed_values_and_compact_round_trips_are_frozen(self) -> None:
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "count=209\n")
        for value, section in enumerate(self.registry["map_sections"]):
            self.assertEqual(section["value"], value)
            self.assertEqual(section["saved_location"], section["id"])
            self.assertEqual(section["met_location"], value)
            self.assertEqual(section["met_location_display"], section["id"])

    def test_duplicate_values_are_rejected(self) -> None:
        registry = self.mutated_registry()
        registry["map_sections"][1]["value"] = 0
        result = self.validate(registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate map-section value", result.stderr)

    def test_unmarked_gaps_are_rejected(self) -> None:
        registry = self.mutated_registry()
        registry["map_sections"][-1]["value"] = 210
        compatibility = copy.deepcopy(self.compatibility)
        compatibility["stable_sections"][-1]["value"] = 210
        result = self.validate(registry, compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unmarked map-section value gap 208", result.stderr)

    def test_reserved_world_values_are_strictly_validated(self) -> None:
        mutations = (["not-a-number"], [-1], [0xFFFF], [0, 0], [0])
        for reserved in mutations:
            with self.subTest(reserved=reserved):
                compatibility = copy.deepcopy(self.compatibility)
                compatibility["reserved_map_section_values"] = reserved
                result = self.validate(compatibility=compatibility)
                self.assertNotEqual(result.returncode, 0)

    def test_compatibility_manifest_changes_are_rejected(self) -> None:
        compatibility = copy.deepcopy(self.compatibility)
        compatibility["stable_sections"][0]["id"] = "MAPSEC_CHANGED"
        result = self.validate(compatibility=compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("compatibility manifest changed", result.stderr)

    def test_missing_kind_and_region_are_rejected(self) -> None:
        for field in ("kind", "region", "region_map_type"):
            with self.subTest(field=field):
                registry = self.mutated_registry()
                del registry["map_sections"][0][field]
                result = self.validate(registry)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(field.split("_")[0], result.stderr)

    def test_met_sentinel_collisions_are_rejected(self) -> None:
        registry = self.mutated_registry()
        registry["map_sections"][0]["met_location"] = 0xFD
        result = self.validate(registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("collides with reserved origin", result.stderr)

    def test_synthetic_wide_sections_require_only_reviewed_compact_aliases(
        self,
    ) -> None:
        registry = self.mutated_registry()
        compatibility = copy.deepcopy(self.compatibility)
        synthetic_values = (253, 254, 255, 256, 300)
        defined = {section["value"] for section in registry["map_sections"]}
        for index, value in enumerate(synthetic_values):
            registry["map_sections"].append(
                {
                    "id": f"MAPSEC_SYNTHETIC_{value}",
                    "value": value,
                    "kind": "geographic",
                    "region": "REGION_HOENN",
                    "region_map_type": "REGION_MAP_HOENN",
                    "saved_location": f"MAPSEC_{['LITTLEROOT_TOWN', 'OLDALE_TOWN', 'DEWFORD_TOWN', 'LAVARIDGE_TOWN', 'FALLARBOR_TOWN'][index]}",
                    "met_location": index,
                    "met_location_display": f"MAPSEC_{['LITTLEROOT_TOWN', 'OLDALE_TOWN', 'DEWFORD_TOWN', 'LAVARIDGE_TOWN', 'FALLARBOR_TOWN'][index]}",
                }
            )
        compatibility["reserved_map_section_values"] = [
            value
            for value in range(301)
            if value not in defined | set(synthetic_values)
        ]
        registry["map_section_count"] = 301
        result = self.validate(registry, compatibility)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_reserved_met_origins_are_frozen(self) -> None:
        compatibility = copy.deepcopy(self.compatibility)
        compatibility["met_location"]["special_origins"]["egg"] = 0xFC
        result = self.validate(compatibility=compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reserved met-location origins changed", result.stderr)

    def test_every_compact_compatibility_domain_field_is_validated(self) -> None:
        mutations = (
            (("saved_location", "invalid_code"), 254),
            (("saved_location", "frozen_round_trip", "first"), 1),
            (("saved_location", "frozen_round_trip", "last"), 207),
            (("saved_location", "reserved_codes", "first"), 210),
            (("saved_location", "reserved_codes", "last"), 253),
            (("met_location", "invalid_code"), 251),
            (("met_location", "frozen_round_trip", "first"), 1),
            (("met_location", "frozen_round_trip", "last"), 207),
            (("met_location", "reserved_codes", "first"), 210),
            (("met_location", "reserved_codes", "last"), 250),
            (("met_location", "special_origins", "egg"), 252),
            (("met_location", "special_origins", "in_game_trade"), 253),
            (("met_location", "special_origins", "fateful_encounter"), 254),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                compatibility = copy.deepcopy(self.compatibility)
                owner = compatibility
                for key in path[:-1]:
                    owner = owner[key]
                owner[path[-1]] = value
                result = self.validate(compatibility=compatibility)
                self.assertNotEqual(result.returncode, 0)


class MapHeaderAbiGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson"], cwd=ROOT, check=True)

    def test_emitter_matches_the_32_byte_c_abi(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = subprocess.run(
                [
                    str(MAPJSON),
                    "map",
                    "allregions",
                    "data/maps/LittlerootTown/map.json",
                    "data/layouts/layouts.json",
                    f"{output}/",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            header = (output / "header.inc").read_text(encoding="utf-8")
            self.assertIn("\t.align 2\nLittlerootTown:", header)
            self.assertIn("\t.2byte MAPSEC_LITTLEROOT_TOWN", header)
            self.assertTrue(header.rstrip().endswith("\t.byte 0, 0, 0"))

        c_header = (ROOT / "include" / "global.fieldmap.h").read_text()
        self.assertIn("sizeof(struct MapHeader) == 0x20", c_header)
        self.assertIn("MapHeaderAbiStride, items[1]) == 0x20", c_header)

    def test_standalone_map_connections_use_the_sibling_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            result = subprocess.run(
                [
                    str(MAPJSON),
                    "map",
                    "allregions",
                    "data/maps/Route101/map.json",
                    "data/layouts/layouts.json",
                    f"{output}/",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            header = (output / "header.inc").read_text(encoding="utf-8")
            connections = (output / "connections.inc").read_text(encoding="utf-8")
            self.assertIn("\t.4byte Route101_MapConnections", header)
            self.assertIn("\t.4byte 2\n\t.4byte Route101_MapConnectionsList", connections)
            self.assertEqual(connections.count("\tconnection "), 2)

    def test_filtered_standalone_connections_clear_header_pointer_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            map_dir = base / "maps" / "Route101"
            output = base / "output"
            map_dir.mkdir(parents=True)
            output.mkdir()
            shutil.copy2(ROOT / "data/maps/Route101/map.json", map_dir / "map.json")
            result = subprocess.run(
                [
                    str(MAPJSON),
                    "map",
                    "allregions",
                    str(map_dir / "map.json"),
                    "data/layouts/layouts.json",
                    f"{output}/",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            header = (output / "header.inc").read_text(encoding="utf-8")
            connections = (output / "connections.inc").read_text(encoding="utf-8")
            self.assertNotIn("\t.4byte Route101_MapConnections", header)
            self.assertIn("\t.4byte NULL", header)
            self.assertIn("\t.4byte 0\n\t.4byte Route101_MapConnectionsList", connections)
            self.assertNotIn("\tconnection ", connections)


if __name__ == "__main__":
    unittest.main()
