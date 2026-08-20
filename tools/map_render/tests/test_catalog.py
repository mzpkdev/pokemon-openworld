from __future__ import annotations

from collections import Counter
from copy import deepcopy
from contextlib import redirect_stderr
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from tools.map_render.catalog import (
    MapRenderError,
    asset_output_paths,
    default_schema_path,
    discover,
    load_config,
    map_entry,
)
from tools.map_render.cli import _prepare_output_directory, _promote_staging, main
from tools.map_render.renderer import downscale_rgb_nearest, render


ROOT = Path(__file__).resolve().parents[3]


def directory_contents(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def decoded_rgb_payload(path: Path) -> bytes:
    png = path.read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")

    position = 8
    header = None
    image_data = []
    while position < len(png):
        length = struct.unpack(">I", png[position : position + 4])[0]
        kind = png[position + 4 : position + 8]
        payload = png[position + 8 : position + 8 + length]
        position += length + 12
        if kind == b"IHDR":
            header = payload
        elif kind == b"IDAT":
            image_data.append(payload)
        elif kind == b"IEND":
            break

    if header is None:
        raise ValueError(f"missing PNG header: {path}")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    if (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0):
        raise ValueError(f"unsupported PNG format: {path}")

    stride = width * 3
    raw = zlib.decompress(b"".join(image_data))
    if len(raw) != height * (stride + 1) or any(
        raw[offset] for offset in range(0, len(raw), stride + 1)
    ):
        raise ValueError(f"expected unfiltered RGB scanlines: {path}")
    return b"".join(
        raw[offset + 1 : offset + stride + 1]
        for offset in range(0, len(raw), stride + 1)
    )


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
                "kanto": 46,
                "johto": 60,
                "sevii-islands": 29,
            },
        )
        self.assertEqual(len(self.discovery.targets), 218)

    def test_categories_preserve_nonstandard_exteriors(self) -> None:
        categories = {target.name: target.category for target in self.discovery.targets}
        self.assertEqual(categories["Underwater_Route124"], "underwater")
        self.assertEqual(categories["AquaHideout_UnusedRubyMap2"], "generated")
        self.assertEqual(categories["Route104_Prototype"], "prototypes")
        self.assertEqual(categories["SaffronCity_Connection_Frlg"], "technical")
        self.assertEqual(categories["SouthernKantoSeaBasin_West_Frlg"], "routes")
        self.assertEqual(categories["SouthernKantoSeaBasin_Central_Frlg"], "routes")
        self.assertEqual(categories["SouthernKantoSeaBasin_East_Frlg"], "routes")
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
        entry = map_entry(target, self.discovery.map_names_by_id, "a" * 64, "b" * 64)
        east = next(
            connection
            for connection in entry["connections"]
            if connection["direction"] == "right"
        )
        self.assertEqual(east["destinationMap"], "Route27")
        self.assertEqual(east["offsetMetatiles"], -11)
        self.assertEqual(entry["layout"]["widthMetatiles"], 30)
        self.assertEqual(entry["image"]["widthPixels"], 480)
        self.assertEqual(
            entry["image"]["overview"],
            {
                "path": "overviews/johto/towns/NewBarkTown.png",
                "sha256": "b" * 64,
                "widthPixels": 120,
                "heightPixels": 156,
            },
        )
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
            map_entry(target, self.discovery.map_names_by_id, "a" * 64, "b" * 64)
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

    def test_asset_output_paths_are_distinct_for_dotted_names_and_collisions(
        self,
    ) -> None:
        source = self.discovery.targets[0]
        plain = replace(source, name="Route")
        dotted = replace(source, name="Route.overview")
        paths = asset_output_paths((plain, dotted))

        self.assertEqual(
            paths,
            (
                f"maps/{source.region_id}/{source.category}/Route.png",
                f"overviews/{source.region_id}/{source.category}/Route.png",
                f"maps/{source.region_id}/{source.category}/Route.overview.png",
                f"overviews/{source.region_id}/{source.category}/Route.overview.png",
            ),
        )
        self.assertEqual(len(asset_output_paths(self.discovery.targets)), 436)
        with self.assertRaisesRegex(MapRenderError, "duplicate catalog asset path"):
            asset_output_paths((plain, replace(plain)))


class RendererTests(unittest.TestCase):
    def test_downscale_rgb_nearest_samples_the_top_left_pixel_of_each_block(
        self,
    ) -> None:
        width, height = 8, 8
        pixels = bytearray(
            component
            for y in range(height)
            for x in range(width)
            for component in (x, y, (x + y) % 256)
        )

        overview_width, overview_height, overview_pixels = downscale_rgb_nearest(
            width, height, pixels
        )

        self.assertEqual((overview_width, overview_height), (2, 2))
        self.assertEqual(
            list(overview_pixels),
            [0, 0, 0, 4, 0, 4, 0, 4, 4, 4, 4, 8],
        )

    def test_render_is_deterministic_at_native_and_overview_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first_native = Path(temporary) / "first.png"
            first_overview = Path(temporary) / "first.overview.png"
            second_native = Path(temporary) / "second.png"
            second_overview = Path(temporary) / "second.overview.png"
            render(
                ROOT,
                "PalletTown_Frlg",
                first_native,
                overview_output=first_overview,
                announce=False,
            )
            render(
                ROOT,
                "PalletTown_Frlg",
                second_native,
                overview_output=second_overview,
                announce=False,
            )
            self.assertEqual(first_native.read_bytes(), second_native.read_bytes())
            self.assertEqual(first_overview.read_bytes(), second_overview.read_bytes())
            self.assertEqual(
                hashlib.sha256(decoded_rgb_payload(first_native)).hexdigest(),
                "1f03658177b2a2269708e09d612ddab3afbe6467f13a9af35f4d336215d06308",
            )
            self.assertEqual(
                hashlib.sha256(decoded_rgb_payload(first_overview)).hexdigest(),
                "890d732047876b416f2019783cb4ef1e63665ff6b538cfd11a7077e0418e9f42",
            )
            native_dimensions = struct.unpack(">II", first_native.read_bytes()[16:24])
            overview_dimensions = struct.unpack(
                ">II", first_overview.read_bytes()[16:24]
            )
            self.assertEqual(native_dimensions, (384, 320))
            self.assertEqual(overview_dimensions, (96, 80))


class CliTests(unittest.TestCase):
    def test_render_writes_selected_region_catalog(self) -> None:
        events = []

        def fake_render(_root, name, output, *, overview_output, announce):
            self.assertEqual(events, ["source-state"])
            self.assertFalse(announce)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"native:{name}".encode())
            self.assertIsNotNone(overview_output)
            overview_output.parent.mkdir(parents=True, exist_ok=True)
            overview_output.write_bytes(f"overview:{name}".encode())

        def fake_source_state(_repo, _revision):
            events.append("source-state")
            return "fixture-revision", False

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            (output / "stale-file.txt").write_text("obsolete")
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
            self.assertEqual(schema["properties"]["schemaVersion"]["const"], 2)
            self.assertEqual(catalog["schemaVersion"], 2)
            self.assertEqual(catalog["source"]["revision"], "fixture-revision")
            self.assertEqual(catalog["regions"][0]["mapCount"], 46)
            self.assertEqual(len(catalog["maps"]), 46)
            self.assertFalse((output / "stale-file.txt").exists())
            self.assertTrue(
                all(
                    (output / entry["image"]["path"]).is_file()
                    for entry in catalog["maps"]
                )
            )
            self.assertTrue(
                all(
                    (output / entry["image"]["overview"]["path"]).is_file()
                    for entry in catalog["maps"]
                )
            )
            first_entry = catalog["maps"][0]
            first_image = first_entry["image"]
            self.assertEqual(
                first_image["overview"]["path"],
                "overviews/"
                f"{first_entry['region']}/{first_entry['category']}/{first_entry['name']}.png",
            )
            self.assertEqual(
                first_image["overview"]["widthPixels"],
                first_image["widthPixels"] // 4,
            )
            self.assertEqual(
                first_image["overview"]["heightPixels"],
                first_image["heightPixels"] // 4,
            )
            self.assertEqual(
                first_image["overview"]["sha256"],
                hashlib.sha256(
                    (output / first_image["overview"]["path"]).read_bytes()
                ).hexdigest(),
            )

    def test_render_failure_leaves_previous_output_unchanged(self) -> None:
        calls: list[str] = []

        def failing_render(_root, name, output, *, overview_output, announce):
            self.assertFalse(announce)
            calls.append(name)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(f"native:{name}".encode())
            overview_output.parent.mkdir(parents=True, exist_ok=True)
            overview_output.write_bytes(f"overview:{name}".encode())
            if len(calls) == 2:
                raise OSError("injected render failure")

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            (output / "maps" / "old").mkdir(parents=True)
            (output / "maps" / "old" / "previous.png").write_bytes(b"previous")
            (output / "catalog.json").write_bytes(b'{"previous": true}\n')
            previous = directory_contents(output)
            with (
                patch("tools.map_render.cli.render", side_effect=failing_render),
                patch(
                    "tools.map_render.cli._source_state",
                    return_value=("fixture-revision", False),
                ),
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as failure,
            ):
                main(
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

            self.assertEqual(failure.exception.code, 2)
            self.assertEqual(len(calls), 2)
            self.assertEqual(directory_contents(output), previous)
            self.assertFalse(list(Path(temporary).glob(".output.staging-*")))

    def test_render_preflights_collisions_before_touching_output(self) -> None:
        discovery = discover(ROOT, load_config())
        first = discovery.targets[0]
        collision = replace(discovery, targets=(first, replace(first)))

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            output.mkdir()
            (output / "catalog.json").write_bytes(b"previous catalog")
            previous = directory_contents(output)
            with (
                patch("tools.map_render.cli.discover", return_value=collision),
                patch(
                    "tools.map_render.cli._source_state",
                    return_value=("fixture-revision", False),
                ),
                patch("tools.map_render.cli.render") as mocked_render,
                redirect_stderr(StringIO()),
                self.assertRaises(SystemExit) as failure,
            ):
                main(
                    [
                        "render",
                        "--repo",
                        str(ROOT),
                        "--output",
                        str(output),
                        "--region",
                        first.region_id,
                    ]
                )

            self.assertEqual(failure.exception.code, 2)
            mocked_render.assert_not_called()
            self.assertEqual(directory_contents(output), previous)
            self.assertFalse(list(Path(temporary).glob(".output.staging-*")))

    def test_render_rejects_file_and_symlink_output_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            file_output = root / "output-file"
            file_output.write_bytes(b"not a directory")
            symlink_target = root / "existing-output"
            symlink_target.mkdir()
            (symlink_target / "keep.txt").write_text("keep")
            symlink_output = root / "output-link"
            symlink_output.symlink_to(symlink_target, target_is_directory=True)

            for output in (file_output, symlink_output):
                with (
                    patch(
                        "tools.map_render.cli._source_state",
                        return_value=("fixture-revision", False),
                    ),
                    patch("tools.map_render.cli.render") as mocked_render,
                    redirect_stderr(StringIO()),
                    self.assertRaises(SystemExit) as failure,
                ):
                    main(
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
                self.assertEqual(failure.exception.code, 2)
                mocked_render.assert_not_called()

            self.assertEqual(file_output.read_bytes(), b"not a directory")
            self.assertEqual((symlink_target / "keep.txt").read_text(), "keep")

    def test_render_restricts_in_repository_outputs_to_build_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            build = repo / "build"
            build.mkdir(parents=True)
            rejected = (
                root,
                repo,
                repo / ".git" / "data" / "maps",
                repo / "data" / "maps",
                build,
            )

            for output in rejected:
                with self.assertRaises(MapRenderError):
                    _prepare_output_directory(output, repo)

            allowed = build / "map-catalog"
            outside = root / "explicit-output" / "map-catalog"
            self.assertEqual(_prepare_output_directory(allowed, repo), allowed)
            self.assertEqual(_prepare_output_directory(outside, repo), outside)
            self.assertFalse((repo / ".git").exists())
            self.assertFalse((repo / "data").exists())

    def test_promotion_keeps_the_new_catalog_when_backup_cleanup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output = parent / "output"
            output.mkdir()
            (output / "old.txt").write_text("old")
            staging = parent / ".output.staging-fixture"
            staging.mkdir()
            (staging / "new.txt").write_text("new")
            backup = parent / ".output.previous-fixture"

            with patch("tools.map_render.cli.shutil.rmtree", side_effect=OSError):
                _promote_staging(staging, output)

            self.assertEqual((output / "new.txt").read_text(), "new")
            self.assertTrue((backup / "old.txt").is_file())


if __name__ == "__main__":
    unittest.main()
