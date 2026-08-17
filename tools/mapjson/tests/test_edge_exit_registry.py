import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools/mapjson/mapjson"
GROUPS = ROOT / "data/maps/map_groups.json"
LAYOUTS = ROOT / "data/layouts/layouts.json"
MAPS = sorted((ROOT / "data/maps").glob("*/map.json"))
SOURCE = ROOT / "data/maps/Route19_Frlg/map.json"


class SurfEdgeExitRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)

    def run_validation(
        self, exits, source_path: Path = SOURCE
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="edge-exit-validation-") as directory:
            source = Path(directory) / "map.json"
            data = json.loads(source_path.read_text())
            data["edge_exits"] = exits
            source.write_text(json.dumps(data))
            maps = [source if path == source_path else path for path in MAPS]
            return subprocess.run(
                [
                    str(MAPJSON),
                    "edge_exits",
                    "allregions",
                    str(GROUPS),
                    str(LAYOUTS),
                    *(str(path) for path in maps),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

    @staticmethod
    def valid_exit(**updates):
        result = {
            "exit_edge": "south",
            "target_map": "MAP_ROUTE40",
            "target_x": 1,
            "target_y": 1,
            "target_facing": "north",
        }
        result.update(updates)
        return result

    def assert_invalid(self, exits, message: str) -> None:
        result = self.run_validation(exits)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)

    def test_validates_strict_schema_and_scalar_types(self) -> None:
        valid = self.run_validation([self.valid_exit()])
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual(valid.stdout, "edge_exits=2\n")

        missing = self.valid_exit()
        del missing["target_facing"]
        self.assert_invalid([missing], "must contain exactly")
        self.assert_invalid([self.valid_exit(comment="extra")], "must contain exactly")
        self.assert_invalid(
            [self.valid_exit(route_profile="unknown")], "invalid route profile 'unknown'"
        )
        self.assert_invalid(
            [self.valid_exit(route_profile=1)], "route_profile must be a string"
        )
        self.assert_invalid(
            [self.valid_exit(target_x=1.5)], "target_x' must be an integer"
        )
        self.assert_invalid(
            [self.valid_exit(target_y=True)], "target_y' must be an integer"
        )
        self.assert_invalid(
            [self.valid_exit(exit_edge=1)], "exit_edge' must be a string"
        )
        self.assert_invalid(None, "edge_exits must be an array")

    def test_rejects_invalid_directions_and_duplicate_source_edges(self) -> None:
        self.assert_invalid([self.valid_exit(exit_edge="up")], "invalid edge 'up'")
        self.assert_invalid(
            [self.valid_exit(target_facing="down")], "invalid facing 'down'"
        )
        self.assert_invalid(
            [self.valid_exit(), self.valid_exit(target_x=2)],
            "duplicate Surf edge 'south'",
        )

    def test_rejects_unknown_or_ungrouped_targets(self) -> None:
        self.assert_invalid(
            [self.valid_exit(target_map="MAP_DOES_NOT_EXIST")],
            "unknown target map id 'MAP_DOES_NOT_EXIST'",
        )
        self.assert_invalid(
            [self.valid_exit(target_map="MAP_ROUTE19_UNUSED_HOUSE")],
            "ungrouped target map 'Route19_UnusedHouse_Frlg'",
        )
        ungrouped_source = ROOT / "data/maps/Route19_UnusedHouse_Frlg/map.json"
        result = self.run_validation([self.valid_exit()], ungrouped_source)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ungrouped map 'Route19_UnusedHouse_Frlg'", result.stderr)

    def test_rejects_coordinate_range_bounds_and_connection_conflicts(self) -> None:
        self.assert_invalid(
            [self.valid_exit(target_x=-1)], "nonnegative signed 16-bit range"
        )
        self.assert_invalid(
            [self.valid_exit(target_y=32768)], "nonnegative signed 16-bit range"
        )
        self.assert_invalid([self.valid_exit(target_x=34)], "outside map 'Route40'")
        self.assert_invalid(
            [self.valid_exit(exit_edge="north")],
            "conflicts with an authored cardinal connection",
        )

    def test_emits_canonical_registry_manifest_and_policy_filtered_zero_form(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="edge-exit-generation-") as directory:
            base = Path(directory)
            copied_map_dir = base / "maps/Route19_Frlg"
            shutil.copytree(SOURCE.parent, copied_map_dir)
            source = copied_map_dir / "map.json"
            data = json.loads(source.read_text())
            data["edge_exits"] = [
                self.valid_exit(
                    exit_edge="east",
                    target_facing="west",
                    target_x=2,
                    route_profile="generated_ocean",
                ),
                self.valid_exit(route_profile="generated_ocean"),
            ]
            source.write_text(json.dumps(data))
            maps = [source if path == SOURCE else path for path in MAPS]

            outputs = {}
            for mode in ("allregions", "firered"):
                output = base / mode / "current"
                result = subprocess.run(
                    [
                        str(MAPJSON),
                        "generate",
                        mode,
                        str(GROUPS),
                        str(LAYOUTS),
                        str(output),
                        *(str(path) for path in maps),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs[mode] = output

            product = outputs["allregions"]
            manifest = json.loads((product / "integrity-manifest.json").read_text())
            entries = [
                entry
                for entry in manifest["edgeExits"]
                if entry["sourceId"] == "MAP_ROUTE19"
            ]
            self.assertEqual(manifest["schemaVersion"], 4)
            self.assertEqual(
                manifest["counts"]["edgeExits"], len(manifest["edgeExits"])
            )
            self.assertGreaterEqual(manifest["counts"]["edgeExits"], 2)
            self.assertEqual(
                manifest["counts"]["edgeRouteProfiles"],
                len(manifest["edgeRouteProfiles"]),
            )
            self.assertEqual([entry["exitEdgeValue"] for entry in entries], [1, 4])
            self.assertEqual(
                entries[0],
                {
                    "sourceName": "Route19_Frlg",
                    "sourceId": "MAP_ROUTE19",
                    "sourceMapValue": entries[0]["sourceNumber"]
                    | (entries[0]["sourceGroup"] << 8),
                    "sourceGroup": entries[0]["sourceGroup"],
                    "sourceNumber": entries[0]["sourceNumber"],
                    "targetName": "Route40",
                    "targetId": "MAP_ROUTE40",
                    "targetMapValue": entries[0]["targetNumber"]
                    | (entries[0]["targetGroup"] << 8),
                    "targetGroup": entries[0]["targetGroup"],
                    "targetNumber": entries[0]["targetNumber"],
                    "exitEdge": "south",
                    "exitEdgeValue": 1,
                    "targetFacing": "north",
                    "targetFacingValue": 2,
                    "targetX": 1,
                    "targetY": 1,
                },
            )
            self.assertEqual(
                manifest["abis"]["surfEdgeExit"],
                {
                    "size": 10,
                    "alignment": 2,
                    "sourceMapOffset": 0,
                    "targetMapOffset": 2,
                    "targetXOffset": 4,
                    "targetYOffset": 6,
                    "exitEdgeOffset": 8,
                    "targetFacingOffset": 9,
                },
            )
            self.assertEqual(
                manifest["countSentinels"]["edgeExits"],
                {
                    "registry": "gSurfEdgeExits",
                    "countSymbol": "gSurfEdgeExitCount",
                    "count": len(manifest["edgeExits"]),
                    "stride": 10,
                },
            )
            self.assertEqual(
                manifest["abis"]["surfEdgeRouteProfile"],
                {
                    "size": 4,
                    "alignment": 2,
                    "sourceMapOffset": 0,
                    "exitEdgeOffset": 2,
                    "profileOffset": 3,
                },
            )
            self.assertEqual(
                [entry["profile"] for entry in manifest["edgeRouteProfiles"] if entry["sourceId"] == "MAP_ROUTE19"],
                ["generated_ocean", "generated_ocean"],
            )
            source_text = (product / "src/data/surf_edge_exits.inc.c").read_text()
            south = "{ MAP_ROUTE19, MAP_ROUTE40, 1, 1, DIR_SOUTH, DIR_NORTH }"
            east = "{ MAP_ROUTE19, MAP_ROUTE40, 2, 1, DIR_EAST, DIR_WEST }"
            self.assertLess(source_text.index(south), source_text.index(east))
            self.assertIn(
                f"const u16 gSurfEdgeExitCount = {len(manifest['edgeExits'])};",
                source_text,
            )
            self.assertIn(
                f"const u16 gSurfEdgeRouteProfileCount = {len(manifest['edgeRouteProfiles'])};",
                source_text,
            )

            fixture = outputs["firered"]
            fixture_manifest = json.loads(
                (fixture / "integrity-manifest.json").read_text()
            )
            self.assertEqual(fixture_manifest["counts"]["edgeExits"], 0)
            self.assertEqual(fixture_manifest["counts"]["edgeRouteProfiles"], 0)
            self.assertEqual(fixture_manifest["edgeExits"], [])
            self.assertEqual(fixture_manifest["edgeRouteProfiles"], [])
            fixture_source = (fixture / "src/data/surf_edge_exits.inc.c").read_text()
            self.assertIn("    {0},", fixture_source)
            self.assertIn("const u16 gSurfEdgeExitCount = 0;", fixture_source)
            self.assertIn("const u16 gSurfEdgeRouteProfileCount = 0;", fixture_source)


if __name__ == "__main__":
    unittest.main()
