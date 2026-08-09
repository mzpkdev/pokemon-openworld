"""Strict access to the sole numeric content placement authority."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import ContentPortError
from .model import MapAllocation


def _object(value: object, pointer: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    return value


def _array(value: object, pointer: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise ContentPortError(f"{pointer}: expected an array")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], pointer: str) -> None:
    unknown = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")


def _string(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def _integer(value: object, pointer: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentPortError(f"{pointer}: expected a non-negative integer")
    return value


def _unique(values: Sequence[object], pointer: str) -> None:
    if len(values) != len(set(values)):
        raise ContentPortError(f"{pointer}: duplicate allocation")


@dataclass(frozen=True)
class AllocationIndex:
    maps: Mapping[str, MapAllocation]
    layouts: Mapping[str, int]
    groups: Mapping[str, int]
    sections: Mapping[str, int]

    def map_slot(self, name: str) -> tuple[str, int, int]:
        return self.map_allocation(name).map_slot

    def map_allocation(self, name: str) -> MapAllocation:
        try:
            return self.maps[name]
        except KeyError as error:
            raise ContentPortError(f"allocation lock has no map {name}") from error

    def layout_slot(self, name: str) -> int:
        try:
            return self.layouts[name]
        except KeyError as error:
            raise ContentPortError(f"allocation lock has no layout {name}") from error

    def group_slot(self, name: str) -> int:
        try:
            return self.groups[name]
        except KeyError as error:
            raise ContentPortError(f"allocation lock has no group {name}") from error

    def section_slot(self, name: str) -> int:
        try:
            return self.sections[name]
        except KeyError as error:
            raise ContentPortError(f"allocation lock has no section {name}") from error


def load_allocation_index(document: object, pointer: str = "$") -> AllocationIndex:
    root = _object(document, pointer)
    _exact_keys(
        root, {"schemaVersion", "groups", "sections", "layouts", "maps"}, pointer
    )
    if root["schemaVersion"] != 1:
        raise ContentPortError(
            f"{pointer}.schemaVersion: unsupported allocation schema"
        )

    simple_specs = {
        "groups": ("name", "targetId"),
        "sections": ("name", "targetId"),
        "layouts": ("id", "targetIndex"),
    }
    registries: dict[str, dict[str, int]] = {}
    for label, (name_key, slot_key) in simple_specs.items():
        records = _array(root[label], f"{pointer}.{label}")
        parsed: dict[str, int] = {}
        slots: list[int] = []
        for index, raw in enumerate(records):
            item_pointer = f"{pointer}.{label}[{index}]"
            item = _object(raw, item_pointer)
            _exact_keys(item, {name_key, slot_key}, item_pointer)
            name = _string(item[name_key], f"{item_pointer}.{name_key}")
            slot = _integer(item[slot_key], f"{item_pointer}.{slot_key}")
            if name in parsed:
                raise ContentPortError(
                    f"{item_pointer}.{name_key}: duplicate allocation {name}"
                )
            parsed[name] = slot
            slots.append(slot)
        _unique(slots, f"{pointer}.{label}.{slot_key}")
        registries[label] = parsed

    map_keys = {
        "name",
        "id",
        "batch",
        "materialization",
        "targetGroup",
        "targetGroupId",
        "targetMember",
        "layout",
        "targetLayoutIndex",
        "section",
        "targetSection",
    }
    maps: dict[str, MapAllocation] = {}
    map_ids: list[str] = []
    map_slots: list[tuple[str, int]] = []
    records = _array(root["maps"], f"{pointer}.maps")
    for index, raw in enumerate(records):
        item_pointer = f"{pointer}.maps[{index}]"
        item = _object(raw, item_pointer)
        _exact_keys(item, map_keys, item_pointer)
        strings = {
            key: _string(item[key], f"{item_pointer}.{key}")
            for key in (
                "name",
                "id",
                "batch",
                "materialization",
                "targetGroup",
                "layout",
                "section",
            )
        }
        if strings["materialization"] not in {"preserve", "residency"}:
            raise ContentPortError(
                f"{item_pointer}.materialization: unknown ownership mode"
            )
        numbers = {
            key: _integer(item[key], f"{item_pointer}.{key}")
            for key in (
                "targetGroupId",
                "targetMember",
                "targetLayoutIndex",
                "targetSection",
            )
        }
        name = strings["name"]
        if name in maps:
            raise ContentPortError(f"{item_pointer}.name: duplicate allocation {name}")
        group = strings["targetGroup"]
        layout = strings["layout"]
        section = strings["section"]
        if registries["groups"].get(group) != numbers["targetGroupId"]:
            raise ContentPortError(
                f"{item_pointer}.targetGroupId: group allocation mismatch"
            )
        if registries["layouts"].get(layout) != numbers["targetLayoutIndex"]:
            raise ContentPortError(
                f"{item_pointer}.targetLayoutIndex: layout allocation mismatch"
            )
        if registries["sections"].get(section) != numbers["targetSection"]:
            raise ContentPortError(
                f"{item_pointer}.targetSection: section allocation mismatch"
            )
        maps[name] = MapAllocation(
            name=name,
            map_id=strings["id"],
            batch=strings["batch"],
            materialization=strings["materialization"],
            target_group=group,
            target_group_id=numbers["targetGroupId"],
            target_member=numbers["targetMember"],
            layout=layout,
            target_layout_index=numbers["targetLayoutIndex"],
            section=section,
            target_section=numbers["targetSection"],
        )
        map_ids.append(strings["id"])
        map_slots.append((group, numbers["targetMember"]))
    _unique(map_ids, f"{pointer}.maps.id")
    _unique(map_slots, f"{pointer}.maps.targetGroup/targetMember")
    for group in registries["groups"]:
        members = sorted(
            member for slot_group, member in map_slots if slot_group == group
        )
        if members and members != list(range(len(members))):
            raise ContentPortError(
                f"{pointer}.maps: non-contiguous members for group {group}"
            )

    return AllocationIndex(
        MappingProxyType(maps),
        MappingProxyType(registries["layouts"]),
        MappingProxyType(registries["groups"]),
        MappingProxyType(registries["sections"]),
    )
