"""Read persistent flags from complete, checksummed historical GBA save slots."""

from __future__ import annotations

import hashlib
from pathlib import Path
import struct

from tools.persistence.contract import ContractError


FLASH_SIZE = 128 * 1024
SECTOR_SIZE = 4096
SECTORS_PER_SLOT = 14
SECTOR_FOOTER_OFFSET = 4084
SECTOR_SIGNATURE = 0x08012025
ERASED_SECTOR = b"\xff" * SECTOR_SIZE
PAYLOAD_SIZES = (
    3884,
    3968,
    3968,
    3968,
    3744,
    3968,
    3968,
    3968,
    3968,
    3968,
    3968,
    3968,
    3968,
    2400,
)
FLAGS_OFFSET = 0x1270


def _checksum(data: bytes, size: int) -> int:
    value = 0
    for (word,) in struct.iter_unpack("<I", data[:size]):
        value = (value + word) & 0xFFFFFFFF
    return ((value >> 16) + value) & 0xFFFF


def inspect_historical_flags(
    path: Path, expected_sha256: str, flag_ids: set[int]
) -> None:
    data = path.read_bytes()
    if len(data) != FLASH_SIZE:
        raise ContractError(f"regional facts: historical fixture size changed {path}")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ContractError(f"regional facts: historical fixture digest changed {path}")

    complete_slots = 0
    for slot_index in range(2):
        physical = tuple(
            data[index * SECTOR_SIZE : (index + 1) * SECTOR_SIZE]
            for index in range(
                slot_index * SECTORS_PER_SLOT,
                (slot_index + 1) * SECTORS_PER_SLOT,
            )
        )
        if all(sector == ERASED_SECTOR for sector in physical):
            continue
        if any(sector == ERASED_SECTOR for sector in physical):
            continue

        logical: dict[int, bytes] = {}
        counters = set()
        for sector in physical:
            sector_id, stored_checksum, signature, counter = struct.unpack_from(
                "<HHII", sector, SECTOR_FOOTER_OFFSET
            )
            if (
                signature != SECTOR_SIGNATURE
                or not 0 <= sector_id < SECTORS_PER_SLOT
                or sector_id in logical
                or _checksum(sector, PAYLOAD_SIZES[sector_id]) != stored_checksum
            ):
                raise ContractError(
                    f"regional facts: historical fixture has invalid slot {path}"
                )
            logical[sector_id] = sector
            counters.add(counter)
        if set(logical) != set(range(SECTORS_PER_SLOT)) or len(counters) != 1:
            raise ContractError(
                f"regional facts: historical fixture has incomplete slot {path}"
            )
        complete_slots += 1
        save_block1 = b"".join(
            logical[sector_id][: PAYLOAD_SIZES[sector_id]] for sector_id in range(1, 5)
        )
        for flag_id in flag_ids:
            if save_block1[FLAGS_OFFSET + flag_id // 8] & (1 << (flag_id % 8)):
                raise ContractError(
                    "regional facts: historical fixture sets reviewed-unused flag "
                    f"{flag_id:#x}"
                )
    if complete_slots == 0:
        raise ContractError(
            f"regional facts: historical fixture has no complete slot {path}"
        )
