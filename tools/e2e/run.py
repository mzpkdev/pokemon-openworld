#!/usr/bin/env python3
"""Run an E2E-instrumented ROM with the bundled headless mGBA frontend."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PASS_MARKER = "E2E PASS milestone=CB2_Overworld"
LOG_TAIL_LINES = 100


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, default=Path("pokeemerald-e2e.gba"))
    parser.add_argument(
        "--emulator", type=Path, default=Path("tools/mgba/mgba-rom-test")
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()

    rom = args.rom.resolve()
    if not rom.is_file():
        print(f"ERROR: E2E ROM does not exist: {args.rom}", file=sys.stderr)
        return 2

    emulator_name = str(args.emulator)
    emulator = shutil.which(emulator_name)
    if emulator is None and args.emulator.is_file():
        emulator = str(args.emulator.resolve())
    if emulator is None:
        print(f"ERROR: mGBA rom-test executable not found: {args.emulator}", file=sys.stderr)
        return 2

    try:
        result = subprocess.run(
            [emulator, "-l", "10", "-S", "3", "-R", "r0", str(rom)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=args.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        captured = []
        for stream in (exc.stdout, exc.stderr):
            if stream:
                captured.append(
                    stream.decode(errors="replace")
                    if isinstance(stream, bytes)
                    else stream
                )
        if captured:
            output = "\n".join(part.strip() for part in captured if part.strip())
            print("\n".join(output.splitlines()[-LOG_TAIL_LINES:]))
        print(f"ERROR: host timeout after {args.timeout:g}s", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERROR: mGBA rom-test could not start: {exc}", file=sys.stderr)
        return 2

    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    if result.returncode != 0:
        if output:
            print("\n".join(output.splitlines()[-LOG_TAIL_LINES:]))
        print(f"ERROR: E2E ROM exited with status {result.returncode}", file=sys.stderr)
        return result.returncode
    if PASS_MARKER not in output:
        if output:
            print("\n".join(output.splitlines()[-LOG_TAIL_LINES:]))
        print(f"ERROR: missing success marker: {PASS_MARKER}", file=sys.stderr)
        return 2

    print(next(line for line in output.splitlines() if PASS_MARKER in line))
    print("PASS Emerald boot smoke: Quickstart reached CB2_Overworld")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
