"""Static effect analysis for expansion script ASM.

This module recognizes the existing macro language. It does not execute scripts
or translate donor commands into a second virtual machine.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Mapping, Sequence

from .errors import ContentPortError

if TYPE_CHECKING:
    from .model import CapabilityDecision


LABEL_RE = re.compile(r"^\s*([A-Za-z_.$][A-Za-z0-9_.$]*)::?\s*(?:@.*)?$")
INCLUDE_RE = re.compile(r'^\s*\.include\s+"([^"]+)"')
COMMAND_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(.*?)\s*$")
EFFECT_KINDS = frozenset(
    {
        "state-read",
        "state-write",
        "special",
        "movement",
        "warp",
        "callback",
        "side-effect",
    }
)
ENTRY_CLASSIFICATIONS = frozenset({"enabled", "story-owned", "deferred", "unsupported"})


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
    dependencies: tuple[tuple[str, int], ...] = ()
    terminal: bool = False


@dataclass(frozen=True)
class ScriptProgram:
    labels: Mapping[str, tuple[Instruction, ...]]
    opcodes: Mapping[str, Opcode]


def split_operands(text: str) -> tuple[str, ...]:
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


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ContentPortError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _read_json(source: Path, description: str) -> object:
    try:
        return json.loads(
            source.read_text(encoding="utf-8"), object_pairs_hook=_json_object
        )
    except (OSError, json.JSONDecodeError, ContentPortError) as exc:
        raise ContentPortError(f"{source}: invalid {description}: {exc}") from exc


def _exact_object(value: object, keys: set[str], pointer: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: must be an object")
    unknown = sorted(set(value) - keys)
    missing = sorted(keys - set(value))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")
    return value


def _nonempty_string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContentPortError(f"{pointer}: must be a non-empty string")
    return value


def load_opcodes(path: Path | str | None = None) -> Mapping[str, Opcode]:
    source = (
        Path(path) if path is not None else Path(__file__).with_name("opcodes.json")
    )
    document = _exact_object(
        _read_json(source, "opcode inventory"),
        {"schemaVersion", "opcodes"},
        str(source),
    )
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise ContentPortError(f"{source}/schemaVersion: unsupported opcode schema")
    inventory = document["opcodes"]
    if not isinstance(inventory, dict) or not inventory:
        raise ContentPortError(f"{source}/opcodes: must be a non-empty object")
    result: dict[str, Opcode] = {}
    for command, raw_spec in inventory.items():
        _nonempty_string(command, f"{source}/opcodes command")
        spec = _exact_object(
            raw_spec,
            {"effects", "calls", "dependencies", "terminal"},
            f"{source}/opcodes/{command}",
        )
        raw_effects = spec["effects"]
        if not isinstance(raw_effects, list):
            raise ContentPortError(
                f"{source}/opcodes/{command}/effects: must be a list"
            )
        effects: list[tuple[str, int | None]] = []
        for index, raw_effect in enumerate(raw_effects):
            effect = _exact_object(
                raw_effect,
                {"kind", "operand"},
                f"{source}/opcodes/{command}/effects/{index}",
            )
            if effect["kind"] not in EFFECT_KINDS:
                raise ContentPortError(
                    f"{source}/opcodes/{command}/effects/{index}/kind: invalid effect"
                )
            operand = effect["operand"]
            if operand is not None and (type(operand) is not int or operand < 0):
                raise ContentPortError(
                    f"{source}/opcodes/{command}/effects/{index}/operand: "
                    "invalid operand index"
                )
            effects.append((str(effect["kind"]), operand))
        calls = spec["calls"]
        if not isinstance(calls, list) or any(
            type(item) is not int or item < 0 for item in calls
        ):
            raise ContentPortError(
                f"{source}/opcodes/{command}/calls: invalid call operand"
            )
        raw_dependencies = spec["dependencies"]
        if not isinstance(raw_dependencies, list):
            raise ContentPortError(
                f"{source}/opcodes/{command}/dependencies: must be a list"
            )
        dependencies: list[tuple[str, int]] = []
        for index, raw_dependency in enumerate(raw_dependencies):
            dependency = _exact_object(
                raw_dependency,
                {"domain", "operand"},
                f"{source}/opcodes/{command}/dependencies/{index}",
            )
            domain = _nonempty_string(
                dependency["domain"],
                f"{source}/opcodes/{command}/dependencies/{index}/domain",
            )
            operand = dependency["operand"]
            if type(operand) is not int or operand < 0:
                raise ContentPortError(
                    f"{source}/opcodes/{command}/dependencies/{index}/operand: "
                    "invalid operand index"
                )
            dependencies.append((domain, operand))
        terminal = spec["terminal"]
        if type(terminal) is not bool:
            raise ContentPortError(
                f"{source}/opcodes/{command}/terminal: must be a boolean"
            )
        result[command] = Opcode(
            tuple(effects), tuple(calls), tuple(dependencies), terminal
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
                    split_operands(command.group(2)),
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
    document = _exact_object(
        _read_json(source, "event policy"),
        {"schemaVersion", "entries", "effects"},
        str(source),
    )
    if type(document["schemaVersion"]) is not int or document["schemaVersion"] != 1:
        raise ContentPortError(f"{source}/schemaVersion: unsupported event schema")
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list):
        raise ContentPortError(f"{source}/entries: must be a list")
    entries: dict[str, EventEntry] = {}
    for index, raw in enumerate(raw_entries):
        item = _exact_object(
            raw, {"name", "capability", "classification"}, f"{source}/entries/{index}"
        )
        entry = EventEntry(
            _nonempty_string(item["name"], f"{source}/entries/{index}/name"),
            _nonempty_string(
                item["capability"], f"{source}/entries/{index}/capability"
            ),
            _nonempty_string(
                item["classification"], f"{source}/entries/{index}/classification"
            ),
        )
        if entry.classification not in ENTRY_CLASSIFICATIONS:
            raise ContentPortError(
                f"{source}/entries/{index}/classification: unknown classification"
            )
        if entry.name in entries:
            raise ContentPortError(
                f"{source}/entries/{index}: duplicate event entry {entry.name}"
            )
        entries[entry.name] = entry
    policy: dict[EffectKey, str] = {}
    raw_effects = document["effects"]
    if not isinstance(raw_effects, list):
        raise ContentPortError(f"{source}/effects: must be a list")
    for index, raw in enumerate(raw_effects):
        item = _exact_object(
            raw,
            {"kind", "command", "operand", "owner"},
            f"{source}/effects/{index}",
        )
        kind = _nonempty_string(item["kind"], f"{source}/effects/{index}/kind")
        if kind not in EFFECT_KINDS:
            raise ContentPortError(f"{source}/effects/{index}/kind: invalid effect")
        operand = item["operand"]
        if operand is not None:
            operand = _nonempty_string(operand, f"{source}/effects/{index}/operand")
        key = (
            kind,
            _nonempty_string(item["command"], f"{source}/effects/{index}/command"),
            operand,
        )
        owner = _nonempty_string(item["owner"], f"{source}/effects/{index}/owner")
        if key in policy:
            raise ContentPortError(
                f"{source}/effects/{index}: duplicate effect policy {key}"
            )
        policy[key] = owner
    return entries, policy


def validate_event_policy_capabilities(
    entries: Mapping[str, EventEntry],
    policy: Mapping[EffectKey, str],
    capabilities: Iterable[CapabilityDecision],
    *,
    source: Path | str,
) -> None:
    from .model import CapabilityState

    capability_states: dict[str, set[CapabilityState]] = {}
    for decision in capabilities:
        capability_states.setdefault(decision.capability, set()).add(decision.state)
    for entry in entries.values():
        states = capability_states.get(entry.capability)
        if states is None:
            raise ContentPortError(
                f"{source}: event {entry.name} names unknown capability "
                f"{entry.capability!r}"
            )
        classification = CapabilityState.parse(
            entry.classification, f"{source}: event {entry.name}.classification"
        )
        if classification not in states:
            raise ContentPortError(
                f"{source}: event {entry.name} classification "
                f"{entry.classification!r} is stale for capability "
                f"{entry.capability!r}"
            )
    allowed_effect_owners = set(capability_states) | {CapabilityState.STORY_OWNED.value}
    unknown_effect_owners = sorted(set(policy.values()) - allowed_effect_owners)
    if unknown_effect_owners:
        raise ContentPortError(
            f"{source}: effect policy names unknown owner {unknown_effect_owners[0]!r}"
        )
