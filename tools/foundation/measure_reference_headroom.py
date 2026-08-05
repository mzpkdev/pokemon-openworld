#!/usr/bin/env python3
"""Attribute Johto resident bytes from a donor's linked ELF symbols."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

ROM_START, ROM_END = 0x08000000, 0x0A000000
RESERVE_BYTES = 512 * 1024
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
TRAINER_FIRST, TRAINER_LAST = 855, 1095  # reviewed Johto-only block in opponents.h
TRAINER_COUNT, TRAINER_RECORD_BYTES, DIFFICULTY_COUNT = 1727, 52, 3
REGION_MAP_ENTRY_BYTES = 8
JOHTO_TRAINER_ART = (
    "LeaderFalkner",
    "LeaderBugsy",
    "LeaderWhitney",
    "LeaderMorty",
    "LeaderChuck",
    "LeaderJasmine",
    "LeaderPryce",
    "LeaderClair",
    "EliteFourWill",
    "EliteFourKoga",
    "EliteFourKaren",
)


class MeasurementError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def donor_commit(donor: Path, declared: str | None) -> tuple[str, str]:
    result = subprocess.run(
        ["git", "-C", str(donor), "rev-parse", "HEAD"], text=True, capture_output=True
    )
    actual = result.stdout.strip()
    if result.returncode == 0 and COMMIT_RE.fullmatch(actual):
        if declared and declared != actual:
            raise MeasurementError("declared donor commit differs from checkout")
        return actual, "git"
    if not declared or not COMMIT_RE.fullmatch(declared):
        raise MeasurementError(
            "donor Git metadata is unavailable; pass the reviewed 40-hex commit with --commit"
        )
    return declared, "declared-commit+source-tree-digest"


def source_records(donor: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(donor.rglob("*")):
        relative = path.relative_to(donor)
        if (
            not path.is_file()
            or relative.parts[0] in {".git", "build", "test-results"}
            or path.name
            in {
                "pokemonworld.elf",
                "pokemonworld.map",
                "pokemonworld.sym",
                "pokemonworld.gba",
            }
        ):
            continue
        records.append(
            {
                "path": str(relative),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    if not records:
        raise MeasurementError("donor source tree contains no evidence files")
    return records


def records_digest(records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(
            f"{record['path']}\0{record['bytes']}\0{record['sha256']}\n".encode()
        )
    return digest.hexdigest()


def discover(donor: Path) -> dict[str, set[str]]:
    layouts = json.loads((donor / "data/layouts/layouts.json").read_text())["layouts"]
    johto_layouts = [item for item in layouts if item.get("layout_version") == "johto"]
    other_layouts = [item for item in layouts if item.get("layout_version") != "johto"]
    layout_ids = {item["id"] for item in johto_layouts}
    tilesets = {
        item[key]
        for item in johto_layouts
        for key in ("primary_tileset", "secondary_tileset")
    }
    shared_tilesets = {
        item[key]
        for item in other_layouts
        for key in ("primary_tileset", "secondary_tileset")
    }
    maps, labels, graphics, sections = set(), set(), set(), set()
    other_graphics = set()
    for path in sorted((donor / "data/maps").glob("*/map.json")):
        data = json.loads(path.read_text())
        target = graphics if data.get("layout") in layout_ids else other_graphics
        target.update(item["graphics_id"] for item in data.get("object_events", []))
        if data.get("layout") not in layout_ids:
            continue
        maps.add(data["name"])
        sections.add(data["region_map_section"])
        for item in (
            data.get("object_events", [])
            + data.get("coord_events", [])
            + data.get("bg_events", [])
        ):
            if item.get("script"):
                labels.add(item["script"])
        for sibling in (path.with_name("scripts.inc"), path.with_name("text.inc")):
            if sibling.is_file():
                labels.update(
                    re.findall(r"^([A-Za-z_]\w*)::?", sibling.read_text(), re.MULTILINE)
                )
    pointer_text = (
        donor / "src/data/object_events/object_event_graphics_info_pointers.h"
    ).read_text()
    suffixes = set()
    for graphics_id in graphics - other_graphics:
        match = re.search(
            r"\["
            + re.escape(graphics_id)
            + r"\]\s*=\s*&gObjectEventGraphicsInfo_(\w+)",
            pointer_text,
        )
        if match:
            suffixes.add(match.group(1))
    return {
        "maps": maps,
        "layouts": {item["name"] for item in johto_layouts},
        "labels": labels,
        "tilesets": {
            name.removeprefix("gTileset_") for name in tilesets - shared_tilesets
        },
        "graphics": suffixes,
        "sections": sections,
    }


def elf_symbols(elf: Path, nm: str) -> list[tuple[int, int, str]]:
    result = subprocess.run(
        [nm, "-S", "--defined-only", str(elf)], text=True, capture_output=True
    )
    if result.returncode:
        raise MeasurementError(
            f"cannot read ELF symbols with {nm}: {result.stderr.strip()}"
        )
    symbols = []
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 4:
            address, size, _, name = fields
        elif len(fields) == 3:
            address, _, name = fields
            size = "0"
        else:
            continue
        value, length = int(address, 16), int(size, 16)
        if ROM_START <= value < ROM_END:
            symbols.append((value, length, name))
    if not symbols:
        raise MeasurementError("ELF contains no ROM symbols")
    return symbols


def read_elf_bytes(elf: Path, address: int, size: int) -> bytes:
    data = elf.read_bytes()
    if data[:4] != b"\x7fELF" or data[4:6] != b"\x01\x01":
        raise MeasurementError("donor artifact is not a 32-bit little-endian ELF")
    program_offset = struct.unpack_from("<I", data, 28)[0]
    entry_size = struct.unpack_from("<H", data, 42)[0]
    entry_count = struct.unpack_from("<H", data, 44)[0]
    for index in range(entry_count):
        kind, offset, virtual, _, file_size, _, _, _ = struct.unpack_from(
            "<IIIIIIII", data, program_offset + index * entry_size
        )
        if kind == 1 and virtual <= address and address + size <= virtual + file_size:
            start = offset + address - virtual
            return data[start : start + size]
    raise MeasurementError(f"ELF does not contain ROM range 0x{address:08x}+{size}")


def trainer_dependency_intervals(
    elf: Path, symbols: list[tuple[int, int, str]]
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    named = {name: (address, size) for address, size, name in symbols}
    try:
        trainers_address, trainers_size = named["gTrainers"]
    except KeyError as error:
        raise MeasurementError("ELF lacks gTrainers") from error
    expected_size = TRAINER_COUNT * TRAINER_RECORD_BYTES * DIFFICULTY_COUNT
    if trainers_size != expected_size:
        raise MeasurementError(
            f"gTrainers size {trainers_size} differs from expected {expected_size}"
        )
    by_address = {
        address: (size, name)
        for address, size, name in symbols
        if size and name.startswith("__compound_literal.")
    }
    party_intervals: set[tuple[int, int]] = set()
    for difficulty in range(DIFFICULTY_COUNT):
        for trainer_id in range(TRAINER_FIRST, TRAINER_LAST + 1):
            record = (
                trainers_address
                + (difficulty * TRAINER_COUNT + trainer_id) * TRAINER_RECORD_BYTES
            )
            party = struct.unpack("<I", read_elf_bytes(elf, record + 8, 4))[0]
            if not party:
                continue
            if party not in by_address:
                raise MeasurementError(
                    f"trainer party 0x{party:08x} lacks a sized linked symbol"
                )
            size, _ = by_address[party]
            party_intervals.add((party, party + size))
    if len(party_intervals) != 254 or union_bytes(list(party_intervals)) != 25632:
        raise MeasurementError("Johto trainer party pointer evidence changed")

    art_intervals = []
    for family in JOHTO_TRAINER_ART:
        for prefix in ("gTrainerFrontPic_", "gTrainerPalette_"):
            name = prefix + family
            if name not in named or named[name][1] <= 0:
                raise MeasurementError(
                    f"ELF lacks sized Johto trainer art symbol {name}"
                )
            address, size = named[name]
            art_intervals.append((address, address + size))
    if union_bytes(art_intervals) != 8460:
        raise MeasurementError("Johto-exclusive trainer art evidence changed")
    return sorted(party_intervals), art_intervals


def union_bytes(intervals: list[tuple[int, int]]) -> int:
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def measure(
    donor: Path,
    *,
    elf: Path,
    linker_map: Path,
    symbols_file: Path,
    declared_commit: str | None = None,
    nm: str = "arm-none-eabi-nm",
) -> dict[str, Any]:
    commit, provenance = donor_commit(donor, declared_commit)
    for artifact in (elf, linker_map, symbols_file):
        if not artifact.is_file() or artifact.stat().st_size == 0:
            raise MeasurementError(f"linked donor evidence is missing: {artifact}")
    seeds = discover(donor)
    symbols = elf_symbols(elf, nm)
    trainer_parties, trainer_art = trainer_dependency_intervals(elf, symbols)
    addresses = sorted({address for address, _, _ in symbols})
    next_address = {
        address: addresses[index + 1] if index + 1 < len(addresses) else address
        for index, address in enumerate(addresses)
    }
    categories: dict[str, list[tuple[int, int]]] = {
        "mapLayoutEventData": [],
        "scriptsTextCallbacks": [],
        "tilesetResourcesCallbacks": [],
        "objectGraphics": [],
        "johtoRuntime": [],
        "trainerParties": trainer_parties,
        "trainerArt": trainer_art,
    }
    for address, explicit_size, name in symbols:
        size = explicit_size or max(0, next_address[address] - address)
        interval = (address, address + size)
        if any(
            name == prefix or name.startswith(prefix + "_")
            for prefix in seeds["maps"] | seeds["layouts"]
        ):
            categories["mapLayoutEventData"].append(interval)
        if name in seeds["labels"]:
            categories["scriptsTextCallbacks"].append(interval)
        if name.startswith(("gTileset", "gMetatile", "TilesetCB")) and any(
            token in name for token in seeds["tilesets"]
        ):
            categories["tilesetResourcesCallbacks"].append(interval)
        if name.startswith(("gObjectEvent", "sPicTable")) and any(
            token in name for token in seeds["graphics"]
        ):
            categories["objectGraphics"].append(interval)
        if "johto" in name.lower():
            categories["johtoRuntime"].append(interval)
    linked_intervals = [
        interval for values in categories.values() for interval in values
    ]
    symbol_bytes = union_bytes(linked_intervals)
    trainer_bytes = (
        (TRAINER_LAST - TRAINER_FIRST + 1) * TRAINER_RECORD_BYTES * DIFFICULTY_COUNT
    )
    region_map_bytes = len(seeds["sections"]) * REGION_MAP_ENTRY_BYTES
    johto_bytes = symbol_bytes + trainer_bytes + region_map_bytes
    source = source_records(donor)
    artifact_records = [
        {"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (elf, linker_map, symbols_file)
    ]
    evidence_digest = records_digest(source + artifact_records)
    return {
        "schemaVersion": 2,
        "source": ".references/PKMN-World",
        "commit": commit,
        "provenanceMode": provenance,
        "measurementKind": "linked-symbol-range-attribution",
        "sourceTreeDigest": records_digest(source),
        "evidenceDigest": evidence_digest,
        "evidenceFileCount": len(source) + len(artifact_records),
        "johtoLayoutCount": len(seeds["layouts"]),
        "johtoMapCount": len(seeds["maps"]),
        "evidenceCategories": {
            **{name: union_bytes(values) for name, values in categories.items()},
            "trainerRecords": trainer_bytes,
            "regionMapEntries": region_map_bytes,
            "deduplicatedSymbolRanges": symbol_bytes,
        },
        "johtoResidentBytes": johto_bytes,
        "integrationMultiplier": 1.25,
        "travelStoryReserveBytes": RESERVE_BYTES,
        "requiredHeadroomBytes": math.ceil(johto_bytes * 1.25) + RESERVE_BYTES,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--donor", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--map", dest="linker_map", type=Path)
    parser.add_argument("--elf", type=Path)
    parser.add_argument("--sym", type=Path)
    parser.add_argument("--nm", default="arm-none-eabi-nm")
    parser.add_argument("--commit")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()
    donor = args.donor.resolve()
    artifacts = (args.artifacts or donor).resolve()
    report = measure(
        donor,
        elf=(args.elf or artifacts / "pokemonworld.elf").resolve(),
        linker_map=(args.linker_map or artifacts / "pokemonworld.map").resolve(),
        symbols_file=(args.sym or artifacts / "pokemonworld.sym").resolve(),
        declared_commit=args.commit,
        nm=args.nm,
    )
    if args.compare and report != json.loads(args.compare.read_text()):
        raise SystemExit(f"donor measurement differs from {args.compare}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
