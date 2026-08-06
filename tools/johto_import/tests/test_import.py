from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
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

    def test_warp_removals_and_reindexes_fail_closed(self):
        maps = [
            {
                "id": "MAP_GATE",
                "name": "Gate",
                "warp_events": [
                    {"dest_map": "MAP_OUT", "dest_warp_id": "4"},
                    {"dest_map": "MAP_ROUTE", "dest_warp_id": "0"},
                ],
            },
            {
                "id": "MAP_ROUTE",
                "name": "Route",
                "warp_events": [{"dest_map": "MAP_GATE", "dest_warp_id": "1"}],
            },
        ]
        manifest = {
            "deferredEdges": [
                {
                    "source": "Gate",
                    "path": "warp_events/0",
                    "kind": "warp",
                    "destination": "MAP_OUT",
                }
            ],
            "warpRemovals": [
                {
                    "source": "Gate",
                    "path": "warp_events/0",
                    "destination": "MAP_OUT",
                    "destWarpId": "4",
                }
            ],
            "warpReindexes": [
                {
                    "source": "Route",
                    "path": "warp_events/0/dest_warp_id",
                    "destination": "MAP_GATE",
                    "from": "1",
                    "to": "0",
                }
            ],
        }
        johto_import.validate_warp_transforms(manifest, maps)
        for key, message in (
            ("warpRemovals", "warp removal manifest drift"),
            ("warpReindexes", "warp reindex manifest drift"),
        ):
            changed = copy.deepcopy(manifest)
            changed[key] = []
            with self.subTest(key=key):
                with self.assertRaisesRegex(johto_import.ImportError, message):
                    johto_import.validate_warp_transforms(changed, maps)

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

    def test_group_target_ids_control_materialized_numeric_placement(self):
        existing = [f"gMapGroup_{index}" for index in range(75)]
        groups = {"group_order": existing} | {name: [] for name in existing}
        allocations = [
            {"name": "gMapGroup_JohtoA", "targetId": 75},
            {"name": "gMapGroup_JohtoB", "targetId": 76},
        ]
        selection = [
            {
                "name": "MapA",
                "targetGroup": "gMapGroup_JohtoA",
                "targetMember": 0,
            },
            {
                "name": "MapB",
                "targetGroup": "gMapGroup_JohtoB",
                "targetMember": 0,
            },
        ]
        first = johto_import._materialized_group_registry(
            groups, selection, allocations
        )
        swapped = copy.deepcopy(allocations)
        swapped[0]["targetId"], swapped[1]["targetId"] = (
            swapped[1]["targetId"],
            swapped[0]["targetId"],
        )
        second = johto_import._materialized_group_registry(groups, selection, swapped)
        self.assertEqual(
            first["group_order"][75:], ["gMapGroup_JohtoA", "gMapGroup_JohtoB"]
        )
        self.assertEqual(
            second["group_order"][75:], ["gMapGroup_JohtoB", "gMapGroup_JohtoA"]
        )


class AtomicOutputTests(unittest.TestCase):
    def test_locked_layout_ids_exactly_partition_discovered_inventory(self):
        lock = {"layouts": [{"id": "LAYOUT_A"}, {"id": "LAYOUT_B"}]}
        johto_import._validate_locked_layout_inventory(lock, ("LAYOUT_A", "LAYOUT_B"))
        for changed in (
            {"layouts": [{"id": "LAYOUT_A"}, {"id": "LAYOUT_A"}]},
            {"layouts": [{"id": "LAYOUT_A"}, {"id": "LAYOUT_C"}]},
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(
                    johto_import.ImportError, "do not partition"
                ):
                    johto_import._validate_locked_layout_inventory(
                        changed, ("LAYOUT_A", "LAYOUT_B")
                    )

    def test_layout_and_group_emission_honor_locked_positions_not_input_order(self):
        layouts = johto_import._append_layouts_at_locked_indices(
            [{"id": "BASE"}],
            [(2, {"id": "LAYOUT_B"}), (1, {"id": "LAYOUT_A"})],
        )
        self.assertEqual(
            [item["id"] for item in layouts], ["BASE", "LAYOUT_A", "LAYOUT_B"]
        )
        groups = {
            "group_order": ["gMapGroup_Base"],
            "gMapGroup_Base": [],
        }
        emitted = johto_import._materialized_group_registry(
            groups,
            [
                {"name": "MapB", "targetGroup": "gMapGroup_New", "targetMember": 1},
                {"name": "MapA", "targetGroup": "gMapGroup_New", "targetMember": 0},
            ],
            [{"name": "gMapGroup_New", "targetId": 1}],
        )
        self.assertEqual(emitted["gMapGroup_New"], ["MapA", "MapB"])

    def test_active_layout_selection_includes_mapless_orphan_at_locked_index(self):
        root = Path(__file__).parents[1]
        manifest = johto_import.load_manifest(root / "import_manifest.json")
        lock = johto_import._json(root / "allocation_lock.json")
        manifest["activeBatches"] = list(johto_import.BATCH_ORDER[:5])
        layouts = johto_import.active_layout_selection(manifest, lock)
        orphan = next(
            item for item in layouts if item["id"] == "LAYOUT_TIN_TOWER_ROOF_NIGHT"
        )
        self.assertEqual(orphan["targetIndex"], 907)
        self.assertFalse(any(item["layout"] == orphan["id"] for item in lock["maps"]))

    def test_active_selection_is_sorted_by_locked_layout_index(self):
        manifest = {
            "activeBatches": ["baseline"],
        }
        lock = {
            "maps": [
                {"name": "B", "batch": "baseline", "targetLayoutIndex": 786},
                {"name": "A", "batch": "baseline", "targetLayoutIndex": 785},
            ]
        }
        self.assertEqual(
            [item["name"] for item in johto_import.active_selection(manifest, lock)],
            ["A", "B"],
        )

    def test_residency_profile_strips_gameplay_but_keeps_spatial_edges(self):
        source = {
            "object_events": [{"script": "Npc"}],
            "coord_events": [{"script": "Story"}],
            "bg_events": [{"script": "Item"}],
            "warp_events": [{"dest_map": "MAP_B", "dest_warp_id": "0"}],
        }
        actual = johto_import.materialize_resident_map(source)
        self.assertEqual(actual["object_events"], [])
        self.assertEqual(actual["coord_events"], [])
        self.assertEqual(actual["bg_events"], [])
        self.assertEqual(actual["warp_events"], source["warp_events"])
        self.assertEqual(
            johto_import.resident_map_script("MapA"),
            "MapA_MapScripts::\n\t.byte 0\n",
        )

    def test_frozen_fallback_and_allocations_cover_the_full_inventory(self):
        root = Path(__file__).parents[1]
        manifest = johto_import.load_manifest(root / "import_manifest.json")
        lock = johto_import._json(root / "allocation_lock.json")
        self.assertEqual(
            manifest["contentFallback"]["maps"], list(johto_import.FALLBACK_MAPS)
        )
        self.assertEqual(len(lock["maps"]), 254)
        self.assertEqual(len(lock["layouts"]), 255)
        self.assertEqual(max(item["targetId"] for item in lock["sections"]), 266)
        self.assertEqual(
            sorted(item["targetId"] for item in lock["sections"]),
            list(range(209, 267)),
        )

    def test_allocation_lock_drift_fails_closed(self):
        root = Path(__file__).parents[1]
        lock = johto_import._json(root / "allocation_lock.json")
        lock["sections"][-1]["targetId"] = 265
        with self.assertRaisesRegex(
            johto_import.ImportError, "section allocation-lock drift"
        ):
            johto_import._validate_allocation_lock(lock)

    def test_proposal_is_deterministic(self):
        root = Path(__file__).parents[1]
        manifest = johto_import.load_manifest(root / "import_manifest.json")
        lock = johto_import._json(root / "allocation_lock.json")
        first = johto_import._dump(johto_import.proposal_document(manifest, lock))
        second = johto_import._dump(johto_import.proposal_document(manifest, lock))
        self.assertEqual(first, second)

    def test_preserved_baseline_apply_is_byte_identical(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        manifest["activeBatches"] = ["baseline"]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            sentinel = target / "data/maps/NewBarkTown/map.json"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b"baseline\n")
            before = sentinel.read_bytes()
            johto_import.materialize_source_tree(
                target, manifest, target / "unused-mechanical", target / "unused-hns"
            )
            self.assertEqual(sentinel.read_bytes(), before)

    def test_reapply_restores_residency_section_and_preserves_baseline(self):
        manifest = {
            "selection": {
                "maps": [
                    {
                        "name": "Baseline",
                        "section": "MAPSEC_BASELINE",
                        "materialization": "preserve",
                    },
                    {
                        "name": "Resident",
                        "section": "MAPSEC_RESIDENT",
                        "materialization": "residency",
                    },
                ]
            },
            "sectionAllocations": [
                {"name": "MAPSEC_BASELINE", "targetId": 1},
                {"name": "MAPSEC_RESIDENT", "targetId": 2},
            ],
        }
        baseline = {
            "id": "MAPSEC_BASELINE",
            "value": 1,
            "name": "BASELINE SENTINEL",
            "custom": "preserve byte-for-byte",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, hns = root / "target", root / "hns"
            registry = target / "src/data/region_map/region_map_sections.json"
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps(
                    {
                        "map_section_count": 2,
                        "map_sections": [
                            {"id": "MAPSEC_ORIGINAL", "value": 0},
                            baseline,
                        ],
                    }
                ),
                encoding="utf-8",
            )
            source = hns / "src/data/region_map/region_map_sections_johto.json"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps(
                    {
                        "map_sections": [
                            {
                                "map_section": "MAPSEC_RESIDENT",
                                "name": "RESIDENT",
                                "x": 3,
                                "y": 4,
                                "width": 5,
                                "height": 6,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            johto_import._materialize_section_registry(target, manifest, hns)
            first = registry.read_bytes()
            corrupted_document = json.loads(first)
            corrupted_section = corrupted_document["map_sections"][2]
            corrupted_section.update(
                {
                    "name": "CORRUPTED",
                    "x": 99,
                    "y": 98,
                    "width": 97,
                    "height": 96,
                }
            )
            registry.write_text(json.dumps(corrupted_document), encoding="utf-8")

            johto_import._materialize_section_registry(target, manifest, hns)
            self.assertEqual(registry.read_bytes(), first)
            document = json.loads(registry.read_bytes())
            self.assertEqual(document["map_sections"][1], baseline)
            self.assertEqual(
                [item["id"] for item in document["map_sections"]],
                ["MAPSEC_ORIGINAL", "MAPSEC_BASELINE", "MAPSEC_RESIDENT"],
            )
            self.assertEqual(
                [item["value"] for item in document["map_sections"]], [0, 1, 2]
            )
            self.assertEqual(
                {
                    key: document["map_sections"][2][key]
                    for key in ("name", "x", "y", "width", "height")
                },
                {
                    "name": "RESIDENT",
                    "x": 3,
                    "y": 4,
                    "width": 5,
                    "height": 6,
                },
            )

    def test_mixed_preserve_and_residency_materializes_only_residency_shell(self):
        manifest = {
            "contentFallback": {"maps": []},
            "regionAssignment": {"target": "REGION_JOHTO"},
            "musicAdaptations": [{"hns": "MUS_UNUSED", "target": "MUS_NONE"}],
            "adaptations": [],
            "mapFieldDecisions": [],
            "deferredEdges": [],
            "warpReindexes": [],
            "berryTreeAllocations": [],
            "warpRemovals": [],
            "graphicsAdaptations": [
                {"hns": "OBJ_EVENT_GFX_UNUSED", "target": "OBJ_EVENT_GFX_NONE"}
            ],
        }
        selection = [
            {"name": "Baseline", "materialization": "preserve"},
            {"name": "Resident", "materialization": "residency"},
        ]
        donor_map = {
            "name": "Resident",
            "id": "MAP_RESIDENT",
            "layout": "LAYOUT_RESIDENT",
            "region": "REGION_KANTO",
            "connections": [],
            "object_events": [{"script": "Npc"}],
            "coord_events": [{"script": "Story"}],
            "bg_events": [{"script": "Item"}],
            "warp_events": [{"dest_map": "MAP_BASELINE", "dest_warp_id": "0"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, mechanical, hns = (
                root / "target",
                root / "mechanical",
                root / "hns",
            )
            baseline = target / "data/maps/Baseline/map.json"
            baseline.parent.mkdir(parents=True)
            baseline.write_bytes(b"baseline sentinel\n")
            for authority in (mechanical, hns):
                path = authority / "data/maps/Resident/map.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(donor_map), encoding="utf-8")

            johto_import._materialize_selected_map_trees(
                target, selection, manifest, mechanical, hns
            )

            self.assertEqual(baseline.read_bytes(), b"baseline sentinel\n")
            resident = json.loads(
                (target / "data/maps/Resident/map.json").read_text(encoding="utf-8")
            )
            for key in johto_import.GAMEPLAY_EVENT_KEYS:
                self.assertEqual(resident[key], [])
            self.assertEqual(resident["warp_events"], donor_map["warp_events"])
            self.assertEqual(
                (target / "data/maps/Resident/scripts.inc").read_text(encoding="utf-8"),
                "Resident_MapScripts::\n\t.byte 0\n",
            )

    def test_active_selection_is_derived_from_allocation_lock(self):
        root = Path(__file__).parents[1]
        manifest = johto_import.load_manifest(root / "import_manifest.json")
        lock = johto_import._json(root / "allocation_lock.json")
        manifest["activeBatches"] = ["baseline", "early-violet-ruins"]
        selected = johto_import.active_selection(manifest, lock)
        self.assertEqual(len(selected), 41)
        self.assertEqual(selected[16]["name"], "Route30")
        self.assertEqual(selected[16]["materialization"], "residency")

    def test_trainer_target_id_mutation_keeps_party_and_header_coherent(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        opponent_text = (
            "#define TRAINER_EXISTING 854\n"
            "#define TRAINERS_COUNT_EMERALD 855\n"
            "#define MAX_TRAINERS_COUNT_EMERALD 864\n"
        )
        parties, macros, count = johto_import._trainer_materialization(
            manifest, opponent_text
        )
        changed = copy.deepcopy(manifest)
        changed["trainerPresentation"][0]["targetId"] = 857
        changed["trainerPresentation"][2]["targetId"] = 855
        changed_parties, changed_macros, changed_count = (
            johto_import._trainer_materialization(changed, opponent_text)
        )
        self.assertEqual((count, changed_count), (858, 858))
        self.assertIn("#define TRAINER_RIVAL_CHIKORITA_1 855", macros)
        self.assertIn("#define TRAINER_RIVAL_CHIKORITA_1 857", changed_macros)
        self.assertLess(
            parties.index("TRAINER_RIVAL_CHIKORITA_1"),
            parties.index("TRAINER_RIVAL_TOTODILE_1"),
        )
        self.assertLess(
            changed_parties.index("TRAINER_RIVAL_TOTODILE_1"),
            changed_parties.index("TRAINER_RIVAL_CHIKORITA_1"),
        )

    def test_trainer_output_uses_target_parser_language_and_record_terminator(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        opponent_text = (
            "#define TRAINER_EXISTING 854\n"
            "#define TRAINERS_COUNT_EMERALD 855\n"
            "#define MAX_TRAINERS_COUNT_EMERALD 864\n"
        )
        parties, _macros, _count = johto_import._trainer_materialization(
            manifest, opponent_text
        )

        self.assertEqual(parties.count("Double Battle: No"), 3)
        self.assertNotIn("Battle Type:", parties)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "trainers.party"
            output.write_text("baseline\n")
            johto_import._replace_generated_section(
                output,
                "rival trainers",
                parties,
                blank_line_before_end=True,
                preprocessor_markers=True,
            )
            self.assertIn(
                "IVs: 0 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\n\n"
                "#endif /* // JOHTO IMPORT END: rival trainers */\n",
                output.read_text(),
            )

    def test_trainer_output_rejects_unknown_battle_type(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        manifest["trainerPresentation"][0]["battleType"] = "Rotation"
        opponent_text = (
            "#define TRAINER_EXISTING 854\n"
            "#define TRAINERS_COUNT_EMERALD 855\n"
            "#define MAX_TRAINERS_COUNT_EMERALD 864\n"
        )

        with self.assertRaisesRegex(
            johto_import.ImportError, "unsupported trainer presentation battleType"
        ):
            johto_import._trainer_materialization(manifest, opponent_text)

    def test_materialized_text_normalization_is_focused_and_idempotent(self):
        donor_text = "label:  \n\t\n\tcommand  value \t\n\n"
        expected = "label:\n\n\tcommand  value\n"

        normalized = johto_import.normalize_materialized_text(donor_text)

        self.assertEqual(normalized, expected)
        self.assertEqual(johto_import.normalize_materialized_text(normalized), expected)

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


class ScriptSubstitutionTests(unittest.TestCase):
    def test_phase3_substitutions_materialize_supported_commands_and_labels(self):
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        scripts = {
            "NewBarkTown": (
                "NewBarkTown_EventScript_TestMan1::\n"
                "\tgivebp 4\n"
                "\tmsgbox BattleFrontier_Text_ObtainedXBattlePoints, MSGBOX_GETPOINTS\n"
            ),
            "NewBarkTown_Lab": "\n".join(
                [
                    *["\tbuffermoncategory STR_VAR_2, PLAYER_STARTER_SPECIES"] * 3,
                    *["\tcallnative DisableStaticRandomizer"] * 3,
                    *["\tcallnative EnableStaticRandomizer"] * 2,
                    "\tsetmetatile 7, 1, METATILE_R26_21_Broken_Window, TRUE",
                ]
            ),
            "Route29": "\n".join(
                [
                    *["\tapplymovement2 OBJ_EVENT_ID_CAMERA, Common_Movement_WalkUp1"]
                    * 4,
                    *["\tapplymovement2 OBJ_EVENT_ID_CAMERA, Common_Movement_WalkDown1"]
                    * 4,
                    "\tapplymovement2 OBJ_EVENT_ID_PLAYER, Common_Movement_WalkDown1",
                ]
            ),
        }
        phase3_old = {
            "givebp 4",
            "buffermoncategory STR_VAR_2, PLAYER_STARTER_SPECIES",
            "applymovement2",
            "Common_Movement_WalkUp1",
            "Common_Movement_WalkDown1",
            "callnative DisableStaticRandomizer",
            "callnative EnableStaticRandomizer",
            "setmetatile 7, 1, METATILE_R26_21_Broken_Window, TRUE",
        }
        for rule in manifest["scriptSubstitutions"]:
            source = rule["source"]
            if source not in scripts or rule["old"] not in phase3_old:
                continue
            scripts[source] = johto_import._apply_script_substitution(
                source,
                scripts[source],
                rule["old"],
                rule["new"],
                rule["occurrences"],
            )

        self.assertNotIn("givebp", scripts["NewBarkTown"])
        self.assertIn(
            "@ HnS Battle Point test grant is outside the resident slice\n"
            "\tmsgbox BattleFrontier_Text_ObtainedXBattlePoints, MSGBOX_GETPOINTS",
            scripts["NewBarkTown"],
        )
        self.assertEqual(
            scripts["NewBarkTown_Lab"].count(
                "bufferstring STR_VAR_2, gText_EmptyString2"
            ),
            3,
        )
        self.assertNotIn("buffermoncategory", scripts["NewBarkTown_Lab"])
        self.assertNotIn("DisableStaticRandomizer", scripts["NewBarkTown_Lab"])
        self.assertNotIn("EnableStaticRandomizer", scripts["NewBarkTown_Lab"])
        self.assertNotIn("METATILE_R26_21_Broken_Window", scripts["NewBarkTown_Lab"])
        self.assertEqual(
            scripts["NewBarkTown_Lab"].count(
                "Static randomizer control is unavailable; dormant starter story needs no state change"
            ),
            5,
        )
        self.assertIn(
            "Police episode and its out-of-layout", scripts["NewBarkTown_Lab"]
        )
        self.assertEqual(scripts["Route29"].count("\tapplymovement "), 9)
        self.assertNotIn("applymovement2", scripts["Route29"])
        self.assertNotIn("Common_Movement_WalkUp1", scripts["Route29"])
        self.assertNotIn("Common_Movement_WalkDown1", scripts["Route29"])

    def test_script_substitution_count_mutation_fails_closed(self):
        with self.assertRaisesRegex(
            johto_import.ImportError,
            "script substitution drift: Route29/'applymovement2': expected 9, got 8",
        ):
            johto_import._apply_script_substitution(
                "Route29", "applymovement2\n" * 8, "applymovement2", "applymovement", 9
            )

    def test_randomizer_substitution_count_mutation_fails_closed(self):
        with self.assertRaisesRegex(
            johto_import.ImportError,
            "expected 3, got 2",
        ):
            johto_import._apply_script_substitution(
                "NewBarkTown_Lab",
                "callnative DisableStaticRandomizer\n" * 2,
                "callnative DisableStaticRandomizer",
                "@ no-op",
                3,
            )


class BerryTreeAllocationTests(unittest.TestCase):
    BERRY_BASELINE = """\
#define BERRY_TREE_ROUTE_123_SITRUS   88
#define BERRY_TREE_ROUTE_123_RAWST    89

// Remainder are unused

#define BERRY_TREES_COUNT 128

#endif // GUARD_CONSTANTS_BERRY_H
"""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.hns = Path(self.directory.name)
        map_dir = self.hns / "data/maps/Route29"
        map_dir.mkdir(parents=True)
        events = [{} for _ in range(16)]
        events[15]["trainer_sight_or_berry_tree_id"] = "BERRY_TREE_ORAN_1"
        (map_dir / "map.json").write_text(json.dumps({"object_events": events}))
        self.manifest = {
            "selection": {"maps": [{"name": "Route29"}]},
            "berryTreeAllocations": [
                {
                    "source": "Route29",
                    "path": "object_events/15/trainer_sight_or_berry_tree_id",
                    "hns": "BERRY_TREE_ORAN_1",
                    "target": "BERRY_TREE_ROUTE_29_ORAN_1",
                    "targetId": 90,
                }
            ],
        }

    def tearDown(self):
        self.directory.cleanup()

    def test_allocation_appends_at_first_unused_target_id(self):
        self.assertEqual(
            johto_import._berry_tree_materialization(
                self.manifest, self.BERRY_BASELINE, self.hns
            ),
            "#define BERRY_TREE_ROUTE_29_ORAN_1          90",
        )

    def test_allocation_rejects_donor_drift_and_target_collisions(self):
        drifted = copy.deepcopy(self.manifest)
        drifted["berryTreeAllocations"][0]["hns"] = "BERRY_TREE_ORAN_2"
        with self.assertRaisesRegex(johto_import.ImportError, "allocation drift"):
            johto_import._berry_tree_materialization(
                drifted, self.BERRY_BASELINE, self.hns
            )

        collided = copy.deepcopy(self.manifest)
        collided["berryTreeAllocations"][0]["targetId"] = 89
        with self.assertRaisesRegex(johto_import.ImportError, "must append"):
            johto_import._berry_tree_materialization(
                collided, self.BERRY_BASELINE, self.hns
            )

        name_collision = self.BERRY_BASELINE.replace(
            "#define BERRY_TREE_ROUTE_123_RAWST    89",
            "#define BERRY_TREE_ROUTE_29_ORAN_1   89",
        )
        with self.assertRaisesRegex(johto_import.ImportError, "name collision"):
            johto_import._berry_tree_materialization(
                self.manifest, name_collision, self.hns
            )


class GeneratedSectionTests(unittest.TestCase):
    MARKER = "#endif // GUARD_FIXTURE_H"

    def test_guarded_section_is_inserted_before_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.h"
            output.write_text(
                f"#ifndef GUARD_FIXTURE_H\n#define VALUE 1\n\n{self.MARKER}\n"
            )

            johto_import._replace_generated_section_before(
                output, "fixture", "#define IMPORTED 2", self.MARKER
            )

            text = output.read_text()
            self.assertLess(
                text.index("// JOHTO IMPORT BEGIN"), text.index(self.MARKER)
            )
            self.assertTrue(text.endswith(f"{self.MARKER}\n"))

    def test_guarded_section_replacement_is_idempotent_and_moves_inside_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.h"
            output.write_text(
                f"#ifndef GUARD_FIXTURE_H\n{self.MARKER}\n\n"
                "// JOHTO IMPORT BEGIN: fixture\n#define OLD 1\n"
                "// JOHTO IMPORT END: fixture\n"
            )

            johto_import._replace_generated_section_before(
                output, "fixture", "#define IMPORTED 2", self.MARKER
            )
            first = output.read_bytes()
            johto_import._replace_generated_section_before(
                output, "fixture", "#define IMPORTED 2", self.MARKER
            )

            self.assertEqual(output.read_bytes(), first)
            text = first.decode()
            self.assertEqual(text.count("// JOHTO IMPORT BEGIN: fixture"), 1)
            self.assertLess(text.index("#define IMPORTED 2"), text.index(self.MARKER))

    def test_guarded_section_requires_one_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.h"
            for contents in ("#define VALUE 1\n", f"{self.MARKER}\n{self.MARKER}\n"):
                with self.subTest(contents=contents):
                    output.write_text(contents)
                    with self.assertRaisesRegex(
                        johto_import.ImportError, "exactly one placement marker"
                    ):
                        johto_import._replace_generated_section_before(
                            output, "fixture", "#define IMPORTED 2", self.MARKER
                        )

    def test_unguarded_section_rejects_unmatched_or_duplicate_markers(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "fixture.s"
            begin = "// JOHTO IMPORT BEGIN: fixture"
            end = "// JOHTO IMPORT END: fixture"
            for contents in (
                f"{begin}\n",
                f"{end}\n",
                f"{begin}\n{end}\n{begin}\n{end}\n",
            ):
                with self.subTest(contents=contents):
                    output.write_text(contents)
                    with self.assertRaisesRegex(
                        johto_import.ImportError, "ambiguous generated section"
                    ):
                        johto_import._replace_generated_section(
                            output, "fixture", "imported"
                        )

    def test_tileset_copy_prunes_excluded_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            (source / "tiles.png").write_bytes(b"new")
            (destination / "anim").mkdir(parents=True)
            (destination / "stale.inc").write_text("stale")
            (destination / "anim" / "stale.bin").write_bytes(b"stale")
            johto_import._copy_tree_without_generated(source, destination)
            self.assertEqual((destination / "tiles.png").read_bytes(), b"new")
            self.assertFalse((destination / "stale.inc").exists())
            self.assertFalse((destination / "anim").exists())

    def test_imported_tileset_copy_never_overwrites_a_preexisting_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, destination = root / "source", root / "destination"
            source.mkdir()
            destination.mkdir()
            (source / "tiles.png").write_bytes(b"donor")
            (destination / "tiles.png").write_bytes(b"target")

            with self.assertRaisesRegex(
                johto_import.ImportError, "refusing to overwrite pre-existing"
            ):
                johto_import._copy_imported_tileset_tree(source, destination)
            self.assertEqual((destination / "tiles.png").read_bytes(), b"target")

            (destination / "tiles.png").write_bytes(b"donor")
            johto_import._copy_imported_tileset_tree(source, destination)
            self.assertEqual((destination / "tiles.png").read_bytes(), b"donor")


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

    def test_fallback_and_mechanical_field_decisions_are_applied(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkouts are unavailable")
        root = Path(__file__).parents[1]
        manifest = johto_import.load_manifest(root / "import_manifest.json")
        lock = johto_import._json(root / "allocation_lock.json")
        _inventory, maps, layouts = johto_import.discover_inventory(pkmn_world)
        johto_import.validate_authority_decisions(
            manifest, maps, layouts, pkmn_world, hns
        )

        fallback = next(
            item for item in lock["maps"] if item["name"] == "JohtoIndigoPlateau"
        )
        fallback_map = johto_import._materialized_map(
            fallback, pkmn_world, hns, manifest
        )
        self.assertEqual(fallback_map["id"], "MAP_JOHTO_INDIGO_PLATEAU")

        reception = next(
            item for item in lock["maps"] if item["name"] == "ReceptionGate"
        )
        reception_map = johto_import._materialized_map(
            reception, pkmn_world, hns, manifest
        )
        self.assertEqual(
            reception_map["region_map_section"], "MAPSEC_JOHTO_VICTORY_ROAD"
        )

        department_store = next(
            item
            for item in lock["maps"]
            if item["layout"] == "LAYOUT_GOLDENROD_CITY_DEPARTMENT_STORE_1F"
        )
        layout = johto_import._materialized_layout(
            department_store, layouts, manifest, pkmn_world, hns
        )
        self.assertEqual(
            layout["secondary_tileset"], "gTileset_GoldenrodDepartmentStore"
        )

        route34_day_care = next(
            item for item in lock["maps"] if item["layout"] == "LAYOUT_ROUTE34_DAY_CARE"
        )
        layout = johto_import._materialized_layout(
            route34_day_care, layouts, manifest, pkmn_world, hns
        )
        self.assertEqual(layout["secondary_tileset"], "gTileset_JohtoPokemonDayCare")

        drifted = copy.deepcopy(manifest)
        drifted["mapFieldDecisions"][0]["mechanical"] = "MAPSEC_VICTORY_ROAD"
        with self.assertRaisesRegex(
            johto_import.ImportError, "map-field decision drift"
        ):
            johto_import.validate_authority_decisions(
                drifted, maps, layouts, pkmn_world, hns
            )

    def test_all_fallback_maps_and_scripts_resolve_only_from_pkmn_world(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkouts are unavailable")
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        lock = johto_import._json(Path(__file__).parents[1] / "allocation_lock.json")
        missing_hns = hns / "does-not-exist"
        for name in johto_import.FALLBACK_MAPS:
            with self.subTest(name=name):
                map_item, script = johto_import._content_map_and_script(
                    name, manifest, pkmn_world, missing_hns
                )
                self.assertEqual(map_item["name"], name)
                self.assertIsInstance(script, str)
        fallback_selection = [
            item for item in lock["maps"] if item["name"] in johto_import.FALLBACK_MAPS
        ]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            johto_import._materialize_selected_map_trees(
                target,
                fallback_selection,
                manifest,
                pkmn_world,
                missing_hns,
            )
            for name in johto_import.FALLBACK_MAPS:
                with self.subTest(materialized=name):
                    map_item = json.loads(
                        (target / "data/maps" / name / "map.json").read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(map_item["name"], name)
                    self.assertEqual(
                        (target / "data/maps" / name / "scripts.inc").read_text(
                            encoding="utf-8"
                        ),
                        johto_import.resident_map_script(name),
                    )

    def test_mapless_orphan_layout_and_binaries_exist_in_content_authority(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkouts are unavailable")
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        _inventory, _maps, layouts = johto_import.discover_inventory(pkmn_world)
        layout = johto_import._materialized_layout(
            {"id": "LAYOUT_TIN_TOWER_ROOF_NIGHT"},
            layouts,
            manifest,
            pkmn_world,
            hns,
        )
        self.assertEqual(layout["id"], "LAYOUT_TIN_TOWER_ROOF_NIGHT")
        self.assertEqual(layout["format"], "johto")
        for key in ("blockdata_filepath", "border_filepath"):
            self.assertTrue((hns / layout[key]).is_file())

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
        selected = manifest["selection"]["maps"]
        lock = johto_import._json(
            Path(manifest["__manifestPath"]).parent / manifest["allocationLock"]
        )
        selected_layouts = johto_import.active_layout_selection(manifest, lock)
        self.assertEqual(closure.maps, tuple(item["name"] for item in selected))
        self.assertEqual(
            closure.layouts, tuple(item["id"] for item in selected_layouts)
        )
        self.assertEqual(
            closure.groups, tuple(sorted({item["targetGroup"] for item in selected}))
        )
        self.assertEqual(
            closure.sections, tuple(sorted({item["section"] for item in selected}))
        )
        self.assertEqual(
            evidence["route28AttributeFormats"],
            {
                "gTileset_Johto_NorthEast": "METATILE_ATTRIBUTES_EMERALD_U16",
                "gTileset_ViridianCity": "METATILE_ATTRIBUTES_FRLG_U32",
            },
        )

    def test_materialization_manifest_mutations_fail_closed(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkouts are unavailable")
        original = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        mutations = []
        for key in (
            "graphicsAdaptations",
            "musicAdaptations",
            "scriptSubstitutions",
            "berryTreeAllocations",
            "layoutBinaryAuthorities",
            "layoutTilesetRemaps",
            "tilesetAdaptations",
            "trainerPresentation",
        ):
            changed = copy.deepcopy(original)
            changed[key] = changed[key][1:]
            mutations.append((key, changed))
        changed = copy.deepcopy(original)
        changed["encounterAdaptations"]["water12To5"]["sourceIndices"] = [
            0,
            3,
            7,
            9,
            12,
        ]
        mutations.append(("encounterAdaptations", changed))
        changed = copy.deepcopy(original)
        changed["regionAssignment"]["target"] = "REGION_HOENN"
        mutations.append(("regionAssignment", changed))
        changed = copy.deepcopy(original)
        changed["tilesetAdaptations"][-2]["targetDirectory"] = "../pokemon_day_care"
        mutations.append(("tilesetTargetTraversal", changed))
        for key, manifest in mutations:
            with self.subTest(key=key):
                with self.assertRaises(johto_import.ImportError):
                    johto_import.validate_materialization_adaptations(
                        manifest, pkmn_world, hns
                    )

    def test_johto_day_care_is_isolated_from_target_route117_assets(self):
        repo = Path(__file__).parents[3]
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        adaptation = next(
            item
            for item in johto_import._tilesets(manifest)
            if item["directory"] == "pokemon_day_care"
        )
        self.assertEqual(
            (
                adaptation["symbol"],
                johto_import._tileset_target_directory(adaptation),
                johto_import._tileset_target_symbol(adaptation),
            ),
            (
                "PokemonDayCare",
                "johto_pokemon_day_care",
                "JohtoPokemonDayCare",
            ),
        )

        records = johto_import.source_tree_records(
            repo / "data/tilesets/secondary/pokemon_day_care"
        )
        self.assertEqual(len(records), 19)
        self.assertEqual(
            johto_import.records_digest(records),
            "7e31d6fb0478538f648bb5c695a946596853083ce8d9436f1487d506f258b562",
        )

        definition_fixtures = (
            (
                "src/data/tilesets/headers.h",
                r"const struct Tileset gTileset_PokemonDayCare =\n\{.*?\n\};",
                "bc32807bb99482072b8ee12b9a04803c620e456c5ae0a3e31e41686db07c6246",
            ),
            (
                "src/data/tilesets/graphics.h",
                r"const u32 gTilesetTiles_PokemonDayCare\[\].*?\n\};",
                "71703936f0a483d46e59c0a1f509912e550d6efb04ca3b56e267e4875198512f",
            ),
            (
                "src/data/tilesets/metatiles.h",
                r"const u16 gMetatiles_PokemonDayCare\[\].*?\nconst u16 gMetatileAttributes_PokemonDayCare\[\].*?;",
                "24937879c60da7f11bda52aec9bbd9927fbc590be237262bf5b62a9089ec066f",
            ),
        )
        for relative, pattern, digest in definition_fixtures:
            with self.subTest(relative=relative):
                matches = re.findall(pattern, (repo / relative).read_text(), re.DOTALL)
                self.assertEqual(len(matches), 1)
                self.assertEqual(
                    hashlib.sha256(matches[0].encode()).hexdigest(), digest
                )

        layouts = johto_import._json(repo / "data/layouts/layouts.json")["layouts"]
        route117 = next(
            item for item in layouts if item["id"] == "LAYOUT_ROUTE117_POKEMON_DAY_CARE"
        )
        route34 = next(
            item for item in layouts if item["id"] == "LAYOUT_ROUTE34_DAY_CARE"
        )
        self.assertEqual(route117["secondary_tileset"], "gTileset_PokemonDayCare")
        self.assertEqual(route34["secondary_tileset"], "gTileset_JohtoPokemonDayCare")

        graphics = johto_import._tileset_graphics(manifest)
        metatiles = johto_import._tileset_metatiles(manifest)
        headers = johto_import._tileset_headers(manifest)
        self.assertEqual(
            graphics.count("const u32 gTilesetTiles_JohtoPokemonDayCare[]"), 1
        )
        self.assertEqual(
            metatiles.count("const u16 gMetatiles_JohtoPokemonDayCare[]"), 1
        )
        self.assertEqual(
            metatiles.count("const u16 gMetatileAttributes_JohtoPokemonDayCare[]"),
            1,
        )
        self.assertEqual(
            headers.count("const struct Tileset gTileset_JohtoPokemonDayCare ="), 1
        )

    def test_selected_materialized_maps_remove_deferred_warps_and_reindex_returns(self):
        pkmn_world, hns = self.donor_paths()
        if not pkmn_world.is_dir() or not hns.is_dir():
            self.skipTest("pinned donor checkout is unavailable")
        manifest = johto_import.load_manifest(
            Path(__file__).parents[1] / "import_manifest.json"
        )
        materialized = {
            item["name"]: johto_import._materialized_map(
                item, pkmn_world, hns, manifest
            )
            for item in manifest["selection"]["maps"]
        }
        for name, map_item in materialized.items():
            with self.subTest(map=name):
                self.assertNotIn("MAP_DYNAMIC", json.dumps(map_item))
        self.assertEqual(
            materialized["Gate_Route29_Route46"]["warp_events"],
            [
                {
                    "x": 7,
                    "y": 9,
                    "elevation": 0,
                    "dest_map": "MAP_ROUTE29",
                    "dest_warp_id": "0",
                }
            ],
        )
        self.assertEqual(
            [edge["dest_warp_id"] for edge in materialized["Route29"]["warp_events"]],
            ["0", "0"],
        )
        self.assertEqual(
            materialized["Route29"]["object_events"][15][
                "trainer_sight_or_berry_tree_id"
            ],
            "BERRY_TREE_ROUTE_29_ORAN_1",
        )
        self.assertEqual(
            materialized["Route28"]["warp_events"],
            [
                {
                    "x": 20,
                    "y": 9,
                    "elevation": 0,
                    "dest_map": "MAP_ROUTE28_HOUSE",
                    "dest_warp_id": "0",
                }
            ],
        )
        self.assertEqual(
            materialized["Route28_House"]["warp_events"][0]["dest_warp_id"],
            "0",
        )


if __name__ == "__main__":
    unittest.main()
