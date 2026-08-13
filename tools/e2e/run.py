#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=("core", "extended", "integrity"))
    args = parser.parse_args()
    suite_dir = Path(__file__).parent / "tests" / args.suite
    tests = sorted(suite_dir.glob("test_*.py"))
    if not tests:
        if args.suite != "extended":
            print(f"ERROR: {args.suite} E2E suite has no tests", file=sys.stderr)
            return 2
        print("E2E extended: 0 tests")
        return 0
    command = [sys.executable, "-m", "pytest", "-q"]
    if args.suite == "integrity" and os.environ.get("E2E_FULL") != "1":
        command.extend(("-m", "not long_journey"))
    return subprocess.call([*command, str(suite_dir)])


if __name__ == "__main__":
    raise SystemExit(main())
