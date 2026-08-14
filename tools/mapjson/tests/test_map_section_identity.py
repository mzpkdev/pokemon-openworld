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
PERSISTENT_IDS = ROOT / "src" / "data" / "persistence" / "persistent_ids.json"
REVIEWED_ALIASES = (
    ("MAPSEC_JOHTO_VICTORY_ROAD", "MAPSEC_VICTORY_ROAD", 70, "MAPSEC_VICTORY_ROAD"),
    ("MAPSEC_BLACKTHORN_CITY", "MAPSEC_BLACKTHORN_CITY", 249, "MAPSEC_ROUTE_44"),
    ("MAPSEC_ROUTE_45", "MAPSEC_ROUTE_45", 249, "MAPSEC_ROUTE_44"),
    ("MAPSEC_ROUTE_46", "MAPSEC_ROUTE_46", 210, "MAPSEC_ROUTE_29"),
    ("MAPSEC_ICE_PATH", "MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"),
    ("MAPSEC_DRAGONS_DEN", "MAPSEC_ROUTE_44", 249, "MAPSEC_ROUTE_44"),
    ("MAPSEC_DARK_CAVE", "MAPSEC_ROUTE_31", 215, "MAPSEC_ROUTE_31"),
    ("MAPSEC_ROUTE_26", "MAPSEC_ROUTE_28", 212, "MAPSEC_ROUTE_28"),
    ("MAPSEC_ROUTE_27", "MAPSEC_NEW_BARK_TOWN", 209, "MAPSEC_NEW_BARK_TOWN"),
    ("MAPSEC_TOHJO_FALLS", "MAPSEC_NEW_BARK_TOWN", 209, "MAPSEC_NEW_BARK_TOWN"),
)


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
        registry = json.loads(REGISTRY.read_text())
        self.assertEqual(result.stdout, f"count={registry['map_section_count']}\n")
        for value, section in enumerate(self.registry["map_sections"][:252]):
            self.assertEqual(section["value"], value)
            self.assertEqual(section["saved_location"], section["id"])
            self.assertEqual(section["met_location"], value)
            self.assertEqual(section["met_location_display"], section["id"])

        sections = {section["id"]: section for section in self.registry["map_sections"]}
        self.assertEqual(
            self.compatibility["reviewed_codecs"]["aliases"],
            [
                {
                    "id": section_id,
                    "saved_location": saved_target,
                    "met_location": compact_code,
                    "met_location_display": met_target,
                }
                for section_id, saved_target, compact_code, met_target in REVIEWED_ALIASES
            ],
        )
        for section_id, saved_target, compact_code, met_target in REVIEWED_ALIASES:
            with self.subTest(section_id=section_id):
                alias = sections[section_id]
                self.assertEqual(alias["saved_location"], saved_target)
                self.assertEqual(alias["met_location"], compact_code)
                self.assertEqual(alias["met_location_display"], met_target)

        for value in (252, 253, 254):
            with self.subTest(saved_reverse_owner=value):
                section = self.registry["map_sections"][value]
                self.assertEqual(section["saved_location"], section["id"])

        ledger = json.loads(PERSISTENT_IDS.read_text(encoding="utf-8"))
        saved_bindings = {
            record["code"]: (record["section"], record["sectionValue"])
            for record in ledger["locationCodecs"]["saved"]
        }
        self.assertEqual(
            {code: saved_bindings[code] for code in (252, 253, 254)},
            {
                252: ("MAPSEC_BLACKTHORN_CITY", 252),
                253: ("MAPSEC_ROUTE_45", 253),
                254: ("MAPSEC_ROUTE_46", 254),
            },
        )

    def test_disabled_wide_section_codecs_are_emitted_as_invalid(self) -> None:
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        for value in (258, 259, 260, 265, 266):
            with self.subTest(value=value):
                section = self.registry["map_sections"][value]
                self.assertIsNone(section["saved_location"])
                self.assertIsNone(section["met_location"])
                self.assertIsNone(section["met_location_display"])

    def test_duplicate_values_are_rejected(self) -> None:
        registry = self.mutated_registry()
        registry["map_sections"][1]["value"] = 0
        result = self.validate(registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate map-section value", result.stderr)

    def test_unmarked_gaps_are_rejected(self) -> None:
        registry = self.mutated_registry()
        removed = registry["map_sections"].pop(-2)
        result = self.validate(registry)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"unmarked map-section value gap {removed['value']}", result.stderr
        )

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

    def test_unreviewed_synthetic_wide_aliases_are_rejected(
        self,
    ) -> None:
        registry = self.mutated_registry()
        compatibility = copy.deepcopy(self.compatibility)
        synthetic_values = (267, 268, 269, 270, 300)
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
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unreviewed saved-location fallback", result.stderr)

    def test_every_reviewed_exact_codec_field_is_required(self) -> None:
        mutations = (
            (209, "saved_location", None),
            (209, "met_location", None),
            (251, "saved_location", "MAPSEC_LITTLEROOT_TOWN"),
            (251, "met_location", 0),
            (251, "met_location_display", "MAPSEC_LITTLEROOT_TOWN"),
        )
        for value, field, replacement in mutations:
            with self.subTest(value=value, field=field):
                registry = self.mutated_registry()
                registry["map_sections"][value][field] = replacement
                if field == "met_location":
                    registry["map_sections"][value]["met_location_display"] = None
                result = self.validate(registry)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(registry["map_sections"][value]["id"], result.stderr)

    def test_reviewed_aliases_are_frozen_and_have_canonical_reverse_owners(
        self,
    ) -> None:
        mutations = {
            "saved_location": "MAPSEC_LITTLEROOT_TOWN",
            "met_location": 0,
            "met_location_display": "MAPSEC_LITTLEROOT_TOWN",
        }
        section_indexes = {
            section["id"]: index
            for index, section in enumerate(self.registry["map_sections"])
        }
        for section_id, _, _, _ in REVIEWED_ALIASES:
            for field, replacement in mutations.items():
                with self.subTest(section_id=section_id, field=field):
                    registry = self.mutated_registry()
                    registry["map_sections"][section_indexes[section_id]][field] = (
                        replacement
                    )
                    result = self.validate(registry)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(section_id, result.stderr)

    def test_reviewed_alias_manifest_fields_are_frozen(self) -> None:
        mutations = {
            "id": "MAPSEC_LITTLEROOT_TOWN",
            "saved_location": "MAPSEC_LITTLEROOT_TOWN",
            "met_location": 0,
            "met_location_display": "MAPSEC_LITTLEROOT_TOWN",
        }
        for index, (section_id, _, _, _) in enumerate(REVIEWED_ALIASES):
            for field, replacement in mutations.items():
                with self.subTest(section_id=section_id, field=field):
                    compatibility = copy.deepcopy(self.compatibility)
                    compatibility["reviewed_codecs"]["aliases"][index][field] = (
                        replacement
                    )
                    result = self.validate(compatibility=compatibility)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("reviewed map-section aliases changed", result.stderr)

    def test_real_consumer_reference_to_incomplete_shell_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = Path(temporary) / "wild_encounters.json"
            consumer.write_text(
                json.dumps({"encounters": [{"map": "MAP_JOHTO_INDIGO_PLATEAU"}]}),
                encoding="utf-8",
            )
            compatibility = copy.deepcopy(self.compatibility)
            compatibility["persistent_consumer_sources"].append(str(consumer))
            result = self.validate(compatibility=compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "persistent consumer section 'MAPSEC_JOHTO_INDIGO_PLATEAU'",
            result.stderr,
        )

    def test_real_consumer_reference_to_unknown_section_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            consumer = Path(temporary) / "destination.c"
            consumer.write_text("MAPSEC_NOT_REGISTERED\n", encoding="utf-8")
            compatibility = copy.deepcopy(self.compatibility)
            compatibility["persistent_consumer_sources"].append(str(consumer))
            result = self.validate(compatibility=compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "names unknown map section 'MAPSEC_NOT_REGISTERED'", result.stderr
        )

    def test_persistent_consumer_inventory_cannot_drop_a_source(self) -> None:
        compatibility = copy.deepcopy(self.compatibility)
        compatibility["persistent_consumer_sources"].remove(
            "src/data/wild_encounters.json"
        )
        result = self.validate(compatibility=compatibility)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("persistent consumer inventory dropped source", result.stderr)

    def test_reviewed_codec_manifest_mutations_are_rejected(self) -> None:
        for field, replacement in (("first", None), ("last", 250)):
            with self.subTest(field=field):
                compatibility = copy.deepcopy(self.compatibility)
                compatibility["reviewed_codecs"]["exact"][field] = replacement
                result = self.validate(compatibility=compatibility)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("reviewed exact", result.stderr)

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
            self.assertIn(
                "\t.4byte 2\n\t.4byte Route101_MapConnectionsList", connections
            )
            self.assertEqual(connections.count("\tconnection "), 2)

    def test_filtered_standalone_connections_clear_header_pointer_and_count(
        self,
    ) -> None:
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
            self.assertIn(
                "\t.4byte 0\n\t.4byte Route101_MapConnectionsList", connections
            )
            self.assertNotIn("\tconnection ", connections)


if __name__ == "__main__":
    unittest.main()
