from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).parents[1] / "import.py"
SPEC = importlib.util.spec_from_file_location("johto_import", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
johto_import = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = johto_import
SPEC.loader.exec_module(johto_import)


class AttributeFormatTests(unittest.TestCase):
    def test_accepts_u16_and_u32_cardinalities(self):
        self.assertEqual(
            johto_import.attribute_format(16 * 7, 2 * 7),
            "METATILE_ATTRIBUTES_EMERALD_U16",
        )
        self.assertEqual(
            johto_import.attribute_format(16 * 7, 4 * 7),
            "METATILE_ATTRIBUTES_FRLG_U32",
        )

    def test_rejects_non_integral_metatiles_and_wrong_width(self):
        for metatiles, attributes in ((0, 0), (17, 2), (160, 30)):
            with self.subTest(metatiles=metatiles, attributes=attributes):
                with self.assertRaises(johto_import.ImportError):
                    johto_import.attribute_format(metatiles, attributes)


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.rules = johto_import.AuthorityRules(
            ("maps", "layout-binaries"),
            ("maps/NewBarkTown/warp_events/4/dest_map",),
        )

    def test_hns_wins_for_content_and_mechanical_wins_for_exact_adaptation(self):
        self.assertEqual(
            johto_import.authoritative_value(
                "maps/Route29/scripts", "HnS", "PKMN", self.rules
            ),
            "HnS",
        )
        self.assertEqual(
            johto_import.authoritative_value(
                "maps/NewBarkTown/warp_events/4/dest_map",
                "MAP_WORLD_HUB",
                "MAP_LAB",
                self.rules,
            ),
            "MAP_LAB",
        )

    def test_unclassified_divergence_fails_closed(self):
        with self.assertRaisesRegex(
            johto_import.ImportError, "unclassified donor divergence"
        ):
            johto_import.authoritative_value("unknown/new-field", 1, 2, self.rules)

    def test_mechanical_adaptation_must_match_exact_path(self):
        self.assertEqual(
            johto_import.authoritative_value(
                "maps/NewBarkTown/warp_events/5/dest_map",
                "MAP_WORLD_HUB",
                "MAP_LAB",
                self.rules,
            ),
            "MAP_WORLD_HUB",
        )


class EvidenceTests(unittest.TestCase):
    def test_source_digest_is_deterministic_and_excludes_disposable_trees(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "z").write_bytes(b"last")
            (root / "a").write_bytes(b"first")
            (root / "build").mkdir()
            (root / "build/ignored").write_bytes(b"ignored")
            first = johto_import.source_tree_records(root)
            second = johto_import.source_tree_records(root)
            self.assertEqual([item["path"] for item in first], ["a", "z"])
            self.assertEqual(
                johto_import.records_digest(first), johto_import.records_digest(second)
            )

    def test_malformed_pin_and_digest_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "evidence").write_text("x")
            malformed = johto_import.DonorPin("fixture", "short", "0" * 64, 1)
            with self.assertRaisesRegex(johto_import.ImportError, "malformed pin"):
                johto_import.authenticate_donor(root, malformed)
            mismatch = johto_import.DonorPin("fixture", "a" * 40, "0" * 64, 1)
            with self.assertRaisesRegex(johto_import.ImportError, "digest mismatch"):
                johto_import.authenticate_donor(root, mismatch)


class InventoryTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> None:
        (root / "data/layouts").mkdir(parents=True)
        (root / "data/maps/JohtoMap").mkdir(parents=True)
        (root / "data/maps/HoennMap").mkdir(parents=True)
        layouts = {
            "layouts": [
                {
                    "id": "LAYOUT_JOHTO",
                    "name": "Johto_Layout",
                    "layout_version": "johto",
                    "primary_tileset": "gTileset_Johto",
                    "secondary_tileset": "gTileset_House",
                },
                {
                    "id": "LAYOUT_HOENN",
                    "name": "Hoenn_Layout",
                    "layout_version": "emerald",
                    "primary_tileset": "gTileset_General",
                    "secondary_tileset": "gTileset_House",
                },
            ]
        }
        (root / "data/layouts/layouts.json").write_text(json.dumps(layouts))
        (root / "data/maps/JohtoMap/map.json").write_text(
            json.dumps(
                {
                    "id": "MAP_JOHTO",
                    "name": "JohtoMap",
                    "layout": "LAYOUT_JOHTO",
                    "region_map_section": "MAPSEC_JOHTO",
                }
            )
        )
        (root / "data/maps/HoennMap/map.json").write_text(
            json.dumps(
                {
                    "id": "MAP_HOENN",
                    "name": "HoennMap",
                    "layout": "LAYOUT_HOENN",
                    "region_map_section": "MAPSEC_HOENN",
                }
            )
        )
        groups = {
            "group_order": [
                "before",
                "gMapGroup_JohtoTownsAndRoutes",
                "gMapGroup_IndoorNewBark",
                "gMapGroup_RegionHub",
            ],
            "before": ["HoennMap"],
            "gMapGroup_JohtoTownsAndRoutes": ["JohtoMap"],
            "gMapGroup_IndoorNewBark": [],
            "gMapGroup_RegionHub": ["JohtoMap"],
        }
        (root / "data/maps/map_groups.json").write_text(json.dumps(groups))

    def test_selection_is_by_johto_layout_and_group_slots_exclude_region_hub(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fixture(root)
            inventory, maps, _layouts = johto_import.discover_inventory(root)
            self.assertEqual(inventory.maps, ("JohtoMap",))
            self.assertEqual(
                inventory.groups,
                ("gMapGroup_IndoorNewBark", "gMapGroup_JohtoTownsAndRoutes"),
            )
            self.assertNotIn("HoennMap", maps)

    def test_count_and_digest_drift_fail(self):
        inventory = johto_import.Inventory(("A",), ("L",), ("G",), ("S",), ("T",))
        expected = {
            field: {
                "count": 1,
                "digest": johto_import.inventory_digest(getattr(inventory, field)),
            }
            for field in ("maps", "layouts", "groups", "sections", "tilesets")
        }
        expected["maps"]["count"] = 2
        with self.assertRaisesRegex(johto_import.ImportError, "maps count drift"):
            johto_import.validate_expected_inventory(inventory, expected)

    def test_duplicate_layout_ids_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_fixture(root)
            path = root / "data/layouts/layouts.json"
            data = json.loads(path.read_text())
            data["layouts"].append(copy.deepcopy(data["layouts"][0]))
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(
                johto_import.ImportError, "duplicate Johto layout id"
            ):
                johto_import.discover_inventory(root)


class ClosureValidationTests(unittest.TestCase):
    def maps(self):
        return [
            {
                "id": "MAP_A",
                "name": "A",
                "connections": [{"map": "MAP_B"}, {"map": "MAP_OUT"}],
                "warp_events": [],
            },
            {
                "id": "MAP_B",
                "name": "B",
                "connections": None,
                "warp_events": [{"dest_map": "MAP_A"}],
            },
        ]

    def test_undeclared_outbound_edge_fails(self):
        retained = [
            {
                "source": "A",
                "path": "connections/0",
                "kind": "connection",
                "destination": "MAP_B",
            },
            {
                "source": "B",
                "path": "warp_events/0",
                "kind": "warp",
                "destination": "MAP_A",
            },
        ]
        with self.assertRaisesRegex(
            johto_import.ImportError, "undeclared outbound edge"
        ):
            johto_import.validate_edges(self.maps(), retained, [])

    def test_reviewed_outbound_and_retained_edges_pass_exactly(self):
        retained = [
            {
                "source": "A",
                "path": "connections/0",
                "kind": "connection",
                "destination": "MAP_B",
            },
            {
                "source": "B",
                "path": "warp_events/0",
                "kind": "warp",
                "destination": "MAP_A",
            },
        ]
        deferred = [
            {
                "source": "A",
                "path": "connections/1",
                "kind": "connection",
                "destination": "MAP_OUT",
            }
        ]
        self.assertEqual(
            johto_import.validate_edges(self.maps(), retained, deferred),
            (("A", "connection", "MAP_OUT"),),
        )

    def test_missing_recursive_include_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_dir = root / "data/maps/A"
            map_dir.mkdir(parents=True)
            (map_dir / "map.json").write_text("{}")
            (map_dir / "scripts.inc").write_text('.include "data/missing.inc"\n')
            with self.assertRaisesRegex(
                johto_import.ImportError, "missing recursively referenced"
            ):
                johto_import.referenced_symbols(root, [{"name": "A"}])

    def test_missing_map_local_symbol_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_dir = root / "data/maps/A"
            map_dir.mkdir(parents=True)
            (map_dir / "map.json").write_text(
                json.dumps({"object_events": [{"script": "A_EventScript_Missing"}]})
            )
            definitions, _records = johto_import.referenced_symbols(
                root, [{"name": "A"}]
            )
            self.assertNotIn("A_EventScript_Missing", definitions)
            with self.assertRaisesRegex(johto_import.ImportError, "missing symbols"):
                johto_import.validate_map_local_symbols(
                    root, [{"name": "A"}], definitions
                )

    def test_recursive_asm_label_definition_satisfies_map_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            map_dir = root / "data/maps/A"
            include = root / "data/shared.inc"
            map_dir.mkdir(parents=True)
            (map_dir / "map.json").write_text(
                json.dumps({"object_events": [{"script": "A_EventScript_Defined"}]})
            )
            (map_dir / "scripts.inc").write_text('.include "data/shared.inc"\n')
            include.write_text("A_EventScript_Defined::\n\tend\n")
            definitions, records = johto_import.referenced_symbols(
                root, [{"name": "A"}]
            )
            self.assertIn("A_EventScript_Defined", definitions)
            self.assertIn("data/shared.inc", {item["path"] for item in records})
            johto_import.validate_map_local_symbols(root, [{"name": "A"}], definitions)

    def test_effective_edges_start_from_hns_and_overlay_only_exact_adaptations(self):
        with tempfile.TemporaryDirectory() as directory:
            hns = Path(directory)
            map_dir = hns / "data/maps/A"
            map_dir.mkdir(parents=True)
            (map_dir / "map.json").write_text(
                json.dumps(
                    {
                        "id": "MAP_A",
                        "name": "A",
                        "connections": [{"map": "MAP_HNS_OUT"}],
                        "warp_events": [],
                    }
                )
            )
            mechanical = {
                "A": {
                    "id": "MAP_A",
                    "name": "A",
                    "connections": [{"map": "MAP_MECHANICAL_OUT"}],
                    "warp_events": [],
                }
            }
            selection = [{"name": "A"}]
            effective = johto_import.effective_selected_maps(
                selection, mechanical, hns, []
            )
            self.assertEqual(effective[0]["connections"][0]["map"], "MAP_HNS_OUT")
            with self.assertRaisesRegex(
                johto_import.ImportError, "undeclared outbound edge"
            ):
                johto_import.validate_edges(effective, [], [])
            adaptation = [
                {
                    "source": "A",
                    "path": "connections/0/map",
                    "mechanical": "MAP_MECHANICAL_OUT",
                }
            ]
            effective = johto_import.effective_selected_maps(
                selection, mechanical, hns, adaptation
            )
            self.assertEqual(
                effective[0]["connections"][0]["map"], "MAP_MECHANICAL_OUT"
            )

    def test_duplicate_layout_allocations_fail(self):
        selection = [
            {"targetGroup": "G", "targetLayoutIndex": 785, "targetSection": 209},
            {"targetGroup": "G", "targetLayoutIndex": 785, "targetSection": 209},
        ]
        with self.assertRaisesRegex(johto_import.ImportError, "duplicate allocation"):
            johto_import._validate_allocations(
                selection, {"groupAllocations": [], "sectionAllocations": []}
            )

    def test_allocation_name_group_membership_and_section_mapping_mutations_fail(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        mutations = []
        duplicate_name = copy.deepcopy(manifest)
        duplicate_name["groupAllocations"][1]["name"] = duplicate_name[
            "groupAllocations"
        ][0]["name"]
        mutations.append((duplicate_name, "duplicate allocation: group name"))
        unknown_group = copy.deepcopy(manifest)
        unknown_group["selection"]["maps"][0]["targetGroup"] = "gMapGroup_Unknown"
        mutations.append((unknown_group, "unallocated targetGroup"))
        wrong_section = copy.deepcopy(manifest)
        wrong_section["selection"]["maps"][0]["targetSection"] = 210
        mutations.append((wrong_section, "section allocation mismatch"))
        for changed, message in mutations:
            with self.subTest(message=message):
                with self.assertRaisesRegex(johto_import.ImportError, message):
                    johto_import._validate_allocations(
                        changed["selection"]["maps"], changed
                    )


class AtomicOutputTests(unittest.TestCase):
    def test_atomic_write_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "closure.json"
            value = {"z": 1, "a": [2, 3]}
            payload = johto_import._dump(value).encode()
            johto_import.atomic_write(output, payload)
            first = output.read_bytes()
            johto_import.atomic_write(output, payload)
            self.assertEqual(first, output.read_bytes())

    def test_atomic_failure_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "closure.json"
            output.write_bytes(b"old")
            with mock.patch.object(
                johto_import.os, "replace", side_effect=OSError("boom")
            ):
                with self.assertRaises(OSError):
                    johto_import.atomic_write(output, b"new")
            self.assertEqual(output.read_bytes(), b"old")
            self.assertEqual(list(output.parent.glob(".closure.json.*.tmp")), [])


class PinnedDonorIntegrationTests(unittest.TestCase):
    def donor_paths(self):
        repo = Path(__file__).parents[3]
        return (
            repo.parents[2] / ".references/PKMN-World",
            repo.parents[2] / ".references/pokemonHnS",
        )

    def test_manifest_commit_cannot_mutate_away_from_reviewed_binding(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        manifest["mechanicalDonor"]["commit"] = "a" * 40
        with self.assertRaisesRegex(johto_import.ImportError, "immutable reviewed"):
            johto_import._pin(manifest, "mechanicalDonor", "PKMN-World")

    def test_route28_fixture_identity_and_declared_path_mutations_fail(self):
        pkmn_world, _hns = self.donor_paths()
        if not pkmn_world.is_dir():
            self.skipTest("pinned donor checkout is unavailable")
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        wrong_label = copy.deepcopy(manifest)
        wrong_label["attributeFixtures"][0]["tileset"] = "gTileset_Fake"
        with self.assertRaisesRegex(johto_import.ImportError, "LAYOUT_ROUTE28"):
            johto_import.validate_route28_widths(pkmn_world, wrong_label)
        wrong_path = copy.deepcopy(manifest)
        wrong_path["attributeFixtures"][1]["metatiles"] = wrong_path[
            "attributeFixtures"
        ][0]["metatiles"]
        with self.assertRaisesRegex(johto_import.ImportError, "tileset declarations"):
            johto_import.validate_route28_widths(pkmn_world, wrong_path)

    def test_pinned_donors_and_complete_selected_closure_pass(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkouts are unavailable")
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        inventory, closure, evidence = johto_import.build_closure(
            manifest, pkmn_world, hns
        )
        self.assertEqual(
            (
                len(inventory.maps),
                len(inventory.layouts),
                len(inventory.groups),
                len(inventory.sections),
                len(inventory.tilesets),
            ),
            (254, 255, 25, 58, 71),
        )
        self.assertEqual(len(closure.maps), 16)
        self.assertEqual(len(closure.layouts), 16)
        self.assertEqual(len(closure.groups), 5)
        self.assertEqual(len(closure.sections), 5)
        self.assertEqual(
            evidence["route28AttributeFormats"],
            {
                "gTileset_Johto_NorthEast": "METATILE_ATTRIBUTES_EMERALD_U16",
                "gTileset_ViridianCity": "METATILE_ATTRIBUTES_FRLG_U32",
            },
        )


if __name__ == "__main__":
    unittest.main()
