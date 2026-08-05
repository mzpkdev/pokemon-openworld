import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class ProductBoundaryTests(unittest.TestCase):
    def test_retail_dialects_are_fixture_only(self) -> None:
        for mode in ("emerald", "firered", "ruby"):
            with self.subTest(mode=mode):
                subprocess.run(
                    ["make", f"generator-fixture-{mode}"], cwd=ROOT, check=True
                )
                fixture = ROOT / "build" / "fixtures" / mode / "current"
                self.assertEqual(
                    (fixture / ".map-build-policy").read_text(), f"{mode}\n"
                )
                self.assertFalse(
                    any(
                        path.name.startswith("pokemon-openworld")
                        for path in fixture.rglob("*")
                    )
                )
                self.assertFalse((ROOT / "release" / mode).exists())


if __name__ == "__main__":
    unittest.main()
