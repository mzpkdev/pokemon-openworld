import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools/mapjson/mapjson"
GROUPS = ROOT / "data/maps/map_groups.json"
LAYOUTS = ROOT / "data/layouts/layouts.json"
MAPS = sorted((ROOT / "data/maps").glob("*/map.json"))


class Phase5GeneratorHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)

    def generate(
        self,
        directory: Path,
        *,
        groups: Path = GROUPS,
        layouts: Path = LAYOUTS,
        replacement: tuple[Path, Path] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        maps = list(MAPS)
        if replacement:
            maps[maps.index(replacement[0])] = replacement[1]
        return subprocess.run(
            [
                str(MAPJSON),
                "generate",
                "allregions",
                str(groups),
                str(layouts),
                str(directory / "current"),
                *(str(path) for path in maps),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def mutated_map(self, directory: Path, name: str, mutate) -> tuple[Path, Path]:
        original = ROOT / "data/maps" / name / "map.json"
        fixture_dir = directory / name
        fixture_dir.mkdir()
        data = json.loads(original.read_text())
        mutate(data)
        fixture = fixture_dir / "map.json"
        fixture.write_text(json.dumps(data))
        scripts = original.parent / "scripts.inc"
        if scripts.exists():
            os.symlink(scripts, fixture_dir / "scripts.inc")
        return original, fixture

    def test_map_contract_mutations_fail_with_owning_record(self) -> None:
        mutations = (
            (
                "missing warp events",
                lambda data: data.pop("warp_events"),
                "warp_events event registry",
            ),
            (
                "missing layout",
                lambda data: data.__setitem__("layout", "LAYOUT_DOES_NOT_EXIST"),
                "missing product layout",
            ),
            (
                "missing scripts",
                lambda data: data.__setitem__("shared_scripts_map", "MissingScripts"),
                "missing scripts owner",
            ),
            (
                "unstable id",
                lambda data: data.__setitem__("id", "MAP BAD"),
                "unstable id",
            ),
            (
                "missing connection destination",
                lambda data: data.__setitem__(
                    "connections",
                    [{"map": "MAP_DOES_NOT_EXIST", "offset": 0, "direction": "up"}],
                ),
                "connection names missing map id",
            ),
        )
        for label, mutate, message in mutations:
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory(prefix="phase5-map-") as temporary,
            ):
                base = Path(temporary)
                replacement = self.mutated_map(base, "LittlerootTown", mutate)
                result = self.generate(base, replacement=replacement)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LittlerootTown", result.stderr)
                self.assertIn(message, result.stderr)
                self.assertFalse((base / "current").exists())

    def test_missing_border_is_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5-layout-") as temporary:
            base = Path(temporary)
            data = json.loads(LAYOUTS.read_text())
            data["layouts"][0]["border_filepath"] = str(base / "missing-border.bin")
            fixture = base / "layouts.json"
            fixture.write_text(json.dumps(data))
            result = self.generate(base, layouts=fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PetalburgCity_Layout", result.stderr)
            self.assertIn("lacks border data", result.stderr)
            self.assertFalse((base / "current").exists())

    def test_local_scripts_registry_must_define_expected_owner_label(self) -> None:
        for comment in ("@", "//"):
            with (
                self.subTest(comment=comment),
                tempfile.TemporaryDirectory(prefix="phase5-scripts-") as temporary,
            ):
                base = Path(temporary)
                original = ROOT / "data/maps/LittlerootTown/map.json"
                fixture_dir = base / "LittlerootTown"
                fixture_dir.mkdir()
                fixture = fixture_dir / "map.json"
                fixture.write_bytes(original.read_bytes())
                (fixture_dir / "scripts.inc").write_text(
                    f"  {comment} LittlerootTown_MapScripts::\n"
                )
                result = self.generate(base, replacement=(original, fixture))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LittlerootTown", result.stderr)
                self.assertIn(
                    "does not define 'LittlerootTown_MapScripts'", result.stderr
                )
                self.assertFalse((base / "current").exists())

    def test_script_registry_parser_accepts_only_real_declaration_lines(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5-script-parser-") as temporary:
            base = Path(temporary)
            valid = base / "valid.inc"
            valid.write_text("\tFixture_MapScripts::  @ trailing comment\n")
            accepted = subprocess.run(
                [str(MAPJSON), "script_registry", "allregions", "Fixture", str(valid)],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            for index, line in enumerate(
                ("@ Fixture_MapScripts::\n", "  // Fixture_MapScripts::\n")
            ):
                commented = base / f"commented-{index}.inc"
                commented.write_text(line)
                rejected = subprocess.run(
                    [
                        str(MAPJSON),
                        "script_registry",
                        "allregions",
                        "Fixture",
                        str(commented),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("does not define 'Fixture_MapScripts'", rejected.stderr)

    def test_global_scripts_registry_accepts_real_owner_declaration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5-global-scripts-") as temporary:
            base = Path(temporary)
            replacement = self.mutated_map(
                base,
                "LittlerootTown",
                lambda data: data.__setitem__("shared_scripts_map", "SecretBase"),
            )
            result = self.generate(base, replacement=replacement)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((base / "current/integrity-manifest.json").is_file())

    def test_generated_headers_are_valid_for_traditional_cpp(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5-cpp-") as temporary:
            base = Path(temporary)
            result = self.generate(base)
            self.assertEqual(result.returncode, 0, result.stderr)
            headers = sorted((base / "current/include").rglob("*.h"))
            self.assertGreater(len(headers), 0)
            for header in headers:
                with self.subTest(header=header.relative_to(base / "current")):
                    preprocessed = subprocess.run(
                        ["cpp", "-traditional-cpp", "-P", str(header)],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(preprocessed.returncode, 0, preprocessed.stderr)
                    compiled = subprocess.run(
                        ["cc", "-x", "c", "-fsyntax-only", "-"],
                        input=(
                            "typedef unsigned short MapSectionId;\n"
                            + preprocessed.stdout
                        ),
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(compiled.returncode, 0, compiled.stderr)

    def test_signed_warp_domain_rejects_map_slot_128(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5-warp-domain-") as temporary:
            base = Path(temporary)
            data = json.loads(GROUPS.read_text())
            first = data["group_order"][0]
            needed = 129 - len(data[first])
            moved = []
            for group in data["group_order"][1:]:
                while data[group] and len(moved) < needed:
                    moved.append(data[group].pop())
                if len(moved) == needed:
                    break
            data[first].extend(moved)
            fixture = base / "map_groups.json"
            fixture.write_text(json.dumps(data))
            result = self.generate(base, groups=fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exceeds signed WarpData range", result.stderr)
            self.assertFalse((base / "current").exists())


if __name__ == "__main__":
    unittest.main()
