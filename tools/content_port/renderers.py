"""Deterministic expansion-native rendering primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from .errors import ContentPortError
from .ownership import (
    OwnershipManifest,
    OwnershipUnit,
    canonical_json,
    content_sha256,
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
        )


Renderer = Callable[[RenderContext, RenderUnit], Iterable[OwnedOutput]]


def _json_output(unit: RenderUnit) -> tuple[OwnedOutput, ...]:
    return (OwnedOutput("file", unit.path, canonical_json(unit.value)),)


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
            "registry-record", unit.path, unit.value, registry=registry, key=key
        ),
    )


def render_layout_registry(
    context: RenderContext, unit: RenderUnit
) -> tuple[OwnedOutput, ...]:
    del context
    return _record_output(unit, "layouts")


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
    begin, end = section_markers(context.port, name)
    marker_style = unit.options.get("markerStyle", "comment")
    if marker_style == "preprocessor":
        content = b"#if 1 /* " + begin + b" */\n"
        content += body
        if body and not body.endswith(b"\n"):
            content += b"\n"
        content += b"#endif /* " + end + b" */\n"
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


RENDERERS: Mapping[str, Renderer] = MappingProxyType(
    {
        "map-json": render_map_json,
        "layout-registry": render_layout_registry,
        "map-group-registry": render_map_group_registry,
        "region-section-registry": render_region_section_registry,
        "tileset-assets": render_tileset_assets,
        "encounter-registry": render_encounter_registry,
        "generated-section": render_generated_section,
    }
)


def render_unit(context: RenderContext, unit: RenderUnit) -> tuple[OwnedOutput, ...]:
    if unit.path in context.hand_owned_paths:
        raise ContentPortError(
            f"{unit.key}: refuses to overwrite hand-owned path {unit.path}"
        )
    if unit.renderer == "generated-section":
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
