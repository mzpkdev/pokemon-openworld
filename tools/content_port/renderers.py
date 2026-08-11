"""Deterministic expansion-native rendering primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .errors import ContentPortError
from .ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
    legacy_section_markers,
    section_markers,
    validate_relative_path,
)


@dataclass(frozen=True)
class RenderContext:
    port: str
    root: Path | None = None
    allocations: object | None = None
    bindings: object | None = None
    hand_owned_paths: frozenset[str] = frozenset()
    hand_owned_sections: frozenset[tuple[str, str]] = frozenset()


@dataclass(frozen=True)
class RenderUnit:
    key: str
    renderer: str
    path: str
    value: object
    name: str | None = None
    registry: str | None = None
    record_key: str | None = None
    slot: int | None = None
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_relative_path(self.path)
        object.__setattr__(self, "options", MappingProxyType(dict(self.options)))


@dataclass(frozen=True)
class OwnedOutput:
    kind: str
    path: str
    content: bytes | object
    name: str | None = None
    registry: str | None = None
    key: str | None = None
    slot: int | None = None

    def payload_bytes(self) -> bytes:
        if self.kind == "registry-record":
            if isinstance(self.content, bytes):
                try:
                    value = json.loads(self.content)
                except json.JSONDecodeError as error:
                    raise ContentPortError(
                        f"{self.path}: invalid registry JSON"
                    ) from error
            else:
                value = self.content
            return canonical_json(value)
        if isinstance(self.content, str):
            return self.content.encode()
        if not isinstance(self.content, bytes):
            raise ContentPortError(
                f"{self.path}: file and section renderers require bytes"
            )
        return self.content

    def ownership_unit(self) -> OwnershipUnit:
        return OwnershipUnit(
            kind=self.kind,
            path=self.path,
            sha256=content_sha256(self.payload_bytes()),
            name=self.name,
            registry=self.registry,
            key=self.key,
            slot=self.slot,
        )


Renderer = Callable[[RenderContext, RenderUnit], Iterable[OwnedOutput]]
_TRAINER_ID_RE = re.compile(r"^TRAINER_[A-Z0-9_]+$")
_TRAINER_DISPLAY_RE = re.compile(r"^[A-Za-z0-9?][A-Za-z0-9 ?.'-]*$")
_TRAINER_SPECIES_RE = re.compile(r"^SPECIES_[A-Z0-9_]+$")
_SCRIPT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_]+$")
_TEXT_FRAGMENT_RE = re.compile(r'^"(?:[^"\\\r\n]|\\.)*"$')


def _trainer_string(value: object, pattern: re.Pattern[str], pointer: str) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ContentPortError(f"{pointer}: invalid trainer render token")
    return value


def _json_output(unit: RenderUnit) -> tuple[OwnedOutput, ...]:
    sort_keys = unit.options.get("sortKeys", True)
    if not isinstance(sort_keys, bool):
        raise ContentPortError(f"{unit.key}: sortKeys must be boolean")
    ensure_ascii = unit.options.get("ensureAscii", False)
    if not isinstance(ensure_ascii, bool):
        raise ContentPortError(f"{unit.key}: ensureAscii must be boolean")
    payload = (
        json.dumps(
            unit.value,
            sort_keys=sort_keys,
            indent=2,
            ensure_ascii=ensure_ascii,
        )
        + "\n"
    ).encode()
    return (OwnedOutput("file", unit.path, payload),)


def render_map_json(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    if not isinstance(unit.value, dict):
        raise ContentPortError(f"{unit.key}: map-json requires an object")
    return _json_output(unit)


def _record_output(unit: RenderUnit, default_registry: str) -> tuple[OwnedOutput, ...]:
    registry = unit.registry or default_registry
    key = unit.record_key or unit.key
    return (
        OwnedOutput(
            "registry-record",
            unit.path,
            unit.value,
            registry=registry,
            key=key,
            slot=unit.slot,
        ),
    )


def render_layout_registry(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    omitted = unit.options.get("omitFields", ())
    if (
        not isinstance(omitted, (list, tuple))
        or any(not isinstance(field, str) for field in omitted)
        or len(omitted) != len(set(omitted))
    ):
        raise ContentPortError(f"{unit.key}: omitFields must be unique strings")
    if not isinstance(unit.value, dict):
        raise ContentPortError(f"{unit.key}: layout-registry requires an object")
    value = {key: item for key, item in unit.value.items() if key not in omitted}
    return _record_output(
        RenderUnit(
            unit.key,
            unit.renderer,
            unit.path,
            value,
            name=unit.name,
            registry=unit.registry,
            record_key=unit.record_key,
            slot=unit.slot,
        ),
        "layouts",
    )


def render_map_group_registry(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    return _record_output(unit, "mapGroups")


def render_region_section_registry(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    return _record_output(unit, "sections")


def render_encounter_registry(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    return _record_output(unit, "encounters")


def render_tileset_assets(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    value = unit.value
    if isinstance(value, (bytes, str)):
        value = {unit.path: value}
    if not isinstance(value, dict) or not value:
        raise ContentPortError(
            f"{unit.key}: tileset-assets requires a non-empty path mapping"
        )
    outputs: list[OwnedOutput] = []
    for path, content in sorted(value.items()):
        if not isinstance(path, str) or not isinstance(content, (bytes, str)):
            raise ContentPortError(f"{unit.key}: invalid tileset asset")
        validate_relative_path(path)
        outputs.append(
            OwnedOutput(
                "file", path, content.encode() if isinstance(content, str) else content
            )
        )
    return tuple(outputs)


def render_generated_section(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    name = unit.name or unit.key
    if isinstance(unit.value, bytes):
        body = unit.value
    elif isinstance(unit.value, str):
        body = unit.value.encode()
    else:
        raise ContentPortError(f"{unit.key}: generated-section requires text or bytes")
    if b"\x00" in body:
        raise ContentPortError(f"{unit.key}: generated text section contains NUL")
    dialect = unit.options.get("markerDialect", "content-port")
    if dialect == "content-port":
        begin, end = section_markers(context.port, name)
    elif dialect == "legacy-import":
        begin, end = legacy_section_markers(context.port, name)
    else:
        raise ContentPortError(f"{unit.key}: unknown section marker dialect")
    marker_style = unit.options.get("markerStyle", "comment")
    if marker_style == "preprocessor":
        marker_comment = b"// " if dialect == "legacy-import" else b""
        content = b"#if 1 /* " + marker_comment + begin + b" */\n"
        content += body
        if body and not body.endswith(b"\n"):
            content += b"\n"
        blank_line = unit.options.get("blankLineBeforeEnd", False)
        if not isinstance(blank_line, bool):
            raise ContentPortError(f"{unit.key}: blankLineBeforeEnd must be boolean")
        if blank_line:
            content += b"\n"
        content += b"#endif /* " + marker_comment + end + b" */\n"
        return (OwnedOutput("section", unit.path, content, name=name),)
    if marker_style != "comment":
        raise ContentPortError(f"{unit.key}: unknown section marker style")
    comment = unit.options.get("comment", "//")
    if not isinstance(comment, str) or "\n" in comment or "\r" in comment:
        raise ContentPortError(f"{unit.key}: invalid section comment prefix")
    prefix = (comment + " ").encode() if comment else b""
    content = prefix + begin + b"\n"
    content += body
    if body and not body.endswith(b"\n"):
        content += b"\n"
    content += prefix + end + b"\n"
    return (OwnedOutput("section", unit.path, content, name=name),)


def render_trainer_script(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    if not isinstance(unit.value, dict) or set(unit.value) != {"map", "events"}:
        raise ContentPortError(f"{unit.key}: trainer-script requires map and events")
    map_name = unit.value["map"]
    events = unit.value["events"]
    if not isinstance(map_name, str) or not isinstance(events, (list, tuple)):
        raise ContentPortError(f"{unit.key}: invalid trainer-script payload")
    blocks = [f"{map_name}_MapScripts::\n\t.byte 0"]
    for event in events:
        if not isinstance(event, dict) or set(event) != {
            "script",
            "instructions",
            "texts",
        }:
            raise ContentPortError(f"{unit.key}: invalid selected trainer event")
        script_name = _trainer_string(
            event["script"], _SCRIPT_TOKEN_RE, f"{unit.key}/script"
        )
        lines = [f"{script_name}::"]
        for instruction in event["instructions"]:
            command = _trainer_string(
                instruction["command"], _SCRIPT_TOKEN_RE, f"{unit.key}/command"
            )
            operands = tuple(
                _trainer_string(value, _SCRIPT_TOKEN_RE, f"{unit.key}/operand")
                for value in instruction["operands"]
            )
            # Expansion ASM convention uses comma+space; keep this renderer
            # independent of the donor's reviewed missing-separator adaptation.
            suffix = f" {', '.join(operands)}" if operands else ""
            lines.append(f"\t{command}{suffix}")
        blocks.append("\n".join(lines))
        for text_record in event["texts"]:
            label = _trainer_string(
                text_record["label"], _SCRIPT_TOKEN_RE, f"{unit.key}/text-label"
            )
            fragments = tuple(
                _trainer_string(
                    fragment, _TEXT_FRAGMENT_RE, f"{unit.key}/text-fragment"
                )
                for fragment in text_record["fragments"]
            )
            text_lines = [f"{label}:"]
            text_lines.extend(f"\t.string {fragment}" for fragment in fragments)
            blocks.append("\n".join(text_lines))
    return (OwnedOutput("file", unit.path, ("\n\n".join(blocks) + "\n").encode()),)


def render_trainer_party(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    if not isinstance(unit.value, (list, tuple)) or not unit.value:
        raise ContentPortError(f"{unit.key}: trainer-party requires trainer records")
    blocks: list[str] = []
    for trainer in unit.value:
        if not isinstance(trainer, dict):
            raise ContentPortError(f"{unit.key}: invalid trainer-party record")
        target = _trainer_string(
            trainer.get("target"), _TRAINER_ID_RE, f"{unit.key}/target"
        )
        display = {
            field: _trainer_string(
                trainer.get(field), _TRAINER_DISPLAY_RE, f"{unit.key}/{field}"
            )
            for field in ("name", "class", "pic", "gender", "music")
        }
        ai = tuple(
            _trainer_string(value, _TRAINER_DISPLAY_RE, f"{unit.key}/ai")
            for value in trainer.get("ai", ())
        )
        if not ai:
            raise ContentPortError(f"{unit.key}/ai: trainer AI must not be empty")
        lines = [
            f"=== {target} ===",
            f"Name: {display['name']}",
            f"Class: {display['class']}",
            f"Pic: {display['pic']}",
            f"Gender: {display['gender']}",
            f"Music: {display['music']}",
            f"Double Battle: {'Yes' if trainer['double'] else 'No'}",
            f"AI: {' / '.join(ai)}",
        ]
        for member in trainer["party"]:
            species = _trainer_string(
                member.get("species"), _TRAINER_SPECIES_RE, f"{unit.key}/species"
            )
            lines.extend(
                (
                    "",
                    species,
                    f"Level: {member['level']}",
                    f"IVs: {member['iv']} HP / {member['iv']} Atk / "
                    f"{member['iv']} Def / {member['iv']} SpA / "
                    f"{member['iv']} SpD / {member['iv']} Spe",
                )
            )
        blocks.append("\n".join(lines))
    body = "\n\n".join(blocks).encode()
    name = unit.name or unit.key
    begin, end = section_markers(context.port, name)
    content = b"#if 1 /* " + begin + b" */\n" + body + b"\n"
    content += b"#endif /* " + end + b" */\n"
    return (OwnedOutput("section", unit.path, content, name=name),)


RENDERERS: Mapping[str, Renderer] = MappingProxyType(
    {
        "map-json": render_map_json,
        "layout-registry": render_layout_registry,
        "map-group-registry": render_map_group_registry,
        "region-section-registry": render_region_section_registry,
        "tileset-assets": render_tileset_assets,
        "encounter-registry": render_encounter_registry,
        "generated-section": render_generated_section,
        "trainer-script": render_trainer_script,
        "trainer-party": render_trainer_party,
    }
)


def render_unit(context: RenderContext, unit: RenderUnit) -> tuple[OwnedOutput, ...]:
    if unit.path in context.hand_owned_paths:
        raise ContentPortError(
            f"{unit.key}: refuses to overwrite hand-owned path {unit.path}"
        )
    if unit.renderer in {"generated-section", "trainer-party"}:
        section = (unit.path, unit.name or unit.key)
        if section in context.hand_owned_sections:
            raise ContentPortError(
                f"{unit.key}: refuses to overwrite hand-owned section {section[1]} in {section[0]}"
            )
    try:
        renderer = RENDERERS[unit.renderer]
    except KeyError as error:
        raise ContentPortError(
            f"{unit.key}: unknown expansion renderer {unit.renderer}"
        ) from error
    outputs = tuple(renderer(context, unit))
    if not outputs:
        raise ContentPortError(f"{unit.key}: renderer emitted no output")
    for output in outputs:
        if output.path in context.hand_owned_paths:
            raise ContentPortError(
                f"{unit.key}: refuses to overwrite hand-owned path {output.path}"
            )
        output.ownership_unit()
    return outputs


def render_units(
    context: RenderContext, units: Iterable[RenderUnit]
) -> tuple[OwnershipManifest, Mapping[tuple[str, ...], object]]:
    """Render a sorted unit set and return its exact manifest plus payloads."""

    outputs: list[OwnedOutput] = []
    seen_keys: set[str] = set()
    for unit in sorted(units, key=lambda item: item.key):
        if unit.key in seen_keys:
            raise ContentPortError(f"duplicate render unit {unit.key}")
        seen_keys.add(unit.key)
        outputs.extend(render_unit(context, unit))
    ownership_units = tuple(output.ownership_unit() for output in outputs)
    manifest = OwnershipManifest(context.port, ownership_units)
    by_identity: dict[tuple[str, ...], object] = {}
    for output in outputs:
        identity = output.ownership_unit().identity
        if identity in by_identity:
            raise ContentPortError(f"duplicate rendered output {identity}")
        by_identity[identity] = output.content
    return manifest, MappingProxyType(by_identity)
