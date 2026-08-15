"""Bounded, read-only access to the pinned Probe retrieval CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .artifact import ArtifactError, repository_root, verified_binary

SCHEMA_VERSION = 1
TIMEOUT_SECONDS = 5
RAW_OUTPUT_BYTES = 1024 * 1024
RESPONSE_BYTES = 32 * 1024
PROBE_CODE_BYTES = 20 * 1024
PROBE_TOKENS = 4_000
MAX_RESULTS = 20
MAX_SOURCE_BYTES = 512 * 1024
MAX_RANGE_LINES = 200
CONTROL_DIRECTORIES = {".cache", ".git", ".references", "build", "test-results"}
LANGUAGE_SUFFIXES = {
    "c": {".c", ".h"},
    "cpp": {".cc", ".cpp", ".cxx", ".hpp", ".hxx"},
    "python": {".py"},
}
SUPPORTED_SUFFIXES = set().union(*LANGUAGE_SUFFIXES.values())
SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:]*$")


class RetrievalError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class JsonParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise RetrievalError("invalid_arguments", message)


def _compact(document: object) -> bytes:
    return json.dumps(
        document, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _relative_path(root: Path, raw: str, *, file_required: bool = False) -> Path:
    if not raw or "\x00" in raw:
        raise RetrievalError("invalid_path", "path must not be empty")
    relative = Path(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise RetrievalError("invalid_path", "path must be repository-relative")
    if relative.parts and relative.parts[0] in CONTROL_DIRECTORIES:
        raise RetrievalError(
            "invalid_path", "path is repository control or output data"
        )
    candidate = root.joinpath(relative)
    try:
        canonical = candidate.resolve(strict=True)
        canonical.relative_to(root)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RetrievalError(
            "invalid_path", "path or symlink target is outside the active worktree"
        ) from exc
    if file_required and not canonical.is_file():
        raise RetrievalError("invalid_path", "command requires a regular file")
    if not file_required and not (canonical.is_file() or canonical.is_dir()):
        raise RetrievalError("invalid_path", "path must be a regular file or directory")
    display = canonical.relative_to(root)
    try:
        ignored = subprocess.run(
            (
                "git",
                "-C",
                str(root),
                "check-ignore",
                "--quiet",
                "--no-index",
                "--",
                str(display),
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RetrievalError(
            "git_failed", f"could not validate Git ignores: {exc}"
        ) from exc
    if ignored.returncode == 0:
        raise RetrievalError(
            "invalid_path", "ignored paths are outside retrieval scope"
        )
    if ignored.returncode not in {0, 1}:
        raise RetrievalError(
            "git_failed", "could not validate the path against Git ignores"
        )
    return display


def _supported_file(root: Path, raw: str) -> Path:
    relative = _relative_path(root, raw, file_required=True)
    absolute = root / relative
    if absolute.suffix.lower() not in SUPPORTED_SUFFIXES:
        raise RetrievalError(
            "unsupported_format",
            "Probe AST retrieval supports C, C++, and Python here; use rg or a bounded file read",
        )
    if absolute.stat().st_size > MAX_SOURCE_BYTES:
        raise RetrievalError(
            "oversized_file",
            "file exceeds the Probe wrapper limit; use a bounded file read",
        )
    return relative


def _run_probe(binary: Path, root: Path, arguments: list[str]) -> bytes:
    environment = {"LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin"}
    try:
        process = subprocess.Popen(
            (str(binary), *arguments),
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise RetrievalError("missing_tool", f"could not start Probe: {exc}") from exc
    assert process.stdout is not None
    assert process.stderr is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, "stdout")
    selector.register(process.stderr, selectors.EVENT_READ, "stderr")
    chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
    size = 0
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise RetrievalError("timeout", "Probe exceeded the fixed timeout")
            events = selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                size += len(chunk)
                if size > RAW_OUTPUT_BYTES:
                    process.kill()
                    process.wait()
                    raise RetrievalError(
                        "output_limit", "Probe exceeded the raw output cap"
                    )
                chunks[key.data].append(chunk)
        try:
            returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise RetrievalError("timeout", "Probe exceeded the fixed timeout") from exc
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
        process.stderr.close()
    stdout = b"".join(chunks["stdout"])
    stderr = b"".join(chunks["stderr"])
    if returncode != 0:
        try:
            detail = stderr.decode("utf-8", errors="strict").strip()[:500]
        except UnicodeDecodeError:
            detail = "non-UTF-8 diagnostic"
        raise RetrievalError("probe_failed", detail or f"Probe exited {returncode}")
    return stdout


def _probe_json(binary: Path, root: Path, arguments: list[str]) -> Any:
    raw = _run_probe(binary, root, arguments)
    try:
        decoded = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RetrievalError(
            "invalid_output", "Probe returned non-UTF-8 output"
        ) from exc
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise RetrievalError("invalid_output", "Probe returned malformed JSON") from exc


def _display_path(root: Path, raw: object) -> str:
    if not isinstance(raw, str):
        raise RetrievalError("invalid_output", "Probe result has no valid file path")
    path = Path(raw)
    candidate = path if path.is_absolute() else root / path
    try:
        return candidate.resolve(strict=True).relative_to(root).as_posix()
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise RetrievalError(
            "invalid_output", "Probe returned an out-of-scope file"
        ) from exc


def _bounded_results(
    base: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    included: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for record in records:
        candidate = {
            **base,
            "omitted_bytes": 0,
            "omitted_records": 0,
            "results": [*included, record],
            "truncated": False,
        }
        if len(_compact(candidate)) <= RESPONSE_BYTES:
            included.append(record)
        else:
            omitted.append(record)
    document = {
        **base,
        "omitted_bytes": sum(len(_compact(record)) for record in omitted),
        "omitted_records": len(omitted),
        "results": included,
        "truncated": bool(omitted),
    }
    while len(_compact(document)) > RESPONSE_BYTES and included:
        record = included.pop()
        omitted.insert(0, record)
        document.update(
            omitted_bytes=sum(len(_compact(item)) for item in omitted),
            omitted_records=len(omitted),
            results=included,
            truncated=True,
        )
    if len(_compact(document)) > RESPONSE_BYTES:
        raise RetrievalError("output_limit", "response metadata exceeds the output cap")
    return document


def _search(args: argparse.Namespace, root: Path, binary: Path) -> dict[str, Any]:
    if (
        not args.query
        or len(args.query) > 256
        or "\n" in args.query
        or "\x00" in args.query
    ):
        raise RetrievalError(
            "invalid_query", "query must be 1 to 256 characters on one line"
        )
    relative = _relative_path(root, args.path)
    absolute = root / relative
    if (
        absolute.is_file()
        and absolute.suffix.lower() not in LANGUAGE_SUFFIXES[args.language]
    ):
        raise RetrievalError(
            "unsupported_format", "file does not match the requested AST language"
        )
    payload = _probe_json(
        binary,
        root,
        [
            "search",
            args.query,
            relative.as_posix() or ".",
            "--language",
            args.language,
            "--max-results",
            str(MAX_RESULTS),
            "--max-bytes",
            str(PROBE_CODE_BYTES),
            "--max-tokens",
            str(PROBE_TOKENS),
            "--timeout",
            str(TIMEOUT_SECONDS),
            "--format",
            "json",
        ],
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RetrievalError("invalid_output", "Probe search JSON has an invalid shape")
    records = []
    for item in payload["results"]:
        if not isinstance(item, dict) or not isinstance(item.get("code"), str):
            raise RetrievalError(
                "invalid_output", "Probe search result has an invalid shape"
            )
        lines = item.get("lines")
        if not (
            isinstance(lines, list)
            and len(lines) == 2
            and all(isinstance(line, int) for line in lines)
        ):
            raise RetrievalError(
                "invalid_output", "Probe search result has invalid lines"
            )
        records.append(
            {
                "code": item["code"],
                "file": _display_path(root, item.get("file")),
                "language": item.get("language", args.language),
                "lines": lines,
                "symbol": item.get("owner_qualified_symbol"),
            }
        )
    return _bounded_results(
        {
            "command": "search",
            "language": args.language,
            "retrieval": "ast",
            "schema_version": SCHEMA_VERSION,
        },
        records,
    )


def _symbols(args: argparse.Namespace, root: Path, binary: Path) -> dict[str, Any]:
    relative = _supported_file(root, args.path)
    payload = _probe_json(
        binary, root, ["symbols", relative.as_posix(), "--format", "json"]
    )
    if not isinstance(payload, list) or len(payload) != 1:
        raise RetrievalError(
            "invalid_output", "Probe symbols JSON has an invalid shape"
        )
    group = payload[0]
    if not isinstance(group, dict) or not isinstance(group.get("symbols"), list):
        raise RetrievalError(
            "invalid_output", "Probe symbols JSON has an invalid shape"
        )
    records = []
    for item in group["symbols"]:
        if not isinstance(item, dict):
            raise RetrievalError("invalid_output", "Probe symbol has an invalid shape")
        record = {
            key: item.get(key)
            for key in ("end_line", "kind", "line", "name", "signature")
        }
        if not isinstance(record["name"], str) or not isinstance(record["line"], int):
            raise RetrievalError("invalid_output", "Probe symbol has an invalid shape")
        records.append(record)
    return _bounded_results(
        {
            "command": "symbols",
            "file": relative.as_posix(),
            "retrieval": "ast",
            "schema_version": SCHEMA_VERSION,
        },
        records,
    )


def _extract_symbol(
    args: argparse.Namespace, root: Path, binary: Path
) -> dict[str, Any]:
    relative = _supported_file(root, args.path)
    if not SYMBOL_PATTERN.fullmatch(args.symbol):
        raise RetrievalError("invalid_symbol", "symbol has an invalid form")
    payload = _probe_json(
        binary,
        root,
        ["extract", f"{relative.as_posix()}#{args.symbol}", "--format", "json"],
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RetrievalError(
            "invalid_output", "Probe extract JSON has an invalid shape"
        )
    if len(payload["results"]) != 1:
        raise RetrievalError(
            "symbol_not_found", "Probe did not resolve exactly one required symbol"
        )
    item = payload["results"][0]
    if not isinstance(item, dict) or not isinstance(item.get("code"), str):
        raise RetrievalError(
            "invalid_output", "Probe extract result has an invalid shape"
        )
    record = {
        "code": item["code"],
        "file": _display_path(root, item.get("file")),
        "lines": item.get("lines"),
        "node_type": item.get("node_type"),
        "symbol": args.symbol,
    }
    return _bounded_results(
        {
            "command": "extract",
            "retrieval": "ast",
            "schema_version": SCHEMA_VERSION,
        },
        [record],
    )


def _extract_range(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    relative = _supported_file(root, args.path)
    if args.start_line < 1 or args.end_line < args.start_line:
        raise RetrievalError("invalid_range", "line range is invalid")
    if args.end_line - args.start_line + 1 > MAX_RANGE_LINES:
        raise RetrievalError(
            "invalid_range", f"line range exceeds {MAX_RANGE_LINES} lines"
        )
    try:
        lines = (
            (root / relative).read_text(encoding="utf-8", errors="strict").splitlines()
        )
    except UnicodeDecodeError as exc:
        raise RetrievalError("invalid_source", "source file is not UTF-8") from exc
    if args.end_line > len(lines):
        raise RetrievalError("invalid_range", "line range exceeds the file")
    if args.start_line == 1 and args.end_line == len(lines):
        raise RetrievalError(
            "whole_file_forbidden", "whole-file extraction is not allowed"
        )
    record = {
        "code": "\n".join(lines[args.start_line - 1 : args.end_line]),
        "file": relative.as_posix(),
        "lines": [args.start_line, args.end_line],
    }
    return _bounded_results(
        {
            "command": "extract",
            "retrieval": "text_fallback",
            "schema_version": SCHEMA_VERSION,
        },
        [record],
    )


def _parser() -> JsonParser:
    parser = JsonParser(description=__doc__)
    commands = parser.add_subparsers(
        dest="command", required=True, parser_class=JsonParser
    )
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--path", default=".")
    search.add_argument("--language", required=True, choices=sorted(LANGUAGE_SUFFIXES))
    symbols = commands.add_parser("symbols")
    symbols.add_argument("path")
    extract = commands.add_parser("extract")
    extract.add_argument("path")
    mode = extract.add_mutually_exclusive_group(required=True)
    mode.add_argument("--symbol")
    mode.add_argument("--start-line", type=int)
    extract.add_argument("--end-line", type=int)
    return parser


def execute(
    argv: list[str], *, cwd: Path | None = None, binary: Path | None = None
) -> dict[str, Any]:
    args = _parser().parse_args(argv)
    root = repository_root(cwd)
    if args.command == "extract" and args.start_line is not None:
        if args.end_line is None:
            raise RetrievalError(
                "invalid_arguments", "--end-line is required with --start-line"
            )
        return _extract_range(args, root)
    if args.command == "extract" and args.end_line is not None:
        raise RetrievalError("invalid_arguments", "--end-line requires --start-line")
    probe = binary or verified_binary(root)
    if args.command == "search":
        return _search(args, root, probe)
    if args.command == "symbols":
        return _symbols(args, root, probe)
    return _extract_symbol(args, root, probe)


def main(argv: list[str] | None = None) -> int:
    try:
        document = execute(list(argv if argv is not None else sys.argv[1:]))
        output = _compact(document)
    except (ArtifactError, RetrievalError) as exc:
        code = exc.code if isinstance(exc, RetrievalError) else "artifact_error"
        output = _compact(
            {
                "error": {"code": code, "message": str(exc)},
                "schema_version": SCHEMA_VERSION,
            }
        )
        sys.stdout.buffer.write(output + b"\n")
        return 2
    sys.stdout.buffer.write(output + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
