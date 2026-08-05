#!/usr/bin/env python3
"""Inspect linked registry pointers, required symbols, memory use, and ROM headroom."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path
from typing import Any

try:
    from .manifest import ManifestError, group_content_region, load_manifest
except ImportError:  # Direct script execution.
    from manifest import ManifestError, group_content_region, load_manifest


ROM_BASE = 0x08000000
ROM_LIMIT = 32 * 1024 * 1024
CAPACITY_SCHEMA_VERSION = 2
CAPACITY_MEASUREMENT_KIND = "linked-symbol-range-attribution"
CAPACITY_SOURCE = ".references/PKMN-World"
CAPACITY_COMMIT = "d40affe26e58a20f445daad84af5e45be812e69f"
CAPACITY_PROVENANCE_MODE = "declared-commit+source-tree-digest"
CAPACITY_SOURCE_TREE_DIGEST = (
    "6bca91e491e7e8304f9268aa41a4c9d629d50baa6d3150fe45d55632b6f4f762"
)
CAPACITY_EVIDENCE_DIGEST = (
    "a656e089dc474bbe62a808957875ee577cd408519e3be4649f120ca9a06ea217"
)
CAPACITY_EVIDENCE_FILE_COUNT = 32_385
CAPACITY_JOHTO_LAYOUT_COUNT = 255
CAPACITY_JOHTO_MAP_COUNT = 254
CAPACITY_EVIDENCE_CATEGORIES = {
    "mapLayoutEventData": 895_864,
    "scriptsTextCallbacks": 281_213,
    "tilesetResourcesCallbacks": 701_120,
    "objectGraphics": 7_412,
    "johtoRuntime": 195_067,
    "trainerParties": 25_632,
    "trainerArt": 8_460,
    "trainerRecords": 37_596,
    "regionMapEntries": 464,
    "deduplicatedSymbolRanges": 1_709_643,
}
JOHTO_RESIDENT_FLOOR_BYTES = 1_747_703
TRAVEL_STORY_RESERVE_FLOOR_BYTES = 512 * 1024
REQUIRED_HEADROOM_FLOOR_BYTES = 2_708_917


class ValidationError(ValueError):
    """A linked product artifact violates the foundation contract."""


def load_capacity_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read capacity policy {path}: {error}") from error
    required = (
        "schemaVersion",
        "source",
        "commit",
        "provenanceMode",
        "measurementKind",
        "sourceTreeDigest",
        "evidenceDigest",
        "evidenceFileCount",
        "johtoLayoutCount",
        "johtoMapCount",
        "evidenceCategories",
        "johtoResidentBytes",
        "integrationMultiplier",
        "travelStoryReserveBytes",
        "requiredHeadroomBytes",
    )
    if not isinstance(policy, dict) or any(key not in policy for key in required):
        raise ValidationError("capacity policy is incomplete")
    categories = policy["evidenceCategories"]
    integer_fields = (
        "evidenceFileCount",
        "johtoLayoutCount",
        "johtoMapCount",
        "johtoResidentBytes",
        "travelStoryReserveBytes",
        "requiredHeadroomBytes",
    )
    if (
        policy["schemaVersion"] != CAPACITY_SCHEMA_VERSION
        or policy["source"] != CAPACITY_SOURCE
        or policy["measurementKind"] != CAPACITY_MEASUREMENT_KIND
        or policy["commit"] != CAPACITY_COMMIT
        or policy["provenanceMode"] != CAPACITY_PROVENANCE_MODE
        or policy["sourceTreeDigest"] != CAPACITY_SOURCE_TREE_DIGEST
        or policy["evidenceDigest"] != CAPACITY_EVIDENCE_DIGEST
        or policy["evidenceFileCount"] != CAPACITY_EVIDENCE_FILE_COUNT
        or policy["johtoLayoutCount"] != CAPACITY_JOHTO_LAYOUT_COUNT
        or policy["johtoMapCount"] != CAPACITY_JOHTO_MAP_COUNT
        or any(
            not isinstance(policy[field], int)
            or isinstance(policy[field], bool)
            or policy[field] <= 0
            for field in integer_fields
        )
        or not isinstance(categories, dict)
        or categories != CAPACITY_EVIDENCE_CATEGORIES
    ):
        raise ValidationError("capacity policy has invalid measurement provenance")
    johto = policy["johtoResidentBytes"]
    multiplier = policy["integrationMultiplier"]
    reserve = policy["travelStoryReserveBytes"]
    required_headroom = policy["requiredHeadroomBytes"]
    measured_johto = sum(
        categories[name]
        for name in (
            "deduplicatedSymbolRanges",
            "trainerRecords",
            "regionMapEntries",
        )
    )
    calculated = (johto * 125 + 99) // 100 + reserve
    if (
        multiplier != 1.25
        or johto != measured_johto
        or johto < JOHTO_RESIDENT_FLOOR_BYTES
        or reserve < TRAVEL_STORY_RESERVE_FLOOR_BYTES
        or calculated != required_headroom
        or required_headroom < REQUIRED_HEADROOM_FLOOR_BYTES
    ):
        raise ValidationError(
            "capacity policy has inconsistent measurement or collapses the reviewed floor"
        )
    return policy


def parse_symbols(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    try:
        lines = path.read_text(errors="strict").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read symbols {path}: {error}") from error
    for line in lines:
        fields = line.split()
        if len(fields) >= 4:
            try:
                address = int(fields[0], 16)
            except ValueError:
                continue
            symbols[fields[-1]] = address
    if not symbols:
        raise ValidationError(f"no symbols parsed from {path}")
    return symbols


def require_rom_address(name: str, value: int, rom_end: int) -> None:
    if not ROM_BASE <= value < rom_end:
        raise ValidationError(f"{name} points outside ROM: 0x{value:08x}")


def read_pointer(rom: bytes, address: int, owner: str) -> int:
    offset = address - ROM_BASE
    if offset < 0 or offset + 4 > len(rom):
        raise ValidationError(f"cannot read {owner} at 0x{address:08x}")
    return struct.unpack_from("<I", rom, offset)[0]


def read_i32(rom: bytes, address: int, owner: str) -> int:
    offset = address - ROM_BASE
    if offset < 0 or offset + 4 > len(rom):
        raise ValidationError(f"cannot read {owner} at 0x{address:08x}")
    return struct.unpack_from("<i", rom, offset)[0]


def read_u16(rom: bytes, address: int, owner: str) -> int:
    offset = address - ROM_BASE
    if offset < 0 or offset + 2 > len(rom):
        raise ValidationError(f"cannot read {owner} at 0x{address:08x}")
    return struct.unpack_from("<H", rom, offset)[0]


def read_u8(rom: bytes, address: int, owner: str) -> int:
    offset = address - ROM_BASE
    if offset < 0 or offset + 1 > len(rom):
        raise ValidationError(f"cannot read {owner} at 0x{address:08x}")
    return rom[offset]


def require_expected_pointer(
    rom: bytes,
    address: int,
    owner: str,
    expected_symbol: str | None,
    symbols: dict[str, int],
    rom_end: int,
    *,
    function: bool = False,
) -> None:
    actual = read_pointer(rom, address, owner)
    if expected_symbol is None:
        if actual != 0:
            raise ValidationError(f"{owner} must be null, got 0x{actual:08x}")
        return
    if expected_symbol not in symbols:
        raise ValidationError(f"{owner} expects unresolved symbol {expected_symbol}")
    expected = symbols[expected_symbol]
    comparable_actual = actual & ~1 if function else actual
    comparable_expected = expected & ~1 if function else expected
    require_rom_address(owner, comparable_actual, rom_end)
    if comparable_actual != comparable_expected:
        raise ValidationError(
            f"{owner} points at 0x{actual:08x}, expected {expected_symbol} at 0x{expected:08x}"
        )


def validate_group_slots(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    groups_table = symbols["gMapGroups"]
    if groups_table % 4:
        raise ValidationError("group pointer table is not four-byte aligned")
    for group in manifest["groups"]:
        pointer = read_pointer(rom, groups_table + group["number"] * 4, group["name"])
        require_rom_address(group["name"], pointer, rom_end)
        if pointer != symbols[group["name"]]:
            raise ValidationError(
                f"group slot {group['number']} points at the wrong symbol"
            )
        expected_maps = {
            entry["number"]: entry
            for entry in manifest["maps"]
            if entry["group"] == group["number"]
        }
        for number in range(group["mapCount"]):
            entry = expected_maps[number]
            require_expected_pointer(
                rom,
                pointer + number * 4,
                f"{group['name']}[{number}]",
                entry["name"],
                symbols,
                rom_end,
            )


def validate_layouts(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    abi = manifest["abis"]["mapLayout"]
    layouts_table = symbols["gMapLayouts"]
    if layouts_table % 4:
        raise ValidationError("layout pointer table is not four-byte aligned")
    for layout in manifest["layouts"]:
        pointer = read_pointer(
            rom, layouts_table + (layout["number"] - 1) * 4, layout["name"]
        )
        require_rom_address(layout["name"], pointer, rom_end)
        if pointer != symbols[layout["name"]]:
            raise ValidationError(
                f"layout slot {layout['number']} points at the wrong symbol"
            )
        if pointer % abi["alignment"]:
            raise ValidationError(f"layout {layout['name']} violates ABI alignment")
        if (
            read_i32(rom, pointer + abi["widthOffset"], f"{layout['name']}.width")
            != layout["width"]
        ):
            raise ValidationError(f"{layout['name']}.width disagrees with the manifest")
        if (
            read_i32(rom, pointer + abi["heightOffset"], f"{layout['name']}.height")
            != layout["height"]
        ):
            raise ValidationError(
                f"{layout['name']}.height disagrees with the manifest"
            )
        for offset, field in (
            (abi["borderOffset"], "border"),
            (abi["mapOffset"], "map"),
            (abi["primaryTilesetOffset"], "primaryTileset"),
            (abi["secondaryTilesetOffset"], "secondaryTileset"),
        ):
            require_expected_pointer(
                rom,
                pointer + offset,
                f"{layout['name']}.{field}",
                layout[field],
                symbols,
                rom_end,
            )
        for offset, field in (
            (abi["formatOffset"], "layoutFormatValue"),
            (abi["borderWidthOffset"], "borderWidth"),
            (abi["borderHeightOffset"], "borderHeight"),
        ):
            actual = read_u8(rom, pointer + offset, f"{layout['name']}.{field}")
            if actual != layout[field]:
                raise ValidationError(
                    f"{layout['name']}.{field} is {actual}, expected {layout[field]}"
                )
        if read_u8(rom, pointer + abi["paddingOffset"], f"{layout['name']}.padding"):
            raise ValidationError(f"{layout['name']}.padding is not zero-filled")


def validate_map_headers(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    abi = manifest["abis"]["mapHeader"]
    section_metadata = manifest.get("mapSectionMetadata")
    if not isinstance(section_metadata, list):
        raise ValidationError("artifact manifest lacks map-section metadata")
    groups = manifest.get("groups")
    if not isinstance(groups, list):
        raise ValidationError("artifact manifest lacks map-group metadata")
    groups_by_number = {
        group.get("number"): group for group in groups if isinstance(group, dict)
    }
    if len(groups_by_number) != len(groups):
        raise ValidationError("artifact manifest has invalid map-group metadata")
    sections_by_id: dict[str, dict[str, Any]] = {}
    for section in section_metadata:
        if (
            not isinstance(section, dict)
            or not isinstance(section.get("id"), str)
            or not isinstance(section.get("value"), int)
            or not isinstance(section.get("region"), str)
            or section["id"] in sections_by_id
        ):
            raise ValidationError("artifact manifest has invalid map-section metadata")
        sections_by_id[section["id"]] = section
    for index, entry in enumerate(manifest["maps"]):
        section_name = entry.get("regionMapSection")
        section_metadata_entry = sections_by_id.get(section_name)
        if section_metadata_entry is None:
            raise ValidationError(
                f"map {entry.get('name')} names unknown map section {section_name!r}"
            )
        if entry.get("regionMapSectionValue") != section_metadata_entry["value"]:
            raise ValidationError(
                f"map {entry.get('name')} map-section name/value disagree: "
                f"{section_name} is {section_metadata_entry['value']}, "
                f"not {entry.get('regionMapSectionValue')}"
            )
        group = groups_by_number.get(entry.get("group"))
        expected_region = (
            group_content_region(group.get("name")) if group is not None else None
        )
        if expected_region is None:
            raise ValidationError(
                f"map {entry.get('name')} references invalid map-group metadata"
            )
        if entry.get("region") != expected_region:
            raise ValidationError(
                f"map {entry.get('name')} region {entry.get('region')!r} disagrees "
                f"with group {entry.get('group')} content origin {expected_region!r}"
            )
        header = symbols[entry["name"]]
        if header % abi["alignment"]:
            raise ValidationError(
                f"map header {entry['name']} is not four-byte aligned"
            )
        for offset, field in (
            (0, "mapLayout"),
            (4, "mapEvents"),
            (8, "mapScripts"),
            (12, "mapConnections"),
        ):
            require_expected_pointer(
                rom,
                header + offset,
                f"{entry['name']}.{field}",
                entry[field],
                symbols,
                rom_end,
            )
        section = read_u16(
            rom,
            header + abi["regionMapSectionIdOffset"],
            f"{entry['name']}.regionMapSectionId",
        )
        if section != entry["regionMapSectionValue"]:
            raise ValidationError(
                f"{entry['name']}.regionMapSectionId is {section}, "
                f"expected {entry['regionMapSectionValue']}"
            )
        battle_type = read_u8(
            rom,
            header + abi["battleTypeOffset"],
            f"{entry['name']}.battleType",
        )
        if battle_type != entry["battleType"]:
            raise ValidationError(
                f"{entry['name']}.battleType is {battle_type}, expected {entry['battleType']}"
            )
        padding_address = header + abi["paddingOffset"]
        padding = bytes(
            read_u8(rom, padding_address + offset, f"{entry['name']}.padding")
            for offset in range(abi["paddingSize"])
        )
        if padding != bytes(abi["paddingSize"]):
            raise ValidationError(f"{entry['name']}.padding is not zero-filled")
        if index + 1 < len(manifest["maps"]):
            next_entry = manifest["maps"][index + 1]
            next_header = symbols[next_entry["name"]]
            if next_header != header + abi["size"]:
                raise ValidationError(
                    f"map headers {entry['name']} and {next_entry['name']} "
                    f"do not have the required {abi['size']}-byte stride"
                )


def validate_tilesets(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    abi = manifest["abis"]["tileset"]
    formats = {
        "METATILE_ATTRIBUTES_EMERALD_U16": 0,
        "METATILE_ATTRIBUTES_FRLG_U32": 1,
    }
    for tileset in manifest["tilesets"]:
        address = symbols[tileset["name"]]
        if address % abi["alignment"]:
            raise ValidationError(f"tileset {tileset['name']} violates ABI alignment")
        flags = read_u8(rom, address + abi["flagsOffset"], f"{tileset['name']}.flags")
        if (flags >> 1) & 0x3 != formats[tileset["attributeFormat"]]:
            raise ValidationError(
                f"{tileset['name']}.flags disagrees with attribute ABI"
            )
        for offset, field in (
            (abi["tilesOffset"], "tiles"),
            (abi["palettesOffset"], "palettes"),
            (abi["metatilesOffset"], "metatiles"),
            (abi["metatileAttributesOffset"], "metatileAttributes"),
        ):
            require_expected_pointer(
                rom,
                address + offset,
                f"{tileset['name']}.{field}",
                tileset[field],
                symbols,
                rom_end,
            )
        require_expected_pointer(
            rom,
            address + abi["callbackOffset"],
            f"{tileset['name']}.callback",
            tileset["callback"],
            symbols,
            rom_end,
            function=True,
        )


def validate_count_sentinels(manifest: dict[str, Any], symbols: dict[str, int]) -> None:
    for name in ("groups", "layouts"):
        sentinel = manifest["countSentinels"][name]
        start = symbols[sentinel["start"]]
        end = symbols[sentinel["end"]]
        expected = sentinel["count"] * sentinel["stride"]
        if end - start != expected:
            raise ValidationError(
                f"{name} linked count sentinel spans {end - start} bytes, expected {expected}"
            )


def validate_section_metadata(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    address = symbols["gMapSectionMetadata"]
    require_rom_address("gMapSectionMetadata", address, rom_end)
    fields = ("regionValue", "kindValue", "regionMapTypeValue")
    for entry in manifest["mapSectionMetadata"]:
        record = address + entry["value"] * 4
        for offset, field in enumerate(fields):
            actual = read_u8(rom, record + offset, f"{entry['id']}.{field}")
            if actual != entry[field]:
                raise ValidationError(
                    f"{entry['id']}.{field} is {actual}, expected {entry[field]}"
                )
        if read_u8(rom, record + 3, f"{entry['id']}.reserved") != 0:
            raise ValidationError(f"{entry['id']}.reserved is not zero-filled")


def validate_section_codecs(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    abi = manifest["abis"]["mapSectionRegistry"]
    registry = symbols["gMapSectionRegistry"]
    if registry % abi["alignment"]:
        raise ValidationError("map-section registry violates ABI alignment")
    fields = (
        ("metadataOffset", "gMapSectionMetadata"),
        ("sectionToSavedLocationOffset", "gMapSectionToSavedLocation"),
        ("sectionToMetLocationOffset", "gMapSectionToMetLocation"),
        ("savedLocationToSectionOffset", "gSavedLocationToMapSection"),
        ("metLocationToSectionOffset", "gMetLocationToMapSection"),
    )
    for offset_name, symbol in fields:
        require_expected_pointer(
            rom,
            registry + abi[offset_name],
            f"gMapSectionRegistry.{offset_name}",
            symbol,
            symbols,
            rom_end,
        )
    section_count = read_pointer(
        rom, registry + abi["sectionCountOffset"], "gMapSectionRegistry.sectionCount"
    )
    expected_count = manifest["countSentinels"]["mapSections"]["count"]
    if section_count != expected_count:
        raise ValidationError(
            f"map-section count sentinel is {section_count}, expected {expected_count}"
        )

    codecs = manifest["codecs"]
    byte_tables = (
        ("sectionToSavedLocation", "gMapSectionToSavedLocation", 0xFF),
        ("sectionToMetLocation", "gMapSectionToMetLocation", 0xFC),
    )
    for name, symbol, invalid in byte_tables:
        address = symbols[symbol]
        for index, expected in enumerate(codecs[name]):
            actual = read_u8(rom, address + index, f"{symbol}[{index}]")
            expected = invalid if expected < 0 else expected
            if actual != expected:
                raise ValidationError(
                    f"{symbol}[{index}] is {actual}, expected {expected}"
                )
    halfword_tables = (
        ("savedLocationToSection", "gSavedLocationToMapSection"),
        ("metLocationToSection", "gMetLocationToMapSection"),
    )
    for name, symbol in halfword_tables:
        address = symbols[symbol]
        for index, expected in enumerate(codecs[name]):
            actual = read_u16(rom, address + index * 2, f"{symbol}[{index}]")
            expected = 0xFFFF if expected < 0 else expected
            if actual != expected:
                raise ValidationError(
                    f"{symbol}[{index}] is {actual}, expected {expected}"
                )


def validate_artifact(
    rom_path: Path,
    map_path: Path,
    sym_path: Path,
    manifest_path: Path,
    capacity_path: Path,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    capacity = load_capacity_policy(capacity_path)
    rom = rom_path.read_bytes()
    if len(rom) > ROM_LIMIT:
        raise ValidationError(f"ROM exceeds 32 MiB: {len(rom)}")
    if (
        len(rom) < 0xB2
        or rom[0xA0:0xAC] != b"POKEMON EMER"
        or rom[0xAC:0xB0] != b"BPEE"
        or rom[0xB0:0xB2] != b"01"
    ):
        raise ValidationError("ROM header does not identify the Emerald product")

    symbols = parse_symbols(sym_path)
    rom_end = symbols.get("__rom_end")
    if rom_end is None:
        raise ValidationError("linked symbols do not define __rom_end")
    require_rom_address("__rom_end - 1", rom_end - 1, ROM_BASE + len(rom))
    linked_bytes = rom_end - ROM_BASE
    headroom = ROM_LIMIT - linked_bytes
    if headroom < capacity["requiredHeadroomBytes"]:
        raise ValidationError(
            f"ROM headroom {headroom} is below required {capacity['requiredHeadroomBytes']}"
        )
    missing = [
        entry["name"] for entry in manifest["symbols"] if entry["name"] not in symbols
    ]
    if missing:
        raise ValidationError(
            f"required ROM symbols are unresolved: {', '.join(missing[:8])}"
        )
    for entry in manifest["symbols"]:
        require_rom_address(entry["name"], symbols[entry["name"]] & ~1, rom_end)

    validate_group_slots(rom, manifest, symbols, rom_end)
    validate_layouts(rom, manifest, symbols, rom_end)
    validate_map_headers(rom, manifest, symbols, rom_end)
    validate_tilesets(rom, manifest, symbols, rom_end)
    validate_count_sentinels(manifest, symbols)
    validate_section_metadata(rom, manifest, symbols, rom_end)
    validate_section_codecs(rom, manifest, symbols, rom_end)

    linker_map = map_path.read_text(errors="strict")

    def section_bytes(names: tuple[str, ...], origin: int) -> int:
        sections = {
            match.group("name"): (
                int(match.group("address"), 16),
                int(match.group("size"), 16),
            )
            for match in re.finditer(
                r"^(?P<name>\.[\w.]+)\s+(?P<address>0x[0-9a-fA-F]+)\s+(?P<size>0x[0-9a-fA-F]+)",
                linker_map,
                re.MULTILINE,
            )
        }
        missing_sections = [name for name in names if name not in sections]
        if missing_sections:
            raise ValidationError(
                f"linker map lacks memory sections: {', '.join(missing_sections)}"
            )
        return max(sections[name][0] + sections[name][1] for name in names) - origin

    ewram_bytes = section_bytes((".ewram", ".ewram.sbss"), 0x02000000)
    iwram_bytes = section_bytes((".iwram", ".iwram.bss"), 0x03000000)
    if not 0 < ewram_bytes <= 0x40000:
        raise ValidationError(f"EWRAM use is outside memory bounds: {ewram_bytes}")
    if not 0 < iwram_bytes <= 0x8000:
        raise ValidationError(f"IWRAM use is outside memory bounds: {iwram_bytes}")

    report = {
        "schemaVersion": 1,
        "product": manifest["product"],
        "registries": manifest["counts"],
        "rom": {
            "artifactBytes": len(rom),
            "linkedBytes": linked_bytes,
            "limitBytes": ROM_LIMIT,
            "headroomBytes": headroom,
        },
        "capacity": capacity,
        "memory": {
            "ewramBytes": ewram_bytes,
            "ewramLimitBytes": 0x40000,
            "iwramBytes": iwram_bytes,
            "iwramLimitBytes": 0x8000,
        },
        "linkerMapBytes": len(linker_map.encode()),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--map", type=Path, required=True)
    parser.add_argument("--sym", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--capacity-policy",
        type=Path,
        default=Path("tools/foundation/capacity_policy.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = validate_artifact(
            args.rom, args.map, args.sym, args.manifest, args.capacity_policy
        )
    except (ManifestError, ValidationError, OSError) as error:
        print(f"foundation validation failed: {error}", file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
