"""Shell-free allowlisted check execution with retained evidence."""

import json
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
    argv, definition = resolve(check_id, selector=selector, workflows=workflows)
    for workflow in workflows:
        if not (root / workflow).is_file():
            raise ValueError(f"workflow does not exist: {workflow}")
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
