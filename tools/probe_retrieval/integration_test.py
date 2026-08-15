"""Repository-scale smoke coverage for the installed Probe artifact."""

from __future__ import annotations

import unittest
from pathlib import Path

from . import cli
from .artifact import repository_root, verified_binary


class FullRepositorySearchSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__).parent)
        cls.binary = verified_binary(cls.root)

    def _assert_cold_and_warm_search(
        self, query: str, *, expected_file: str | None = None
    ) -> None:
        for cache_state in ("cold_process", "warm_process"):
            with self.subTest(query=query, cache_state=cache_state):
                document = cli.execute(
                    ["search", query, "--language", "c", "--path", "src"],
                    cwd=self.root,
                    binary=self.binary,
                )
                serialized = cli._compact(document)
                code_bytes = sum(
                    len(result["code"].encode("utf-8"))
                    for result in document["results"]
                )
                self.assertTrue(document["results"])
                self.assertLessEqual(len(serialized), cli.RESPONSE_BYTES)
                self.assertLessEqual(code_bytes, cli.PROBE_CODE_BYTES)
                self.assertLessEqual(len(document["results"]), cli.MAX_RESULTS)
                if expected_file is not None:
                    self.assertIn(
                        expected_file,
                        {result["file"] for result in document["results"]},
                    )

    def test_exact_c_symbol_search_cold_and_warm(self) -> None:
        self._assert_cold_and_warm_search(
            "CB2_InitTitleScreen", expected_file="src/title_screen.c"
        )

    def test_exploratory_c_search_cold_and_warm(self) -> None:
        self._assert_cold_and_warm_search("battle")


if __name__ == "__main__":
    unittest.main()
