from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ALLOWED_TRAINER_TABLE_SOURCES = {
    Path("src/data.c"),
    Path("src/trainer_registry.c"),
    Path("test/test_runner_battle.c"),
}


class TrainerRegistrySourceTests(unittest.TestCase):
    def test_raw_trainer_table_is_private_to_definition_registry_and_fixture(
        self,
    ) -> None:
        references: set[Path] = set()
        for directory in ("include", "src", "test"):
            for path in (ROOT / directory).rglob("*"):
                if path.suffix not in {".c", ".h"} or not path.is_file():
                    continue
                if re.search(r"\bgTrainers\s*\[", path.read_text(encoding="utf-8")):
                    references.add(path.relative_to(ROOT))

        self.assertEqual(references, ALLOWED_TRAINER_TABLE_SOURCES)

    def test_public_trainer_string_metadata_uses_the_empty_string_authority(
        self,
    ) -> None:
        source = (ROOT / "src" / "trainer_registry.c").read_text(encoding="utf-8")
        for function in ("GetTrainerClassNameFromId", "GetTrainerNameFromId"):
            match = re.search(
                rf"const u8 \*{function}\(u16 trainerId\)\n\{{(?P<body>.*?)\n\}}",
                source,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            body = match.group("body")
            self.assertIn("gText_EmptyString2", body)
            self.assertNotIn("return NULL", body)


if __name__ == "__main__":
    unittest.main()
