from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import MappingProxyType
import unittest
from unittest.mock import patch

from tools.content_port.descriptor import load_port
from tools.content_port.donors import records_digest, source_tree_records
from tools.content_port.errors import ContentPortError
from tools.content_port.materialize import (
    _asset_units,
    _group_units,
    _generated_body,
    _layout_units,
    _map_units,
    _section_units,
    _trainer_units,
    derive_desired_state,
)
from tools.content_port.model import DonorPin, PersistentBindingRef
from tools.content_port.ownership import OwnershipManifest
from tools.content_port.renderers import RenderContext, render_units
from tools.content_port.sources import resolve_port_sources


ROOT = Path(__file__).resolve().parents[3]
PORT = ROOT / "tools/content_port/ports/johto"


class MaterializeTests(unittest.TestCase):
    def descriptor(self):
        donor_root = Path(os.environ.get("CONTENT_PORT_DONOR_ROOT", ".references"))
        if not all(
            (donor_root / name).is_dir() for name in ("PKMN-World", "pokemonHnS")
        ):
            message = "authenticated donor checkouts are required for materialization"
            if os.environ.get("CONTENT_PORT_REQUIRE_DONORS") == "1":
                self.fail(message)
            self.skipTest(message)
        return load_port(PORT, donor_root)

    def test_selected_samuel_materialization_and_rival_projection_stability(
        self,
    ) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        map_units = {unit.key: unit for unit in _map_units(descriptor, state)}
        route_map = map_units["map:Route34"].value
        self.assertEqual(len(route_map["object_events"]), 1)
        self.assertEqual(
            route_map["object_events"][0]["script"],
            "Route34_EventScript_YoungsterSamuel",
        )
        script = map_units["map-script:Route34"].value
        self.assertEqual(
            script["events"][0]["instructions"][0]["operands"][0],
            "TRAINER_YOUNGSTER_SAMUEL_JOHTO",
        )
        trainer_units = _trainer_units(descriptor, state, ROOT)
        self.assertEqual(len(trainer_units), 1)
        self.assertEqual(
            [member["species"] for member in trainer_units[0].value[0]["party"]],
            ["SPECIES_TEDDIURSA", "SPECIES_SANDSHREW", "SPECIES_SPEAROW"],
        )
        self.assertEqual(
            hashlib.sha256(
                _generated_body("trainer-bindings", descriptor, state, ROOT).encode()
            ).hexdigest(),
            "e73b027b1743a157afcef41189ea2c80c7172504dd547cb7059f824db05d0f79",
        )
        self.assertEqual(
            hashlib.sha256(
                _generated_body("trainer-parties", descriptor, state, ROOT).encode()
            ).hexdigest(),
            "f2163b8059ef83d28fc87e422705125e8e7517e92cc90b2baf8e27ab5bdaf393",
        )

    def test_asset_policy_capability_and_support_state_are_render_authority(
        self,
    ) -> None:
        descriptor = self.descriptor()
        donor_root = descriptor.donors[0].root.parent
        cases = (
            ("capability", "spatail", "unknown capability 'spatail'"),
            (
                "supportState",
                "disabled",
                "asset emission requires 'enabled'",
            ),
            ("source", "", r"\.source: expected a non-empty string"),
            (
                "license",
                {"arbitrary": True},
                r"\.license: expected a non-empty string",
            ),
        )
        for field, value, message in cases:
            with (
                self.subTest(field=field),
                tempfile.TemporaryDirectory(dir=ROOT) as directory,
            ):
                port = Path(directory) / "johto"
                shutil.copytree(PORT, port)
                path = port / "assets.json"
                document = json.loads(path.read_text(encoding="utf-8"))
                document["assets"][0][field] = value
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ContentPortError, message):
                    load_port(port, donor_root)

    def test_enabled_non_spatial_capability_cannot_be_stripped_by_rendering(
        self,
    ) -> None:
        descriptor = self.descriptor()
        donor_root = descriptor.donors[0].root.parent
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            port = Path(directory) / "johto"
            shutil.copytree(PORT, port)
            path = port / "capabilities.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            blackthorn = next(
                item
                for item in document["maps"]
                if item["map"] == "BlackthornCity_House1"
            )
            blackthorn["capabilities"]["interactions"] = "enabled"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(
                ContentPortError,
                "enabled capability is not materialized by the current render profile",
            ):
                load_port(port, donor_root)

    def test_owned_output_corruption_cannot_change_desired_state(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        recipe = OwnershipManifest.load(PORT / "ownership.json")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            ledger = ROOT / "src/data/persistence/persistent_ids.json"
            destination = repo / ledger.relative_to(ROOT)
            destination.parent.mkdir(parents=True)
            shutil.copyfile(ledger, destination)
            installed = repo / "tools/content_port/ports/johto/ownership.json"
            installed.parent.mkdir(parents=True)
            shutil.copyfile(PORT / "ownership.json", installed)
            for path in {
                unit.path for unit in recipe.units if unit.kind == "registry-record"
            }:
                source = ROOT / path
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            for name, mode in descriptor.map_ownership.items():
                if mode != "preserve":
                    continue
                for leaf in ("map.json", "scripts.inc"):
                    source = ROOT / "data/maps" / name / leaf
                    target = repo / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)

            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
            ):
                first_manifest, first_payloads = derive_desired_state(descriptor, repo)
                for path in sorted(
                    {
                        unit.path
                        for unit in recipe.units
                        if unit.kind != "registry-record"
                    }
                ):
                    target = repo / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"corrupt installed output\n")
                for path in {
                    unit.path for unit in recipe.units if unit.kind == "registry-record"
                }:
                    target = repo / path
                    document = json.loads(target.read_bytes())
                    for unit in (
                        candidate
                        for candidate in recipe.units
                        if candidate.kind == "registry-record"
                        and candidate.path == path
                    ):
                        records = document
                        if unit.registry not in {"$", "root"}:
                            for part in (unit.registry or "").split("."):
                                records = records[part]
                        if isinstance(records, dict):
                            value = records[unit.key]
                        elif unit.slot is not None:
                            value = records[unit.slot]
                        else:
                            value = next(
                                record
                                for record in records
                                if isinstance(record, dict)
                                and unit.key
                                in (
                                    record.get("key"),
                                    record.get("id"),
                                    record.get("name"),
                                )
                            )
                        if isinstance(value, dict):
                            value["_corrupt"] = True
                        elif isinstance(value, list):
                            value.append("CORRUPT_OUTPUT")
                    target.write_text(json.dumps(document), encoding="utf-8")
                second_manifest, second_payloads = derive_desired_state(
                    descriptor, repo
                )

            self.assertEqual(first_manifest.to_json(), second_manifest.to_json())
            self.assertEqual(dict(first_payloads), dict(second_payloads))
            policy_target_by_source = {
                f"{record['donor']}:{record['sourcePath']}": record["semanticTarget"]
                for record in descriptor.assets["assets"]
            }
            self.assertEqual(
                set(policy_target_by_source),
                set(state.inventory["asset-policy"]),
            )
            self.assertEqual(
                set(policy_target_by_source),
                set(state.inventory["asset-required"]),
            )
            self.assertEqual(
                {unit.key for unit in _asset_units(descriptor, state)},
                {f"asset:{target}" for target in state.asset_targets.values()},
            )
            self.assertEqual(policy_target_by_source, dict(state.asset_targets))
            actual_identities = tuple(unit.identity for unit in first_manifest.units)
            expected_identities = {unit.identity for unit in recipe.units} | {
                (
                    "section",
                    "src/data/trainers.party",
                    "selected trainer parties",
                )
            }
            self.assertEqual(len(actual_identities), len(set(actual_identities)))
            self.assertEqual(set(actual_identities), expected_identities)
            self.assertEqual(len(actual_identities), len(expected_identities))
            route30 = json.loads(first_payloads[("file", "data/maps/Route30/map.json")])
            route30_allocation = descriptor.allocation_index.map_allocation("Route30")
            self.assertEqual(route30["id"], route30_allocation.map_id)
            self.assertEqual(route30["layout"], route30_allocation.layout)
            self.assertEqual(route30["region_map_section"], route30_allocation.section)
            for field in descriptor.adaptations["materializationProfile"][
                "stripEventKinds"
            ]:
                self.assertEqual(route30[field], [])
            self.assertTrue(route30["warp_events"])
            incomplete_adaptations = dict(descriptor.adaptations)
            incomplete_profile = dict(descriptor.adaptations["materializationProfile"])
            incomplete_profile["stripEventKinds"] = (
                "bg_events",
                "coord_events",
            )
            incomplete_adaptations["materializationProfile"] = MappingProxyType(
                incomplete_profile
            )
            incomplete_descriptor = replace(
                descriptor,
                adaptations=MappingProxyType(incomplete_adaptations),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "must strip every non-warp event collection",
            ):
                _map_units(incomplete_descriptor, state)
            interaction_decisions = tuple(
                replace(decision, state=type(decision.state).ENABLED)
                if decision.map_name == "BlackthornCity_House1"
                and decision.capability == "interactions"
                else decision
                for decision in descriptor.capabilities
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "enabled capability 'interactions' is not materialized",
            ):
                _map_units(
                    replace(descriptor, capabilities=interaction_decisions),
                    state,
                )
            disabled_assets = dict(descriptor.assets)
            disabled_records = list(descriptor.assets["assets"])
            disabled_record = dict(disabled_records[0])
            disabled_record["supportState"] = "disabled"
            disabled_records[0] = MappingProxyType(disabled_record)
            disabled_assets["assets"] = tuple(disabled_records)
            disabled_descriptor = replace(
                descriptor,
                assets=MappingProxyType(disabled_assets),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset emission requires enabled support",
            ):
                _asset_units(disabled_descriptor, state)
            missing_asset_descriptor = replace(
                descriptor,
                assets=MappingProxyType(
                    {
                        **descriptor.assets,
                        "assets": descriptor.assets["assets"][1:],
                    }
                ),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset render inventory does not match authenticated closure",
            ):
                _asset_units(missing_asset_descriptor, state)
            removed_target = descriptor.assets["assets"][0]["semanticTarget"]
            self.assertIn(
                ("file", removed_target),
                {unit.identity for unit in recipe.units},
            )
            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
                self.assertRaisesRegex(
                    ContentPortError,
                    "asset render inventory does not match authenticated closure",
                ),
            ):
                derive_desired_state(missing_asset_descriptor, repo)
            mistargeted_assets = dict(descriptor.assets)
            mistargeted_records = list(descriptor.assets["assets"])
            mistargeted_record = dict(mistargeted_records[0])
            mistargeted_record["semanticTarget"] = (
                "data/layouts/AzaleaTown/unreferenced.bin"
            )
            mistargeted_records[0] = MappingProxyType(mistargeted_record)
            mistargeted_assets["assets"] = tuple(mistargeted_records)
            mistargeted_descriptor = replace(
                descriptor,
                assets=MappingProxyType(mistargeted_assets),
            )
            with self.assertRaisesRegex(
                ContentPortError,
                "asset render targets do not match authenticated closure",
            ):
                _asset_units(mistargeted_descriptor, state)
            victory_road = first_payloads[
                (
                    "registry-record",
                    "src/data/region_map/region_map_sections.json",
                    "map_sections",
                    "MAPSEC_JOHTO_VICTORY_ROAD",
                )
            ]
            self.assertEqual(victory_road["met_location"], 70)
            new_bark = first_payloads[
                (
                    "registry-record",
                    "data/layouts/layouts.json",
                    "layouts",
                    "LAYOUT_NEW_BARK_TOWN",
                )
            ]
            self.assertEqual(new_bark["width"], 30)
            self.assertEqual(new_bark["border_width"], 0)
            self.assertEqual(new_bark["border_height"], 0)
            self.assertRegex(
                first_payloads[
                    ("section", "include/constants/berry.h", "berry tree allocations")
                ].decode(),
                r"(?m)^#define BERRY_TREE_ROUTE_29_ORAN_1 +90$",
            )

    def test_new_group_and_layout_use_exact_authored_slots(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        layout_id = "LAYOUT_TEST_ALLOCATION"
        group_id = "gMapGroup_TestAllocation"
        allocation_index = replace(
            descriptor.allocation_index,
            layouts=MappingProxyType(
                {**descriptor.allocation_index.layouts, layout_id: 1040}
            ),
            groups=MappingProxyType(
                {**descriptor.allocation_index.groups, group_id: 100}
            ),
        )
        layout = dict(state.layouts["LAYOUT_NEW_BARK_TOWN"])
        layout["id"] = layout_id
        expanded_state = replace(
            state,
            layouts=MappingProxyType({**state.layouts, layout_id: layout}),
        )
        expanded = replace(descriptor, allocation_index=allocation_index)

        layout_unit = next(
            unit
            for unit in _layout_units(expanded, expanded_state)
            if unit.key == layout_id
        )
        group_order = next(
            unit
            for unit in _group_units(expanded)
            if unit.key == f"group-order:{group_id}"
        )
        self.assertEqual(layout_unit.slot, 1040)
        self.assertEqual(group_order.registry, "group_order")
        self.assertEqual(group_order.record_key, group_id)
        self.assertEqual(group_order.slot, 100)

    def test_map_identity_layout_and_section_come_from_allocation(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        route30 = dict(state.maps["Route30"])
        route30.update(
            {
                "id": "MAP_DONOR_DRIFT",
                "layout": "LAYOUT_DONOR_DRIFT",
                "region_map_section": "MAPSEC_DONOR_DRIFT",
            }
        )
        drifted = replace(
            state,
            maps=MappingProxyType({**state.maps, "Route30": route30}),
        )
        unit = next(
            unit
            for unit in _map_units(descriptor, drifted)
            if unit.key == "map:Route30"
        )
        allocation = descriptor.allocation_index.map_allocation("Route30")
        section_remaps = {
            item["source"]: item["target"]
            for item in descriptor.adaptations["sectionSymbolRemaps"]
        }
        self.assertEqual(unit.value["id"], allocation.map_id)
        self.assertEqual(unit.value["layout"], allocation.layout)
        self.assertEqual(
            unit.value["region_map_section"],
            section_remaps.get(allocation.section, allocation.section),
        )

        vermilion_map = next(
            item
            for item in _map_units(descriptor, state)
            if item.key == "map:VermilionCity_PortInside"
        )
        vermilion_allocation = descriptor.allocation_index.map_allocation(
            "VermilionCity_PortInside"
        )
        sections_by_slot = {
            item.slot: item for item in _section_units(descriptor, state, ROOT)
        }
        vermilion_section = sections_by_slot[vermilion_allocation.target_section]
        self.assertEqual(
            vermilion_map.value["region_map_section"], vermilion_section.record_key
        )
        self.assertEqual(vermilion_map.value["region"], "REGION_JOHTO")
        self.assertEqual(vermilion_section.value["region"], "REGION_JOHTO")
        self.assertEqual(vermilion_section.slot, 260)
        manifest, _ = render_units(
            RenderContext("johto"), (vermilion_map, vermilion_section)
        )
        self.assertIn(
            ("file", "data/maps/VermilionCity_PortInside/map.json"),
            manifest.by_identity,
        )
        section_identity = (
            "registry-record",
            "src/data/region_map/region_map_sections.json",
            "map_sections",
            "MAPSEC_JOHTO_VERMILION_PORT",
        )
        self.assertEqual(manifest.by_identity[section_identity].slot, 260)

    def test_transient_route30_mutation_cannot_enter_snapshot_render(
        self,
    ) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        source = (
            descriptor.donors_by_role["content"].root / "data/maps/Route30/map.json"
        )
        source_document = json.loads(source.read_bytes())
        original_weather = source_document["weather"]
        transient_weather = "WEATHER_SUNNY_CLOUDS"
        self.assertNotEqual(original_weather, transient_weather)

        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory) / "donor"
            route30 = donor / "data/maps/Route30/map.json"
            route30.parent.mkdir(parents=True)
            route30.write_bytes(source.read_bytes())
            records = source_tree_records(donor)
            pin = DonorPin(
                "isolated",
                "example/isolated",
                "0" * 40,
                records_digest(records),
                len(records),
                donor,
            )
            isolated_descriptor = replace(
                descriptor,
                donors=(pin,),
                donors_by_role=MappingProxyType({"content": pin, "mechanical": pin}),
                map_ownership=MappingProxyType({"Route30": "rendered"}),
            )
            original = route30.read_bytes()

            def resolve_during_transient_mutation(snapshot_descriptor, _repo):
                document = json.loads(original)
                document["weather"] = transient_weather
                route30.write_text(json.dumps(document), encoding="utf-8")
                try:
                    snapshot_route30 = (
                        snapshot_descriptor.donors_by_role["content"].root
                        / "data/maps/Route30/map.json"
                    )
                    self.assertFalse(os.path.samefile(route30, snapshot_route30))
                    rendered_map = json.loads(snapshot_route30.read_bytes())
                    isolated_state = replace(
                        state,
                        maps=MappingProxyType({"Route30": rendered_map}),
                        donor_roots=MappingProxyType(
                            {
                                role: pin.root
                                for role, pin in snapshot_descriptor.donors_by_role.items()
                            }
                        ),
                    )
                    return (), isolated_state
                finally:
                    route30.write_bytes(original)

            with (
                patch.dict(os.environ, {"CONTENT_PORT_REQUIRE_DONORS": "0"}),
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    side_effect=resolve_during_transient_mutation,
                ),
                patch("tools.content_port.materialize._layout_units", return_value=[]),
                patch("tools.content_port.materialize._group_units", return_value=[]),
                patch("tools.content_port.materialize._section_units", return_value=[]),
                patch("tools.content_port.materialize._asset_units", return_value=[]),
                patch(
                    "tools.content_port.materialize._generated_units", return_value=[]
                ),
            ):
                _, payloads = derive_desired_state(isolated_descriptor, Path(directory))

            rendered = json.loads(payloads[("file", "data/maps/Route30/map.json")])
            self.assertEqual(rendered["weather"], original_weather)
            self.assertEqual(route30.read_bytes(), original)

    def test_mechanical_layout_border_drift_fails_authentication(self) -> None:
        descriptor = self.descriptor()
        source = (
            descriptor.donors_by_role["mechanical"].root / "data/layouts/layouts.json"
        )
        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory) / "donor"
            layouts = donor / "data/layouts/layouts.json"
            layouts.parent.mkdir(parents=True)
            layouts.write_bytes(source.read_bytes())
            records = source_tree_records(donor)
            pin = DonorPin(
                "isolated",
                "example/isolated",
                "0" * 40,
                records_digest(records),
                len(records),
                donor,
            )
            document = json.loads(layouts.read_bytes())
            new_bark = next(
                item
                for item in document["layouts"]
                if item["id"] == "LAYOUT_NEW_BARK_TOWN"
            )
            self.assertEqual(new_bark["border_width"], 0)
            new_bark["border_width"] = 1
            layouts.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            isolated_descriptor = replace(
                descriptor,
                donors=(pin,),
                donors_by_role=MappingProxyType({"content": pin, "mechanical": pin}),
            )
            with (
                patch.dict(os.environ, {"CONTENT_PORT_REQUIRE_DONORS": "0"}),
                self.assertRaisesRegex(ContentPortError, "source-tree digest mismatch"),
            ):
                derive_desired_state(isolated_descriptor, ROOT)

    def test_victory_road_codec_requires_a_ledger_binding(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        bindings = descriptor.target_bindings
        assert bindings is not None
        codec = bindings.section_persistence_codecs[0]
        broken = replace(
            descriptor,
            target_bindings=replace(
                bindings,
                section_persistence_codecs=(
                    replace(
                        codec,
                        met_location_binding=PersistentBindingRef(
                            "destinations", "MAPSEC_BLACKTHORN_CITY"
                        ),
                    ),
                ),
            ),
        )
        with (
            patch(
                "tools.content_port.materialize.resolve_port_sources",
                return_value=(evidence, state),
            ),
            patch(
                "tools.content_port.materialize.authenticated_donor_snapshot",
                return_value=nullcontext(descriptor.donors),
            ),
            self.assertRaisesRegex(ContentPortError, "must match its display identity"),
        ):
            derive_desired_state(broken, ROOT)

    def test_ordinary_section_codes_must_agree_with_the_persistent_ledger(
        self,
    ) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        source = ROOT / "src/data/persistence/persistent_ids.json"
        original = json.loads(source.read_text(encoding="utf-8"))
        for domain, label in (
            ("destinations", "persistent destination binding"),
            ("savedLocations", "persistent saved location binding"),
        ):
            with (
                self.subTest(domain=domain),
                tempfile.TemporaryDirectory() as directory,
            ):
                repo = Path(directory)
                document = json.loads(json.dumps(original))
                binding = next(
                    item
                    for item in document["entries"]
                    if item["domain"] == domain
                    and item["symbol"] == "MAPSEC_NEW_BARK_TOWN"
                )
                self.assertEqual(binding["value"], 209)
                binding["value"] = 10000
                target = repo / source.relative_to(ROOT)
                target.parent.mkdir(parents=True)
                target.write_text(json.dumps(document), encoding="utf-8")
                with (
                    patch(
                        "tools.content_port.materialize.resolve_port_sources",
                        return_value=(evidence, state),
                    ),
                    patch(
                        "tools.content_port.materialize.authenticated_donor_snapshot",
                        return_value=nullcontext(descriptor.donors),
                    ),
                    self.assertRaisesRegex(ContentPortError, label),
                ):
                    derive_desired_state(descriptor, repo)

    def test_berry_tree_binding_requires_an_allocated_ledger_identity(self) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            source = ROOT / "src/data/persistence/persistent_ids.json"
            document = json.loads(source.read_text(encoding="utf-8"))
            document["entries"] = [
                item
                for item in document["entries"]
                if item["symbol"] != "BERRY_TREE_ROUTE_29_ORAN_1"
            ]
            target = repo / source.relative_to(ROOT)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps(document), encoding="utf-8")
            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    return_value=(evidence, state),
                ),
                patch(
                    "tools.content_port.materialize.authenticated_donor_snapshot",
                    return_value=nullcontext(descriptor.donors),
                ),
                self.assertRaisesRegex(ContentPortError, "has no ledger binding"),
            ):
                derive_desired_state(descriptor, repo)

    def test_generated_section_authority_contract_is_enforced_in_production(
        self,
    ) -> None:
        descriptor = self.descriptor()
        evidence, state = resolve_port_sources(descriptor, ROOT)
        policies = tuple(
            replace(policy, authorities=("mechanical",))
            if policy.source_symbol == "flag-bindings"
            else policy
            for policy in descriptor.generated_sections
        )
        with (
            patch(
                "tools.content_port.materialize.resolve_port_sources",
                return_value=(evidence, state),
            ),
            patch(
                "tools.content_port.materialize.authenticated_donor_snapshot",
                return_value=nullcontext(descriptor.donors),
            ),
            self.assertRaisesRegex(ContentPortError, "authority contract drift"),
        ):
            derive_desired_state(replace(descriptor, generated_sections=policies), ROOT)

    def test_donor_asset_mutation_fails_closed(self) -> None:
        descriptor = self.descriptor()
        _, state = resolve_port_sources(descriptor, ROOT)
        asset = descriptor.assets["assets"][0]
        role = asset["donor"]
        source_path = asset["sourcePath"]
        with tempfile.TemporaryDirectory() as directory:
            donor = Path(directory)
            target = donor / source_path
            target.parent.mkdir(parents=True)
            shutil.copyfile(state.donor_roots[role] / source_path, target)
            isolated = replace(
                state,
                donor_roots=MappingProxyType({**state.donor_roots, role: donor}),
                asset_targets=MappingProxyType(
                    {f"{role}:{source_path}": asset["semanticTarget"]}
                ),
                inventory=MappingProxyType(
                    {
                        **state.inventory,
                        "asset-policy": (f"{role}:{source_path}",),
                        "asset-required": (f"{role}:{source_path}",),
                    }
                ),
            )
            focused = replace(
                descriptor,
                assets=MappingProxyType({"schemaVersion": 1, "assets": (asset,)}),
            )
            self.assertEqual(len(_asset_units(focused, isolated)), 1)
            target.write_bytes(target.read_bytes() + b"mutation")
            with self.assertRaisesRegex(ContentPortError, "hash drift"):
                _asset_units(focused, isolated)


if __name__ == "__main__":
    unittest.main()
