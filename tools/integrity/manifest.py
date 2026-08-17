#!/usr/bin/env python3
"""Validate the deterministic integrity manifest emitted by mapjson."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).parents[2]
JOHTO_PORT_ROOT = ROOT / "tools/content_port/ports/johto"
JOHTO_PORT = json.loads((JOHTO_PORT_ROOT / "port.json").read_text(encoding="utf-8"))
JOHTO_ADAPTATIONS = json.loads(
    (JOHTO_PORT_ROOT / JOHTO_PORT["adaptations"]).read_text(encoding="utf-8")
)
JOHTO_LOCK = json.loads(
    (JOHTO_PORT_ROOT / JOHTO_PORT["allocationLock"]).read_text(encoding="utf-8")
)
JOHTO_ANIMATIONS = json.loads(
    (JOHTO_PORT_ROOT / JOHTO_PORT["animationPolicy"]).read_text(encoding="utf-8")
)
EXPECTED_ANIMATION_CALLBACKS = {
    f"gTileset_{item['tileset']}": item["callback"]
    for item in JOHTO_ANIMATIONS["schedules"]
}


def group_content_region(group_name: Any) -> str | None:
    """Return the content origin encoded by the product's map-group namespace."""
    if not isinstance(group_name, str) or not group_name.startswith("gMapGroup_"):
        return None
    if group_name.endswith("_Frlg"):
        return "REGION_KANTO"
    if group_name in {item["name"] for item in JOHTO_LOCK["groups"]}:
        return "REGION_JOHTO"
    return "REGION_HOENN"


def _reviewed_cross_geography_maps() -> dict[str, str]:
    """Bind map geography exceptions to allocation and authored gateway policy."""
    allocated_groups = {
        item["name"]: item["targetGroup"] for item in JOHTO_LOCK["maps"]
    }
    claimed_regions: dict[str, str] = {}
    valid_regions = {"REGION_KANTO", "REGION_JOHTO", "REGION_HOENN"}
    for gateway in JOHTO_ADAPTATIONS["worldPolicy"]["scriptWarps"]:
        for map_field, region_field in (
            ("source", "sourceRegion"),
            ("destination", "targetRegion"),
        ):
            map_name = gateway.get(map_field)
            region = gateway.get(region_field)
            if map_name not in allocated_groups or region not in valid_regions:
                raise RuntimeError("integrity script-warp geography authority drift")
            previous = claimed_regions.setdefault(map_name, region)
            if previous != region:
                raise RuntimeError(
                    f"integrity script-warp geography conflict for {map_name}"
                )
    return {
        map_name: region
        for map_name, region in claimed_regions.items()
        if region != group_content_region(allocated_groups[map_name])
    }


def _validate_final_johto_source_contract() -> None:
    expected = JOHTO_PORT["expectedInventory"]
    actual = {
        "maps": len(JOHTO_LOCK["maps"]),
        "layouts": len(JOHTO_LOCK["layouts"]),
        "groups": len(JOHTO_LOCK["groups"]),
        "sections": len(JOHTO_LOCK["sections"]),
        "tilesets": expected["tilesets"]["count"],
    }
    expected_counts = {name: record["count"] for name, record in expected.items()}
    if actual != expected_counts:
        raise RuntimeError(f"integrity final Johto counts drift: {actual!r}")
    map_names = {item["name"] for item in JOHTO_LOCK["maps"]}
    fallback_maps = JOHTO_ADAPTATIONS["contentFallback"]["maps"]
    if (
        len(fallback_maps) != len(set(fallback_maps))
        or not set(fallback_maps) <= map_names
    ):
        raise RuntimeError("integrity Johto fallback allowlist drift")
    if [item["targetId"] for item in JOHTO_LOCK["groups"]] != list(
        range(75, 75 + actual["groups"])
    ):
        raise RuntimeError("integrity Johto group allocation drift")
    if [item["targetId"] for item in JOHTO_LOCK["sections"]] != list(
        range(209, 209 + actual["sections"])
    ):
        raise RuntimeError("integrity Johto section allocation drift")
    if [item["targetIndex"] for item in JOHTO_LOCK["layouts"]] != list(
        range(785, 785 + actual["layouts"])
    ):
        raise RuntimeError("integrity Johto layout allocation drift")


_validate_final_johto_source_contract()
JOHTO_FORMAT_CLOSURE_MAPS = list(JOHTO_LOCK["maps"])
JOHTO_FORMAT_CLOSURE_LAYOUTS = list(JOHTO_LOCK["layouts"])
ACTIVE_JOHTO_GROUPS = {item["name"] for item in JOHTO_LOCK["groups"]}
REVIEWED_CROSS_GEOGRAPHY_MAPS = _reviewed_cross_geography_maps()


def expected_map_geography(map_name: Any, group_name: Any) -> str | None:
    """Return the reviewed geographic region for a map in its product group."""
    group_region = group_content_region(group_name)
    if group_region is None:
        return None
    return REVIEWED_CROSS_GEOGRAPHY_MAPS.get(map_name, group_region)


INACTIVE_JOHTO_GROUPS: dict[int, str] = {}
ACTIVE_JOHTO_SECTIONS = {item["targetSection"] for item in JOHTO_FORMAT_CLOSURE_MAPS}
BASE_GROUPS = 75
BASE_GROUPED_MAPS = 935
BASE_REVIEWED_MAPS = 939
BASE_LAYOUTS = 785
BASE_MAP_SECTIONS = 209
EXPECTED_GROUPS = BASE_GROUPS + len(ACTIVE_JOHTO_GROUPS)
EXPECTED_GROUPED_MAPS = BASE_GROUPED_MAPS + len(JOHTO_FORMAT_CLOSURE_MAPS)
EXPECTED_REVIEWED_MAPS = BASE_REVIEWED_MAPS + len(JOHTO_FORMAT_CLOSURE_MAPS)
EXPECTED_LAYOUTS = BASE_LAYOUTS + len(JOHTO_FORMAT_CLOSURE_LAYOUTS)
EXPECTED_MAP_SECTIONS = BASE_MAP_SECTIONS + len(ACTIVE_JOHTO_SECTIONS)
EXPECTED_COUNTS = {
    "groups": EXPECTED_GROUPS,
    "groupedMaps": EXPECTED_GROUPED_MAPS,
    "reviewedMaps": EXPECTED_REVIEWED_MAPS,
    "layouts": EXPECTED_LAYOUTS,
    "regions": {
        "REGION_HOENN": 518,
        "REGION_KANTO": 422,
        "REGION_JOHTO": 253,
    },
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
    },
    "mapLayout": {
        "size": 28,
        "alignment": 4,
        "widthOffset": 0,
        "heightOffset": 4,
        "borderOffset": 8,
        "mapOffset": 12,
        "primaryTilesetOffset": 16,
        "secondaryTilesetOffset": 20,
        "formatOffset": 24,
        "borderWidthOffset": 25,
        "borderHeightOffset": 26,
        "paddingOffset": 27,
    },
    "tileset": {
        "size": 24,
        "alignment": 4,
        "flagsOffset": 1,
        "tilesOffset": 4,
        "palettesOffset": 8,
        "metatilesOffset": 12,
        "metatileAttributesOffset": 16,
        "callbackOffset": 20,
    },
    "mapSectionRegistry": {
        "size": 24,
        "alignment": 4,
        "metadataOffset": 0,
        "sectionToSavedLocationOffset": 4,
        "sectionToMetLocationOffset": 8,
        "savedLocationToSectionOffset": 12,
        "metLocationToSectionOffset": 16,
        "sectionCountOffset": 20,
    },
    "surfEdgeExit": {
        "size": 10,
        "alignment": 2,
        "sourceMapOffset": 0,
        "targetMapOffset": 2,
        "targetXOffset": 4,
        "targetYOffset": 6,
        "exitEdgeOffset": 8,
        "targetFacingOffset": 9,
    },
}

CARDINAL_VALUES = {"south": 1, "north": 2, "west": 3, "east": 4}
EDGE_EXIT_FIELDS = {
    "sourceName",
    "sourceId",
    "sourceGroup",
    "sourceNumber",
    "sourceMapValue",
    "exitEdge",
    "exitEdgeValue",
    "targetName",
    "targetId",
    "targetGroup",
    "targetNumber",
    "targetMapValue",
    "targetX",
    "targetY",
    "targetFacing",
    "targetFacingValue",
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


def _map_value(group: int, number: int) -> int:
    return number | (group << 8)


def _validate_edge_exits(
    edge_exits: Any,
    maps: list[dict[str, Any]],
    layouts: list[dict[str, Any]],
) -> None:
    if not isinstance(edge_exits, list):
        raise ManifestError("edgeExits must be an array")
    maps_by_name = {entry["name"]: entry for entry in maps}
    layouts_by_id = {entry["id"]: entry for entry in layouts}
    seen: set[tuple[int, int, int]] = set()
    order: list[tuple[int, int, int]] = []
    string_fields = {
        "sourceName",
        "sourceId",
        "exitEdge",
        "targetName",
        "targetId",
        "targetFacing",
    }
    int_fields = EDGE_EXIT_FIELDS - string_fields
    for index, entry in enumerate(edge_exits):
        if not isinstance(entry, dict) or set(entry) != EDGE_EXIT_FIELDS:
            raise ManifestError(f"edgeExits[{index}] has invalid fields")
        if any(type(entry[field]) is not str for field in string_fields) or any(
            type(entry[field]) is not int for field in int_fields
        ):
            raise ManifestError(f"edgeExits[{index}] has invalid field types")
        if entry["exitEdgeValue"] != CARDINAL_VALUES.get(entry["exitEdge"]):
            raise ManifestError(f"edgeExits[{index}] exit edge name/value disagree")
        if entry["targetFacingValue"] != CARDINAL_VALUES.get(entry["targetFacing"]):
            raise ManifestError(f"edgeExits[{index}] facing name/value disagree")
        for prefix in ("source", "target"):
            map_entry = maps_by_name.get(entry[f"{prefix}Name"])
            if map_entry is None:
                raise ManifestError(f"edgeExits[{index}] names unknown {prefix} map")
            identity = (
                map_entry.get("id"),
                map_entry.get("group"),
                map_entry.get("number"),
            )
            declared = (
                entry[f"{prefix}Id"],
                entry[f"{prefix}Group"],
                entry[f"{prefix}Number"],
            )
            if declared != identity or entry[f"{prefix}MapValue"] != _map_value(
                entry[f"{prefix}Group"], entry[f"{prefix}Number"]
            ):
                raise ManifestError(
                    f"edgeExits[{index}] {prefix} map identity disagrees"
                )
        target = maps_by_name[entry["targetName"]]
        layout = layouts_by_id.get(target.get("layoutId"))
        if layout is None or not (
            0 <= entry["targetX"] < layout["width"]
            and 0 <= entry["targetY"] < layout["height"]
        ):
            raise ManifestError(f"edgeExits[{index}] target is outside its layout")
        key = (
            entry["sourceGroup"],
            entry["sourceNumber"],
            entry["exitEdgeValue"],
        )
        if key in seen:
            raise ManifestError("edgeExits must have unique source edge values")
        seen.add(key)
        order.append(key)
    if order != sorted(order):
        raise ManifestError("edgeExits are not in canonical order")


def validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("schemaVersion") != 3:
        raise ManifestError("unsupported integrity manifest schema")
    if manifest.get("product") != EXPECTED_PRODUCT:
        raise ManifestError(f"wrong product identity: {manifest.get('product')!r}")
    counts = manifest.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != {*EXPECTED_COUNTS, "edgeExits"}
        or any(counts.get(name) != value for name, value in EXPECTED_COUNTS.items())
        or type(counts.get("edgeExits")) is not int
        or counts["edgeExits"] < 0
    ):
        raise ManifestError(f"wrong registry counts: {manifest.get('counts')!r}")
    if manifest.get("abis") != EXPECTED_ABIS:
        raise ManifestError(f"wrong ABI contracts: {manifest.get('abis')!r}")

    groups = manifest.get("groups")
    maps = manifest.get("maps")
    layouts = manifest.get("layouts")
    tilesets = manifest.get("tilesets")
    exclusions = manifest.get("exclusions")
    symbols = manifest.get("symbols")
    count_sentinels = manifest.get("countSentinels")
    codecs = manifest.get("codecs")
    section_metadata = manifest.get("mapSectionMetadata")
    edge_exits = manifest.get("edgeExits")
    if not all(
        isinstance(records, list)
        for records in (groups, maps, layouts, tilesets, exclusions, symbols)
    ):
        raise ManifestError(
            "groups, maps, layouts, tilesets, exclusions, and symbols must be arrays"
        )
    if not isinstance(count_sentinels, dict) or not isinstance(codecs, dict):
        raise ManifestError("countSentinels and codecs must be objects")
    if (
        not isinstance(section_metadata, list)
        or len(section_metadata) != EXPECTED_MAP_SECTIONS
    ):
        raise ManifestError(
            f"mapSectionMetadata must contain all {EXPECTED_MAP_SECTIONS} tuples"
        )
    if (len(groups), len(maps), len(layouts), len(exclusions)) != (
        EXPECTED_GROUPS,
        EXPECTED_GROUPED_MAPS,
        EXPECTED_LAYOUTS,
        4,
    ):
        raise ManifestError("manifest arrays disagree with their count sentinels")
    if not isinstance(edge_exits, list) or len(edge_exits) != counts["edgeExits"]:
        raise ManifestError("edgeExits disagree with their count sentinel")

    _unique(groups, "name", "groups")
    _unique(maps, "name", "maps")
    _unique(maps, "id", "maps")
    _unique(layouts, "id", "layouts")
    _unique(layouts, "name", "layouts")
    _unique(tilesets, "name", "tilesets")
    _unique(exclusions, "name", "exclusions")
    _unique(symbols, "name", "symbols")

    if sorted(group["number"] for group in groups) != list(range(EXPECTED_GROUPS)):
        raise ManifestError("group numbers must be contiguous from zero")
    group_counts = {group["number"]: group["mapCount"] for group in groups}
    group_names = {group["number"]: group.get("name") for group in groups}
    group_regions = {
        group["number"]: group_content_region(group.get("name")) for group in groups
    }
    if any(region is None for region in group_regions.values()):
        raise ManifestError("groups must use the product map-group namespace")
    empty_groups = {
        group["number"]: group["name"] for group in groups if group["mapCount"] == 0
    }
    if (
        any(count < 0 for count in group_counts.values())
        or empty_groups != INACTIVE_JOHTO_GROUPS
    ):
        raise ManifestError("every product group must be non-null")
    seen_slots = {(entry["group"], entry["number"]) for entry in maps}
    expected_slots = {
        (group_number, map_number)
        for group_number, count in group_counts.items()
        for map_number in range(count)
    }
    if seen_slots != expected_slots:
        raise ManifestError("map slots are missing, duplicated, or outside their group")
    if sorted(layout["number"] for layout in layouts) != list(
        range(1, EXPECTED_LAYOUTS + 1)
    ):
        raise ManifestError("layout slots must be contiguous from one")
    expected_sentinels = {
        "groups": {
            "start": "gMapGroups",
            "end": "gMapGroupsEnd",
            "count": EXPECTED_GROUPS,
            "stride": 4,
        },
        "layouts": {
            "start": "gMapLayouts",
            "end": "gMapLayoutsEnd",
            "count": EXPECTED_LAYOUTS,
            "stride": 4,
        },
        "mapSections": {
            "registry": "gMapSectionRegistry",
            "count": EXPECTED_MAP_SECTIONS,
        },
        "edgeExits": {
            "registry": "gSurfEdgeExits",
            "countSymbol": "gSurfEdgeExitCount",
            "count": counts["edgeExits"],
            "stride": EXPECTED_ABIS["surfEdgeExit"]["size"],
        },
    }
    if count_sentinels != expected_sentinels:
        raise ManifestError(f"wrong linked count sentinels: {count_sentinels!r}")
    codec_lengths = {
        "sectionToSavedLocation": EXPECTED_MAP_SECTIONS,
        "sectionToMetLocation": EXPECTED_MAP_SECTIONS,
        "savedLocationToSection": 256,
        "metLocationToSection": 256,
    }
    for name, length in codec_lengths.items():
        values = codecs.get(name)
        if (
            not isinstance(values, list)
            or len(values) != length
            or any(
                not isinstance(value, int) or not -1 <= value < 0xFFFF
                for value in values
            )
        ):
            raise ManifestError(f"codec {name} lacks {length} valid entries")
    _unique(section_metadata, "id", "mapSectionMetadata")
    if [entry.get("value") for entry in section_metadata] != list(
        range(EXPECTED_MAP_SECTIONS)
    ):
        raise ManifestError("mapSectionMetadata values must be ordered and contiguous")
    region_values = {"REGION_KANTO": 1, "REGION_JOHTO": 2, "REGION_HOENN": 3}
    kind_values = {"geographic": 0, "special": 1, "reserved": 2}
    presentation_values = {
        "REGION_MAP_HOENN": 0,
        "REGION_MAP_KANTO": 1,
        "REGION_MAP_SEVII123": 2,
        "REGION_MAP_SEVII45": 3,
        "REGION_MAP_SEVII67": 4,
    }
    for entry in section_metadata:
        if (
            entry.get("regionValue") != region_values.get(entry.get("region"))
            or entry.get("kindValue") != kind_values.get(entry.get("kind"))
            or entry.get("regionMapTypeValue")
            != presentation_values.get(entry.get("regionMapType"))
        ):
            raise ManifestError(
                f"map-section metadata tuple {entry.get('id')} has inconsistent encodings"
            )
    sections_by_id = {entry["id"]: entry for entry in section_metadata}
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
        section = sections_by_id.get(entry["regionMapSection"])
        if section is None:
            raise ManifestError(
                f"map {entry.get('name')} names unknown map section "
                f"{entry['regionMapSection']!r}"
            )
        if entry["regionMapSectionValue"] != section["value"]:
            raise ManifestError(
                f"map {entry.get('name')} map-section name/value disagree: "
                f"{entry['regionMapSection']} is {section['value']}, "
                f"not {entry['regionMapSectionValue']}"
            )
        expected_region = expected_map_geography(
            entry.get("name"), group_names[entry["group"]]
        )
        if entry.get("region") != expected_region:
            raise ManifestError(
                f"map {entry.get('name')} region {entry.get('region')!r} disagrees "
                f"with group {entry['group']} content origin {expected_region!r}"
            )
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
        if tileset.get("attributeFormat") not in {
            "METATILE_ATTRIBUTES_EMERALD_U16",
            "METATILE_ATTRIBUTES_FRLG_U32",
        }:
            raise ManifestError(
                f"tileset {tileset['name']} lacks an exact attribute ABI"
            )
    tilesets_by_name = {tileset["name"]: tileset for tileset in tilesets}
    _validate_edge_exits(edge_exits, maps, layouts)
    for name, callback in EXPECTED_ANIMATION_CALLBACKS.items():
        tileset = tilesets_by_name.get(name)
        if tileset is None or tileset.get("callback") != callback:
            raise ManifestError(
                f"tileset {name} lacks reviewed animation callback {callback}"
            )
    if any(not symbol["name"] or symbol.get("kind") != "rom" for symbol in symbols):
        raise ManifestError("every required symbol must name a ROM resident object")
    symbol_names = {symbol["name"] for symbol in symbols}
    if not {"gSurfEdgeExits", "gSurfEdgeExitCount"} <= symbol_names:
        raise ManifestError("surf edge-exit symbols are not required ROM symbols")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    print(json.dumps(manifest["counts"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
