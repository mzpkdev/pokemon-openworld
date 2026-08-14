#!/usr/bin/env python3
"""Generate the reviewed pre-journey Kanto save used by continuity E2E."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from tools.e2e.save_file import SaveImage, decode_box_pokemon
from tools.e2e.save_journey import add_party_through_debug_menu, save_from_start_menu
from tools.e2e.skyemu import (
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
    SkyEmuSession,
    Symbols,
)
from tools.e2e.start_profile import StartProfile, quickstart_with_profile
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)


ITEM_OLD_ROD = 709
ITEM_POKE_BALL = 1
MART_START = (3, 4)


def _inventory_count(image: SaveImage, *, offset: int, slots: int, item: int) -> int:
    block1 = image.active_slot.save_block1
    block2 = image.active_slot.save_block2
    encryption_key = struct.unpack_from("<I", block2, 0xAC)[0]
    total = 0
    for index in range(slots):
        item_id, encrypted_quantity = struct.unpack_from(
            "<HH", block1, offset + index * 4
        )
        if item_id == item:
            total += encrypted_quantity ^ (encryption_key & 0xFFFF)
    return total


def _manifest(image: SaveImage, *, rom: Path, source_commit: str) -> dict:
    block1 = image.active_slot.save_block1
    block2 = image.active_slot.save_block2
    encryption_key = struct.unpack_from("<I", block2, 0xAC)[0]
    party_count = block1[0x234]
    party = [
        decode_box_pokemon(block1[0x238 + index * 100 : 0x288 + index * 100])
        for index in range(party_count)
    ]
    x, y = struct.unpack_from("<hh", block1, 0)
    map_group, map_num, warp_id, _padding = struct.unpack_from("<bbbB", block1, 4)
    return {
        "schemaVersion": 1,
        "fixture": {
            "file": "kanto_continuity_start.sav",
            "sha256": image.sha256,
            "sourceCommit": source_commit,
            "sourceRomSha256": hashlib.sha256(rom.read_bytes()).hexdigest(),
        },
        "generation": {
            "method": (
                "Kanto new-game profile, shipped FRLG Cheat start action, reviewed "
                "pre-journey map placement, then two ordinary field Start-menu saves"
            ),
            "constructionOnlyOperations": [
                "DEBUG new-game Kanto profile selector",
                "DEBUG Utilities > Cheat start (FRLG ordinary game services)",
                "DEBUG integrity map load to the Vermilion Mart start boundary",
            ],
            "postLoadHostWritesAllowed": False,
        },
        "semanticExpectations": {
            "identity": {
                "playerNameEncodedHex": block2[:8].hex(),
                "gender": block2[8],
                "trainerIdHex": block2[10:14].hex(),
            },
            "location": {
                "mapGroup": map_group,
                "mapNumber": map_num,
                "warpId": warp_id,
                "position": [x, y],
            },
            "money": struct.unpack_from("<I", block1, 0x490)[0] ^ encryption_key,
            "party": {"count": party_count, "pokemon": party},
            "inventory": {
                "oldRodCount": _inventory_count(
                    image, offset=0x560 + 30 * 4, slots=30, item=ITEM_OLD_ROD
                ),
                "pokeBallCount": _inventory_count(
                    image, offset=0x560 + 60 * 4, slots=16, item=ITEM_POKE_BALL
                ),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rom", type=Path, required=True)
    parser.add_argument("--symbols", type=Path, required=True)
    parser.add_argument("--skyemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    maps = {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }
    mart = maps["VermilionCity_Mart_Frlg"]
    with tempfile.TemporaryDirectory(prefix="continuity-fixture-") as temporary:
        game = SkyEmuSession(
            binary=args.skyemu.resolve(),
            rom=args.rom.resolve(),
            symbols=Symbols(args.symbols.resolve()),
            workdir=Path(temporary) / "emulator",
        )
        try:
            quickstart_with_profile(game, StartProfile.KANTO, 0x4B414E54)
            add_party_through_debug_menu(game)
            result = game.request_map_load(
                IntegrityMapLoadRequest(
                    request_id=0x564D4152,
                    map_group=mart.group,
                    map_num=mart.number,
                    x=MART_START[0],
                    y=MART_START[1],
                ),
                max_frames=1_800,
            )
            assert result.status is IntegrityLoadStatus.SUCCESS
            assert result.phase is IntegrityLoadPhase.FIELD_READY
            assert result.error is IntegrityLoadError.NONE
            game.wait_for_controls_unlocked(max_frames=1_200)
            save_from_start_menu(game)
            game.wait_for_controls_unlocked(max_frames=1_200)
            image = save_from_start_menu(game)
        finally:
            game.close()

    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout.strip()
    document = _manifest(image, rom=args.rom.resolve(), source_commit=source_commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".sav").write_bytes(image.data)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
