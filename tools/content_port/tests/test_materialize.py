from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
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
from tools.content_port.materialize import _asset_units, derive_desired_state
from tools.content_port.model import DonorPin, PersistentBindingRef
from tools.content_port.ownership import OwnershipManifest
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
                for path in sorted({unit.path for unit in recipe.units}):
                    target = repo / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"corrupt installed output\n")
                second_manifest, second_payloads = derive_desired_state(
                    descriptor, repo
                )

            self.assertEqual(first_manifest.to_json(), second_manifest.to_json())
            self.assertEqual(dict(first_payloads), dict(second_payloads))
            self.assertEqual(len(first_manifest.units), len(recipe.units))
            self.assertEqual(
                {unit.identity for unit in first_manifest.units},
                {unit.identity for unit in recipe.units},
            )
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
