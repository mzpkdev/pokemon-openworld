#!/usr/bin/env python3
"""Inspect linked registry pointers, required symbols, memory use, and ROM headroom."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from tools.content_port.animations import (
        MANDATORY_BINDINGS,
        TILESET_ANIM_QUEUE_CAPACITY,
        maximum_combined_queue_demand,
    )
except ImportError:  # Direct script execution from outside the repository root.
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from tools.content_port.animations import (
        MANDATORY_BINDINGS,
        TILESET_ANIM_QUEUE_CAPACITY,
        maximum_combined_queue_demand,
    )

try:
    from .manifest import ManifestError, expected_map_geography, load_manifest
except ImportError:  # Direct script execution.
    from manifest import ManifestError, expected_map_geography, load_manifest

try:
    from tools.persistence.contract import (
        ContractError,
        projected_abi_evidence_values_for_purpose,
        validate_contract,
    )
except ImportError:  # Direct script execution from outside the repository root.
    sys.path.insert(0, str(Path(__file__).parents[2]))
    from tools.persistence.contract import (
        ContractError,
        projected_abi_evidence_values_for_purpose,
        validate_contract,
    )


ROOT = Path(__file__).parents[2]
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
EWRAM_LIMIT = 256 * 1024
IWRAM_LIMIT = 32 * 1024
SAVE_ABI_MAGIC = 0x53414249
SAVE_ABI_VERSION = 1
ANIMATION_POLICY = ROOT / "tools/content_port/ports/johto/animation_policy.json"
PRIMARY_ANIMATION_TILESETS = {
    "Johto_General",
    "Johto_NorthEast",
    "Johto_South",
    "Johto_NorthWest",
}
ANIMATION_FRAME_SYMBOL_PREFIXES = {
    "johto_general.flower": "sTilesetAnims_JohtoGeneral_Flower",
    "johto_general.sandwatersedge": "sTilesetAnims_JohtoGeneral_Sand",
    "johto_general.water_current_landwatersedge": "sTilesetAnims_JohtoGeneral_Water",
    "johto_north_east.flower": "sTilesetAnims_JohtoNorthEast_Flower",
    "johto_north_east.sandwatersedge": "sTilesetAnims_JohtoNorthEast_Sand",
    "johto_north_east.water_current_landwatersedge": "sTilesetAnims_JohtoNorthEast_Water",
    "johto_south.flower": "sTilesetAnims_JohtoSouth_Flower",
    "johto_south.sandwatersedge": "sTilesetAnims_JohtoSouth_Sand",
    "johto_south.water_current_landwatersedge": "sTilesetAnims_JohtoSouth_Water",
    "johto_north_west.flower": "sTilesetAnims_JohtoNorthWest_Flower",
    "johto_north_west.sandwatersedge": "sTilesetAnims_JohtoNorthWest_Sand",
    "johto_north_west.water_current_landwatersedge": "sTilesetAnims_JohtoNorthWest_Water",
    "national_park.large_fountain": "sTilesetAnims_NationalParkLarge",
    "national_park.small_fountain": "sTilesetAnims_NationalParkSmall",
    "national_park.red_flower": "sTilesetAnims_NationalParkRed",
    "national_park.yellow_flower": "sTilesetAnims_NationalParkYellow",
    "ecruteak_theater.flower": "sTilesetAnims_EcruteakTheater",
    "azalea_town_gym.yellow_flower": "sTilesetAnims_AzaleaGym",
    "blackthorn_gym.cave_lava": "sTilesetAnims_BlackthornGym",
}


class ValidationError(ValueError):
    """A linked product artifact violates the integrity contract."""


def load_save_contract(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        contract = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(f"cannot read save contract {path}: {error}") from error
    if not isinstance(contract, dict) or not isinstance(contract.get("structs"), dict):
        raise ValidationError("save contract is incomplete")
    return contract, hashlib.sha256(raw).hexdigest()


def expected_save_abi_values(
    contract: dict[str, Any], purpose: str
) -> list[tuple[str, int]]:
    try:
        validate_contract(contract)
        return projected_abi_evidence_values_for_purpose(contract, purpose)
    except (ContractError, KeyError, TypeError, ValueError) as error:
        raise ValidationError(
            f"save contract ABI evidence is incomplete: {error}"
        ) from error


def validate_linked_save_abi(
    rom: bytes, symbols: dict[str, int], contract: dict[str, Any], purpose: str
) -> dict[str, Any]:
    address = symbols.get("gSaveAbiEvidence")
    if address is None:
        raise ValidationError("linked symbols do not define gSaveAbiEvidence")
    offset = (address & ~1) - ROM_BASE
    if offset < 0 or offset + 8 > len(rom):
        raise ValidationError("gSaveAbiEvidence points outside the ROM artifact")
    magic, version = struct.unpack_from("<II", rom, offset)
    expected = expected_save_abi_values(contract, purpose)
    if magic != SAVE_ABI_MAGIC or version != SAVE_ABI_VERSION:
        raise ValidationError("linked save ABI evidence header is invalid")
    count = len(expected)
    end = offset + 8 + count * 4
    if end > len(rom):
        raise ValidationError("linked save ABI evidence is truncated")
    actual = struct.unpack_from(f"<{count}I", rom, offset + 8)
    for (name, wanted), value in zip(expected, actual):
        if value != wanted:
            raise ValidationError(
                f"linked save ABI drift: {name} is {value}, expected {wanted}"
            )
    evidence = rom[offset:end]
    return {
        "symbol": "gSaveAbiEvidence",
        "address": address & ~1,
        "valueCount": count,
        "sha256": hashlib.sha256(evidence).hexdigest(),
    }


def parse_elf_symbols(text: str) -> dict[str, tuple[int, int]]:
    symbols: dict[str, tuple[int, int]] = {}
    pattern = re.compile(
        r"^\s*\d+:\s+(?P<address>[0-9a-fA-F]{1,8})\s+"
        r"(?P<size>(?:0[xX][0-9a-fA-F]{1,8}|\d{1,10}))\s+"
        r"\S+\s+\S+\s+\S+\s+\S+\s+(?P<name>\S+)\s*$",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        size_token = match.group("size")
        size = int(size_token, 16 if size_token[:2].lower() == "0x" else 10)
        if size > 0xFFFFFFFF:
            continue
        symbols[match.group("name")] = (
            int(match.group("address"), 16),
            size,
        )
    return symbols


def validate_elf_linked_save_abi(
    elf_path: Path,
    sections: list[dict[str, Any]],
    symbols: dict[str, tuple[int, int]],
    contract: dict[str, Any],
    purpose: str,
) -> dict[str, Any]:
    symbol = symbols.get("gSaveAbiEvidence")
    if symbol is None:
        raise ValidationError("linked ELF does not define gSaveAbiEvidence")
    address, symbol_size = symbol
    expected_size = 8 + len(expected_save_abi_values(contract, purpose)) * 4
    if symbol_size != expected_size:
        raise ValidationError(
            f"linked save ABI evidence size is {symbol_size}, expected {expected_size}"
        )
    section = next(
        (
            item
            for item in sections
            if item["type"] != "NOBITS"
            and item["address"] <= address
            and address + symbol_size <= item["address"] + item["size"]
        ),
        None,
    )
    if section is None:
        raise ValidationError("gSaveAbiEvidence is outside loadable ELF sections")
    data = elf_path.read_bytes()
    file_offset = section["offset"] + address - section["address"]
    end = file_offset + symbol_size
    if file_offset < 0 or end > len(data):
        raise ValidationError("gSaveAbiEvidence points outside the ELF artifact")
    # Reuse the ROM validator with a synthetic zero-based image and symbol.
    linked = validate_linked_save_abi(
        data[file_offset:end], {"gSaveAbiEvidence": ROM_BASE}, contract, purpose
    )
    linked["address"] = address
    return linked


def parse_elf_sections(text: str) -> list[dict[str, Any]]:
    sections = []
    pattern = re.compile(
        r"^\s*\[\s*\d+\]\s+(?P<name>\S+)\s+(?P<type>\S+)\s+"
        r"(?P<address>[0-9a-fA-F]+)\s+(?P<offset>[0-9a-fA-F]+)\s+"
        r"(?P<size>[0-9a-fA-F]+)\s+\S+\s+(?P<flags>\S*)",
        re.MULTILINE,
    )
    for match in pattern.finditer(text):
        sections.append(
            {
                "name": match.group("name"),
                "type": match.group("type"),
                "address": int(match.group("address"), 16),
                "offset": int(match.group("offset"), 16),
                "size": int(match.group("size"), 16),
                "flags": match.group("flags"),
            }
        )
    if not sections:
        raise ValidationError("ELF section table is empty or unreadable")
    return sections


def measure_elf_capacity(elf_path: Path) -> dict[str, int]:
    try:
        result = subprocess.run(
            ["arm-none-eabi-readelf", "-SW", str(elf_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError as error:
        raise ValidationError(
            "required tool not found: arm-none-eabi-readelf"
        ) from error
    except subprocess.CalledProcessError as error:
        raise ValidationError(
            f"cannot inspect ELF {elf_path}: {error.stderr.strip()}"
        ) from error
    sections = parse_elf_sections(result.stdout)
    by_name = {section["name"]: section for section in sections}
    required = (".ewram", ".ewram.sbss", ".iwram", ".iwram.bss")
    missing = [name for name in required if name not in by_name]
    if missing:
        raise ValidationError(
            f"ELF lacks required memory sections: {', '.join(missing)}"
        )

    def range_bytes(origin: int, limit: int, *, loadable: bool = False) -> int:
        candidates = [
            section
            for section in sections
            if "A" in section["flags"]
            and origin <= section["address"] < limit
            and (not loadable or section["type"] != "NOBITS")
        ]
        if not candidates:
            raise ValidationError(f"ELF has no allocatable sections at 0x{origin:08x}")
        end = max(section["address"] + section["size"] for section in candidates)
        if end > limit:
            raise ValidationError(
                f"ELF section range exceeds memory ending at 0x{limit:08x}"
            )
        return end - origin

    return {
        "romBytes": range_bytes(ROM_BASE, ROM_BASE + ROM_LIMIT, loadable=True),
        "ewramBytes": range_bytes(0x02000000, 0x02000000 + EWRAM_LIMIT),
        "iwramBytes": range_bytes(0x03000000, 0x03000000 + IWRAM_LIMIT),
    }


def purpose_limits(contract: dict[str, Any]) -> dict[str, Any]:
    budgets = contract.get("purposeBudgets")
    if not isinstance(budgets, dict) or budgets.get("schemaVersion") != 1:
        raise ValidationError("save contract lacks purposeBudgets schema 1")
    limits = budgets.get("limits")
    baselines = budgets.get("baselines")
    purposes = {"normal", "debug", "release", "test-runner", "headless-test"}
    if (
        not isinstance(limits, dict)
        or not isinstance(baselines, dict)
        or set(baselines) != purposes
    ):
        raise ValidationError("save contract purpose budgets are incomplete")
    expected_limits = {
        "romBytes": ROM_LIMIT,
        "ewramBytes": EWRAM_LIMIT,
        "iwramBytes": IWRAM_LIMIT,
        "releaseHeadroomBytes": REQUIRED_HEADROOM_FLOOR_BYTES,
    }
    if limits != expected_limits:
        raise ValidationError("save contract purpose limits drift from hardware policy")
    return budgets


def enforce_purpose_usage(
    purpose: str,
    usage: dict[str, int],
    contract: dict[str, Any],
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    budgets = purpose_limits(contract)
    if purpose not in budgets["baselines"]:
        raise ValidationError(f"unknown artifact purpose: {purpose}")
    limits = budgets["limits"]
    baseline = budgets["baselines"][purpose]
    if artifact_path is not None and artifact_path.name != baseline["artifact"]:
        raise ValidationError(
            f"{purpose} artifact is {artifact_path.name}, expected {baseline['artifact']}"
        )
    for field in ("romBytes", "ewramBytes", "iwramBytes"):
        if usage[field] <= 0 or usage[field] > limits[field]:
            raise ValidationError(
                f"{purpose} {field} use is outside budget: {usage[field]}"
            )
    if (
        purpose == "release"
        and limits["romBytes"] - usage["romBytes"] < limits["releaseHeadroomBytes"]
    ):
        raise ValidationError(
            f"release ROM headroom {limits['romBytes'] - usage['romBytes']} is below required "
            f"{limits['releaseHeadroomBytes']}"
        )
    return {"purpose": purpose, "usage": usage, "limits": limits, "baseline": baseline}


def validate_elf_artifact(
    elf_path: Path, purpose: str, save_contract_path: Path
) -> dict[str, Any]:
    contract, digest = load_save_contract(save_contract_path)
    try:
        metadata = subprocess.run(
            ["arm-none-eabi-readelf", "-SWs", str(elf_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except FileNotFoundError as error:
        raise ValidationError(
            "required tool not found: arm-none-eabi-readelf"
        ) from error
    except subprocess.CalledProcessError as error:
        raise ValidationError(
            f"cannot inspect ELF {elf_path}: {error.stderr.strip()}"
        ) from error
    symbol_records = parse_elf_symbols(metadata)
    linked_save_abi = validate_elf_linked_save_abi(
        elf_path,
        parse_elf_sections(metadata),
        symbol_records,
        contract,
        purpose,
    )
    result = enforce_purpose_usage(
        purpose, measure_elf_capacity(elf_path), contract, elf_path
    )
    animation = validate_linked_animation_contract(symbol_records, ANIMATION_POLICY)
    return {
        "schemaVersion": 1,
        "artifact": str(elf_path),
        **result,
        "saveContract": {"sha256": digest, "linkedAbi": linked_save_abi},
        "tilesetAnimations": animation,
    }


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


def parse_symbol_records(path: Path) -> dict[str, tuple[int, int]]:
    symbols: dict[str, tuple[int, int]] = {}
    try:
        lines = path.read_text(errors="strict").splitlines()
    except OSError as error:
        raise ValidationError(f"cannot read symbols {path}: {error}") from error
    for line in lines:
        fields = line.split()
        if len(fields) >= 4:
            try:
                address = int(fields[0], 16)
                size = int(fields[2], 16)
            except ValueError:
                continue
            symbols[fields[-1]] = (address, size)
    # Release LTO marks many retained product symbols HIDDEN; the established
    # objdump pipeline omits those records even though they remain in the ELF.
    elf_path = path.with_suffix(".elf")
    if path.suffix == ".sym" and elf_path.is_file():
        try:
            metadata = subprocess.run(
                ["arm-none-eabi-readelf", "-Ws", str(elf_path)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout
        except (FileNotFoundError, subprocess.CalledProcessError) as error:
            raise ValidationError(
                f"cannot inspect linked symbols in {elf_path}"
            ) from error
        symbols.update(parse_elf_symbols(metadata))
    if not symbols:
        raise ValidationError(f"no symbols parsed from {path}")
    return symbols


def parse_symbols(path: Path) -> dict[str, int]:
    return {name: record[0] for name, record in parse_symbol_records(path).items()}


def validate_linked_animation_contract(
    symbols: dict[str, tuple[int, int]], policy_path: Path
) -> dict[str, Any]:
    def require_extent(symbol: str, *, function: bool = False) -> tuple[int, int]:
        if symbol not in symbols:
            raise ValidationError(f"linked animation symbol is missing: {symbol}")
        address, size = symbols[symbol]
        start = address & ~1 if function else address
        end = start + size
        if size <= 0 or start < ROM_BASE or end > ROM_BASE + ROM_LIMIT or end <= start:
            raise ValidationError(
                f"linked animation symbol is outside ROM: {symbol} at 0x{address:08x}+{size}"
            )
        return address, size

    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValidationError(
            f"cannot read animation policy {policy_path}: {error}"
        ) from error
    schedules = policy.get("schedules")
    frame_sets = policy.get("frameSets")
    if (
        policy.get("queueCapacity") != TILESET_ANIM_QUEUE_CAPACITY
        or not isinstance(schedules, list)
        or not isinstance(frame_sets, list)
    ):
        raise ValidationError("animation policy lacks linked-artifact evidence")
    schedule_by_name = {
        item.get("tileset"): item for item in schedules if isinstance(item, dict)
    }
    if set(schedule_by_name) != MANDATORY_BINDINGS:
        raise ValidationError(
            "animation policy does not cover mandatory linked tilesets"
        )
    callbacks = {str(item.get("callback")) for item in schedules}
    for callback in callbacks:
        require_extent(callback, function=True)

    linked_frames = 0
    for frame_set in frame_sets:
        if not isinstance(frame_set, dict) or not frame_set.get("requiredFrames"):
            continue
        frame_id = str(frame_set.get("id"))
        prefix = ANIMATION_FRAME_SYMBOL_PREFIXES.get(frame_id)
        if prefix is None:
            raise ValidationError(
                f"animation frame set lacks linked identity: {frame_id}"
            )
        expected_size = int(frame_set.get("sourceTilesPerFrame", 0)) * 32
        for frame in frame_set["requiredFrames"]:
            symbol = f"{prefix}{frame}"
            _, actual_size = require_extent(symbol)
            if actual_size != expected_size:
                raise ValidationError(
                    f"linked animation frame {symbol} is {actual_size} bytes, expected {expected_size}"
                )
            linked_frames += 1

    primary = [schedule_by_name[name] for name in PRIMARY_ANIMATION_TILESETS]
    secondary = [
        schedule
        for name, schedule in schedule_by_name.items()
        if name not in PRIMARY_ANIMATION_TILESETS
    ]
    peak = max(
        maximum_combined_queue_demand(first, second)
        for first in primary
        for second in secondary
    )
    if peak > TILESET_ANIM_QUEUE_CAPACITY:
        raise ValidationError(
            f"linked animation queue demand {peak} exceeds capacity {TILESET_ANIM_QUEUE_CAPACITY}"
        )
    return {
        "callbacks": len(callbacks),
        "frames": linked_frames,
        "queue": {
            "capacityEntries": TILESET_ANIM_QUEUE_CAPACITY,
            "peakEntries": peak,
            "remainingEntries": TILESET_ANIM_QUEUE_CAPACITY - peak,
        },
    }


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
        expected_region = expected_map_geography(
            entry.get("name"), group.get("name") if group is not None else None
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


def validate_surf_edge_exits(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> dict[str, Any]:
    """Validate the linked Surf edge-exit sidecar without symbol adjacency assumptions."""
    abi = manifest["abis"]["surfEdgeExit"]
    sentinel = manifest["countSentinels"]["edgeExits"]
    registry = symbols[sentinel["registry"]]
    count_address = symbols[sentinel["countSymbol"]]
    if registry % abi["alignment"]:
        raise ValidationError("Surf edge-exit registry violates ABI alignment")
    if count_address % 2:
        raise ValidationError("Surf edge-exit count violates u16 alignment")
    require_rom_address("gSurfEdgeExits", registry, rom_end)
    require_rom_address("gSurfEdgeExitCount", count_address, rom_end)
    if count_address + 2 > rom_end:
        raise ValidationError("Surf edge-exit count is truncated")
    linked_count = read_u16(rom, count_address, "gSurfEdgeExitCount")
    expected_count = sentinel["count"]
    if linked_count != expected_count or linked_count != len(manifest["edgeExits"]):
        raise ValidationError(
            f"Surf edge-exit count is {linked_count}, expected {expected_count}"
        )
    byte_count = abi["size"] if linked_count == 0 else linked_count * abi["size"]
    registry_offset = registry - ROM_BASE
    if (
        registry_offset < 0
        or registry + byte_count > rom_end
        or registry_offset + byte_count > len(rom)
    ):
        raise ValidationError("Surf edge-exit registry is truncated")
    if linked_count == 0:
        if rom[registry_offset : registry_offset + abi["size"]] != bytes(abi["size"]):
            raise ValidationError(
                "empty Surf edge-exit registry sentinel is not zero-filled"
            )
        return {"count": 0, "bytes": abi["size"]}

    fields = (
        "sourceMapValue",
        "targetMapValue",
        "targetX",
        "targetY",
        "exitEdgeValue",
        "targetFacingValue",
    )
    for index, expected in enumerate(manifest["edgeExits"]):
        offset = registry_offset + index * abi["size"]
        actual = struct.unpack_from("<HHhhBB", rom, offset)
        for field, value in zip(fields, actual):
            if value != expected[field]:
                raise ValidationError(
                    f"Surf edge-exit {index}.{field} is {value}, expected {expected[field]}"
                )
    return {"count": linked_count, "bytes": linked_count * abi["size"]}


def validate_surf_edge_route_profiles(
    rom: bytes, manifest: dict[str, Any], symbols: dict[str, int], rom_end: int
) -> dict[str, Any]:
    """Validate the linked Surf edge route-profile sidecar."""
    abi = manifest["abis"]["surfEdgeRouteProfile"]
    sentinel = manifest["countSentinels"]["edgeRouteProfiles"]
    registry = symbols[sentinel["registry"]]
    count_address = symbols[sentinel["countSymbol"]]
    if registry % abi["alignment"]:
        raise ValidationError("Surf edge route-profile registry violates ABI alignment")
    if count_address % 2:
        raise ValidationError("Surf edge route-profile count violates u16 alignment")
    require_rom_address("gSurfEdgeRouteProfiles", registry, rom_end)
    require_rom_address("gSurfEdgeRouteProfileCount", count_address, rom_end)
    if count_address + 2 > rom_end:
        raise ValidationError("Surf edge route-profile count is truncated")
    linked_count = read_u16(rom, count_address, "gSurfEdgeRouteProfileCount")
    expected_count = sentinel["count"]
    if linked_count != expected_count or linked_count != len(manifest["edgeRouteProfiles"]):
        raise ValidationError(
            f"Surf edge route-profile count is {linked_count}, expected {expected_count}"
        )
    byte_count = abi["size"] if linked_count == 0 else linked_count * abi["size"]
    registry_offset = registry - ROM_BASE
    if (
        registry_offset < 0
        or registry + byte_count > rom_end
        or registry_offset + byte_count > len(rom)
    ):
        raise ValidationError("Surf edge route-profile registry is truncated")
    if linked_count == 0:
        if rom[registry_offset : registry_offset + abi["size"]] != bytes(abi["size"]):
            raise ValidationError(
                "empty Surf edge route-profile registry sentinel is not zero-filled"
            )
        return {"count": 0, "bytes": abi["size"]}

    fields = ("sourceMapValue", "exitEdgeValue", "profileValue")
    for index, expected in enumerate(manifest["edgeRouteProfiles"]):
        offset = registry_offset + index * abi["size"]
        actual = struct.unpack_from("<HBB", rom, offset)
        for field, value in zip(fields, actual):
            if value != expected[field]:
                raise ValidationError(
                    f"Surf edge route-profile {index}.{field} is {value}, expected {expected[field]}"
                )
    return {"count": linked_count, "bytes": linked_count * abi["size"]}


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
    save_contract_path: Path = Path("tools/integrity/save_contract.json"),
    purpose: str = "normal",
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    capacity = load_capacity_policy(capacity_path)
    save_contract, save_contract_digest = load_save_contract(save_contract_path)
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

    symbol_records = parse_symbol_records(sym_path)
    symbols = {name: record[0] for name, record in symbol_records.items()}
    rom_end = symbols.get("__rom_end")
    if rom_end is None:
        raise ValidationError("linked symbols do not define __rom_end")
    require_rom_address("__rom_end - 1", rom_end - 1, ROM_BASE + len(rom))
    linked_bytes = rom_end - ROM_BASE
    headroom = ROM_LIMIT - linked_bytes
    if purpose == "release" and headroom < capacity["requiredHeadroomBytes"]:
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

    linked_save_abi = validate_linked_save_abi(rom, symbols, save_contract, purpose)

    validate_group_slots(rom, manifest, symbols, rom_end)
    validate_layouts(rom, manifest, symbols, rom_end)
    validate_map_headers(rom, manifest, symbols, rom_end)
    validate_tilesets(rom, manifest, symbols, rom_end)
    validate_count_sentinels(manifest, symbols)
    surf_edge_exits = validate_surf_edge_exits(rom, manifest, symbols, rom_end)
    surf_edge_route_profiles = validate_surf_edge_route_profiles(rom, manifest, symbols, rom_end)
    validate_section_metadata(rom, manifest, symbols, rom_end)
    validate_section_codecs(rom, manifest, symbols, rom_end)
    animation = validate_linked_animation_contract(symbol_records, ANIMATION_POLICY)

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
    if not 0 < ewram_bytes <= EWRAM_LIMIT:
        raise ValidationError(f"EWRAM use is outside memory bounds: {ewram_bytes}")
    if not 0 < iwram_bytes <= IWRAM_LIMIT:
        raise ValidationError(f"IWRAM use is outside memory bounds: {iwram_bytes}")

    purpose_budget = enforce_purpose_usage(
        purpose,
        {
            "romBytes": linked_bytes,
            "ewramBytes": ewram_bytes,
            "iwramBytes": iwram_bytes,
        },
        save_contract,
        rom_path,
    )
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
            "ewramLimitBytes": EWRAM_LIMIT,
            "iwramBytes": iwram_bytes,
            "iwramLimitBytes": IWRAM_LIMIT,
        },
        "purposeBudget": purpose_budget,
        "saveContract": {
            "sha256": save_contract_digest,
            "baselineCommit": save_contract.get("baselineCommit"),
            "linkedAbi": linked_save_abi,
        },
        "tilesetAnimations": animation,
        "surfEdgeExits": surf_edge_exits,
        "surfEdgeRouteProfiles": surf_edge_route_profiles,
        "linkerMapBytes": len(linker_map.encode()),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--map", type=Path)
    parser.add_argument("--sym", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument(
        "--purpose",
        choices=("normal", "debug", "release", "test-runner", "headless-test"),
        default="normal",
    )
    parser.add_argument(
        "--save-contract",
        type=Path,
        default=Path("tools/integrity/save_contract.json"),
    )
    parser.add_argument(
        "--capacity-policy",
        type=Path,
        default=Path("tools/integrity/capacity_policy.json"),
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.elf:
            if any((args.rom, args.map, args.sym, args.manifest)):
                parser.error(
                    "--elf cannot be combined with --rom/--map/--sym/--manifest"
                )
            if args.purpose not in ("test-runner", "headless-test"):
                parser.error("--elf requires a test-runner or headless-test purpose")
            report = validate_elf_artifact(args.elf, args.purpose, args.save_contract)
        else:
            if not all((args.rom, args.map, args.sym, args.manifest)):
                parser.error(
                    "--rom, --map, --sym, and --manifest are required together"
                )
            report = validate_artifact(
                args.rom,
                args.map,
                args.sym,
                args.manifest,
                args.capacity_policy,
                args.save_contract,
                args.purpose,
            )
    except (ManifestError, ValidationError, OSError) as error:
        print(f"integrity validation failed: {error}", file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
