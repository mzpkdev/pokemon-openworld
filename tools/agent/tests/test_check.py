import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.agent.check import execute
from tools.agent.output import CHECK_LIMIT, render_json
from tools.agent.registry import load_registry, resolve


class RegistryTests(unittest.TestCase):
    def test_registry_matches_agent_command_policy(self):
        root = Path(__file__).resolve().parents[3]
        text = (root / "AGENTS.md").read_text()
        checks = load_registry()["checks"]
        expected = {
            "format-check",
            "lint-check",
            "product-check",
            "check",
            "debug-check",
            "integrity-check",
            "release-check",
            "integrity-check-rom-purposes",
            "e2e-core",
            "e2e-integrity",
            "e2e-integrity-full",
            "e2e-extended",
            "content-port-transaction-check",
            "content-port-ownership-check",
            "content-port-test",
            "content-port-check",
            "content-port-bundle",
            "wild-encounter-test",
            "agent-test",
        }
        self.assertTrue(expected <= set(checks))
        for check_id in expected:
            self.assertIn(check_id, text)

    def test_registry_rejects_unknown_checks_and_untyped_arguments(self):
        with self.assertRaisesRegex(ValueError, "unknown check"):
            resolve("arbitrary-command")
        with self.assertRaisesRegex(ValueError, "valid --selector"):
            resolve("python-unittest", selector="-c")
        with self.assertRaisesRegex(ValueError, "outside"):
            resolve("actionlint", workflows=["../workflow.yml"])

    def test_typed_selectors_resolve_exact_argv(self):
        argv, _ = resolve("python-unittest", selector="tools.agent.tests.test_check")
        self.assertEqual(
            argv, ["python3", "-m", "unittest", "tools.agent.tests.test_check", "-v"]
        )
        argv, _ = resolve(
            "actionlint",
            workflows=[".github/workflows/pr.yml", ".github/workflows/ci.yml"],
        )
        self.assertEqual(
            argv, ["actionlint", ".github/workflows/ci.yml", ".github/workflows/pr.yml"]
        )


class ExecutionTests(unittest.TestCase):
    def run_command(self, root, source, timeout=5):
        with patch(
            "tools.agent.check.resolve",
            return_value=([sys.executable, "-c", source], {"tier": "iteration"}),
        ):
            return execute(root, "fixture", timeout=timeout)

    def test_success_and_failure_retain_collision_free_complete_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            success = self.run_command(root, "print('complete output')")
            failure = self.run_command(
                root, "import sys; print('ERROR: broken'); sys.exit(7)"
            )
            success_log = root / success["logs"][0]["path"]
            failure_log = root / failure["logs"][0]["path"]
            self.assertNotEqual(success_log, failure_log)
            self.assertEqual(success_log.read_text(), "complete output\n")
            self.assertIn("ERROR: broken", failure_log.read_text())
            self.assertEqual(failure["status"], "failed")
            self.assertEqual(failure["items"][0]["exitStatus"], 7)
            self.assertLessEqual(
                len(failure["diagnostics"][0]["excerpt"].encode()), 1024
            )
            metadata = json.loads((root / failure["logs"][1]["path"]).read_text())
            self.assertEqual(
                metadata["argv"],
                [
                    sys.executable,
                    "-c",
                    "import sys; print('ERROR: broken'); sys.exit(7)",
                ],
            )
            self.assertEqual(metadata["exitStatus"], 7)
            self.assertIn("result", metadata)
            self.assertLessEqual(
                len(render_json(failure, CHECK_LIMIT).encode()), CHECK_LIMIT
            )

    def test_timeout_terminates_process_group_and_reports_signal(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_command(
                Path(directory), "import time; time.sleep(30)", timeout=0.01
            )
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["items"][0]["timedOut"])
        self.assertEqual(result["items"][0]["signal"], 15)

    def test_start_failure_still_retains_log_and_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "tools.agent.check.resolve",
                return_value=(["/definitely/missing/check"], {"tier": "iteration"}),
            ):
                result = execute(root, "fixture")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["items"][0]["exitStatus"], 127)
            self.assertIn("FileNotFoundError", result["items"][0]["executionError"])
            self.assertTrue((root / result["logs"][0]["path"]).is_file())
            self.assertTrue((root / result["logs"][1]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
