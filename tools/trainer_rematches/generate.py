#!/usr/bin/env python3
"""Validate and render the reviewed FRLG trainer-rematch authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


SCHEMA_VERSION = 1
CHAIN_COUNT = 221
CHAIN_WIDTH = 6
SKIP = "SKIP"
NONE = "NONE"
MANIFEST_PATH = Path("src/data/trainer_rematches/frlg.json")
OUTPUT_PATH = Path("src/data/trainer_rematches/frlg.inc.c")
TRAINER_HEADERS = (
    Path("include/constants/opponents.h"),
    Path("include/constants/opponents_frlg.h"),
)
PROVENANCE = {
    "repository": "https://github.com/pret/pokefirered",
    "commit": "c75f352304d529f6ba92d4f74b9cf8b5c3810788",
    "path": "src/vs_seeker.c",
    "gitBlob": "772e5516bdcf5382ddb8d53f9501676140e9f47e",
    "sha256": "35fae0cd75989534e25c463a21e1c5c74f5688b57d8b73b2ee58e03c5db4509d",
    "size": 52111,
}
REVIEWED_ROWS_SHA256 = (
    "33b4f3e6faa54359e4c3ec3400e137affdf803fb07dc62ace001808acd7fbf19"
)
NONE_BINDINGS = {
    "TRAINER_FRLG_RUIN_MANIAC_LAWSON": 1345,
    "TRAINER_YOUNGSTER_SAMUEL_JOHTO": 1481,
    "TRAINER_SAILOR_EUGENE_JOHTO": 1482,
}
BEN = [858, 870, 0xFFFF, 1241, 1242, 0]
CALVIN = [859, 859, 0, 0, 0, 0]


class RematchDataError(ValueError):
    """The authored rematch authority is malformed."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RematchDataError(f"{path}: {error}") from error
    if not isinstance(value, dict):
        raise RematchDataError("$: expected an object")
    return value


def _trainer_values(repo: Path) -> dict[str, int]:
    values: dict[str, int] = {}
    pattern = re.compile(
        r"^#define\s+(TRAINER_[A-Z0-9_]+)\s+"
        r"(0[xX][0-9A-Fa-f]+|[0-9]+)\s*(?://[^\r\n]*)?$",
        re.MULTILINE,
    )
    for relative in TRAINER_HEADERS:
        text = (repo / relative).read_text(encoding="utf-8")
        for symbol, raw_value in pattern.findall(text):
            value = int(raw_value, 0)
            previous = values.setdefault(symbol, value)
            if previous != value:
                raise RematchDataError(
                    f"{relative}: conflicting values for {symbol}: "
                    f"{previous} and {value}"
                )
    return values


def _concrete_value(symbol: str, values: dict[str, int], path: str) -> int:
    if not symbol.startswith("TRAINER_FRLG_"):
        raise RematchDataError(f"{path}: {symbol!r} is not a live FRLG identity")
    if symbol not in values:
        raise RematchDataError(f"{path}: unknown trainer symbol {symbol!r}")
    value = values[symbol]
    if not 858 <= value <= 1480:
        raise RematchDataError(
            f"{path}: {symbol} resolves outside the live FRLG range: {value}"
        )
    return value


def validate_manifest(
    manifest: dict[str, Any], values: dict[str, int]
) -> list[dict[str, Any]]:
    required = {"schemaVersion", "provenance", "noneBindings", "rows"}
    if set(manifest) != required:
        raise RematchDataError(f"$: expected exactly {sorted(required)}")
    if manifest["schemaVersion"] != SCHEMA_VERSION:
        raise RematchDataError(f"$.schemaVersion: expected {SCHEMA_VERSION}")
    if manifest["provenance"] != PROVENANCE:
        raise RematchDataError("$.provenance: reviewed upstream identity drifted")

    none_bindings = manifest["noneBindings"]
    if not isinstance(none_bindings, list) or none_bindings != list(NONE_BINDINGS):
        raise RematchDataError(
            "$.noneBindings: expected exact reviewed NONE bindings"
        )
    for index, (symbol, expected) in enumerate(NONE_BINDINGS.items()):
        if values.get(symbol) != expected:
            raise RematchDataError(
                f"$.noneBindings[{index}]: {symbol} must resolve to {expected}"
            )

    rows = manifest["rows"]
    if not isinstance(rows, list) or len(rows) != CHAIN_COUNT:
        raise RematchDataError(f"$.rows: expected exactly {CHAIN_COUNT} rows")

    family_index: dict[str, int] = {}
    member_family: dict[str, str] = {}
    value_member: dict[int, str] = {}
    resolved_rows: list[dict[str, Any]] = []
    for row_index, row in enumerate(rows):
        row_path = f"$.rows[{row_index}]"
        if not isinstance(row, list) or len(row) != CHAIN_WIDTH:
            raise RematchDataError(
                f"{row_path}: expected exactly {CHAIN_WIDTH} stage symbols"
            )
        stages = row
        family = stages[0]
        if not isinstance(family, str):
            raise RematchDataError(f"{row_path}[0]: expected a family symbol")
        if family in family_index:
            raise RematchDataError(
                f"{row_path}[0]: duplicate family from row {family_index[family]}"
            )
        family_index[family] = row_index

        seen_none = False
        resolved: list[int] = []
        for stage_index, stage in enumerate(stages):
            stage_path = f"{row_path}[{stage_index}]"
            if not isinstance(stage, str):
                raise RematchDataError(f"{stage_path}: expected a symbol")
            if stage == NONE:
                seen_none = True
                resolved.append(0)
                continue
            if seen_none:
                raise RematchDataError(f"{stage_path}: nonzero value after NONE tail")
            if stage == SKIP:
                if stage_index == 0:
                    raise RematchDataError(f"{stage_path}: SKIP cannot start a family")
                resolved.append(0xFFFF)
                continue

            value = _concrete_value(stage, values, stage_path)
            resolved.append(value)
            previous_family = member_family.setdefault(stage, family)
            if previous_family != family:
                raise RematchDataError(
                    f"{stage_path}: {stage} also belongs to {previous_family}"
                )
            previous_member = value_member.setdefault(value, stage)
            if previous_member != stage:
                raise RematchDataError(
                    f"{stage_path}: trainer ID {value} also names {previous_member}"
                )

        resolved_rows.append({"family": family, "stages": stages, "values": resolved})

    examples = {
        "TRAINER_FRLG_YOUNGSTER_BEN": BEN,
        "TRAINER_FRLG_YOUNGSTER_CALVIN": CALVIN,
    }
    by_family = {row["family"]: row["values"] for row in resolved_rows}
    for family, expected in examples.items():
        if by_family.get(family) != expected:
            raise RematchDataError(
                f"$.rows: {family} must resolve exactly to {expected}"
            )

    overlap = set(member_family).intersection(none_bindings)
    if overlap:
        raise RematchDataError(
            f"$.noneBindings: trainer also belongs to a chain: {sorted(overlap)}"
        )
    row_bytes = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode()
    if hashlib.sha256(row_bytes).hexdigest() != REVIEWED_ROWS_SHA256:
        raise RematchDataError("$.rows: reviewed upstream row order or content drifted")
    return resolved_rows


def render(manifest: dict[str, Any], values: dict[str, int]) -> str:
    rows = validate_manifest(manifest, values)
    lines = [
        "// Generated by tools/trainer_rematches/generate.py. Do not edit.",
        f"#define FRLG_TRAINER_REMATCH_CHAIN_COUNT {CHAIN_COUNT}",
        "",
        "static const struct TrainerRematchChain sTrainerRematchChains_FRLG[] =",
        "{",
    ]
    for index, row in enumerate(rows):
        stages = ", ".join(
            "0" if stage == NONE else "0xFFFF" if stage == SKIP else stage
            for stage in row["stages"]
        )
        lines.append(f"    [{index}] = {{ .trainerIds = {{ {stages} }} }},")
    lines.extend(
        [
            "};",
            "",
            "static const struct TrainerRematchBinding sTrainerRematchBindings_FRLG[TRAINERS_COUNT] =",
            "{",
        ]
    )
    for index, row in enumerate(rows):
        for symbol in dict.fromkeys(
            stage for stage in row["stages"] if stage not in {NONE, SKIP}
        ):
            lines.append(
                f"    [{symbol}] = {{ .kind = TRAINER_REMATCH_BINDING_CHAIN, .index = {index} }},"
            )
    for symbol in NONE_BINDINGS:
        lines.append(
            f"    [{symbol}] = {{ .kind = TRAINER_REMATCH_BINDING_NONE, .index = 0 }},"
        )
    lines.extend(["};", ""])
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _extract_rows(source: str) -> list[list[str]]:
    marker = "static const struct RematchData sRematches[] = {"
    start = source.find(marker)
    if start == -1:
        raise RematchDataError("upstream source: sRematches table is absent")
    cursor = start + len(marker)
    depth = 1
    row_start: int | None = None
    raw_rows: list[str] = []
    while cursor < len(source) and depth:
        char = source[cursor]
        if char == "{":
            if depth == 1:
                row_start = cursor
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 1 and row_start is not None:
                raw_rows.append(source[row_start : cursor + 1])
                row_start = None
        cursor += 1
    if depth:
        raise RematchDataError("upstream source: unterminated sRematches table")

    rows: list[list[str]] = []
    pattern = re.compile(r"^\{\s*\{(?P<stages>.*?)\}\s*,\s*MAP\(", re.DOTALL)
    for index, raw_row in enumerate(raw_rows):
        match = pattern.search(raw_row)
        if match is None:
            raise RematchDataError(f"upstream row {index}: malformed initializer")
        stages = [part.strip() for part in match.group("stages").split(",")]
        if not 1 <= len(stages) <= CHAIN_WIDTH:
            raise RematchDataError(f"upstream row {index}: invalid width")
        for stage in stages:
            if stage != SKIP and re.fullmatch(r"TRAINER_[A-Z0-9_]+", stage) is None:
                raise RematchDataError(f"upstream row {index}: invalid stage {stage!r}")
        stages.extend(["TRAINER_NONE"] * (CHAIN_WIDTH - len(stages)))
        rows.append(stages)
    return rows


def import_upstream(source_path: Path, repo: Path) -> dict[str, Any]:
    source_bytes = source_path.read_bytes()
    if len(source_bytes) != PROVENANCE["size"]:
        raise RematchDataError("upstream source: reviewed size mismatch")
    if hashlib.sha256(source_bytes).hexdigest() != PROVENANCE["sha256"]:
        raise RematchDataError("upstream source: reviewed SHA-256 mismatch")
    git_blob = hashlib.sha1(
        f"blob {len(source_bytes)}\0".encode() + source_bytes,
        usedforsecurity=False,
    ).hexdigest()
    if git_blob != PROVENANCE["gitBlob"]:
        raise RematchDataError("upstream source: reviewed git blob mismatch")

    rows = []
    for stages in _extract_rows(source_bytes.decode("utf-8")):
        adapted = [
            NONE
            if stage == "TRAINER_NONE"
            else stage
            if stage == SKIP
            else "TRAINER_FRLG_" + stage.removeprefix("TRAINER_")
            for stage in stages
        ]
        rows.append(adapted)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "provenance": PROVENANCE,
        "noneBindings": list(NONE_BINDINGS),
        "rows": rows,
    }
    validate_manifest(manifest, _trainer_values(repo))
    return manifest


def _canonical_json(value: dict[str, Any]) -> str:
    lines = [
        "{",
        f'  "schemaVersion": {json.dumps(value["schemaVersion"])},',
        f'  "provenance": {json.dumps(value["provenance"], ensure_ascii=True)},',
        f'  "noneBindings": {json.dumps(value["noneBindings"], ensure_ascii=True)},',
        '  "rows": [',
    ]
    rows = value["rows"]
    for index, row in enumerate(rows):
        suffix = "," if index + 1 < len(rows) else ""
        lines.append(f"    {json.dumps(row, ensure_ascii=True)}{suffix}")
    lines.extend(["  ]", "}"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    generate_parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    import_parser = subparsers.add_parser("import-upstream")
    import_parser.add_argument("source", type=Path)
    import_parser.add_argument("--output", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)
    repo = Path.cwd()
    try:
        values = _trainer_values(repo)
        if args.command == "import-upstream":
            manifest = import_upstream(args.source, repo)
            _atomic_write(args.output, _canonical_json(manifest))
        else:
            manifest = _load_json(args.manifest)
            if args.command == "validate":
                validate_manifest(manifest, values)
            else:
                content = render(manifest, values)
                _atomic_write(args.output, content)
    except (OSError, RematchDataError) as error:
        print(f"trainer rematch data: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
