from __future__ import annotations

import unittest
import os
import json
import tempfile
from dataclasses import replace
from pathlib import Path

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
            root, persistent_ledger="src/data/persistence/persistent_ids.json"
        )
        graph = build_source_graph(context, [ResourceKey("map", "NewBarkTown")])
        self.assertIn(ResourceKey("layout", "LAYOUT_NEW_BARK_TOWN"), graph.resources)
        self.assertIn(ResourceKey("map", "Route29"), graph.resources)

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

        decisions = list(descriptor.capabilities)
        decisions[0] = replace(
            decisions[0], dependencies=(ResourceKey("binding", "FLAG_NOT_ALLOCATED"),)
        )
        with self.assertRaisesRegex(ContentPortError, "FLAG_NOT_ALLOCATED"):
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

        legacy = self._mutable(descriptor.legacy_report)
        legacy["closure"]["maps"].pop()
        with self.assertRaisesRegex(ContentPortError, "required legacy baseline"):
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
            self.assertEqual(
                validate_port_sources(descriptor, target).inventory["tilesets"], 71
            )
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


if __name__ == "__main__":
    unittest.main()
