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
from tools.content_port.model import ResourceKey
from tools.content_port.descriptor import load_port
from tools.content_port.sources import (
    ExpansionSourceContext,
    SourceContext,
    SourceRecord,
    Provenance,
    build_source_graph,
    resolve_port_sources,
    validate_port_sources,
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
