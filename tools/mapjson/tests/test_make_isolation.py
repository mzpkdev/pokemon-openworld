import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ProductMakeContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
