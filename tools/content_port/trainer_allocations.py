#!/usr/bin/env python3
"""Synchronize reviewed Johto trainer identities into persistence authorities."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "tools/content_port/ports/johto/trainer_classification.json"
OPPONENTS = ROOT / "include/constants/opponents.h"
SOURCES = ROOT / "tools/persistence/persistent_sources.json"
PUBLICATION = ROOT / "tools/persistence/published_allocations.json"

FIRST_NEW_ID = 1483
EXPECTED_ADMITTED = 195
EXPECTED_NEW = 193
TRAINER_COUNT = 1676
TRAINER_CAPACITY = 1792
BITMAP_FIRST = 858
BITMAP_BITS = TRAINER_COUNT - BITMAP_FIRST
BITMAP_BYTES = (BITMAP_BITS + 7) // 8
EXISTING = {
    "TRAINER_YOUNGSTER_SAMUEL_JOHTO": 1481,
    "TRAINER_SAILOR_EUGENE_JOHTO": 1482,
}
BEGIN = "// JOHTO ORDINARY TRAINER ALLOCATIONS BEGIN"
END = "// JOHTO ORDINARY TRAINER ALLOCATIONS END"


class AllocationError(RuntimeError):
    """The reviewed inventory cannot produce the frozen allocation."""


def compact_bytes(value: Any) -> bytes:
    """Match the persistence authorities' reviewed one-record-per-line style."""

    def render(item: Any, indent: int) -> list[str]:
        prefix = " " * indent
        if isinstance(item, dict):
            lines = [prefix + "{"]
            children = list(item.items())
            for index, (key, child) in enumerate(children):
                comma = "," if index + 1 < len(children) else ""
                label = " " * (indent + 2) + json.dumps(key) + ": "
                if isinstance(child, list) and all(
                    isinstance(value, dict) for value in child
                ):
                    lines.append(label + "[")
                    for child_index, value in enumerate(child):
                        child_comma = "," if child_index + 1 < len(child) else ""
                        encoded = json.dumps(
                            value, ensure_ascii=True, separators=(", ", ": ")
                        )
                        lines.append(" " * (indent + 4) + encoded + child_comma)
                    lines.append(" " * (indent + 2) + "]" + comma)
                elif isinstance(child, dict) and key == "locationCodecs":
                    lines.append(
                        label
                        + json.dumps(child, ensure_ascii=True, separators=(", ", ": "))
                        + comma
                    )
                elif isinstance(child, dict):
                    nested = render(child, indent + 2)
                    nested[0] = label + nested[0].lstrip()
                    nested[-1] += comma
                    lines.extend(nested)
                else:
                    lines.append(
                        label
                        + json.dumps(child, ensure_ascii=True, separators=(", ", ": "))
                        + comma
                    )
            lines.append(prefix + "}")
            return lines
        raise AllocationError("compact persistence document must be an object")

    return ("\n".join(render(value, 0)) + "\n").encode()


def admitted_targets(document: dict[str, Any]) -> tuple[str, ...]:
    identities = document.get("identities")
    if document.get("schemaVersion") != 2 or not isinstance(identities, list):
        raise AllocationError("trainer inventory must use schema version 2")
    targets = []
    for index, identity in enumerate(identities):
        if not identity.get("admitted"):
            continue
        projection = identity.get("projection")
        target = projection.get("target") if isinstance(projection, dict) else None
        if not isinstance(target, str) or not re.fullmatch(
            r"TRAINER_[A-Z0-9_]+", target
        ):
            raise AllocationError(f"identity {index}: admitted target is invalid")
        targets.append(target)
    if len(targets) != EXPECTED_ADMITTED:
        raise AllocationError(
            f"expected {EXPECTED_ADMITTED} admitted identities, got {len(targets)}"
        )
    if len(set(targets)) != len(targets):
        raise AllocationError("admitted target identities are not unique")
    if set(EXISTING) - set(targets):
        raise AllocationError("Samuel and Eugene must remain admitted")
    return tuple(targets)


def new_allocations(document: dict[str, Any]) -> tuple[tuple[str, int], ...]:
    targets = admitted_targets(document)
    new_targets = [target for target in targets if target not in EXISTING]
    if len(new_targets) != EXPECTED_NEW:
        raise AllocationError(
            f"expected {EXPECTED_NEW} new identities, got {len(new_targets)}"
        )
    allocations = tuple(
        (target, FIRST_NEW_ID + index) for index, target in enumerate(new_targets)
    )
    if allocations[-1][1] != TRAINER_COUNT - 1:
        raise AllocationError("allocation does not exactly fill the reviewed range")
    return allocations


def _replace_numeric_define(text: str, symbol: str, value: int) -> str:
    pattern = re.compile(rf"(?m)^(#define {re.escape(symbol)}\s+)[0-9]+$")
    replaced, count = pattern.subn(rf"\g<1>{value}", text)
    if count != 1:
        raise AllocationError(f"expected one numeric definition for {symbol}")
    return replaced


def render_opponents(text: str, allocations: tuple[tuple[str, int], ...]) -> str:
    text = _replace_numeric_define(text, "TRAINERS_COUNT", TRAINER_COUNT)
    text = _replace_numeric_define(text, "MAX_TRAINERS_COUNT", TRAINER_CAPACITY)
    block = "\n".join(
        [BEGIN]
        + [f"#define {symbol:<49} {value}" for symbol, value in allocations]
        + [END]
    )
    if BEGIN in text or END in text:
        pattern = re.compile(rf"(?ms)^{re.escape(BEGIN)}$.*?^{re.escape(END)}$")
        text, count = pattern.subn(block, text)
        if count != 1:
            raise AllocationError("malformed Johto allocation marker block")
        return text
    anchor = '#include "constants/persistent_opponents.inc.h"'
    if text.count(anchor) != 1:
        raise AllocationError("persistent opponent facade anchor is missing")
    return text.replace(anchor, f"{block}\n\n{anchor}")


def update_sources(
    sources: dict[str, Any], allocations: tuple[tuple[str, int], ...]
) -> dict[str, Any]:
    projection = sources["trainerIdentityProjection"]
    projection["additional"] = [
        {"source": "johto-trainer-identities", "symbol": symbol, "value": value}
        for symbol, value in (*EXISTING.items(), *allocations)
    ]
    defeat = sources["trainerDefeat"]
    defeat["count"] = TRAINER_COUNT
    defeat["bitmapStorage"] = {
        "firstTrainerId": BITMAP_FIRST,
        "bitCount": BITMAP_BITS,
        "byteCount": BITMAP_BYTES,
    }
    return sources


def update_publication(
    publication: dict[str, Any], allocations: tuple[tuple[str, int], ...]
) -> dict[str, Any]:
    entries = publication["entries"]
    expected_entries = [
        _published_entry(symbol, value) for symbol, value in allocations
    ]
    existing_symbols = {
        item["symbol"] for item in entries if item["domain"] == "trainerIds"
    }
    expected = {symbol for symbol, _ in allocations}
    stale = expected & existing_symbols
    if stale:
        published = {
            item["symbol"]: item
            for item in entries
            if item["domain"] == "trainerIds" and item["symbol"] in expected
        }
        if set(published) != expected:
            raise AllocationError(
                "published Johto allocation is only partially present"
            )
        for symbol, value in allocations:
            if published[symbol] != _published_entry(symbol, value):
                raise AllocationError(f"published allocation drifted: {symbol}")
        if entries[-EXPECTED_NEW:] != expected_entries:
            raise AllocationError(
                "published Johto allocations must be the exact append-only suffix"
            )
        return publication
    entries.extend(expected_entries)
    return publication


def _published_entry(symbol: str, value: int) -> dict[str, Any]:
    return {
        "domain": "trainerIds",
        "source": "johto-trainer-identities",
        "storage": "u32-id",
        "symbol": symbol,
        "value": value,
        "physicalBinding": {
            "bitIndex": value - BITMAP_FIRST,
            "kind": "trainer-defeat-bitmap",
        },
    }


def synchronize(root: Path = ROOT) -> tuple[tuple[str, int], ...]:
    inventory = json.loads((root / INVENTORY.relative_to(ROOT)).read_text())
    allocations = new_allocations(inventory)
    opponents = root / OPPONENTS.relative_to(ROOT)
    sources_path = root / SOURCES.relative_to(ROOT)
    publication_path = root / PUBLICATION.relative_to(ROOT)
    opponents.write_text(render_opponents(opponents.read_text(), allocations))
    sources_path.write_bytes(
        compact_bytes(update_sources(json.loads(sources_path.read_text()), allocations))
    )
    publication_path.write_bytes(
        compact_bytes(
            update_publication(json.loads(publication_path.read_text()), allocations)
        )
    )
    return allocations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sync", "check"))
    args = parser.parse_args(argv)
    try:
        document = json.loads(INVENTORY.read_text())
        allocations = new_allocations(document)
        if args.command == "sync":
            synchronize()
        else:
            opponents = render_opponents(OPPONENTS.read_text(), allocations)
            sources = compact_bytes(
                update_sources(json.loads(SOURCES.read_text()), allocations)
            )
            publication = compact_bytes(
                update_publication(json.loads(PUBLICATION.read_text()), allocations)
            )
            if opponents != OPPONENTS.read_text():
                raise AllocationError("opponent allocation surface is stale")
            if sources != SOURCES.read_bytes():
                raise AllocationError("persistent source allocation surface is stale")
            if publication != PUBLICATION.read_bytes():
                raise AllocationError("published allocation surface is stale")
        print(
            "PASS: 195 admitted Johto identities, 193 appended IDs "
            "1483..1675, bitmap bits 625..817"
        )
        return 0
    except (AllocationError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
