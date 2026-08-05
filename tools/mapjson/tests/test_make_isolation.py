import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ProductMakeContractTests(unittest.TestCase):
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
            check=True,
            text=True,
            capture_output=True,
        )
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


if __name__ == "__main__":
    unittest.main()
