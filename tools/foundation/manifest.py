#!/usr/bin/env python3
"""Validate the deterministic foundation manifest emitted by mapjson."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


EXPECTED_COUNTS = {
    "groups": 75,
    "groupedMaps": 935,
    "reviewedMaps": 939,
    "layouts": 785,
    "regions": {"REGION_HOENN": 518, "REGION_KANTO": 421},
}
EXPECTED_PRODUCT = {
    "gameVersion": "EMERALD",
    "mapVersion": "allregions",
    "allRegions": 1,
    "fileName": "pokemon-openworld",
}
EXPECTED_ABIS = {
    "mapHeader": {
        "size": 32,
        "alignment": 4,
        "regionMapSectionIdOffset": 20,
        "battleTypeOffset": 28,
        "paddingOffset": 29,
        "paddingSize": 3,
    }
}


class ManifestError(ValueError):
    """The generated registry does not meet the product contract."""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ManifestError(f"cannot read manifest {path}: {error}") from error
    if not isinstance(data, dict):
        raise ManifestError("manifest root must be an object")
    validate_manifest(data)
    return data


def _unique(records: list[dict[str, Any]], field: str, owner: str) -> None:
    values = [record.get(field) for record in records]
    if None in values or len(values) != len(set(values)):
        raise ManifestError(f"{owner} must have unique non-null {field} values")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != 2:
        raise ManifestError("unsupported foundation manifest schema")
    if manifest.get("product") != EXPECTED_PRODUCT:
        raise ManifestError(f"wrong product identity: {manifest.get('product')!r}")
    if manifest.get("counts") != EXPECTED_COUNTS:
        raise ManifestError(f"wrong registry counts: {manifest.get('counts')!r}")
    if manifest.get("abis") != EXPECTED_ABIS:
        raise ManifestError(f"wrong ABI contracts: {manifest.get('abis')!r}")

    groups = manifest.get("groups")
    maps = manifest.get("maps")
    layouts = manifest.get("layouts")
    tilesets = manifest.get("tilesets")
    exclusions = manifest.get("exclusions")
    symbols = manifest.get("symbols")
    if not all(
        isinstance(records, list)
        for records in (groups, maps, layouts, tilesets, exclusions, symbols)
    ):
        raise ManifestError(
            "groups, maps, layouts, tilesets, exclusions, and symbols must be arrays"
        )
    if (len(groups), len(maps), len(layouts), len(exclusions)) != (75, 935, 785, 4):
        raise ManifestError("manifest arrays disagree with their count sentinels")

    _unique(groups, "name", "groups")
    _unique(maps, "name", "maps")
    _unique(maps, "id", "maps")
    _unique(layouts, "id", "layouts")
    _unique(layouts, "name", "layouts")
    _unique(tilesets, "name", "tilesets")
    _unique(exclusions, "name", "exclusions")
    _unique(symbols, "name", "symbols")

    if sorted(group["number"] for group in groups) != list(range(75)):
        raise ManifestError("group numbers must be contiguous from zero")
    group_counts = {group["number"]: group["mapCount"] for group in groups}
    if any(count <= 0 for count in group_counts.values()):
        raise ManifestError("every product group must be non-null")
    seen_slots = {(entry["group"], entry["number"]) for entry in maps}
    expected_slots = {
        (group_number, map_number)
        for group_number, count in group_counts.items()
        for map_number in range(count)
    }
    if seen_slots != expected_slots:
        raise ManifestError("map slots are missing, duplicated, or outside their group")
    if sorted(layout["number"] for layout in layouts) != list(range(1, 786)):
        raise ManifestError("layout slots must be contiguous from one")
    layout_ids = {layout["id"]: layout for layout in layouts}
    tileset_names = {tileset["name"] for tileset in tilesets}
    for entry in maps:
        layout = layout_ids.get(entry.get("layoutId"))
        if layout is None or entry.get("mapLayout") != layout["name"]:
            raise ManifestError(
                f"map {entry.get('name')} has an invalid layout dependency"
            )
        if not entry.get("mapEvents") or not entry.get("mapScripts"):
            raise ManifestError(f"map {entry.get('name')} lacks header dependencies")
        if (
            not isinstance(entry.get("regionMapSection"), str)
            or not isinstance(entry.get("regionMapSectionValue"), int)
            or not 0 <= entry["regionMapSectionValue"] < 0xFFFF
            or not isinstance(entry.get("battleType"), int)
            or not 0 <= entry["battleType"] <= 0xFF
        ):
            raise ManifestError(f"map {entry.get('name')} lacks scalar header metadata")
    for layout in layouts:
        if layout.get("width", 0) <= 0 or layout.get("height", 0) <= 0:
            raise ManifestError(f"layout {layout['name']} has invalid dimensions")
        if not layout.get("border") or not layout.get("map"):
            raise ManifestError(f"layout {layout['name']} lacks data dependencies")
        if layout.get("primaryTileset") not in tileset_names:
            raise ManifestError(
                f"layout {layout['name']} has an invalid primary tileset"
            )
        secondary = layout.get("secondaryTileset")
        if secondary is not None and secondary not in tileset_names:
            raise ManifestError(
                f"layout {layout['name']} has an invalid secondary tileset"
            )
    for tileset in tilesets:
        if any(
            not tileset.get(field)
            for field in ("tiles", "palettes", "metatiles", "metatileAttributes")
        ):
            raise ManifestError(f"tileset {tileset['name']} lacks data dependencies")
        if (tileset.get("callback") is None) != bool(tileset.get("allowNullCallback")):
            raise ManifestError(
                f"tileset {tileset['name']} has inconsistent callback policy"
            )
    if any(not symbol["name"] or symbol.get("kind") != "rom" for symbol in symbols):
        raise ManifestError("every required symbol must name a ROM resident object")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
