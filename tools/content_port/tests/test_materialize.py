from __future__ import annotations

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
from tools.content_port.errors import ContentPortError
from tools.content_port.materialize import _asset_units, derive_desired_state
from tools.content_port.model import PersistentBindingRef
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
            for name, mode in descriptor.map_ownership.items():
                if mode != "preserve":
                    continue
                for leaf in ("map.json", "scripts.inc"):
                    source = ROOT / "data/maps" / name / leaf
                    target = repo / source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)

            with patch(
                "tools.content_port.materialize.resolve_port_sources",
                return_value=(evidence, state),
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
            self.assertRegex(
                first_payloads[
                    ("section", "include/constants/berry.h", "berry tree allocations")
                ].decode(),
                r"(?m)^#define BERRY_TREE_ROUTE_29_ORAN_1 +90$",
            )

    def test_route30_mutation_during_derivation_fails_post_authentication(
        self,
    ) -> None:
        descriptor = self.descriptor()
        donor = descriptor.donors_by_role["content"].root
        route30 = donor / "data/maps/Route30/map.json"
        original = route30.read_bytes()
        resolved = resolve_port_sources

        def mutate_after_resolving(*args, **kwargs):
            result = resolved(*args, **kwargs)
            route30.write_bytes(original + b"\n")
            return result

        self.addCleanup(route30.write_bytes, original)
        try:
            with (
                patch(
                    "tools.content_port.materialize.resolve_port_sources",
                    side_effect=mutate_after_resolving,
                ),
                self.assertRaisesRegex(ContentPortError, "source-tree digest mismatch"),
            ):
                derive_desired_state(descriptor, ROOT)
        finally:
            route30.write_bytes(original)

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
                "tools.content_port.materialize.authenticate_donors", return_value=()
            ),
            self.assertRaisesRegex(ContentPortError, "must match its display identity"),
        ):
            derive_desired_state(broken, ROOT)

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
                    "tools.content_port.materialize.authenticate_donors",
                    return_value=(),
                ),
                self.assertRaisesRegex(ContentPortError, "has no ledger binding"),
            ):
                derive_desired_state(descriptor, repo)

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
