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
    from .manifest import ManifestError, load_manifest
except ImportError:  # Direct script execution.
    from manifest import ManifestError, load_manifest


ROM_BASE = 0x08000000
ROM_LIMIT = 32 * 1024 * 1024


class ValidationError(ValueError):
    """A linked product artifact violates the foundation contract."""


def load_capacity_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read capacity policy {path}: {error}") from error
    required = (
        "commit",
        "evidenceDigest",
        "evidenceFileCount",
        "johtoResidentBytes",
        "integrationMultiplier",
        "travelStoryReserveBytes",
        "requiredHeadroomBytes",
    )
    if any(key not in policy for key in required):
        raise ValidationError("capacity policy is incomplete")
    johto = policy["johtoResidentBytes"]
    multiplier = policy["integrationMultiplier"]
    reserve = policy["travelStoryReserveBytes"]
    required_headroom = policy["requiredHeadroomBytes"]
    calculated = -(-int(johto * 125) // 100) + reserve if multiplier == 1.25 else None
    digest = policy["evidenceDigest"]
    snapshot_commit = f"snapshot-sha256:{digest}"
    if (
        not policy["commit"]
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or policy["evidenceFileCount"] <= 0
        or (
            policy["commit"].startswith("snapshot-sha256:")
            and policy["commit"] != snapshot_commit
        )
        or johto <= 0
        or reserve <= 0
        or calculated != required_headroom
    ):
        raise ValidationError(
            "capacity policy has invalid evidence or inconsistent arithmetic"
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
        if read_i32(rom, pointer, f"{layout['name']}.width") != layout["width"]:
            raise ValidationError(f"{layout['name']}.width disagrees with the manifest")
        if read_i32(rom, pointer + 4, f"{layout['name']}.height") != layout["height"]:
            raise ValidationError(
                f"{layout['name']}.height disagrees with the manifest"
            )
        for offset, field in (
            (8, "border"),
            (12, "map"),
            (16, "primaryTileset"),
            (20, "secondaryTileset"),
        ):
            require_expected_pointer(
                rom,
                pointer + offset,
                f"{layout['name']}.{field}",
                layout[field],
                symbols,
                rom_end,
            )


def validate_map_headers(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    for entry in manifest["maps"]:
        header = symbols[entry["name"]]
        if header % 4:
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


def validate_tilesets(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> None:
    for tileset in manifest["tilesets"]:
        address = symbols[tileset["name"]]
        for offset, field in (
            (4, "tiles"),
            (8, "palettes"),
            (12, "metatiles"),
            (16, "metatileAttributes"),
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
            address + 20,
            f"{tileset['name']}.callback",
            tileset["callback"],
            symbols,
            rom_end,
            function=True,
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
    if len(rom) < 0xB0 or rom[0xAC:0xB0] != b"BPEE":
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
            "ewramBytes": section_bytes((".ewram", ".ewram.sbss"), 0x02000000),
            "iwramBytes": section_bytes((".iwram", ".iwram.bss"), 0x03000000),
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
