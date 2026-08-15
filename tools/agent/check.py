"""Shell-free allowlisted check execution with retained evidence."""

import json
import math
import os
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .output import CHECK_LIMIT, DIAGNOSTIC_LIMIT, bound, envelope
from .registry import resolve

ANSI = re.compile(rb"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
DIAGNOSTIC = re.compile(
    r"(?i)(?:error|failed|failure|traceback|assertionerror|warning):?"
)


def _unique_log(root, check_id):
    directory = root / "build/agent-logs"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    base = directory / f"{stamp}-{os.getpid()}-{check_id}"
    counter = 0
    while True:
        suffix = "" if counter == 0 else f"-{counter}"
        path = Path(f"{base}{suffix}.log")
        if not path.exists():
            return path
        counter += 1


def _excerpt(data):
    clean = ANSI.sub(b"", data).decode("utf-8", "replace")
    lines = clean.splitlines()
    selected = [line for line in lines if DIAGNOSTIC.search(line)]
    kind = "parsed" if selected else "tail"
    value = "\n".join((selected or lines)[-20:])
    encoded = value.encode()
    omitted = max(0, len(encoded) - DIAGNOSTIC_LIMIT)
    if omitted:
        value = encoded[-DIAGNOSTIC_LIMIT:].decode("utf-8", "replace")
    return {"kind": kind, "excerpt": value, "omittedBytes": omitted}


def execute(root, check_id, *, selector=None, workflows=(), timeout=900):
    if not math.isfinite(timeout) or not 0 < timeout <= 86_400:
        raise ValueError("timeout must be finite and between 0 and 86400 seconds")
    argv, definition = resolve(check_id, selector=selector, workflows=workflows)
    selector_type = definition.get("selector")
    if selector_type == "pytest":
        _require_repo_file(root, selector.split("::", 1)[0], "pytest selector")
    elif selector_type == "unittest":
        _require_unittest_module(root, selector)
    for workflow in workflows:
        _require_repo_file(root, workflow, "workflow")
    log_path = _unique_log(root, check_id)
    started_wall = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    timed_out = False
    returncode = None
    signal_number = None
    execution_error = None
    with log_path.open("xb") as log:
        try:
            process = subprocess.Popen(
                argv,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    returncode = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    returncode = process.wait()
        except OSError as error:
            execution_error = f"{type(error).__name__}: {error}"
            log.write((execution_error + "\n").encode())
            returncode = 127
    elapsed = time.monotonic() - started
    if returncode is not None and returncode < 0:
        signal_number = -returncode
    raw = log_path.read_bytes()
    status = "timeout" if timed_out else ("ok" if returncode == 0 else "failed")
    result = envelope(
        status=status,
        summary=f"{check_id} {status} in {elapsed:.3f}s",
        inputs={
            "checkId": check_id,
            "selector": selector,
            "workflows": sorted(set(workflows)),
            "timeoutSeconds": timeout,
        },
    )
    result["items"] = [
        {
            "id": check_id,
            "tier": definition["tier"],
            "argv": argv,
            "cwd": str(root),
            "startedAt": started_wall,
            "elapsedSeconds": round(elapsed, 3),
            "exitStatus": returncode,
            "signal": signal_number,
            "timedOut": timed_out,
            "executionError": execution_error,
        }
    ]
    result["diagnostics"] = [_excerpt(raw)] if raw else []
    result["logs"] = [
        {
            "path": log_path.relative_to(root).as_posix(),
            "bytes": len(raw),
            "combined": True,
        }
    ]
    bounded = bound(result, CHECK_LIMIT)
    metadata = {
        "argv": argv,
        "cwd": str(root),
        "startedAt": started_wall,
        "elapsedSeconds": elapsed,
        "exitStatus": returncode,
        "signal": signal_number,
        "timedOut": timed_out,
        "executionError": execution_error,
        "result": bounded,
    }
    metadata_path = log_path.with_suffix(".json")
    with metadata_path.open("x") as evidence:
        json.dump(metadata, evidence, sort_keys=True, separators=(",", ":"))
        evidence.write("\n")
    bounded["logs"].append(
        {
            "path": metadata_path.relative_to(root).as_posix(),
            "bytes": metadata_path.stat().st_size,
            "kind": "metadata",
        }
    )
    return bound(bounded, CHECK_LIMIT)


def _require_repo_file(root, relative, label):
    candidate = root / relative
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as error:
        raise ValueError(f"{label} is not a repository file: {relative}") from error
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"{label} is not a regular repository file: {relative}")


def _require_unittest_module(root, selector):
    parts = selector.split(".")
    for length in range(len(parts), 0, -1):
        relative = Path(*parts[:length]).with_suffix(".py")
        if (root / relative).exists():
            _require_repo_file(root, relative.as_posix(), "unittest selector")
            return
    raise ValueError(f"unittest selector is not a repository module: {selector}")
