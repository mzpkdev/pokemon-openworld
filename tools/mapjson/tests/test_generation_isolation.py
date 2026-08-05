import hashlib
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"
GROUPS = ROOT / "data" / "maps" / "map_groups.json"
LAYOUTS = ROOT / "data" / "layouts" / "layouts.json"
MAPS = sorted((ROOT / "data" / "maps").glob("*/map.json"))


def reviewed_inputs() -> tuple[Path, ...]:
    """Hash the full reviewed boundary, deliberately excluding ignored products."""
    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--",
            "src/data/heal_locations.json",
            "data",
            "include/constants",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return tuple(ROOT / path.decode() for path in result.stdout.split(b"\0") if path)


REVIEWED_INPUTS = reviewed_inputs()


def digest_tree(root: Path) -> dict[str, str]:
    root = root.resolve(strict=True)
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def digest_files(paths: tuple[Path, ...]) -> dict[str, str]:
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def generate(
    mode: str, root: Path, layouts: Path = LAYOUTS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(MAPJSON),
            "generate",
            mode,
            str(GROUPS),
            str(layouts),
            str(root),
            *(str(path) for path in MAPS),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )


class GenerationIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)

    def test_alternating_modes_are_deterministic_and_isolated(self) -> None:
        reviewed_before = digest_files(REVIEWED_INPUTS)
        self.assertGreater(len(REVIEWED_INPUTS), 1000)
        expected: dict[str, dict[str, str]] = {}

        with tempfile.TemporaryDirectory(prefix="mapjson-isolation-") as directory:
            base = Path(directory)
            for mode in (
                "emerald",
                "firered",
                "allregions",
                "firered",
                "emerald",
                "allregions",
            ):
                output = base / mode
                result = generate(mode, output)
                self.assertEqual(result.returncode, 0, result.stderr)
                digest = digest_tree(output)
                if mode in expected:
                    self.assertEqual(digest, expected[mode])
                else:
                    expected[mode] = digest
                self.assertEqual(
                    (output / ".map-build-policy").read_text(), f"{mode}\n"
                )

            emerald_headers = (
                base / "emerald" / "data" / "maps" / "headers.inc"
            ).read_text()
            firered_headers = (
                base / "firered" / "data" / "maps" / "headers.inc"
            ).read_text()
            allregions_headers = (
                base / "allregions" / "data" / "maps" / "headers.inc"
            ).read_text()
            self.assertIn("LittlerootTown/header.inc", emerald_headers)
            self.assertNotIn("PalletTown_Frlg/header.inc", emerald_headers)
            self.assertIn("PalletTown_Frlg/header.inc", firered_headers)
            self.assertNotIn("LittlerootTown/header.inc", firered_headers)
            self.assertIn("LittlerootTown/header.inc", allregions_headers)
            self.assertIn("PalletTown_Frlg/header.inc", allregions_headers)

        self.assertEqual(digest_files(REVIEWED_INPUTS), reviewed_before)

    def test_failed_generation_does_not_replace_last_complete_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapjson-promotion-") as directory:
            base = Path(directory)
            output = base / "emerald"
            good = generate("emerald", output)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertTrue(output.is_symlink())
            before = digest_tree(output)
            pointer_before = os.readlink(output)

            invalid_layouts = base / "invalid-layouts.json"
            invalid_layouts.write_text("{not valid json\n")
            failed = generate("emerald", output, invalid_layouts)
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(digest_tree(output), before)
            self.assertEqual(os.readlink(output), pointer_before)

    def test_concurrent_publication_uses_unique_trees_and_never_removes_pointer(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="mapjson-concurrent-") as directory:
            output = Path(directory) / "current"
            initial = generate("emerald", output)
            self.assertEqual(initial.returncode, 0, initial.stderr)

            commands = []
            for mode in ("firered", "allregions"):
                commands.append(
                    [
                        str(MAPJSON),
                        "generate",
                        mode,
                        str(GROUPS),
                        str(LAYOUTS),
                        str(output),
                        *(str(path) for path in MAPS),
                    ]
                )
            processes = [subprocess.Popen(command, cwd=ROOT) for command in commands]
            missing = False
            while any(process.poll() is None for process in processes):
                missing |= not (output / ".map-build-policy").is_file()
                time.sleep(0.002)
            self.assertEqual([process.wait() for process in processes], [0, 0])
            self.assertFalse(missing)
            self.assertTrue(output.is_symlink())
            self.assertIn(
                (output / ".map-build-policy").read_text(),
                {"firered\n", "allregions\n"},
            )
            generations = list(output.parent.glob(".generation-*"))
            self.assertEqual(len(generations), 1)
            self.assertFalse(list(output.parent.glob(".staging-*")))
            self.assertFalse(list(output.parent.glob(".current-*")))

    def test_successful_publish_removes_stale_work_trees(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapjson-cleanup-") as directory:
            base = Path(directory)
            output = base / "current"
            (base / ".staging-abandoned").mkdir()
            (base / ".generation-abandoned").mkdir()

            result = generate("emerald", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((base / ".staging-abandoned").exists())
            self.assertFalse((base / ".generation-abandoned").exists())
            self.assertEqual(len(list(base.glob(".generation-*"))), 1)

    def test_cleanup_preserves_direct_child_target_with_trailing_separator(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapjson-active-generation-") as directory:
            base = Path(directory)
            active = base / ".generation-active"
            active.mkdir()
            os.symlink(".generation-active/", base / "other-current")
            (base / ".generation-stale").mkdir()

            result = generate("emerald", base / "current")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(active.is_dir())
            self.assertTrue((base / "other-current").is_symlink())
            self.assertFalse((base / ".generation-stale").exists())
            self.assertEqual(len(list(base.glob(".generation-*"))), 2)

    def test_cleanup_preserves_generation_owning_a_symlinked_subtree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mapjson-active-subtree-") as directory:
            base = Path(directory)
            active_data = base / ".generation-active" / "data"
            active_data.mkdir(parents=True)
            (active_data / "sentinel").write_text("active\n")
            os.symlink(".generation-active/data", base / "other-data")
            (base / ".generation-stale").mkdir()

            result = generate("emerald", base / "current")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((base / "other-data/sentinel").read_text(), "active\n")
            self.assertFalse((base / ".generation-stale").exists())
            self.assertEqual(len(list(base.glob(".generation-*"))), 2)

    def test_windows_publication_lock_uses_native_unicode_path_api(self) -> None:
        source = (ROOT / "tools/mapjson/mapjson.cpp").read_text(encoding="utf-8")
        self.assertIn("CreateFileW(lock_path.c_str()", source)
        self.assertNotIn("CreateFileA(", source)


if __name__ == "__main__":
    unittest.main()
