import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ProductMakeContractTests(unittest.TestCase):
    def run_make(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "NODEP=1", "SETUP_PREREQS=0", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def make_recipe(
        self, target: str, *, testing: bool, assignments: tuple[str, ...] = ()
    ) -> str:
        result = subprocess.run(
            [
                "make",
                "-nB",
                "NODEP=1",
                "SETUP_PREREQS=0",
                f"TEST={int(testing)}",
                *assignments,
                target,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_product_tuple_is_forced_for_every_build_purpose(self) -> None:
        # Query the parsed make database through a phony goal whose prerequisites
        # are present in a clean checkout.  The production `generated` goal needs
        # ignored tool binaries and generated headers even under `make -n`, which
        # would make this global variable contract depend on prior local builds.
        result = subprocess.run(
            ["make", "-pn", "clean-generated"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        values: dict[str, str] = {}
        for line in result.stdout.splitlines():
            match = re.match(
                r"^(GAME_VERSION|IS_FRLG|ALL_REGIONS|MAP_VERSION|FILE_NAME)\s*:?=\s*(.*)$",
                line,
            )
            if match:
                values[match.group(1)] = match.group(2)
        self.assertEqual(
            values,
            {
                "GAME_VERSION": "EMERALD",
                "IS_FRLG": "0",
                "ALL_REGIONS": "1",
                "MAP_VERSION": "allregions",
                "FILE_NAME": "pokemon-openworld",
            },
        )

    def test_auto_generated_targets_contain_files_not_include_search_dirs(self) -> None:
        result = subprocess.run(
            ["make", "-pn", "NODEP=1", "SETUP_PREREQS=0", "clean-generated"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        assignment = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("AUTO_GEN_TARGETS :=")
        )
        targets = assignment.partition(":=")[2].split()
        self.assertEqual(targets.count("include/constants/script_commands.h"), 1)
        self.assertNotIn("build/generated/allregions/current/src", targets)
        self.assertNotIn("build/generated/allregions/current/include", targets)
        database_targets = {
            line.partition(":")[0]
            for line in result.stdout.splitlines()
            if line and not line[0].isspace() and ":" in line
        }
        self.assertNotIn("build/generated/allregions/current/src", database_targets)
        self.assertNotIn("build/generated/allregions/current/include", database_targets)

    def test_map_generation_stamp_tracks_every_indirect_input_class(self) -> None:
        result = subprocess.run(
            ["make", "-pn", "NODEP=1", "SETUP_PREREQS=0", "clean-generated"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        rule = next(
            line
            for line in result.stdout.splitlines()
            if line.startswith("build/generated/allregions/current/.map-build-policy:")
        )
        for dependency in (
            "tools/mapjson/required_map_defines.json",
            "src/data/tilesets/headers.h",
            "src/data/tilesets/metatiles.h",
            "data/tilesets/primary/general/metatiles.bin",
            "data/layouts/LittlerootTown/map.bin",
            "data/layouts/LittlerootTown/border.bin",
            "data/maps/LittlerootTown/scripts.inc",
            "data/scripts/movement.inc",
        ):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, rule)

    def test_global_script_registry_dependency_scan_is_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            nested = temp / "data/scripts/nested/deeper/registry.inc"
            nested.parent.mkdir(parents=True)
            nested.write_text("NestedOwner_MapScripts::\n")
            makefile = temp / "Makefile"
            makefile.write_text(
                "DATA_ASM_SUBDIR := data\n"
                "DATA_ASM_BUILDDIR := build/data\n"
                "C_BUILDDIR := build/src\n"
                "TEST_BUILDDIR := build/test\n"
                "GENERATED_ROOT := build/generated/current\n"
                "MAPJSON := mapjson\n"
                f"include {ROOT / 'map_data_rules.mk'}\n"
                ".PHONY: print-global-script-registries\n"
                "print-global-script-registries:\n"
                "\t@printf '%s\\n' $(GLOBAL_SCRIPT_REGISTRIES)\n"
            )
            result = subprocess.run(
                ["make", "--no-print-directory", "print-global-script-registries"],
                cwd=temp,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "data/scripts/nested/deeper/registry.inc", result.stdout.splitlines()
            )

    def test_deleting_wildcard_inputs_regenerates_the_map_tree(self) -> None:
        deletion_cases = (
            "data/maps/Only/map.json",
            "data/maps/Only/scripts.inc",
            "data/layouts/Only/map.bin",
        )
        for deleted_path in deletion_cases:
            with (
                self.subTest(deleted_path=deleted_path),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                temp = Path(temp_dir)
                for relative, contents in (
                    ("data/maps/map_groups.json", "{}\n"),
                    ("data/maps/Only/map.json", "{}\n"),
                    ("data/maps/Only/scripts.inc", "Only_MapScripts::\n"),
                    ("data/layouts/layouts.json", "{}\n"),
                    ("data/layouts/Only/map.bin", "map\n"),
                    ("data/layouts/Only/border.bin", "border\n"),
                    ("data/scripts/global.inc", "Global_MapScripts::\n"),
                    ("src/data/tilesets/headers.h", "\n"),
                    ("src/data/tilesets/metatiles.h", "\n"),
                    ("src/data/region_map/region_map_sections.json", "{}\n"),
                    ("src/data/region_map/map_section_compatibility.json", "{}\n"),
                    ("tools/mapjson/required_map_defines.json", "{}\n"),
                    ("tools/mapjson/product_exclusions.json", "{}\n"),
                    ("tools/mapjson/product_hidden_item_flags.json", "{}\n"),
                ):
                    path = temp / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(contents)

                log = temp / "generations.log"
                mapjson = temp / "fake-mapjson"
                mapjson.write_text(
                    "#!/bin/sh\n"
                    "set -eu\n"
                    "printf 'generate\\n' >> \"$CONTRACT_LOG\"\n"
                    'mkdir -p "$5"\n'
                    "printf 'allregions\\n' > \"$5/.map-build-policy\"\n"
                )
                mapjson.chmod(0o755)
                makefile = temp / "Makefile"
                makefile.write_text(
                    "DATA_ASM_SUBDIR := data\n"
                    "DATA_ASM_BUILDDIR := build/data\n"
                    "C_BUILDDIR := build/src\n"
                    "TEST_BUILDDIR := build/test\n"
                    "GENERATED_ROOT := build/generated/current\n"
                    "MAP_VERSION := allregions\n"
                    f"MAPJSON := {mapjson}\n"
                    f"include {ROOT / 'map_data_rules.mk'}\n"
                )
                target = "build/generated/current/.map-build-policy"
                environment = {**os.environ, "CONTRACT_LOG": str(log)}
                first = subprocess.run(
                    ["make", "--no-print-directory", target],
                    cwd=temp,
                    text=True,
                    capture_output=True,
                    env=environment,
                )
                self.assertEqual(first.returncode, 0, first.stderr)

                deleted = temp / deleted_path
                containing_directory = deleted.parent
                deleted.unlink()
                stamp_mtime = (temp / target).stat().st_mtime + 10
                os.utime(containing_directory, (stamp_mtime, stamp_mtime))
                second = subprocess.run(
                    ["make", "--no-print-directory", target],
                    cwd=temp,
                    text=True,
                    capture_output=True,
                    env=environment,
                )
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(log.read_text().splitlines(), ["generate", "generate"])

    def test_built_tree_supports_clean_generated_and_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checkout = Path(temp_dir) / "checkout"
            checkout.mkdir()
            archive = subprocess.Popen(
                ["git", "archive", "--format=tar", "HEAD"],
                cwd=ROOT,
                stdout=subprocess.PIPE,
            )
            extract = subprocess.run(
                ["tar", "-xf", "-", "-C", str(checkout)],
                stdin=archive.stdout,
                text=False,
                capture_output=True,
            )
            assert archive.stdout is not None
            archive.stdout.close()
            archive_returncode = archive.wait()
            self.assertEqual(archive_returncode, 0)
            self.assertEqual(extract.returncode, 0, extract.stderr.decode())
            # Local runs exercise the working Makefile; in CI this is identical
            # to the archived committed copy.
            shutil.copy2(ROOT / "Makefile", checkout / "Makefile")
            self.assertFalse((checkout / ".git").exists())

            header = checkout / "include/constants/script_commands.h"
            generated_dirs = (
                checkout / "build/generated/allregions/current/src",
                checkout / "build/generated/allregions/current/include",
            )
            for clean_goal in ("clean-generated", "clean"):
                with self.subTest(clean_goal=clean_goal):
                    build = subprocess.run(
                        [
                            "make",
                            "NODEP=1",
                            "SETUP_PREREQS=0",
                            "include/constants/script_commands.h",
                        ],
                        cwd=checkout,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(build.returncode, 0, build.stderr)
                    self.assertNotIn("not a git repository", build.stderr)
                    self.assertEqual(
                        build.stdout.count("make_scr_cmd_constants.py"),
                        1,
                        build.stdout,
                    )
                    self.assertTrue(header.is_file())
                    self.assertFalse(any(path.exists() for path in generated_dirs))

                    clean = subprocess.run(
                        ["make", "NODEP=1", "SETUP_PREREQS=0", clean_goal],
                        cwd=checkout,
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(clean.returncode, 0, clean.stderr)
                    self.assertNotIn("not a git repository", clean.stderr)
                    self.assertFalse(header.exists())
                    self.assertFalse((checkout / "content-port-transaction").exists())

    def test_conflicting_command_line_values_fail_before_assignment(self) -> None:
        conflicts = {
            "GAME_VERSION=FIRERED": "pokemon-openworld requires GAME_VERSION=EMERALD",
            "ALL_REGIONS=0": "pokemon-openworld requires ALL_REGIONS=1",
            "MAP_VERSION=firered": "pokemon-openworld requires MAP_VERSION=allregions",
            "FILE_NAME=pokefirered": "pokemon-openworld requires FILE_NAME=pokemon-openworld",
        }
        for assignment, message in conflicts.items():
            with self.subTest(assignment=assignment):
                result = subprocess.run(
                    ["make", "-n", "generated", assignment],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)

    def test_generated_constants_are_forced_only_into_c_compilation(self) -> None:
        generated_headers = (
            "include/constants/map_groups.h",
            "include/constants/layouts.h",
            "include/constants/map_event_ids.h",
        )
        for testing in (False, True):
            with self.subTest(testing=testing):
                trainer_recipe = self.make_recipe(
                    "src/data/trainers.h",
                    testing=testing,
                    assignments=("CPPFLAGS+=-include include/global.h",),
                )
                trainer_line = next(
                    line
                    for line in trainer_recipe.splitlines()
                    if "trainerproc -o src/data/trainers.h" in line
                )
                self.assertIn(f"-DTESTING={int(testing)}", trainer_line)
                self.assertIn("-DEMERALD", trainer_line)
                self.assertIn("-DALL_REGIONS=1", trainer_line)
                self.assertIn("-include include/global.h", trainer_line)
                for header in generated_headers:
                    self.assertNotIn(header, trainer_line)

                object_dir = "emerald-allregions-allregions1"
                if testing:
                    object_dir += "-test"
                c_recipe = self.make_recipe(
                    f"build/{object_dir}/src/trainer.o",
                    testing=testing,
                    assignments=("CPPFLAGS+=-include include/global.h",),
                )
                cpp_line = next(
                    line
                    for line in c_recipe.splitlines()
                    if line.startswith("arm-none-eabi-cpp ")
                    and " src/trainer.c |" in line
                )
                self.assertIn(f"-DTESTING={int(testing)}", cpp_line)
                self.assertIn("-include include/global.h", cpp_line)
                self.assertIn(
                    "-iquote build/generated/allregions/current/include/constants",
                    cpp_line,
                )
                for header in generated_headers:
                    self.assertIn(
                        f"-include build/generated/allregions/current/{header}",
                        cpp_line,
                    )

        purposes = {
            (): (),
            ("DEBUG=1",): ("-DDEBUG",),
            ("RELEASE=1",): ("-DRELEASE",),
        }
        for assignments, expected_defines in purposes.items():
            with self.subTest(assignments=assignments):
                recipe = self.make_recipe(
                    "src/data/trainers.h",
                    testing=False,
                    assignments=assignments,
                )
                trainer_line = next(
                    line
                    for line in recipe.splitlines()
                    if "trainerproc -o src/data/trainers.h" in line
                )
                for define in expected_defines:
                    self.assertIn(define, trainer_line)

        result = subprocess.run(
            ["make", "-pn", "clean-generated"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertNotIn(
            "build/generated/allregions/current/include/constants/constants/",
            result.stdout,
        )
        self.assertNotIn(
            "build/generated/allregions/current/include/constants/config/",
            result.stdout,
        )

    def test_c_objects_regenerate_partial_constants_and_track_each_header(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            build_dir = temp / "build"
            generated_root = build_dir / "generated/allregions/current"
            constants_dir = generated_root / "include/constants"
            constants_dir.mkdir(parents=True)
            (constants_dir / "map_groups.h").write_text("/* partial */\n")
            (generated_root / ".map-build-policy").write_text("allregions\n")

            log = temp / "commands.log"
            mapjson = temp / "mapjson"
            mapjson.write_text(
                """#!/usr/bin/env bash
set -eu
printf 'generate\\n' >> "$CONTRACT_LOG"
root=$5
mkdir -p "$root/include/constants"
for header in map_groups.h layouts.h map_event_ids.h; do
    printf '/* generated %s */\\n' "$header" > "$root/include/constants/$header"
done
printf 'allregions\\n' > "$root/.map-build-policy"
"""
            )
            mapjson.chmod(0o755)

            cpp = temp / "cpp"
            cpp.write_text(
                """#!/usr/bin/env bash
set -eu
printf 'compile\\n' >> "$CONTRACT_LOG"
cat "${@: -1}"
"""
            )
            cpp.chmod(0o755)

            pipeline_filter = temp / "pipeline-filter"
            pipeline_filter.write_text("#!/usr/bin/env bash\ncat\n")
            pipeline_filter.chmod(0o755)

            object_file = build_dir / "emerald-allregions-allregions1/src/trainer.o"
            command = [
                "make",
                "NODEP=1",
                "SETUP_PREREQS=0",
                f"BUILD_DIR={build_dir}",
                f"MAPJSON={mapjson}",
                f"CPP={cpp}",
                f"PREPROC={pipeline_filter}",
                f"CC1={pipeline_filter}",
                f"AS={pipeline_filter}",
                str(object_file),
            ]
            result = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                env={**os.environ, "CONTRACT_LOG": str(log)},
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(log.read_text().splitlines(), ["generate", "compile"])
            for header in ("map_groups.h", "layouts.h", "map_event_ids.h"):
                self.assertTrue((constants_dir / header).is_file())

            object_file.touch()
            object_mtime = (generated_root / ".map-build-policy").stat().st_mtime + 100
            for changed_header in ("layouts.h", "map_event_ids.h"):
                with self.subTest(changed_header=changed_header):
                    # Use explicit mtimes so the rebuild assertion is independent
                    # of filesystem timestamp resolution.
                    os.utime(object_file, (object_mtime, object_mtime))
                    for header in (
                        "map_groups.h",
                        "layouts.h",
                        "map_event_ids.h",
                    ):
                        os.utime(
                            constants_dir / header,
                            (object_mtime - 10, object_mtime - 10),
                        )
                    os.utime(
                        constants_dir / changed_header,
                        (object_mtime + 10, object_mtime + 10),
                    )
                    log.write_text("")

                    result = subprocess.run(
                        command,
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        env={**os.environ, "CONTRACT_LOG": str(log)},
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(log.read_text().splitlines(), ["compile"])

    def test_stale_bundled_tools_rebuild_before_their_outputs(self) -> None:
        tools = (
            (
                ROOT / "tools/mapjson/mapjson",
                ROOT / "tools/mapjson/json11.h",
            ),
            (
                ROOT / "tools/trainerproc/trainerproc",
                ROOT / "tools/trainerproc/main.c",
            ),
        )
        for executable, _ in tools:
            result = subprocess.run(
                ["make", "-C", str(executable.parent), executable.name],
                cwd=ROOT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)

            mapjson, mapjson_source = tools[0]
            stale_mtime = mapjson_source.stat().st_mtime_ns - 1_000_000_000
            os.utime(mapjson, ns=(stale_mtime, stale_mtime))
            generated_root = temp / "build/generated/allregions/current"
            result = self.run_make(
                f"BUILD_DIR={temp / 'build'}",
                str(generated_root / ".map-build-policy"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(mapjson.stat().st_mtime_ns, stale_mtime)
            self.assertEqual(
                (generated_root / ".map-build-policy").read_text(), "allregions\n"
            )

            trainerproc, trainerproc_source = tools[1]
            stale_mtime = trainerproc_source.stat().st_mtime_ns - 1_000_000_000
            os.utime(trainerproc, ns=(stale_mtime, stale_mtime))
            party = temp / "fixture.party"
            header = temp / "fixture.h"
            party.write_text(
                """=== TRAINER_TEST ===
Name: TEST
Class: Hiker
Pic: Hiker
Gender: Male
Music: Male
Double Battle: No

Pikachu
Level: 5

"""
            )
            result = self.run_make("CPP=cpp", str(header))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertGreater(trainerproc.stat().st_mtime_ns, stale_mtime)
            self.assertIn("[DIFFICULTY_NORMAL][TRAINER_TEST]", header.read_text())

    def test_external_tool_overrides_do_not_build_bundled_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            generated_root = temp / "build/generated/allregions/current"
            result = self.run_make(
                f"BUILD_DIR={temp / 'build'}",
                "MAPJSON=/bin/true",
                "CXX=false",
                str(generated_root / ".map-build-policy"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("mapjson.cpp", result.stdout + result.stderr)

            party = temp / "override.party"
            party.write_text("override input\n")
            result = self.run_make(
                "CPP=/bin/true",
                "TRAINERPROC=/bin/true",
                "CC=false",
                str(temp / "override.h"),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("trainerproc/main.c", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
