import json
import unittest
from pathlib import Path

from tools.agent.benchmarks.run_issue_74 import TASKS, _score, _summarize


def events(response, *, input_tokens=1000, cached_tokens=200, exit_code=0):
    return [
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "/bin/bash -lc 'make agent-test'",
                "aggregated_output": "check output\n",
                "exit_code": exit_code,
            },
        },
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": json.dumps(response)},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "output_tokens": 10,
            },
        },
    ]


class BenchmarkTests(unittest.TestCase):
    def test_frozen_manifest_has_eight_representative_tasks(self):
        manifest = json.loads(TASKS.read_text())
        self.assertEqual(manifest["benchmark"], "issue-74-same-model-v1")
        self.assertEqual(len(manifest["tasks"]), 8)
        self.assertEqual(
            {task["id"] for task in manifest["tasks"]},
            {
                "release-workflow",
                "content-port",
                "map-travel",
                "wild-encounters",
                "persistence",
                "e2e-focused",
                "trainer",
                "make-orchestration",
            },
        )

    def test_score_uses_provider_cache_and_completed_check_output(self):
        task = {
            "id": "fixture",
            "expectedChecks": ["agent-test"],
            "expectedSources": ["Makefile"],
            "baselineCheck": ["make", "agent-test"],
            "agentCheck": ["make", "agent-test"],
        }
        response = {
            "taskId": "fixture",
            "checkPassed": True,
            "requiredChecks": ["agent-test (required)"],
            "sources": ["Makefile"],
            "conclusion": "pass",
        }
        score = _score(task, "baseline", events(response), 1.5, 0)
        self.assertTrue(score["correct"])
        self.assertEqual(score["uncachedInputTokens"], 800)
        self.assertEqual(score["admittedCheckOutputBytes"], 13)
        self.assertEqual(score["checkExitStatuses"], [0])

    def test_no_regression_gate_is_paired_not_aggregate(self):
        manifest = {
            "benchmark": "fixture",
            "model": "model",
            "reasoningEffort": "medium",
            "tasks": [{"id": "a"}, {"id": "b"}],
        }

        def result(task_id, arm, correct):
            return {
                "taskId": task_id,
                "arm": arm,
                "correct": correct,
                "uncachedInputTokens": 100 if arm == "baseline" else 50,
                "admittedCheckOutputBytes": 100 if arm == "baseline" else 40,
                "toolRounds": 1,
                "latencySeconds": 1,
            }

        summary = _summarize(
            manifest,
            [
                result("a", "baseline", True),
                result("a", "agent", False),
                result("b", "baseline", False),
                result("b", "agent", True),
            ],
        )
        self.assertEqual(
            summary["metrics"]["correctTasks"], {"baseline": 1, "agent": 1}
        )
        self.assertFalse(summary["gates"]["noOutcomeRegression"])

    def test_retained_result_fails_the_frozen_gates(self):
        root = Path(__file__).resolve().parents[3]
        result_path = (
            root / "docs/benchmarks/issue-74/2026-08-15-gpt-5.6-sol-medium/results.json"
        )
        document = json.loads(result_path.read_text())
        self.assertEqual(
            document["gates"],
            {
                "inputTokens": True,
                "checkOutputBytes": False,
                "noOutcomeRegression": False,
            },
        )


if __name__ == "__main__":
    unittest.main()
