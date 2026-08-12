from __future__ import annotations

import unittest
import os
import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.content_port.errors import ContentPortError
from tools.content_port.model import CapabilityState, ResourceKey
from tools.content_port.descriptor import load_port
from tools.content_port.semantics import EventEntry
from tools.content_port.sources import (
    ExpansionSourceContext,
    SourceContext,
    SourceRecord,
    Provenance,
    build_source_graph,
    extract_service_edges,
    resolve_port_sources,
    validate_port_sources,
    _automatic_unreachable_shells,
    _semantic_record_digest,
    _bind_script_warp_policy,
    _extract_preserved_script_warps,
    _validate_selected_trainer_event,
)
from tools.content_port.world_graph import (
    WorldEdge,
    WorldPolicy,
    validate_world_graph,
    with_script_warps,
    world_graph_from_maps,
)


class SourceGraphTests(unittest.TestCase):
    @staticmethod
    def _mutable(value):
        if isinstance(value, dict) or hasattr(value, "items"):
            return {
                key: SourceGraphTests._mutable(child) for key, child in value.items()
            }
        if isinstance(value, tuple):
            return [SourceGraphTests._mutable(child) for child in value]
        return value

    def _donor_root(self) -> Path | None:
        repo_root = Path(__file__).resolve().parents[3]
        configured = os.environ.get("CONTENT_PORT_DONOR_ROOT")
        candidates = tuple(
            path
            for path in (
                Path(configured) if configured else None,
                repo_root / ".references",
                repo_root.parents[2] / ".references",
                Path("/tmp/content-port-donors.ATzdJy"),
            )
            if path is not None
        )
        return next(
            (
                path
                for path in candidates
                if (path / "pokemonHnS").is_dir() and (path / "PKMN-World").is_dir()
            ),
            None,
        )

    def test_extracts_native_cross_domain_edges_with_provenance(self) -> None:
        records = {
            ResourceKey("map", "Town"): SourceRecord(
                {
                    "layout": "LAYOUT_TOWN",
                    "connections": [
                        {"map": "MAP_ROUTE", "offset": 0, "direction": "up"}
                    ],
                    "warp_events": [],
                    "object_events": [{"script": "Town_Event", "flag": "FLAG_VISITED"}],
                },
                Provenance("data/maps/Town/map.json"),
            ),
            ResourceKey("layout", "LAYOUT_TOWN"): {
                "primary_tileset": "gTileset_General"
            },
            ResourceKey("map", "ROUTE"): {"layout": "LAYOUT_ROUTE"},
            ResourceKey("layout", "LAYOUT_ROUTE"): {},
            ResourceKey("service", "Town_Event"): {},
            ResourceKey("binding", "FLAG_VISITED"): {},
            ResourceKey("asset", "gTileset_General"): {},
        }
        graph = build_source_graph(SourceContext(records), [ResourceKey("map", "Town")])
        self.assertIn(ResourceKey("map", "ROUTE"), graph.resources)
        edge = next(edge for edge in graph.edges if edge.role == "connection")
        self.assertEqual(
            str(edge.provenance), "data/maps/Town/map.json/connections/0/map"
        )

    def test_script_warp_policy_binds_parsed_owned_evidence_exactly(self) -> None:
        maps = {
            "A": {
                "id": "MAP_A",
                "region": "REGION_A",
                "connections": [],
                "warp_events": [],
                "object_events": [{"script": "A_EventScript_Travel"}],
            },
            "B": {
                "id": "MAP_B",
                "region": "REGION_B",
                "connections": [],
                "warp_events": [],
                "object_events": [{"script": "B_EventScript_Travel"}],
            },
        }
        ownership = {"A": "preserve", "B": "preserve"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, destination, x, y in (
                ("A", "B", 3, 4),
                ("B", "A", 5, 6),
            ):
                path = root / "data" / "maps" / name / "scripts.inc"
                path.parent.mkdir(parents=True)
                path.write_text(
                    f"{name}_EventScript_Travel::\n msgbox Text, MSGBOX_YESNO\n"
                    f" warp MAP_{destination}, {x}, {y}\n end\n",
                    encoding="utf-8",
                )
            evidence, entries = _extract_preserved_script_warps(
                maps, ownership, root
            )
            graph = with_script_warps(world_graph_from_maps(maps), evidence)
            declarations = [
                {
                    "source": source,
                    "destination": destination,
                    "script": f"{source}_EventScript_Travel",
                    "label": f"{source}_EventScript_Travel",
                    "command": "warp",
                    "index": 0,
                    "x": x,
                    "y": y,
                    "sourceRegion": f"REGION_{source}",
                    "targetRegion": f"REGION_{destination}",
                }
                for source, destination, x, y in (
                    ("A", "B", 3, 4),
                    ("B", "A", 5, 6),
                )
            ]
            gateways = _bind_script_warp_policy(
                graph, declarations, ownership, entries
            )
            validate_world_graph(
                graph,
                WorldPolicy(
                    inter_region_gateways=gateways, roots=frozenset({"A"})
                ),
            )

            with self.assertRaisesRegex(
                ContentPortError, "policy differs from resolved topology"
            ):
                _bind_script_warp_policy(
                    graph, declarations[:1], ownership, entries
                )

            same_region_maps = json.loads(json.dumps(maps))
            same_region_maps["B"]["region"] = "REGION_A"
            same_region_graph = with_script_warps(
                world_graph_from_maps(same_region_maps), evidence
            )
            same_region_declaration = json.loads(json.dumps(declarations[:1]))
            same_region_declaration[0]["targetRegion"] = "REGION_A"
            with self.assertRaisesRegex(
                ContentPortError, "policy differs from resolved topology"
            ):
                _bind_script_warp_policy(
                    same_region_graph,
                    same_region_declaration,
                    ownership,
                    entries,
                )

            for field, value, message in (
                ("destination", "MISSING", "stale script warp"),
                ("x", 99, "stale script warp"),
                ("command", "warpsilent", "stale script warp"),
                ("index", 1, "stale script warp"),
                ("sourceRegion", "REGION_WRONG", "region evidence drift"),
                ("targetRegion", "REGION_WRONG", "region evidence drift"),
            ):
                with self.subTest(field=field):
                    drifted = json.loads(json.dumps(declarations))
                    drifted[0][field] = value
                    with self.assertRaisesRegex(ContentPortError, message):
                        _bind_script_warp_policy(
                            graph, drifted, ownership, entries
                        )

            wrong_entry = json.loads(json.dumps(declarations))
            wrong_entry[0]["script"] = "B_EventScript_Travel"
            with self.assertRaisesRegex(ContentPortError, "not owned"):
                _bind_script_warp_policy(graph, wrong_entry, ownership, entries)
            wrong_ownership = dict(ownership, A="rendered")
            with self.assertRaisesRegex(ContentPortError, "does not preserve"):
                _bind_script_warp_policy(
                    graph, declarations, wrong_ownership, entries
                )

            missing_script = root / "data" / "maps" / "B" / "scripts.inc"
            missing_script.unlink()
            incomplete_evidence, incomplete_entries = _extract_preserved_script_warps(
                maps, ownership, root
            )
            incomplete_graph = with_script_warps(
                world_graph_from_maps(maps), incomplete_evidence
            )
            self.assertEqual(
                {edge.source for edge in incomplete_evidence},
                {"A"},
            )
            with self.assertRaisesRegex(ContentPortError, "not owned"):
                _bind_script_warp_policy(
                    incomplete_graph, declarations, ownership, incomplete_entries
                )

            persistent = root / "data" / "maps" / "A" / "scripts.inc"
            persistent.write_text(
                "A_EventScript_Travel::\n setwarp MAP_B, 3, 4\n end\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContentPortError, "unsupported persistent"):
                _extract_preserved_script_warps(maps, ownership, root)

    def test_script_warp_keeps_last_static_warp_removal_from_becoming_a_shell(
        self,
    ) -> None:
        maps = {
            name: {
                "id": f"MAP_{name}",
                "region": "REGION_A",
                "connections": [],
                "warp_events": [],
            }
            for name in ("PORT", "DESTINATION", "SHELL")
        }
        graph = with_script_warps(
            world_graph_from_maps(maps),
            (
                WorldEdge(
                    "PORT",
                    "DESTINATION",
                    "script-warp",
                    0,
                    script_entry="Port_EventScript_Travel",
                    script_label="Port_EventScript_Travel",
                    command="warp",
                    x=1,
                    y=2,
                ),
            ),
        )

        self.assertEqual(
            _automatic_unreachable_shells(
                graph, {"PORT": {0}, "SHELL": {0}}
            ),
            frozenset({"SHELL"}),
        )

    def test_rejects_descriptor_dependency_graph(self) -> None:
        key = ResourceKey("capability", "spatial")
        with self.assertRaisesRegex(ContentPortError, "precomputed dependency graphs"):
            build_source_graph(SourceContext({key: {"dependencies": []}}), [key])

    def test_closes_every_cross_domain_resource(self) -> None:
        root = ResourceKey("capability", "field-ready")
        records = {
            root: {
                "references": {
                    "map": ["Town"],
                    "trainer": ["ACE"],
                    "encounter": ["TownLand"],
                    "service": ["Mart"],
                }
            },
            ResourceKey("map", "Town"): {"layout": "LAYOUT_TOWN"},
            ResourceKey("layout", "LAYOUT_TOWN"): {"primary_tileset": "gTileset_Town"},
            ResourceKey("trainer", "ACE"): {
                "parties": ["ACE_1"],
                "front_pic": "AcePic",
            },
            ResourceKey("party", "ACE_1"): {"members": [{"sprite": "PikachuPic"}]},
            ResourceKey("encounter", "TownLand"): {"maps": ["Town"]},
            ResourceKey("service", "Mart"): {
                "references": {"binding": ["FLAG_MART"], "asset": ["MartIcon"]}
            },
            ResourceKey("binding", "FLAG_MART"): {},
            ResourceKey("asset", "gTileset_Town"): {},
            ResourceKey("asset", "AcePic"): {},
            ResourceKey("asset", "PikachuPic"): {},
            ResourceKey("asset", "MartIcon"): {},
        }
        graph = build_source_graph(SourceContext(records), [root])
        self.assertEqual(
            {key.domain for key in graph.resources},
            {
                "capability",
                "map",
                "layout",
                "trainer",
                "party",
                "encounter",
                "service",
                "binding",
                "asset",
            },
        )

    def test_missing_dependency_names_owning_resource(self) -> None:
        key = ResourceKey("map", "Town")
        with self.assertRaisesRegex(ContentPortError, "while loading layout:LOST"):
            build_source_graph(SourceContext({key: {"layout": "LOST"}}), [key])

    def test_indexes_real_expansion_map_and_layout_inputs(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required pokemonHnS donor checkout is missing")
            self.skipTest("pokemonHnS donor checkout is not present")
        root = donor_root / "pokemonHnS"
        context = ExpansionSourceContext(
            root,
            capabilities={
                "domain-test": {
                    "references": {
                        "trainer": ["TRAINER_SAWYER_1"],
                        "encounter": ["gRoute29"],
                        "service": ["NewBarkTown_OnTransition"],
                    }
                }
            },
            persistent_ledger="src/data/persistence/persistent_ids.json",
            active_capabilities=("spatial", "encounters"),
        )
        graph = build_source_graph(context, [ResourceKey("map", "NewBarkTown")])
        self.assertIn(ResourceKey("layout", "LAYOUT_NEW_BARK_TOWN"), graph.resources)
        self.assertIn(ResourceKey("map", "Route29"), graph.resources)
        domain_graph = build_source_graph(
            context, [ResourceKey("capability", "domain-test")]
        )
        for key in (
            ResourceKey("trainer", "TRAINER_SAWYER_1"),
            ResourceKey("party", "sParty_Sawyer1"),
            ResourceKey("encounter", "gRoute29"),
            ResourceKey("service", "NewBarkTown_OnTransition"),
        ):
            self.assertIn(key, domain_graph.resources)
        mechanical = ExpansionSourceContext(
            donor_root / "PKMN-World", active_capabilities=("encounters",)
        )
        hidden_graph = build_source_graph(
            mechanical, [ResourceKey("encounter", "gRoute29")]
        )
        self.assertIn(ResourceKey("species", "SPECIES_PHANPY"), hidden_graph.resources)
        for donor_name in ("pokemonHnS", "PKMN-World"):
            generated = ExpansionSourceContext(donor_root / donor_name)
            for symbol in ("ITEM_HM_CUT", "ITEM_TM_FOCUS_PUNCH"):
                record = generated.load(ResourceKey("item", symbol))
                self.assertTrue(record.provenance.path.endswith("tms_hms.h"))
        service_key = ResourceKey(
            "service", "RustboroCity_CuttersHouse_EventScript_Cutter"
        )
        service = context.load(service_key)
        service_edges = tuple(extract_service_edges(context, service_key, service))
        self.assertIn(
            ResourceKey("item", "ITEM_HM_CUT"),
            {edge.target for edge in service_edges},
        )
        for key in (
            ResourceKey("species", "SPECIES_GEODUDE"),
            ResourceKey("asset", "TRAINER_PIC_HIKER"),
            ResourceKey("asset", "TRAINER_ENCOUNTER_MUSIC_HG_SUSPICIOUS_2"),
            ResourceKey("trainer-class", "TRAINER_CLASS_HIKER"),
        ):
            self.assertIn(key, domain_graph.resources)

    def test_native_trainer_party_encounter_and_script_edges_are_not_leaves(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "src/data").mkdir(parents=True)
            (root / "data/maps/Town").mkdir(parents=True)
            (root / "include/constants").mkdir(parents=True)
            declarations = {
                "species.h": [
                    "SPECIES_PIKACHU",
                    "SPECIES_RATTATA",
                    "SPECIES_HIDDEN",
                ],
                "moves.h": ["MOVE_THUNDERBOLT", "MOVE_QUICK_ATTACK"],
                "items.h": ["ITEM_ORAN_BERRY", "ITEM_POTION"],
                "trainers.h": [
                    "TRAINER_CLASS_ACE",
                    "TRAINER_PIC_ACE",
                    "TRAINER_ENCOUNTER_MUSIC_HG_BOY_1",
                ],
            }
            for filename, symbols in declarations.items():
                (root / "include/constants" / filename).write_text(
                    "".join(
                        f"#define {symbol} {index}\n"
                        for index, symbol in enumerate(symbols)
                    ),
                    encoding="utf-8",
                )
            (root / "src/data/trainer_parties.h").write_text(
                """static const struct TrainerMonItemCustomMoves sParty_Test[] = {
    {.species = SPECIES_PIKACHU, .heldItem = ITEM_ORAN_BERRY,
     .moves = {MOVE_THUNDERBOLT, MOVE_QUICK_ATTACK}}
};
""",
                encoding="utf-8",
            )
            (root / "src/data/trainers.h").write_text(
                """[TRAINER_TEST] = {
 .trainerClass = TRAINER_CLASS_ACE,
 .encounterMusic_gender = TRAINER_ENCOUNTER_MUSIC_HG_BOY_1,
 .trainerPic = TRAINER_PIC_ACE,
 .items = {ITEM_POTION},
 .party = ITEM_CUSTOM_MOVES(sParty_Test),
};
""",
                encoding="utf-8",
            )
            (root / "data/maps/Town/map.json").write_text(
                json.dumps({"name": "Town", "id": "MAP_TOWN"}), encoding="utf-8"
            )
            (root / "data/maps/Town/scripts.inc").write_text(
                "Entry::\n call Helper\n setflag FLAG_TEST\n "
                "playmoncry SPECIES_PIKACHU, CRY_MODE_NORMAL\n end\n"
                "Helper::\n return\n",
                encoding="utf-8",
            )
            encounter = {
                "wild_encounter_groups": [
                    {
                        "encounters": [
                            {
                                "map": "MAP_TOWN",
                                "base_label": "gTown",
                                "land_mons": {
                                    "encounter_rate": 20,
                                    "mons": [
                                        {
                                            "min_level": 2,
                                            "max_level": 3,
                                            "species": "SPECIES_RATTATA",
                                        }
                                    ],
                                },
                                "hidden_mons": {
                                    "encounter_rate": 0,
                                    "mons": [
                                        {
                                            "min_level": 4,
                                            "max_level": 6,
                                            "species": "SPECIES_HIDDEN",
                                        }
                                    ],
                                },
                            }
                        ]
                    }
                ]
            }
            (root / "src/data/wild_encounters.json").write_text(
                json.dumps(encounter), encoding="utf-8"
            )
            ledger = root / "ledger.json"
            ledger.write_text(
                json.dumps({"entries": [{"symbol": "FLAG_TEST"}]}),
                encoding="utf-8",
            )
            context = ExpansionSourceContext(
                root,
                capabilities={
                    "native": {
                        "references": {
                            "trainer": ["TRAINER_TEST"],
                            "encounter": ["gTown"],
                            "service": ["Entry"],
                        }
                    }
                },
                persistent_ledger=ledger,
                active_capabilities=("trainers", "encounters", "events"),
            )
            graph = build_source_graph(context, [ResourceKey("capability", "native")])
            expected = {
                ResourceKey("party", "sParty_Test"),
                ResourceKey("species", "SPECIES_PIKACHU"),
                ResourceKey("species", "SPECIES_RATTATA"),
                ResourceKey("species", "SPECIES_HIDDEN"),
                ResourceKey("move", "MOVE_THUNDERBOLT"),
                ResourceKey("move", "MOVE_QUICK_ATTACK"),
                ResourceKey("item", "ITEM_ORAN_BERRY"),
                ResourceKey("item", "ITEM_POTION"),
                ResourceKey("asset", "TRAINER_PIC_ACE"),
                ResourceKey("asset", "TRAINER_ENCOUNTER_MUSIC_HG_BOY_1"),
                ResourceKey("trainer-class", "TRAINER_CLASS_ACE"),
                ResourceKey("service", "Helper"),
                ResourceKey("binding", "FLAG_TEST"),
            }
            self.assertTrue(expected <= set(graph.resources))

            native_files = {
                "species": (
                    root / "src/data/trainer_parties.h",
                    "SPECIES_PIKACHU",
                    "SPECIES_NOT_DECLARED",
                ),
                "move": (
                    root / "src/data/trainer_parties.h",
                    "MOVE_THUNDERBOLT",
                    "MOVE_NOT_DECLARED",
                ),
                "item": (
                    root / "src/data/trainer_parties.h",
                    "ITEM_ORAN_BERRY",
                    "ITEM_NOT_DECLARED",
                ),
                "trainer-class": (
                    root / "src/data/trainers.h",
                    "TRAINER_CLASS_ACE",
                    "TRAINER_CLASS_NOT_DECLARED",
                ),
                "portrait": (
                    root / "src/data/trainers.h",
                    "TRAINER_PIC_ACE",
                    "TRAINER_PIC_NOT_DECLARED",
                ),
                "music": (
                    root / "src/data/trainers.h",
                    "TRAINER_ENCOUNTER_MUSIC_HG_BOY_1",
                    "TRAINER_ENCOUNTER_MUSIC_NOT_DECLARED",
                ),
                "hidden-species": (
                    root / "src/data/wild_encounters.json",
                    "SPECIES_HIDDEN",
                    "SPECIES_NOT_DECLARED",
                ),
            }
            for label, (path, declared, missing) in native_files.items():
                with self.subTest(native_leaf=label):
                    original = path.read_text(encoding="utf-8")
                    path.write_text(
                        original.replace(declared, missing, 1), encoding="utf-8"
                    )
                    with self.assertRaisesRegex(
                        ContentPortError, "no authenticated declaration"
                    ):
                        ExpansionSourceContext(root)
                    path.write_text(original, encoding="utf-8")

            (root / "data/maps/Town/scripts.inc").write_text(
                "Entry::\n call MissingService\n end\n", encoding="utf-8"
            )
            broken = ExpansionSourceContext(
                root,
                capabilities={"native": {"references": {"service": ["Entry"]}}},
                persistent_ledger=ledger,
                active_capabilities=("events",),
            )
            with self.assertRaisesRegex(ContentPortError, "service:MissingService"):
                build_source_graph(broken, [ResourceKey("capability", "native")])

            (root / "data/maps/Town/scripts.inc").write_text(
                "Entry::\n setflag FLAG_UNALLOCATED\n end\n", encoding="utf-8"
            )
            broken = ExpansionSourceContext(
                root,
                capabilities={"native": {"references": {"service": ["Entry"]}}},
                persistent_ledger=ledger,
                active_capabilities=("events",),
            )
            with self.assertRaisesRegex(ContentPortError, "binding:FLAG_UNALLOCATED"):
                build_source_graph(broken, [ResourceKey("capability", "native")])

            (root / "data/maps/Town/scripts.inc").write_text(
                "Entry::\n playmoncry SPECIES_NOT_DECLARED, CRY_MODE_NORMAL\n end\n",
                encoding="utf-8",
            )
            broken = ExpansionSourceContext(
                root,
                capabilities={"native": {"references": {"service": ["Entry"]}}},
                persistent_ledger=ledger,
                active_capabilities=("events",),
            )
            with self.assertRaisesRegex(
                ContentPortError, "species:SPECIES_NOT_DECLARED"
            ):
                build_source_graph(broken, [ResourceKey("capability", "native")])

    def test_full_real_port_contract_closes_and_rejects_stale_world_policy(
        self,
    ) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        evidence, state = resolve_port_sources(descriptor, Path("."))
        self.assertEqual(evidence.inventory["maps"], 254)
        self.assertEqual(evidence.inventory["layouts"], 255)
        expected_asset_policy = tuple(
            sorted(
                f"{item['donor']}:{item['sourcePath']}"
                for item in descriptor.assets["assets"]
            )
        )
        self.assertEqual(state.inventory["asset-policy"], expected_asset_policy)
        self.assertTrue(
            all(
                ResourceKey("asset", identity) in state.resources
                for identity in expected_asset_policy
            )
        )
        azalea_border = "data/layouts/AzaleaTown/border.bin"
        missing_asset_policy = {
            **descriptor.assets,
            "assets": tuple(
                item
                for item in descriptor.assets["assets"]
                if item["sourcePath"] != azalea_border
            ),
        }
        with self.assertRaisesRegex(ContentPortError, "exactly cover"):
            resolve_port_sources(
                replace(
                    descriptor,
                    assets=missing_asset_policy,
                    legacy_report=None,
                ),
                Path("."),
            )
        target_drift = [self._mutable(item) for item in descriptor.assets["assets"]]
        next(item for item in target_drift if item["sourcePath"] == azalea_border)[
            "semanticTarget"
        ] = "data/layouts/AzaleaTown/wrong-border.bin"
        with self.assertRaisesRegex(ContentPortError, "semantic targets differ"):
            resolve_port_sources(
                replace(
                    descriptor,
                    assets={**descriptor.assets, "assets": tuple(target_drift)},
                    legacy_report=None,
                ),
                Path("."),
            )
        self.assertEqual(state.map_authorities["JohtoVictoryRoad_1F"], "mechanical")
        self.assertEqual(
            state.layout_authorities["LAYOUT_CHERRYGROVE_CITY_POKEMON_CENTER"],
            "mechanical",
        )
        content_root = descriptor.donors_by_role["content"].root.resolve()
        for layout_name in (
            "LAYOUT_NEW_BARK_TOWN",
            "LAYOUT_AZALEA_TOWN",
        ):
            layout = state.layouts[layout_name]
            for field_name in ("border_filepath", "blockdata_filepath"):
                asset = ResourceKey("asset", f"content:{layout[field_name]}")
                provenance = state.resources[asset]
                self.assertTrue(Path(provenance.path).is_relative_to(content_root))
                self.assertNotIn(
                    ResourceKey("asset", str(layout[field_name])), state.resources
                )
        overlapping = "LAYOUT_CHERRYGROVE_CITY_POKEMON_CENTER"
        for donor_name in ("pokemonHnS", "PKMN-World"):
            context = ExpansionSourceContext(donor_root / donor_name)
            self.assertEqual(
                context.load(ResourceKey("layout", overlapping)).value["id"],
                overlapping,
            )
        with self.assertRaises(TypeError):
            state.maps["NewBarkTown"]["layout"] = "MUTATED"
        adaptations = {key: value for key, value in descriptor.adaptations.items()}
        policy = dict(adaptations["worldPolicy"])
        policy["unreachableShells"] = tuple(policy["unreachableShells"]) + (
            "NewBarkTown",
        )
        adaptations["worldPolicy"] = policy
        with self.assertRaisesRegex(ContentPortError, "stale unreachable-shell"):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

    def test_real_trainer_capability_uses_map_authority_without_event_leakage(
        self,
    ) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        _, state = resolve_port_sources(
            replace(descriptor, legacy_report=None),
            Path("."),
        )
        expected = {
            ResourceKey("trainer", "TRAINER_SAMUEL"),
            ResourceKey("party", "sParty_Samuel"),
            ResourceKey("species", "SPECIES_TEDDIURSA"),
            ResourceKey("trainer-class", "TRAINER_CLASS_YOUNGSTER"),
            ResourceKey("asset", "TRAINER_PIC_YOUNGSTER"),
            ResourceKey("service", "Route34_EventScript_YoungsterSamuel"),
        }
        self.assertTrue(expected <= set(state.resources))
        self.assertNotIn(ResourceKey("trainer", "TRAINER_TODD"), state.resources)
        self.assertNotIn(ResourceKey("trainer", "TRAINER_KEITH"), state.resources)
        trainer_evidence = state.semantic_evidence["content:trainer:TRAINER_SAMUEL"]
        self.assertRegex(trainer_evidence, r"^[0-9a-f]{64}$")
        trainer = state.semantic_values[ResourceKey("trainer", "TRAINER_SAMUEL")]
        self.assertEqual(trainer["trainer_name"], "SAMUEL")
        self.assertEqual(trainer["double_battle"], "FALSE")
        self.assertEqual(trainer["ai_flags"], ("AI_SCRIPT_CHECK_BAD_MOVE",))
        party = state.semantic_values[ResourceKey("party", "sParty_Samuel")]
        self.assertEqual(
            [
                (member["species"], member["level"], member["iv"])
                for member in party["members"]
            ],
            [
                ("SPECIES_TEDDIURSA", 12, 0),
                ("SPECIES_SANDSHREW", 10, 0),
                ("SPECIES_SPEAROW", 12, 0),
            ],
        )
        event = state.trainer_events["Route34"][0]
        self.assertEqual(event.trainers, ("TRAINER_SAMUEL",))
        self.assertEqual(
            event.instructions[0].operands,
            (
                "TRAINER_SAMUEL",
                "Route34_Text_YoungsterSamuel_Seen",
                "Route34_Text_YoungsterSamuel_Beaten",
            ),
        )
        event_key = ResourceKey(
            "trainer-event", "Route34/0/Route34_EventScript_YoungsterSamuel"
        )
        semantic_event = self._mutable(state.semantic_values[event_key])
        self.assertEqual(
            [item["command"] for item in semantic_event["instructions"]],
            ["trainerbattle_single", "msgbox", "end"],
        )
        baseline_digest = _semantic_record_digest("content", event_key, semantic_event)
        self.assertEqual(
            baseline_digest,
            state.semantic_evidence[f"content:{event_key}"],
        )
        for label, mutate in (
            (
                "operand",
                lambda value: value["instructions"][0]["operands"].__setitem__(
                    1, "ChangedIntro"
                ),
            ),
            (
                "text",
                lambda value: value["texts"][0]["fragments"].__setitem__(
                    0, '"Changed$"'
                ),
            ),
        ):
            with self.subTest(semantic_mutation=label):
                mutated = self._mutable(semantic_event)
                mutate(mutated)
                self.assertNotEqual(
                    baseline_digest,
                    _semantic_record_digest("content", event_key, mutated),
                )
        with self.assertRaisesRegex(ContentPortError, "exactly contain"):
            _validate_selected_trainer_event(replace(event, texts=event.texts[:-1]))
        duplicate_after = replace(
            event.instructions[1],
            operands=(event.instructions[0].operands[1], "MSGBOX_AUTOCLOSE"),
        )
        with self.assertRaisesRegex(ContentPortError, "must be distinct"):
            _validate_selected_trainer_event(
                replace(
                    event,
                    instructions=(
                        event.instructions[0],
                        duplicate_after,
                        event.instructions[2],
                    ),
                )
            )
        implicit_trainer_capabilities = tuple(
            replace(decision, state=CapabilityState.ENABLED)
            if decision.map_name == "Route30" and decision.capability == "trainers"
            else decision
            for decision in descriptor.capabilities
        )
        with self.assertRaisesRegex(ContentPortError, "explicit trainer dependencies"):
            resolve_port_sources(
                replace(
                    descriptor,
                    capabilities=implicit_trainer_capabilities,
                    legacy_report=None,
                ),
                Path("."),
            )

    def test_enabled_event_entry_must_be_reachable_from_its_map_policy(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        with tempfile.TemporaryDirectory(dir="tools/content_port/tests") as directory:
            port = Path(directory) / "johto"
            shutil.copytree("tools/content_port/ports/johto", port)
            descriptor = load_port(port, donor_root)
            capabilities = tuple(
                replace(decision, state=CapabilityState.ENABLED)
                if decision.map_name == "DragonsDen_Entrance"
                and decision.capability == "interactions"
                else decision
                for decision in descriptor.capabilities
            )
            unrelated = EventEntry(
                name="BlackthornCity_House1_Unrelated",
                capability="interactions",
                classification="enabled",
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "enabled event entry BlackthornCity_House1_Unrelated is not reachable",
            ):
                resolve_port_sources(
                    replace(
                        descriptor,
                        capabilities=capabilities,
                        event_entries={
                            **descriptor.event_entries,
                            unrelated.name: unrelated,
                        },
                        legacy_report=None,
                    ),
                    Path("."),
                )

    def test_resolver_uses_descriptor_event_policy_path_not_sibling_name(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        with tempfile.TemporaryDirectory(dir="tools/content_port/tests") as directory:
            port = Path(directory) / "johto"
            shutil.copytree("tools/content_port/ports/johto", port)
            selected = port / "semantic-events.json"
            (port / "events.json").rename(selected)
            port_document = json.loads((port / "port.json").read_text(encoding="utf-8"))
            port_document["eventPolicy"] = selected.name
            (port / "port.json").write_text(json.dumps(port_document), encoding="utf-8")
            (port / "events.json").write_text(
                json.dumps({"schemaVersion": 999, "entires": []}),
                encoding="utf-8",
            )
            descriptor = load_port(port, donor_root)
            self.assertEqual(descriptor.event_policy_path, selected.resolve())
            evidence, _ = resolve_port_sources(descriptor, Path("."))
            self.assertEqual(evidence.inventory["maps"], 254)

    def test_full_real_port_contract_rejects_cross_domain_mutations(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)

        without_legacy = validate_port_sources(
            replace(descriptor, legacy_report=None), Path(".")
        )
        self.assertEqual(without_legacy.inventory["maps"], 254)

        _, resolved = resolve_port_sources(descriptor, Path("."))
        new_bark = resolved.layouts["LAYOUT_NEW_BARK_TOWN"]
        self.assertEqual(resolved.layout_authorities["LAYOUT_NEW_BARK_TOWN"], "content")
        self.assertEqual(new_bark["width"], 30)
        self.assertEqual(new_bark["border_width"], 0)
        self.assertEqual(new_bark["border_height"], 0)
        self.assertEqual(
            resolved.layout_field_authorities["LAYOUT_NEW_BARK_TOWN"]["width"],
            "content",
        )
        self.assertEqual(
            resolved.layout_field_authorities["LAYOUT_NEW_BARK_TOWN"]["border_width"],
            "mechanical",
        )

        missing_border_rule = tuple(
            authority
            for authority in descriptor.layout_field_authorities
            if authority.field != "border_width"
        )
        with self.assertRaisesRegex(ContentPortError, "unresolved layout field"):
            resolve_port_sources(
                replace(descriptor, layout_field_authorities=missing_border_rule),
                Path("."),
            )

        authorities = list(descriptor.layout_binary_authorities)
        mechanical_index = next(
            index
            for index, authority in enumerate(authorities)
            if authority.layout == "LAYOUT_JOHTO_VICTORY_ROAD_1F"
        )
        authorities[mechanical_index] = replace(
            authorities[mechanical_index], source_role="content"
        )
        with self.assertRaisesRegex(ContentPortError, "source map.*content donor"):
            validate_port_sources(
                replace(descriptor, layout_binary_authorities=tuple(authorities)),
                Path("."),
            )

        authorities = list(descriptor.layout_binary_authorities)
        authorities.append(authorities[0])
        with self.assertRaisesRegex(ContentPortError, "uniquely cover"):
            validate_port_sources(
                replace(descriptor, layout_binary_authorities=tuple(authorities)),
                Path("."),
            )

        renamed_donors = {
            role: replace(pin, name=f"role-{role}")
            for role, pin in descriptor.donors_by_role.items()
        }
        renamed = validate_port_sources(
            replace(descriptor, donors_by_role=renamed_donors), Path(".")
        )
        self.assertEqual(renamed.inventory["maps"], 254)

        adaptations = self._mutable(descriptor.adaptations)
        adaptations["contentFallback"]["maps"].append("NewBarkTown")
        with self.assertRaisesRegex(ContentPortError, "exists in the content donor"):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        adaptations = self._mutable(descriptor.adaptations)
        adaptations["adaptations"][0]["hns"] = "MAP_MUTATED"
        with self.assertRaisesRegex(ContentPortError, "map.*preimage drift"):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        adaptations = self._mutable(descriptor.adaptations)
        adaptations["layoutHeaderDecisions"][0]["hns"] = "gTileset_Mutated"
        with self.assertRaisesRegex(
            ContentPortError, "layout authority evidence drift"
        ):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        adaptations = self._mutable(descriptor.adaptations)
        decision = next(
            item
            for item in adaptations["mapFieldDecisions"]
            if item["map"] == "ReceptionGate" and item["field"] == "region_map_section"
        )
        decision["mechanical"] = "MAPSEC_NEW_BARK_TOWN"
        with self.assertRaisesRegex(
            ContentPortError, "mechanical map-field evidence drift"
        ):
            from tools.content_port.materialize import derive_desired_state

            derive_desired_state(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        adaptations = self._mutable(descriptor.adaptations)
        adaptations["layoutTilesetRemaps"][0]["target"] = "gTileset_MissingBinding"
        with self.assertRaisesRegex(
            ContentPortError, "target tileset binding.*missing"
        ):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        for collection, message in (
            ("warpRemovals", "duplicate warp removal"),
            ("deferredEdges", "duplicate deferred edge"),
        ):
            adaptations = self._mutable(descriptor.adaptations)
            adaptations[collection].append(dict(adaptations[collection][0]))
            with self.assertRaisesRegex(ContentPortError, message):
                validate_port_sources(
                    replace(descriptor, adaptations=adaptations), Path(".")
                )

        decisions = list(descriptor.capabilities)
        decisions[0] = replace(
            decisions[0], dependencies=(ResourceKey("binding", "FLAG_NOT_ALLOCATED"),)
        )
        with self.assertRaisesRegex(ContentPortError, "FLAG_NOT_ALLOCATED"):
            validate_port_sources(
                replace(descriptor, capabilities=tuple(decisions)), Path(".")
            )

        decisions = list(descriptor.capabilities)
        spatial_index = next(
            index
            for index, decision in enumerate(decisions)
            if decision.capability == "spatial"
        )
        decisions[spatial_index] = replace(
            decisions[spatial_index],
            dependencies=(ResourceKey("trainer", "TRAINER_SAWYER_1"),),
        )
        with self.assertRaisesRegex(ContentPortError, "disabled capability trainers"):
            validate_port_sources(
                replace(descriptor, capabilities=tuple(decisions)), Path(".")
            )

        adaptations = self._mutable(descriptor.adaptations)
        adaptations["worldPolicy"]["unreachableShells"].remove("SafariZone1")
        with self.assertRaisesRegex(ContentPortError, "SafariZone1"):
            validate_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        expected_inventory = {
            key: dict(value) for key, value in descriptor.expected_inventory.items()
        }
        expected_inventory["maps"]["digest"] = "0" * 64
        with self.assertRaisesRegex(ContentPortError, "maps inventory digest"):
            validate_port_sources(
                replace(descriptor, expected_inventory=expected_inventory), Path(".")
            )

        self.assertIsNotNone(descriptor.legacy_report)
        legacy = self._mutable(descriptor.legacy_report)
        legacy["closure"]["maps"].pop()
        with self.assertRaisesRegex(ContentPortError, "declared legacy baseline"):
            validate_port_sources(replace(descriptor, legacy_report=legacy), Path("."))

        for section, field in (
            ("closure", "symbols"),
            ("evidence", "attributeFormats"),
            ("evidence", "inputs"),
        ):
            legacy = self._mutable(descriptor.legacy_report)
            if isinstance(legacy[section][field], list):
                legacy[section][field].pop()
            else:
                legacy[section][field].pop(next(iter(legacy[section][field])))
            with self.assertRaisesRegex(ContentPortError, field):
                validate_port_sources(
                    replace(descriptor, legacy_report=legacy), Path(".")
                )

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            ledger_target = target / "src/data/persistence/persistent_ids.json"
            ledger_target.parent.mkdir(parents=True)
            ledger = json.loads(
                Path("src/data/persistence/persistent_ids.json").read_text()
            )
            ledger_target.write_text(json.dumps(ledger), encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError, "preserved target map NewBarkTown is unavailable"
            ):
                validate_port_sources(descriptor, target)
            for name, ownership in descriptor.map_ownership.items():
                if ownership != "preserve":
                    continue
                source_map = Path("data/maps") / name / "map.json"
                target_map = target / source_map
                target_map.parent.mkdir(parents=True)
                shutil.copyfile(source_map, target_map)
            self.assertEqual(
                validate_port_sources(descriptor, target).inventory["tilesets"], 71
            )
            new_bark = target / "data/maps/NewBarkTown/map.json"
            original_new_bark = new_bark.read_bytes()
            broken_map = json.loads(original_new_bark)
            broken_map["warp_events"][0]["dest_map"] = "MAP_MISSING_TARGET"
            new_bark.write_text(json.dumps(broken_map), encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError, "reviewed world edge drift|MISSING_TARGET"
            ):
                validate_port_sources(descriptor, target)
            new_bark.write_bytes(original_new_bark)
            corrupt_header = target / "src/data/tilesets/headers.h"
            corrupt_header.parent.mkdir(parents=True)
            corrupt_header.write_text("corrupt generated output\n", encoding="utf-8")
            self.assertEqual(
                validate_port_sources(descriptor, target).inventory["tilesets"], 71
            )
            first = ledger["entries"][0]
            duplicate = dict(first)
            duplicate["symbol"] = "MUTATED_COLLISION"
            ledger["entries"].append(duplicate)
            ledger_target.write_text(json.dumps(ledger), encoding="utf-8")
            with self.assertRaisesRegex(ContentPortError, "collision"):
                validate_port_sources(descriptor, target)

    def test_warp_removals_are_resolved_once_for_graph_and_renderer(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        content_root = descriptor.donors_by_role["content"].root.resolve()
        real_context = ExpansionSourceContext
        original_context = real_context(content_root)
        source_record = original_context.load(ResourceKey("map", "EcruteakCity"))
        document = self._mutable(source_record.value)
        gym_warp = dict(document["warp_events"][13])
        document["warp_events"].insert(14, gym_warp)

        def context_with_duplicate(root, **kwargs):
            context = real_context(root, **kwargs)
            if Path(root).resolve() == content_root:
                context._records[ResourceKey("map", "EcruteakCity")] = SourceRecord(
                    document, source_record.provenance
                )
            return context

        adaptations = self._mutable(descriptor.adaptations)
        for collection in ("deferredEdges", "warpRemovals"):
            battle_frontier = next(
                item
                for item in adaptations[collection]
                if item["source"] == "EcruteakCity" and item["path"] == "warp_events/14"
            )
            battle_frontier["path"] = "warp_events/15"
        adaptations["retainedEdges"].append(
            {
                "source": "EcruteakCity",
                "path": "warp_events/14",
                "kind": "warp",
                "destination": gym_warp["dest_map"],
            }
        )
        adaptations["warpRemovals"].append(
            {
                "source": "EcruteakCity",
                "path": "warp_events/13",
                "destination": gym_warp["dest_map"],
                "destWarpId": str(gym_warp["dest_warp_id"]),
                "reason": "test exact-index removal with an identical following warp",
            }
        )
        with patch(
            "tools.content_port.sources.ExpansionSourceContext",
            side_effect=context_with_duplicate,
        ):
            _, state = resolve_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        ecruteak_warps = state.maps["EcruteakCity"]["warp_events"]
        self.assertEqual(ecruteak_warps[13]["dest_map"], gym_warp["dest_map"])
        self.assertEqual(
            sum(warp["dest_map"] == gym_warp["dest_map"] for warp in ecruteak_warps),
            1,
        )
        self.assertEqual(
            state.maps["GoldenrodCity_DepartmentStoreElevator"]["warp_events"], ()
        )

        from tools.content_port.materialize import _map_units

        rendered = {
            unit.key.removeprefix("map:"): unit.value
            for unit in _map_units(replace(descriptor, adaptations=adaptations), state)
            if unit.key.startswith("map:")
        }
        for name in ("EcruteakCity", "GoldenrodCity_DepartmentStoreElevator"):
            self.assertEqual(
                rendered[name]["warp_events"], list(state.maps[name]["warp_events"])
            )

    def test_warp_reindexes_are_graph_validated_and_rendered_once(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail("required donor checkouts are missing")
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        adaptations = self._mutable(descriptor.adaptations)
        reindex = {
            "source": "EcruteakCity",
            "path": "warp_events/0/dest_warp_id",
            "to": 999,
        }
        adaptations["warpReindexes"] = [reindex, dict(reindex)]
        with self.assertRaisesRegex(ContentPortError, "duplicate warp reindex"):
            resolve_port_sources(
                replace(descriptor, adaptations=adaptations, legacy_report=None),
                Path("."),
            )
        adaptations["warpReindexes"] = [reindex]
        with self.assertRaisesRegex(ContentPortError, "out of bounds"):
            resolve_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )

        reindex["to"] = 1
        _, state = resolve_port_sources(
            replace(descriptor, adaptations=adaptations), Path(".")
        )
        self.assertEqual(
            state.maps["EcruteakCity"]["warp_events"][0]["dest_warp_id"], 1
        )

        from tools.content_port.materialize import _map_units

        renderer_policy = self._mutable(adaptations)
        renderer_policy["warpReindexes"][0]["to"] = 999
        rendered = next(
            unit.value
            for unit in _map_units(
                replace(descriptor, adaptations=renderer_policy), state
            )
            if unit.key == "map:EcruteakCity"
        )
        self.assertEqual(
            rendered["warp_events"], list(state.maps["EcruteakCity"]["warp_events"])
        )

    def test_dynamic_warps_require_exact_authored_metadata(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        adaptations = self._mutable(descriptor.adaptations)
        source = "GoldenrodCity_DepartmentStoreElevator"
        adaptations["warpRemovals"] = [
            item for item in adaptations["warpRemovals"] if item["source"] != source
        ]
        dynamic_edge = next(
            item for item in adaptations["deferredEdges"] if item["source"] == source
        )
        adaptations["deferredEdges"].remove(dynamic_edge)
        adaptations["retainedEdges"].append(dynamic_edge)
        with self.assertRaisesRegex(ContentPortError, "dynamic warp policy"):
            resolve_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )
        adaptations["worldPolicy"]["dynamicWarps"] = [
            {"source": source, "index": 0, "token": "WARP_ID_DYNAMIC"}
        ]
        resolve_port_sources(
            replace(descriptor, adaptations=adaptations, legacy_report=None), Path(".")
        )
        adaptations["worldPolicy"]["dynamicWarps"][0]["token"] = "WRONG_TOKEN"
        with self.assertRaisesRegex(ContentPortError, "dynamic warp policy"):
            resolve_port_sources(
                replace(descriptor, adaptations=adaptations, legacy_report=None),
                Path("."),
            )

    def test_gateway_policy_binds_edges_and_regions(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        content_root = descriptor.donors_by_role["content"].root.resolve()
        real_context = ExpansionSourceContext

        def regional_context(root, **kwargs):
            context = real_context(root, **kwargs)
            if Path(root).resolve() == content_root:
                for name, region in (
                    ("EcruteakCity", "REGION_A"),
                    ("Gate_EcruteakCity_Route38", "REGION_B"),
                ):
                    key = ResourceKey("map", name)
                    record = context._records[key]
                    value = self._mutable(record.value)
                    value["region"] = region
                    context._records[key] = SourceRecord(value, record.provenance)
            return context

        with patch(
            "tools.content_port.sources.ExpansionSourceContext",
            side_effect=regional_context,
        ):
            with self.assertRaisesRegex(ContentPortError, "declared gateway"):
                resolve_port_sources(descriptor, Path("."))
            adaptations = self._mutable(descriptor.adaptations)
            adaptations["worldPolicy"]["gateways"] = [
                {
                    "source": "EcruteakCity",
                    "destination": "Gate_EcruteakCity_Route38",
                    "kind": "warp",
                    "index": 0,
                    "sourceRegion": "REGION_A",
                    "targetRegion": "REGION_B",
                },
                {
                    "source": "Gate_EcruteakCity_Route38",
                    "destination": "EcruteakCity",
                    "kind": "warp",
                    "index": 0,
                    "sourceRegion": "REGION_B",
                    "targetRegion": "REGION_A",
                },
            ]
            resolve_port_sources(
                replace(descriptor, adaptations=adaptations), Path(".")
            )
            adaptations["worldPolicy"]["gateways"][0]["destination"] = "Typo"
            with self.assertRaisesRegex(ContentPortError, "stale gateway"):
                resolve_port_sources(
                    replace(descriptor, adaptations=adaptations), Path(".")
                )

    def test_map_bindings_must_match_allocation_authority(self) -> None:
        donor_root = self._donor_root()
        if donor_root is None:
            self.skipTest("donor checkouts are not present")
        descriptor = load_port(Path("tools/content_port/ports/johto"), donor_root)
        content_root = descriptor.donors_by_role["content"].root.resolve()
        real_context = ExpansionSourceContext
        for field_name, replacement_value in (
            ("id", "MAP_AZALEA_TOWN"),
            ("layout", "LAYOUT_AZALEA_TOWN"),
            ("region_map_section", "MAPSEC_AZALEA_TOWN"),
        ):
            with self.subTest(field=field_name):

                def drifted_context(root, **kwargs):
                    context = real_context(root, **kwargs)
                    if Path(root).resolve() == content_root:
                        key = ResourceKey("map", "EcruteakCity")
                        record = context._records[key]
                        value = self._mutable(record.value)
                        value[field_name] = replacement_value
                        context._records[key] = SourceRecord(value, record.provenance)
                    return context

                with (
                    patch(
                        "tools.content_port.sources.ExpansionSourceContext",
                        side_effect=drifted_context,
                    ),
                    self.assertRaisesRegex(ContentPortError, "allocation authority"),
                ):
                    resolve_port_sources(descriptor, Path("."))


if __name__ == "__main__":
    unittest.main()
