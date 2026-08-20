from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.map_render.catalog import (
    MapRenderError,
    default_schema_path,
    discover,
    load_config,
    map_entry,
)
from tools.map_render.cli import main
from tools.map_render.renderer import render


ROOT = Path(__file__).resolve().parents[3]


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        cls.discovery = discover(ROOT, cls.config)

    def test_all_exterior_maps_have_one_region(self) -> None:
        counts = Counter(target.region_id for target in self.discovery.targets)
        self.assertEqual(
            counts,
            {
                "hoenn": 83,
                "kanto": 43,
                "johto": 60,
                "sevii-islands": 29,
            },
        )
        self.assertEqual(len(self.discovery.targets), 215)

    def test_categories_preserve_nonstandard_exteriors(self) -> None:
        categories = {target.name: target.category for target in self.discovery.targets}
        self.assertEqual(categories["Underwater_Route124"], "underwater")
        self.assertEqual(categories["AquaHideout_UnusedRubyMap2"], "generated")
        self.assertEqual(categories["Route104_Prototype"], "prototypes")
        self.assertEqual(categories["SaffronCity_Connection_Frlg"], "technical")
        self.assertEqual(
            categories["GoldenrodCity_DepartmentStore_7FNight"], "technical"
        )

    def test_variants_and_layers_are_explicit(self) -> None:
        targets = {target.name: target for target in self.discovery.targets}
        self.assertEqual(targets["Underwater_Route124"].world["layer"], "underwater")
        self.assertEqual(
            targets["AquaHideout_UnusedRubyMap2"].world["layer"], "generated"
        )
        self.assertFalse(targets["AquaHideout_UnusedRubyMap2"].world["defaultVisible"])
        self.assertFalse(targets["MtSilver_SummitNight"].world["defaultVisible"])
        self.assertFalse(
            targets["GoldenrodCity_DepartmentStore_7FNight"].world["defaultVisible"]
        )
        self.assertEqual(
            targets["MtSilver_SummitNight"].world["variantGroup"],
            "johto-mt-silver-summit",
        )

    def test_catalog_entry_has_connection_and_warp_geometry(self) -> None:
        target = next(
            target for target in self.discovery.targets if target.name == "NewBarkTown"
        )
        entry = map_entry(target, self.discovery.map_names_by_id, "a" * 64)
        east = next(
            connection
            for connection in entry["connections"]
            if connection["direction"] == "right"
        )
        self.assertEqual(east["destinationMap"], "Route27")
        self.assertEqual(east["offsetMetatiles"], -11)
        self.assertEqual(entry["layout"]["widthMetatiles"], 30)
        self.assertEqual(entry["image"]["widthPixels"], 480)
        self.assertTrue(entry["warps"])
        self.assertEqual(entry["warps"][0]["warpId"], "0")

    def test_schema_covers_every_connection_and_warp_record(self) -> None:
        schema = json.loads(default_schema_path().read_text())
        connection_schema = schema["$defs"]["connection"]
        warp_schema = schema["$defs"]["warp"]
        self.assertFalse(connection_schema["additionalProperties"])
        self.assertFalse(warp_schema["additionalProperties"])
        allowed_directions = set(connection_schema["properties"]["direction"]["enum"])
        entries = [
            map_entry(target, self.discovery.map_names_by_id, "a" * 64)
            for target in self.discovery.targets
        ]
        connections = [
            connection for entry in entries for connection in entry["connections"]
        ]
        warps = [warp for entry in entries for warp in entry["warps"]]
        self.assertLessEqual(
            {connection["direction"] for connection in connections},
            allowed_directions,
        )
        self.assertTrue(
            all(
                set(connection) == set(connection_schema["properties"])
                for connection in connections
            )
        )
        self.assertTrue(
            all(set(warp) == set(warp_schema["properties"]) for warp in warps)
        )

    def test_unassigned_exterior_is_rejected(self) -> None:
        config = deepcopy(self.config)
        config["regions"] = [
            region for region in config["regions"] if region["id"] != "sevii-islands"
        ]
        with self.assertRaisesRegex(MapRenderError, "unassigned exterior map"):
            discover(ROOT, config)


class RendererTests(unittest.TestCase):
    def test_render_is_deterministic_and_native_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.png"
            second = Path(temporary) / "second.png"
            render(ROOT, "PalletTown_Frlg", first, announce=False)
            render(ROOT, "PalletTown_Frlg", second, announce=False)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            width, height = struct.unpack(">II", first.read_bytes()[16:24])
            self.assertEqual((width, height), (384, 320))


class CliTests(unittest.TestCase):
    def test_render_writes_selected_region_catalog(self) -> None:
        events = []

        def fake_render(_root, name, output, *, announce):
            self.assertEqual(events, ["source-state"])
            self.assertFalse(announce)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(name.encode())

        def fake_source_state(_repo, _revision):
            events.append("source-state")
            return "fixture-revision", False

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with (
                patch("tools.map_render.cli.render", side_effect=fake_render),
                patch(
                    "tools.map_render.cli._source_state",
                    side_effect=fake_source_state,
                ),
            ):
                result = main(
                    [
                        "render",
                        "--repo",
                        str(ROOT),
                        "--output",
                        str(output),
                        "--region",
                        "kanto",
                    ]
                )
            self.assertEqual(result, 0)
            catalog = json.loads((output / "catalog.json").read_text())
            schema = json.loads((output / "catalog.schema.json").read_text())
            self.assertEqual(catalog["$schema"], "catalog.schema.json")
            self.assertEqual(schema["properties"]["schemaVersion"]["const"], 1)
            self.assertEqual(catalog["source"]["revision"], "fixture-revision")
            self.assertEqual(catalog["regions"][0]["mapCount"], 43)
            self.assertEqual(len(catalog["maps"]), 43)
            self.assertTrue(
                all(
                    (output / entry["image"]["path"]).is_file()
                    for entry in catalog["maps"]
                )
            )


if __name__ == "__main__":
    unittest.main()
