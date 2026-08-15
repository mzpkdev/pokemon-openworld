import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.agent.context import build_context, changed_paths, classify, infer
from tools.agent.output import CONTEXT_LIMIT, render_json


class ContextTests(unittest.TestCase):
    def test_classification_keeps_independent_dimensions(self):
        root = Path(__file__).resolve().parents[3]
        item = classify(root, "src/data/trainers.h", {})
        self.assertEqual(item["authority"], "engine-source")
        self.assertEqual(item["materialization"], "generated")
        self.assertFalse(item["editable"])
        self.assertEqual(item["ownership"], {"kind": "repository"})
        self.assertEqual(item["generator"]["source"], "src/data/trainers.party")
        self.assertEqual(item["impacts"], ["product-mechanics"])

    def test_unknown_paths_escalate_and_explicit_impacts_only_add(self):
        items = [
            {
                "path": "odd.input",
                "authority": "unknown",
                "ownership": {"kind": "repository"},
                "impacts": ["shared-behavior", "unknown"],
            }
        ]
        impacts, checks = infer(items, {"emulator-evidence"})
        self.assertEqual(impacts, ["emulator-evidence", "shared-behavior", "unknown"])
        ids = {check["id"] for check in checks}
        self.assertTrue({"check", "debug-check", "e2e-core"} <= ids)

    def test_workflow_recommendation_has_exact_paths(self):
        items = [
            {
                "path": ".github/workflows/pr.yml",
                "authority": "workflow-source",
                "ownership": {"kind": "repository"},
                "impacts": ["workflow"],
            },
            {
                "path": ".github/workflows/ci.yml",
                "authority": "workflow-source",
                "ownership": {"kind": "repository"},
                "impacts": ["workflow"],
            },
        ]
        _, checks = infer(items, set())
        actionlint = next(check for check in checks if check["id"] == "actionlint")
        self.assertEqual(
            actionlint["parameters"]["workflows"],
            [".github/workflows/pr.yml", ".github/workflows/ci.yml"],
        )

    def test_default_git_set_includes_untracked_and_both_rename_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(
                ["git", "config", "user.email", "agent@example.invalid"],
                cwd=root,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Agent Test"], cwd=root, check=True
            )
            (root / "old.txt").write_text("content\n")
            subprocess.run(["git", "add", "old.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
            subprocess.run(["git", "mv", "old.txt", "new.txt"], cwd=root, check=True)
            (root / "untracked.txt").write_text("new\n")
            paths, mode = changed_paths(root)
        self.assertEqual(mode, "working-tree")
        self.assertEqual(paths, ["new.txt", "old.txt", "untracked.txt"])

    def test_explicit_context_is_deterministic_and_bounded(self):
        root = Path(__file__).resolve().parents[3]
        paths = [f"unknown/path-{index}" for index in range(1000)]
        first = render_json(build_context(root, explicit=paths), CONTEXT_LIMIT)
        second = render_json(
            build_context(root, explicit=reversed(paths)), CONTEXT_LIMIT
        )
        self.assertEqual(first, second)
        self.assertLessEqual(len(first.encode()), CONTEXT_LIMIT)
        document = json.loads(first)
        self.assertTrue(document["truncated"]["value"])
        self.assertGreater(document["truncated"]["omittedRecords"], 0)

    def test_explicit_paths_cannot_escape_repository(self):
        root = Path(__file__).resolve().parents[3]
        with self.assertRaisesRegex(ValueError, "within the repository"):
            build_context(root, explicit=["../outside"])


if __name__ == "__main__":
    unittest.main()
