"""Decide whether changed repository paths require donor-backed CI checks."""

from __future__ import annotations

import sys
from collections.abc import Iterable


DONOR_CONTRACT_FILES = frozenset(
    {
        ".github/workflows/ci.yml",
        "CREDITS.md",
        "Makefile",
    }
)
DONOR_CONTRACT_PREFIXES = (
    "data/",
    "graphics/trainers/front_pics/",
    "include/constants/",
    "src/data/",
    "tools/content_port/",
)


def requires_donor_contracts(paths: Iterable[str]) -> bool:
    return any(
        path in DONOR_CONTRACT_FILES or path.startswith(DONOR_CONTRACT_PREFIXES)
        for path in paths
    )


def main() -> int:
    paths = (path for path in sys.stdin.read().split("\0") if path)
    return 0 if requires_donor_contracts(paths) else 1


if __name__ == "__main__":
    raise SystemExit(main())
