"""Command line contract for ``python3 -m tools.agent``."""

import argparse
import subprocess
import sys
from pathlib import Path

from .check import execute
from .context import SEMANTIC_IMPACTS, build_context
from .output import CHECK_LIMIT, CONTEXT_LIMIT, envelope, render_json, render_text
from .query import run_query


def parser():
    root = argparse.ArgumentParser(prog="python3 -m tools.agent")
    root.add_argument(
        "--text",
        dest="global_text",
        action="store_true",
        help="render concise text instead of JSON",
    )
    commands = root.add_subparsers(dest="command", required=True)
    context = commands.add_parser("context")
    context.add_argument("--base")
    context.add_argument("--path", action="append", default=[])
    context.add_argument(
        "--impact", action="append", choices=sorted(SEMANTIC_IMPACTS), default=[]
    )
    context.add_argument("--text", action="store_true")
    query = commands.add_parser("query")
    query.add_argument(
        "kind", choices=("map", "trainer", "persistence", "content-port")
    )
    query.add_argument("key")
    query.add_argument("--text", action="store_true")
    check = commands.add_parser("check")
    check.add_argument("check_id")
    check.add_argument("--selector")
    check.add_argument("--workflow", action="append", default=[])
    check.add_argument("--timeout", type=float, default=900)
    check.add_argument("--text", action="store_true")
    return root


def main(argv=None):
    arguments = parser().parse_args(argv)
    repository = Path(__file__).resolve().parents[2]
    try:
        if arguments.command == "context":
            document = build_context(
                repository,
                base=arguments.base,
                explicit=arguments.path,
                explicit_impacts=arguments.impact,
            )
            limit = CONTEXT_LIMIT
        elif arguments.command == "query":
            document = run_query(repository, arguments.kind, arguments.key)
            limit = CONTEXT_LIMIT
        else:
            document = execute(
                repository,
                arguments.check_id,
                selector=arguments.selector,
                workflows=arguments.workflow,
                timeout=arguments.timeout,
            )
            limit = CHECK_LIMIT
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        document = envelope(
            status="error", summary=str(error), inputs={"command": arguments.command}
        )
        limit = CHECK_LIMIT
        output = (
            render_text(document, limit)
            if arguments.global_text or arguments.text
            else render_json(document, limit)
        )
        sys.stdout.write(output)
        return 2
    output = (
        render_text(document, limit)
        if arguments.global_text or arguments.text
        else render_json(document, limit)
    )
    sys.stdout.write(output)
    return 0 if document["status"] in {"ok", "not-found"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
