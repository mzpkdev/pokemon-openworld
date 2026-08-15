"""Run and score the frozen same-model benchmark for issue 74."""

import argparse
import json
import shlex
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TASKS = Path(__file__).with_name("issue_74_tasks.json")
SCHEMA = Path(__file__).with_name("response.schema.json")


def _prompt(task, arm):
    common = f"""You are running one frozen read-only benchmark task in pokemon-openworld.
Do not edit files. Scenario: {task["scenario"]}
Changed paths: {json.dumps(task["paths"])}
Determine the required handoff or conditional checks and the authoritative source paths. Run the assigned check exactly once. Return only the response-schema JSON. Set checkPassed from the actual command exit status, include every required check you identify, and cite repository-relative source paths.
Task id: {task["id"]}
"""
    if arm == "baseline":
        command = shlex.join(task["baselineCheck"])
        return (
            common
            + f"""This is the baseline arm. Do not use tools.agent. Read AGENTS.md and inspect only the repository evidence needed for the answer. Run this exact check command once in its own tool call so its admitted output can be measured separately: {command}
"""
        )
    commands = [
        ["python3", "-m", "tools.agent", "context"],
        *(
            [["python3", "-m", "tools.agent", "query", *task["query"]]]
            if task.get("query")
            else []
        ),
        [task["agentCheck"]],
    ]
    context = commands[0]
    for path in task["paths"]:
        context.extend(["--path", path])
    for impact in task.get("impacts", []):
        context.extend(["--impact", impact])
    flattened = [commands[0], *commands[1:-1], commands[-1][0]]
    rendered = "\n".join(f"- {shlex.join(command)}" for command in flattened)
    return (
        common
        + f"""This is the bounded-agent arm. Use only the following repository interface commands for discovery and checking, in order and in separate tool calls. Do not replace them with direct manifest dumps or direct check commands.
{rendered}
"""
    )


def _command(model, effort, prompt):
    common_git_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.strip()
    return [
        "codex",
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-s",
        "workspace-write",
        "-C",
        str(ROOT),
        "--add-dir",
        common_git_dir,
        "--output-schema",
        str(SCHEMA),
        prompt,
    ]


def _events(stdout):
    parsed = []
    for line in stdout.splitlines():
        if line.startswith("{"):
            parsed.append(json.loads(line))
    return parsed


def _score(task, arm, events, elapsed, returncode):
    completed = next(
        event for event in reversed(events) if event.get("type") == "turn.completed"
    )
    usage = completed["usage"]
    messages = [
        event["item"]["text"]
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "agent_message"
    ]
    response = json.loads(messages[-1])
    commands = [
        event["item"]
        for event in events
        if event.get("type") == "item.completed"
        and event.get("item", {}).get("type") == "command_execution"
    ]
    marker = shlex.join(
        task["baselineCheck"] if arm == "baseline" else task["agentCheck"]
    )
    matched_checks = [item for item in commands if marker in item.get("command", "")]
    check_outputs = [item.get("aggregated_output", "") for item in matched_checks]
    check_exit_statuses = [item.get("exit_code") for item in matched_checks]
    expected_checks = set(task["expectedChecks"])
    expected_sources = set(task["expectedSources"])
    reported_checks = {
        value.split(maxsplit=1)[0].removesuffix(":")
        for value in response.get("requiredChecks", [])
    }
    actual_check_passed = check_exit_statuses == [0]
    reported_outcome_matches = response.get(
        "checkPassed"
    ) is actual_check_passed and response.get("conclusion") == (
        "pass" if actual_check_passed else "fail"
    )
    correct = (
        returncode == 0
        and response.get("taskId") == task["id"]
        and reported_outcome_matches
        and expected_checks <= reported_checks
        and expected_sources <= set(response.get("sources", []))
    )
    return {
        "taskId": task["id"],
        "arm": arm,
        "returnCode": returncode,
        "correct": correct,
        "response": response,
        "providerUsage": usage,
        "uncachedInputTokens": usage["input_tokens"]
        - usage.get("cached_input_tokens", 0),
        "admittedCheckOutputBytes": sum(
            len(output.encode()) for output in check_outputs
        ),
        "matchedCheckCommands": len(check_outputs),
        "checkExitStatuses": check_exit_statuses,
        "toolRounds": len(commands),
        "latencySeconds": round(elapsed, 3),
    }


def _reduction(baseline, bounded):
    return round((baseline - bounded) / baseline * 100, 2) if baseline else 0.0


def _summarize(manifest, results):
    baseline = [result for result in results if result["arm"] == "baseline"]
    bounded = [result for result in results if result["arm"] == "agent"]
    baseline_tokens = statistics.median(
        result["uncachedInputTokens"] for result in baseline
    )
    bounded_tokens = statistics.median(
        result["uncachedInputTokens"] for result in bounded
    )
    baseline_bytes = sum(result["admittedCheckOutputBytes"] for result in baseline)
    bounded_bytes = sum(result["admittedCheckOutputBytes"] for result in bounded)
    summary = {
        "schemaVersion": 1,
        "benchmark": manifest["benchmark"],
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "model": manifest["model"],
        "reasoningEffort": manifest["reasoningEffort"],
        "taskCount": len(manifest["tasks"]),
        "results": results,
        "metrics": {
            "medianUncachedInputTokens": {
                "baseline": baseline_tokens,
                "agent": bounded_tokens,
                "reductionPercent": _reduction(baseline_tokens, bounded_tokens),
            },
            "totalAdmittedCheckOutputBytes": {
                "baseline": baseline_bytes,
                "agent": bounded_bytes,
                "reductionPercent": _reduction(baseline_bytes, bounded_bytes),
            },
            "medianToolRounds": {
                "baseline": statistics.median(
                    result["toolRounds"] for result in baseline
                ),
                "agent": statistics.median(result["toolRounds"] for result in bounded),
            },
            "medianLatencySeconds": {
                "baseline": statistics.median(
                    result["latencySeconds"] for result in baseline
                ),
                "agent": statistics.median(
                    result["latencySeconds"] for result in bounded
                ),
            },
            "correctTasks": {
                "baseline": sum(result["correct"] for result in baseline),
                "agent": sum(result["correct"] for result in bounded),
            },
        },
    }
    summary["gates"] = {
        "inputTokens": summary["metrics"]["medianUncachedInputTokens"][
            "reductionPercent"
        ]
        >= 20,
        "checkOutputBytes": summary["metrics"]["totalAdmittedCheckOutputBytes"][
            "reductionPercent"
        ]
        >= 50,
        "noOutcomeRegression": all(
            not baseline_result["correct"] or bounded_result["correct"]
            for baseline_result in baseline
            for bounded_result in bounded
            if baseline_result["taskId"] == bounded_result["taskId"]
        ),
    }
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rescore", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.output.exists() and not arguments.rescore:
        raise SystemExit(
            f"refusing to overwrite benchmark evidence: {arguments.output}"
        )
    if arguments.rescore:
        manifest = json.loads((arguments.output / "tasks.json").read_text())
        previous = json.loads((arguments.output / "results.json").read_text())
        timing = {
            (result["taskId"], result["arm"]): result["latencySeconds"]
            for result in previous["results"]
        }
        results = []
        for index, task in enumerate(manifest["tasks"]):
            for arm in ("baseline", "agent"):
                stem = f"{index + 1:02d}-{task['id']}-{arm}"
                stdout = (arguments.output / "runs" / f"{stem}.jsonl").read_text()
                results.append(
                    _score(
                        task,
                        arm,
                        _events(stdout),
                        timing[(task["id"], arm)],
                        0,
                    )
                )
        summary = _summarize(manifest, results)
        (arguments.output / "results.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        print(json.dumps(summary["metrics"], indent=2, sort_keys=True))
        print(json.dumps(summary["gates"], sort_keys=True))
        return 0 if all(summary["gates"].values()) else 1
    manifest = json.loads(TASKS.read_text())
    arguments.output.mkdir(parents=True)
    (arguments.output / "runs").mkdir()
    (arguments.output / "tasks.json").write_text(json.dumps(manifest, indent=2) + "\n")
    results = []
    arms = ("baseline", "agent")
    for index, task in enumerate(manifest["tasks"]):
        for arm in arms if index % 2 == 0 else tuple(reversed(arms)):
            print(f"benchmark {task['id']} {arm}", flush=True)
            prompt = _prompt(task, arm)
            started = time.monotonic()
            run = subprocess.run(
                _command(manifest["model"], manifest["reasoningEffort"], prompt),
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            elapsed = time.monotonic() - started
            stem = f"{index + 1:02d}-{task['id']}-{arm}"
            (arguments.output / "runs" / f"{stem}.jsonl").write_text(run.stdout)
            (arguments.output / "runs" / f"{stem}.stderr.txt").write_text(run.stderr)
            try:
                score = _score(task, arm, _events(run.stdout), elapsed, run.returncode)
            except (StopIteration, KeyError, ValueError, json.JSONDecodeError) as error:
                score = {
                    "taskId": task["id"],
                    "arm": arm,
                    "returnCode": run.returncode,
                    "correct": False,
                    "scoringError": f"{type(error).__name__}: {error}",
                    "latencySeconds": round(elapsed, 3),
                }
            results.append(score)
            (arguments.output / "partial-results.json").write_text(
                json.dumps(results, indent=2, sort_keys=True) + "\n"
            )
    summary = _summarize(manifest, results)
    (arguments.output / "results.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary["metrics"], indent=2, sort_keys=True))
    print(json.dumps(summary["gates"], sort_keys=True))
    return 0 if all(summary["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
