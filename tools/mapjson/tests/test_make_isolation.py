import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def make_variables(map_version: str, all_regions: int) -> dict[str, str]:
    result = subprocess.run(
        [
            "make",
            "-pn",
            "generated",
            f"MAP_VERSION={map_version}",
            f"ALL_REGIONS={all_regions}",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    wanted = {"OBJ_DIR_NAME", "OBJ_DIR_NAME_TEST", "OBJ_DIR_NAME_DEBUG", "OBJ_DIR_NAME_RELEASE", "ROM_NAME"}
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Z_]+)\s*:?=\s*(.*)$", line)
        if match and match.group(1) in wanted:
            values[match.group(1)] = match.group(2)
    return values


class MakeIsolationTests(unittest.TestCase):
    def test_content_policy_tuples_have_disjoint_object_roots(self) -> None:
        tuples = (("emerald", 0), ("emerald", 1), ("firered", 0), ("allregions", 0), ("allregions", 1))
        graphs = [make_variables(*build_tuple) for build_tuple in tuples]
        for variable in ("OBJ_DIR_NAME", "OBJ_DIR_NAME_TEST", "OBJ_DIR_NAME_DEBUG", "OBJ_DIR_NAME_RELEASE"):
            roots = [graph[variable] for graph in graphs]
            self.assertEqual(len(roots), len(set(roots)), (variable, roots))

    def test_policy_changes_do_not_rename_normal_rom(self) -> None:
        self.assertEqual(make_variables("emerald", 0)["ROM_NAME"], "pokemon-openworld.gba")
        self.assertEqual(make_variables("allregions", 1)["ROM_NAME"], "pokemon-openworld.gba")


if __name__ == "__main__":
    unittest.main()
