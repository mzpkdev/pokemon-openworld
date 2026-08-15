from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools.probe_retrieval import cli


class RetrievalCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(("git", "init", "-q", str(self.root)), check=True)
        (self.root / ".gitignore").write_text("ignored/\n", encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src/example.py").write_text(
            "def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n",
            encoding="utf-8",
        )
        (self.root / "src/data.json").write_text("{}\n", encoding="utf-8")
        self.binary = self.root / "fake-probe"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _fake(self, body: str) -> Path:
        self.binary.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
        self.binary.chmod(0o755)
        return self.binary

    def test_rejects_absolute_parent_and_ignored_paths(self) -> None:
        for path in (str(self.root / "src"), "../outside", "ignored"):
            with (
                self.subTest(path=path),
                self.assertRaises(cli.RetrievalError) as raised,
            ):
                cli.execute(
                    ["search", "alpha", "--language", "python", "--path", path],
                    cwd=self.root,
                    binary=self.binary,
                )
            self.assertEqual(raised.exception.code, "invalid_path")

    def test_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "escape").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(cli.RetrievalError) as raised:
                cli.execute(
                    ["search", "alpha", "--language", "python", "--path", "escape"],
                    cwd=self.root,
                    binary=self.binary,
                )
        self.assertEqual(raised.exception.code, "invalid_path")

    def test_timeout_is_fixed(self) -> None:
        binary = self._fake("import time\ntime.sleep(10)\n")
        with (
            mock.patch.object(cli, "TIMEOUT_SECONDS", 0.05),
            self.assertRaises(cli.RetrievalError) as raised,
        ):
            cli.execute(["symbols", "src/example.py"], cwd=self.root, binary=binary)
        self.assertEqual(raised.exception.code, "timeout")

    def test_malformed_and_non_utf8_output(self) -> None:
        cases = (
            ("print('{')\n", "malformed JSON"),
            ("import os\nos.write(1, b'\\xff')\n", "non-UTF-8"),
        )
        for body, message in cases:
            with self.subTest(message=message):
                binary = self._fake(body)
                with self.assertRaisesRegex(cli.RetrievalError, message):
                    cli.execute(
                        ["symbols", "src/example.py"], cwd=self.root, binary=binary
                    )

    def test_search_normalizes_paths_and_caps_complete_json(self) -> None:
        code = "x" * 3000
        result = {
            "code": code,
            "file": str(self.root / "src/example.py"),
            "language": "python",
            "lines": [1, 2],
            "owner_qualified_symbol": "alpha",
        }
        payload = json.dumps({"results": [result] * 20})
        binary = self._fake(f"print({payload!r})\n")
        document = cli.execute(
            ["search", "alpha", "--language", "python", "--path", "src"],
            cwd=self.root,
            binary=binary,
        )
        self.assertTrue(document["truncated"])
        self.assertGreater(document["omitted_records"], 0)
        self.assertLessEqual(len(cli._compact(document)), cli.RESPONSE_BYTES)
        self.assertEqual(document["results"][0]["file"], "src/example.py")

    def test_raw_output_cap_is_enforced(self) -> None:
        binary = self._fake("print('x' * 2000)\n")
        with (
            mock.patch.object(cli, "RAW_OUTPUT_BYTES", 100),
            self.assertRaises(cli.RetrievalError) as raised,
        ):
            cli.execute(["symbols", "src/example.py"], cwd=self.root, binary=binary)
        self.assertEqual(raised.exception.code, "output_limit")

    def test_rejects_unsupported_format_and_oversized_file(self) -> None:
        with self.assertRaises(cli.RetrievalError) as unsupported:
            cli.execute(["symbols", "src/data.json"], cwd=self.root, binary=self.binary)
        self.assertEqual(unsupported.exception.code, "unsupported_format")
        with (
            mock.patch.object(cli, "MAX_SOURCE_BYTES", 1),
            self.assertRaises(cli.RetrievalError) as oversized,
        ):
            cli.execute(
                ["symbols", "src/example.py"], cwd=self.root, binary=self.binary
            )
        self.assertEqual(oversized.exception.code, "oversized_file")

    def test_missing_tool_is_reported(self) -> None:
        with self.assertRaises(cli.RetrievalError) as raised:
            cli.execute(
                ["symbols", "src/example.py"],
                cwd=self.root,
                binary=self.root / "missing",
            )
        self.assertEqual(raised.exception.code, "missing_tool")

    def test_line_range_is_bounded_not_whole_file_and_network_free(self) -> None:
        with mock.patch("urllib.request.urlopen") as network:
            document = cli.execute(
                ["extract", "src/example.py", "--start-line", "1", "--end-line", "2"],
                cwd=self.root,
            )
        network.assert_not_called()
        self.assertEqual(document["retrieval"], "text_fallback")
        with self.assertRaises(cli.RetrievalError) as whole_file:
            cli.execute(
                ["extract", "src/example.py", "--start-line", "1", "--end-line", "6"],
                cwd=self.root,
            )
        self.assertEqual(whole_file.exception.code, "whole_file_forbidden")
        with (
            mock.patch.object(cli, "MAX_RANGE_LINES", 1),
            self.assertRaises(cli.RetrievalError) as too_large,
        ):
            cli.execute(
                ["extract", "src/example.py", "--start-line", "1", "--end-line", "2"],
                cwd=self.root,
            )
        self.assertEqual(too_large.exception.code, "invalid_range")

    def test_symbol_listing_and_required_symbol_are_ast_results(self) -> None:
        symbols = json.dumps(
            [
                {
                    "file": "src/example.py",
                    "symbols": [
                        {
                            "name": "alpha",
                            "kind": "function",
                            "signature": "def alpha():",
                            "line": 1,
                            "end_line": 2,
                        }
                    ],
                }
            ]
        )
        extract = json.dumps(
            {
                "results": [
                    {
                        "code": "def alpha():\n    return 1",
                        "file": "src/example.py",
                        "lines": [1, 2],
                        "node_type": "function_definition",
                    }
                ]
            }
        )
        body = f"import sys\nprint({symbols!r} if sys.argv[1] == 'symbols' else {extract!r})\n"
        binary = self._fake(body)
        with mock.patch("urllib.request.urlopen") as network:
            listed = cli.execute(
                ["symbols", "src/example.py"], cwd=self.root, binary=binary
            )
            extracted = cli.execute(
                ["extract", "src/example.py", "--symbol", "alpha"],
                cwd=self.root,
                binary=binary,
            )
        network.assert_not_called()
        self.assertEqual(listed["retrieval"], "ast")
        self.assertEqual(extracted["retrieval"], "ast")
        self.assertEqual(extracted["results"][0]["symbol"], "alpha")


if __name__ == "__main__":
    unittest.main()
