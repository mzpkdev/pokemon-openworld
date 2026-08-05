from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ManifestMap:
    name: str
    group: int
    number: int
    region: str

    @property
    def map_id(self) -> tuple[int, int]:
        return self.group, self.number


@dataclass(frozen=True)
class RepresentativeMap:
    name: str
    seed_vars: tuple[tuple[int, int], ...]


def foundation_manifest_path() -> Path:
    return Path(
        os.environ.get(
            "FOUNDATION_MANIFEST",
            "build/generated/allregions/current/foundation-manifest.json",
        )
    )


def _required(entry: dict[str, Any], key: str, index: int) -> Any:
    try:
        return entry[key]
    except KeyError as error:
        raise ValueError(
            f"manifest maps[{index}] is missing required field {key!r}"
        ) from error


def _required_with_aliases(
    entry: dict[str, Any], key: str, aliases: tuple[str, ...], index: int
) -> Any:
    present = [candidate for candidate in (key, *aliases) if candidate in entry]
    if not present:
        raise ValueError(f"manifest maps[{index}] is missing required field {key!r}")
    value = entry[present[0]]
    if any(entry[candidate] != value for candidate in present[1:]):
        raise ValueError(
            f"manifest maps[{index}] has conflicting values for {key!r}: {present}"
        )
    return value


def load_manifest_maps(path: Path) -> list[ManifestMap]:
    try:
        document = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Foundation manifest does not exist: {path}; build the all-regions "
            "debug ROM and its foundation manifest first"
        ) from error
    if not isinstance(document, dict):
        raise ValueError("foundation manifest root must be an object")
    if document.get("schemaVersion") not in (1, 2):
        raise ValueError(
            "foundation manifest schemaVersion must be 1 or 2, got "
            f"{document.get('schemaVersion')!r}"
        )
    entries = document.get("maps")
    if not isinstance(entries, list) or not entries:
        raise ValueError("foundation manifest maps must be a non-empty array")

    maps: list[ManifestMap] = []
    seen_ids: set[tuple[int, int]] = set()
    seen_names: set[str] = set()
    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"manifest maps[{index}] must be an object")
        name = _required(raw_entry, "name", index)
        group = _required_with_aliases(raw_entry, "group", ("mapGroup",), index)
        number = _required_with_aliases(
            raw_entry, "number", ("mapNum", "mapNumber"), index
        )
        region = _required(raw_entry, "region", index)
        if not isinstance(name, str) or not name:
            raise ValueError(f"manifest maps[{index}].name must be a non-empty string")
        if not isinstance(region, str) or not region:
            raise ValueError(
                f"manifest maps[{index}].region must be a non-empty string"
            )
        if (
            isinstance(group, bool)
            or not isinstance(group, int)
            or not 0 <= group <= 0xFFFF
        ):
            raise ValueError(f"manifest maps[{index}].group must be a u16 integer")
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or not 0 <= number <= 0xFFFF
        ):
            raise ValueError(f"manifest maps[{index}].number must be a u16 integer")
        map_id = (group, number)
        if name in seen_names:
            raise ValueError(f"foundation manifest repeats map name {name!r}")
        if map_id in seen_ids:
            raise ValueError(f"foundation manifest repeats map id {map_id}")
        seen_names.add(name)
        seen_ids.add(map_id)
        maps.append(ManifestMap(name=name, group=group, number=number, region=region))
    return maps


def load_representatives(path: Path) -> list[RepresentativeMap]:
    document = json.loads(path.read_text())
    if document.get("schemaVersion") != 1:
        raise ValueError("representative map schemaVersion must be 1")
    entries = document.get("representatives")
    if not isinstance(entries, list) or not entries:
        raise ValueError("representatives must be a non-empty array")
    representatives: list[RepresentativeMap] = []
    regions: set[str] = set()
    kinds: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise ValueError(f"representatives[{index}].name must be a string")
        if not isinstance(entry.get("region"), str):
            raise ValueError(f"representatives[{index}].region must be a string")
        if not isinstance(entry.get("kind"), str):
            raise ValueError(f"representatives[{index}].kind must be a string")
        seed_vars = entry.get("seedVars", [])
        if not isinstance(seed_vars, list):
            raise ValueError(f"representatives[{index}].seedVars must be an array")
        parsed_vars: list[tuple[int, int]] = []
        for var_index, seed_var in enumerate(seed_vars):
            if not isinstance(seed_var, dict):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}] must be an object"
                )
            var_id = seed_var.get("id")
            value = seed_var.get("value")
            if (
                isinstance(var_id, bool)
                or not isinstance(var_id, int)
                or not 0x4000 <= var_id <= 0x40FF
            ):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}].id "
                    "must be a saved variable id"
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 0xFFFF
            ):
                raise ValueError(
                    f"representatives[{index}].seedVars[{var_index}].value must be u16"
                )
            parsed_vars.append((var_id, value))
        representatives.append(RepresentativeMap(entry["name"], tuple(parsed_vars)))
        regions.add(entry["region"])
        kinds.add(entry["kind"])
    names = [representative.name for representative in representatives]
    if len(names) != len(set(names)):
        raise ValueError("representative map names must be unique")
    required_regions = {"hoenn", "kanto", "sevii123", "sevii45", "sevii67"}
    if not required_regions <= regions:
        raise ValueError(
            "representatives are missing required region classes: "
            f"{sorted(required_regions - regions)}"
        )
    required_kinds = {"exterior", "interior", "cave"}
    if not required_kinds <= kinds:
        raise ValueError(
            "representatives are missing required map kinds: "
            f"{sorted(required_kinds - kinds)}"
        )
    return representatives
