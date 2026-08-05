import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MAPJSON = ROOT / "tools" / "mapjson" / "mapjson"


def policy(mode: str) -> dict[str, str]:
    result = subprocess.run(
        [str(MAPJSON), "policy", mode],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class MapBuildPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-C", "tools/mapjson", "all"], cwd=ROOT, check=True)

    def test_fixture_modes_have_explicit_defaults(self) -> None:
        self.assertEqual(policy("emerald")["dialect"], "emerald")
        self.assertEqual(policy("firered")["dialect"], "firered")
        self.assertEqual(policy("ruby")["dialect"], "ruby")

    def test_single_region_modes_only_include_their_region_and_layout(self) -> None:
        emerald = policy("emerald")
        self.assertEqual((emerald["hoenn"], emerald["kanto"]), ("1", "0"))
        self.assertEqual(
            (emerald["emerald_layout"], emerald["frlg_layout"]), ("1", "0")
        )

        firered = policy("firered")
        self.assertEqual((firered["hoenn"], firered["kanto"]), ("0", "1"))
        self.assertEqual(
            (firered["emerald_layout"], firered["frlg_layout"]), ("0", "1")
        )

        ruby = policy("ruby")
        self.assertEqual((ruby["hoenn"], ruby["kanto"]), ("1", "0"))
        self.assertEqual(ruby["ruby_layout"], "1")

    def test_allregions_includes_both_reviewed_region_and_layout_families(self) -> None:
        allregions = policy("allregions")
        self.assertEqual(allregions["dialect"], "emerald")
        self.assertEqual((allregions["hoenn"], allregions["kanto"]), ("1", "1"))
        self.assertEqual(
            (allregions["emerald_layout"], allregions["frlg_layout"]), ("1", "1")
        )
        self.assertEqual(allregions["johto_layout"], "1")
        self.assertEqual(allregions["product"], "1")

    def test_unknown_mode_is_fatal(self) -> None:
        result = subprocess.run(
            [str(MAPJSON), "policy", "yellow"], cwd=ROOT, text=True, capture_output=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown map build mode", result.stderr)


if __name__ == "__main__":
    unittest.main()
