"""Static effect analysis for expansion script ASM.

This module recognizes the existing macro language. It does not execute scripts
or translate donor commands into a second virtual machine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .errors import ContentPortError


LABEL_RE = re.compile(r"^\s*([A-Za-z_.$][A-Za-z0-9_.$]*)::?\s*(?:@.*)?$")
INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"')
COMMAND_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*$")


@dataclass(frozen=True, order=True)
class Effect:
    kind: str
    command: str
    operand: str | None
    source: str
    line: int


@dataclass(frozen=True)
class EventEntry:
    name: str
    capability: str
    classification: str


@dataclass(frozen=True)
class Instruction:
    command: str
    operands: tuple[str, ...]
    source: str
    line: int
    scope: str


@dataclass(frozen=True)
class Opcode:
    effects: tuple[tuple[str, int | None], ...] = ()
    calls: tuple[int, ...] = ()
    terminal: bool = False


@dataclass(frozen=True)
class ScriptProgram:
    labels: Mapping[str, tuple[Instruction, ...]]
    opcodes: Mapping[str, Opcode]


def _split_operands(text: str) -> tuple[str, ...]:
    # Expansion script operands do not contain unquoted, nested commas. Preserve
    # strings so diagnostics quote the exact semantic operand.
    values: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\" and quoted:
            current.append(char)
            escaped = True
        elif char == '"':
            current.append(char)
            quoted = not quoted
        elif char == "," and not quoted:
            values.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current or text:
        values.append("".join(current).strip())
    return tuple(value for value in values if value)


def load_opcodes(path: Path | str | None = None) -> Mapping[str, Opcode]:
    source = (
        Path(path) if path is not None else Path(__file__).with_name("opcodes.json")
    )
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPortError(f"{source}: invalid opcode inventory: {exc}") from exc
    if not isinstance(document, dict):
        raise ContentPortError(f"{source}: opcode inventory must be an object")
    result: dict[str, Opcode] = {}
    for command, spec in document.items():
        if not isinstance(spec, dict):
            raise ContentPortError(f"{source}/{command}: opcode must be an object")
        effects: list[tuple[str, int | None]] = []
        for effect in spec.get("effects", []):
            if not isinstance(effect, dict) or effect.get("kind") not in {
                "state-read",
                "state-write",
                "special",
                "movement",
                "warp",
                "callback",
                "side-effect",
            }:
                raise ContentPortError(f"{source}/{command}/effects: invalid effect")
            operand = effect.get("operand")
            if operand is not None and (not isinstance(operand, int) or operand < 0):
                raise ContentPortError(
                    f"{source}/{command}/effects: invalid operand index"
                )
            effects.append((effect["kind"], operand))
        calls = spec.get("calls", [])
        if not isinstance(calls, list) or any(
            not isinstance(item, int) or item < 0 for item in calls
        ):
            raise ContentPortError(f"{source}/{command}/calls: invalid call operand")
        result[command] = Opcode(
            tuple(effects), tuple(calls), bool(spec.get("terminal", False))
        )
    return result


def _strip_comment(line: str) -> str:
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == "@" and not quoted:
            return line[:index]
    return line


def parse_scripts(
    paths: Iterable[Path | str],
    *,
    root: Path | str | None = None,
    opcodes: Mapping[str, Opcode] | None = None,
) -> ScriptProgram:
    try:
        base = (Path(root) if root is not None else Path.cwd()).resolve(strict=True)
    except OSError as exc:
        raise ContentPortError(f"{root}: invalid script root: {exc}") from exc
    pending = [Path(path) for path in paths]
    visited: set[Path] = set()
    labels: dict[str, list[Instruction]] = {}
    global_scope = ""
    current: str | None = None
    while pending:
        requested = pending.pop(0)
        path = requested if requested.is_absolute() else base / requested
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(base)
            text = resolved.read_text(encoding="utf-8")
        except ValueError as exc:
            raise ContentPortError(
                f"{path}: script source escapes authenticated root {base}"
            ) from exc
        except OSError as exc:
            raise ContentPortError(
                f"{path}: cannot read script include: {exc}"
            ) from exc
        if resolved in visited:
            continue
        visited.add(resolved)
        display = resolved.relative_to(base).as_posix()
        for line_number, raw in enumerate(text.splitlines(), 1):
            include = INCLUDE_RE.match(raw)
            if include:
                include_path = Path(include.group(1))
                if include_path.is_absolute() or ".." in include_path.parts:
                    raise ContentPortError(
                        f"{display}:{line_number}: unsafe script include "
                        f"{include.group(1)!r}"
                    )
                root_candidate = base / include_path
                candidate = (
                    root_candidate
                    if root_candidate.exists()
                    else resolved.parent / include_path
                )
                try:
                    lexical = candidate.absolute()
                    included = candidate.resolve(strict=True)
                    included.relative_to(base)
                except (OSError, ValueError) as exc:
                    raise ContentPortError(
                        f"{display}:{line_number}: script include escapes "
                        "authenticated root"
                    ) from exc
                if lexical != included:
                    raise ContentPortError(
                        f"{display}:{line_number}: script include traverses a symlink"
                    )
                pending.append(included)
                continue
            stripped = _strip_comment(raw).strip()
            if not stripped:
                continue
            match = LABEL_RE.match(stripped)
            if match:
                raw_label = match.group(1)
                if raw_label.startswith("."):
                    if not global_scope:
                        raise ContentPortError(
                            f"{display}:{line_number}: local label has no global scope"
                        )
                    current = f"{global_scope}{raw_label}"
                else:
                    global_scope = raw_label
                    current = raw_label
                if current in labels:
                    raise ContentPortError(
                        f"{display}:{line_number}: duplicate label {current}"
                    )
                labels[current] = []
                continue
            if stripped.startswith(".") or stripped.startswith("#"):
                continue
            if current is None:
                # Top-level macro tables are not reachable script entries.
                continue
            command = COMMAND_RE.match(stripped)
            if command is None:
                raise ContentPortError(
                    f"{display}:{line_number}: malformed script command"
                )
            labels[current].append(
                Instruction(
                    command.group(1),
                    _split_operands(command.group(2)),
                    display,
                    line_number,
                    global_scope,
                )
            )
    return ScriptProgram(
        {key: tuple(value) for key, value in sorted(labels.items())},
        opcodes or load_opcodes(),
    )


def _resolve_label(
    label: str, scope: str, labels: Mapping[str, Sequence[Instruction]]
) -> str | None:
    if label.startswith("."):
        label = f"{scope}{label}"
    return label if label in labels else None


def analyze_entry(program: ScriptProgram, entry: str) -> tuple[Effect, ...]:
    if entry not in program.labels:
        raise ContentPortError(f"script entry {entry} is missing")
    effects: set[Effect] = set()
    pending = [entry]
    visited: set[str] = set()
    while pending:
        label = pending.pop()
        if label in visited:
            continue
        visited.add(label)
        for instruction in program.labels[label]:
            opcode = program.opcodes.get(instruction.command)
            if opcode is None:
                raise ContentPortError(
                    f"{instruction.source}:{instruction.line}: unknown script opcode {instruction.command}"
                )
            for kind, operand_index in opcode.effects:
                operand = None
                if operand_index is not None:
                    if operand_index >= len(instruction.operands):
                        raise ContentPortError(
                            f"{instruction.source}:{instruction.line}: {instruction.command} lacks operand {operand_index}"
                        )
                    operand = instruction.operands[operand_index]
                effects.add(
                    Effect(
                        kind,
                        instruction.command,
                        operand,
                        instruction.source,
                        instruction.line,
                    )
                )
            for call_index in opcode.calls:
                if call_index >= len(instruction.operands):
                    raise ContentPortError(
                        f"{instruction.source}:{instruction.line}: {instruction.command} lacks label operand {call_index}"
                    )
                raw_target = instruction.operands[call_index]
                target = _resolve_label(raw_target, instruction.scope, program.labels)
                if target is None:
                    raise ContentPortError(
                        f"{instruction.source}:{instruction.line}: {instruction.command} target {raw_target} is missing"
                    )
                pending.append(target)
            if opcode.terminal:
                break
    return tuple(
        sorted(
            effects,
            key=lambda effect: (
                effect.source,
                effect.line,
                effect.kind,
                effect.command,
                effect.operand or "",
            ),
        )
    )


EffectKey = tuple[str, str, str | None]


def validate_effects(
    entry: EventEntry,
    effects: Iterable[Effect],
    policy: Mapping[EffectKey, str],
) -> None:
    if entry.classification in {"story-owned", "deferred", "unsupported"}:
        raise ContentPortError(
            f"{entry.name} is {entry.classification} and cannot enter an enabled closure"
        )
    for effect in sorted(
        effects,
        key=lambda item: (
            item.source,
            item.line,
            item.kind,
            item.command,
            item.operand or "",
        ),
    ):
        key = (effect.kind, effect.command, effect.operand)
        owner = policy.get(key)
        if owner is None or owner == "story-owned" or owner != entry.capability:
            raise ContentPortError(
                f"{effect.source}:{effect.line}: {entry.name} ({entry.classification}) cannot use {key}; owner={owner}"
            )


def load_event_policy(
    path: Path | str,
) -> tuple[Mapping[str, EventEntry], Mapping[EffectKey, str]]:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContentPortError(f"{source}: invalid event policy: {exc}") from exc
    if not isinstance(document, dict):
        raise ContentPortError(f"{source}: event policy must be an object")
    entries: dict[str, EventEntry] = {}
    for index, raw in enumerate(document.get("entries", [])):
        try:
            entry = EventEntry(
                str(raw["name"]), str(raw["capability"]), str(raw["classification"])
            )
        except (KeyError, TypeError) as exc:
            raise ContentPortError(
                f"{source}/entries/{index}: malformed event entry"
            ) from exc
        if entry.name in entries:
            raise ContentPortError(
                f"{source}/entries/{index}: duplicate event entry {entry.name}"
            )
        entries[entry.name] = entry
    policy: dict[EffectKey, str] = {}
    for index, raw in enumerate(document.get("effects", [])):
        try:
            key = (
                str(raw["kind"]),
                str(raw["command"]),
                str(raw["operand"]) if raw.get("operand") is not None else None,
            )
            owner = str(raw["owner"])
        except (KeyError, TypeError) as exc:
            raise ContentPortError(
                f"{source}/effects/{index}: malformed effect policy"
            ) from exc
        if key in policy:
            raise ContentPortError(
                f"{source}/effects/{index}: duplicate effect policy {key}"
            )
        policy[key] = owner
    return entries, policy
