from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, Mapping


FLASH_SIZE = 128 * 1024
SECTOR_SIZE = 4096
SECTORS_PER_SLOT = 14
SECTOR_DATA_SIZE = 3968
SECTOR_FOOTER_OFFSET = 4084
SECTOR_SIGNATURE = 0x08012025
ERASED_SECTOR = b"\xff" * SECTOR_SIZE
SAVE_BLOCK1_SIZE = 0x3D20
TRAINER_DEFEATED_OFFSET = 0x3CD0
TRAINER_DEFEATED_SIZE = 79

# Defined by the current serialized layout. These are the exact
# byte counts passed to CalculateChecksum for logical sector ids 0..13.
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

SUBSTRUCT_OFFSETS = (
    (0, 0, 0, 0, 0, 0, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3, 1, 1, 2, 3, 2, 3),
    (1, 1, 2, 3, 2, 3, 0, 0, 0, 0, 0, 0, 2, 3, 1, 1, 3, 2, 2, 3, 1, 1, 3, 2),
    (2, 3, 1, 1, 3, 2, 2, 3, 1, 1, 3, 2, 0, 0, 0, 0, 0, 0, 3, 2, 3, 2, 1, 1),
    (3, 2, 3, 2, 1, 1, 3, 2, 3, 2, 1, 1, 3, 2, 3, 2, 1, 1, 0, 0, 0, 0, 0, 0),
)


def is_strictly_newer_save_counter(candidate: int, previous: int) -> bool:
    """Compare uint32 save generations using the game's wrap-safe ordering."""
    delta = (candidate - previous) & 0xFFFFFFFF
    return 0 < delta < 0x80000000


def calculate_checksum(data: bytes, size: int) -> int:
    """Match src/save.c CalculateChecksum (sum-le32, folded to u16)."""
    if size < 0 or size > len(data) or size % 4:
        raise ValueError(f"invalid checksum coverage: size={size}, data={len(data)}")
    checksum = 0
    for (word,) in struct.iter_unpack("<I", data[:size]):
        checksum = (checksum + word) & 0xFFFFFFFF
    return ((checksum >> 16) + checksum) & 0xFFFF


def decode_box_pokemon(record: bytes) -> dict[str, Any] | None:
    if len(record) < 80:
        raise ValueError(f"BoxPokemon record must be 80 bytes, got {len(record)}")
    personality, ot_id = struct.unpack_from("<II", record)
    has_species = bool(record[19] & 0x02)
    if not has_species and not personality and not ot_id:
        return None
    key = personality ^ ot_id
    secure = bytearray(record[32:80])
    for offset in range(0, len(secure), 4):
        word = struct.unpack_from("<I", secure, offset)[0] ^ key
        struct.pack_into("<I", secure, offset, word)
    stored_checksum = struct.unpack_from("<H", record, 28)[0]
    actual_checksum = sum(struct.unpack("<24H", secure)) & 0xFFFF
    if actual_checksum != stored_checksum:
        raise ValueError(
            "BoxPokemon checksum mismatch: "
            f"stored=0x{stored_checksum:04x}, calculated=0x{actual_checksum:04x}"
        )
    order = personality % 24
    type0 = SUBSTRUCT_OFFSETS[0][order] * 12
    type3 = SUBSTRUCT_OFFSETS[3][order] * 12
    species_and_type = struct.unpack_from("<H", secure, type0)[0]
    met_bits = struct.unpack_from("<H", secure, type3 + 2)[0]
    iv_bits = struct.unpack_from("<I", secure, type3 + 4)[0]
    return {
        "personality": personality,
        "otId": ot_id,
        "species": species_and_type & 0x7FF,
        "metLocation": secure[type3 + 1],
        "metLevel": met_bits & 0x7F,
        "metGame": (met_bits >> 7) & 0xF,
        "isEgg": bool((iv_bits >> 30) & 1),
        "checksum": stored_checksum,
    }


@dataclass(frozen=True)
class SaveSlot:
    physical_index: int
    counter: int
    sectors: tuple[bytes, ...]

    def logical_sector(self, sector_id: int) -> bytes:
        return self.sectors[sector_id]

    @property
    def save_block2(self) -> bytes:
        return self.logical_sector(0)[: PAYLOAD_SIZES[0]]

    @property
    def save_block1(self) -> bytes:
        return b"".join(
            self.logical_sector(sector_id)[: PAYLOAD_SIZES[sector_id]]
            for sector_id in range(1, 5)
        )

    @property
    def trainer_defeated_bitmap(self) -> bytes:
        block = self.save_block1
        if len(block) != SAVE_BLOCK1_SIZE:
            raise ValueError(f"SaveBlock1 must be {SAVE_BLOCK1_SIZE} bytes")
        return block[
            TRAINER_DEFEATED_OFFSET : TRAINER_DEFEATED_OFFSET + TRAINER_DEFEATED_SIZE
        ]

    @property
    def pokemon_storage(self) -> bytes:
        return b"".join(
            self.logical_sector(sector_id)[: PAYLOAD_SIZES[sector_id]]
            for sector_id in range(5, 14)
        )

    def saved_flag(self, flag_id: int) -> bool:
        if not 0 <= flag_id < 0x960:
            raise ValueError(
                f"saved flag is outside the serialized range: {flag_id:#x}"
            )
        value = self.save_block1[0x1270 + flag_id // 8]
        return bool(value & (1 << (flag_id % 8)))


@dataclass(frozen=True)
class SaveImage:
    data: bytes
    slots: tuple[SaveSlot, ...]
    active_slot: SaveSlot

    @classmethod
    def from_path(cls, path: Path) -> "SaveImage":
        try:
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise ValueError(f"battery save does not exist: {path}") from error
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "SaveImage":
        if len(data) != FLASH_SIZE:
            raise ValueError(
                f"battery save must be exactly {FLASH_SIZE} bytes, got {len(data)}"
            )

        slots = []
        incomplete_slots = []
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
                # A power-interrupted/older slot may coexist with a newer,
                # complete slot. It is never eligible to become active, but it
                # must not hide a coherent save written by the game afterward.
                incomplete_slots.append(slot_index)
                continue

            logical: dict[int, bytes] = {}
            counters = set()
            for physical_index, sector in enumerate(physical):
                sector_id, expected, signature, counter = struct.unpack_from(
                    "<HHII", sector, SECTOR_FOOTER_OFFSET
                )
                if signature != SECTOR_SIGNATURE:
                    raise ValueError(
                        f"slot {slot_index} sector {physical_index} has invalid "
                        f"signature 0x{signature:08x}"
                    )
                if not 0 <= sector_id < SECTORS_PER_SLOT:
                    raise ValueError(
                        f"slot {slot_index} sector {physical_index} has invalid "
                        f"logical id {sector_id}"
                    )
                if sector_id in logical:
                    raise ValueError(
                        f"slot {slot_index} repeats logical sector {sector_id}"
                    )
                actual = calculate_checksum(sector, PAYLOAD_SIZES[sector_id])
                if actual != expected:
                    raise ValueError(
                        f"slot {slot_index} logical sector {sector_id} checksum "
                        f"mismatch: stored=0x{expected:04x}, calculated=0x{actual:04x}"
                    )
                logical[sector_id] = sector
                counters.add(counter)
            if set(logical) != set(range(SECTORS_PER_SLOT)):
                raise ValueError(f"save slot {slot_index} lacks a complete sector set")
            if len(counters) != 1:
                raise ValueError(
                    f"save slot {slot_index} mixes save counters: {sorted(counters)}"
                )
            slots.append(
                SaveSlot(
                    physical_index=slot_index,
                    counter=counters.pop(),
                    sectors=tuple(logical[index] for index in range(SECTORS_PER_SLOT)),
                )
            )

        # The four special sectors may be unused (erased) or emulator/game-owned.
        # Their formats are not part of a normal-save slot and cannot substitute
        # for one. The complete 128 KiB size check above still covers them.
        if not slots:
            if incomplete_slots:
                raise ValueError(
                    "battery save has no complete valid save slot; partial slots: "
                    + ", ".join(map(str, incomplete_slots))
                )
            raise ValueError("battery save has no complete valid save slot")
        active = slots[0]
        for candidate in slots[1:]:
            if is_strictly_newer_save_counter(candidate.counter, active.counter):
                active = candidate
        return cls(data=data, slots=tuple(slots), active_slot=active)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    def semantics(self) -> dict[str, Any]:
        block1 = self.active_slot.save_block1
        block2 = self.active_slot.save_block2
        storage = self.active_slot.pokemon_storage

        def saved_flag(flag_id: int) -> bool:
            value = block1[0x1270 + flag_id // 8]
            return bool(value & (1 << (flag_id % 8)))

        def saved_var(var_id: int) -> int:
            return struct.unpack_from("<H", block1, 0x139C + (var_id - 0x4000) * 2)[0]

        party_record = block1[0x238 : 0x238 + 100]
        box_record = storage[4 : 4 + 80]
        box_pokemon = decode_box_pokemon(box_record)
        daycare = block1[0x3030 : 0x3030 + 288]
        frontier = block2[0x64C : 0x64C + 2272]
        return {
            "identity": {
                "playerNameEncodedHex": block2[:8].hex(),
                "gender": block2[8],
                "trainerIdHex": block2[10:14].hex(),
            },
            "checkpoint": {
                "position": list(struct.unpack_from("<hh", block1, 0)),
                "locationHex": block1[4:12].hex(),
                "continueWarpHex": block1[12:20].hex(),
            },
            "story": {
                "flags": {
                    "FLAG_RESCUED_BIRCH": saved_flag(0x52),
                    "FLAG_ADVENTURE_STARTED": saved_flag(0x74),
                    "FLAG_DEFEATED_RIVAL_ROUTE103": saved_flag(0x82),
                    "FLAG_SYS_POKEMON_GET": saved_flag(0x860),
                    "FLAG_SYS_POKEDEX_GET": saved_flag(0x861),
                    "FLAG_RECEIVED_POKEDEX_FROM_BIRCH": saved_flag(0x8E4),
                },
                "vars": {
                    "VAR_LITTLEROOT_TOWN_STATE": saved_var(0x4050),
                    "VAR_OLDALE_TOWN_STATE": saved_var(0x4051),
                    "VAR_ROUTE101_STATE": saved_var(0x4060),
                    "VAR_BIRCH_LAB_STATE": saved_var(0x4084),
                    "VAR_LITTLEROOT_RIVAL_STATE": saved_var(0x408D),
                    "VAR_LITTLEROOT_INTRO_STATE": saved_var(0x4092),
                },
            },
            "party": {
                "count": block1[0x234],
                "firstRecordHex": party_record.hex(),
                "firstRecordMeaning": (
                    "empty-slot-with-mail-sentinel"
                    if block1[0x234] == 0
                    else "occupied-party-slot"
                ),
                "pokemonProvenance": "absent" if block1[0x234] == 0 else "encoded",
                "firstPokemon": decode_box_pokemon(party_record[:80]),
            },
            "box": {
                "currentBox": storage[0],
                "firstRecordHex": box_record.hex(),
                "firstRecordMeaning": "empty-box-slot"
                if box_pokemon is None
                else "occupied-box-slot",
                "pokemonProvenance": "absent" if box_pokemon is None else "encoded",
                "firstPokemon": box_pokemon,
            },
            "daycare": {
                "recordHex": daycare.hex(),
                "meaning": "both-mon-slots-empty; no egg; zero step counter",
            },
            "facilitySession": {
                "challengeStatus": frontier[1628],
                "levelModeAndPauseBits": frontier[1629],
                "selectedPartyHex": frontier[1630:1636].hex(),
                "currentBattle": struct.unpack_from("<H", frontier, 1638)[0],
                "meaning": "no active or paused Battle Frontier challenge",
            },
        }


def with_saved_flags(image: SaveImage, flags: Mapping[int, bool]) -> SaveImage:
    """Return a checksum-valid variant with the same flags in every complete slot."""
    output = bytearray(image.data)
    for flag_id in flags:
        if not 0 <= flag_id < 0x960:
            raise ValueError(
                f"saved flag is outside the serialized range: {flag_id:#x}"
            )

    for slot in image.slots:
        for flag_id, enabled in flags.items():
            block_offset = 0x1270 + flag_id // 8
            sector_id = 1 + block_offset // SECTOR_DATA_SIZE
            sector_offset = block_offset % SECTOR_DATA_SIZE
            bit = 1 << (flag_id % 8)

            physical_sector = None
            slot_start = slot.physical_index * SECTORS_PER_SLOT
            for physical_index in range(SECTORS_PER_SLOT):
                absolute_index = slot_start + physical_index
                start = absolute_index * SECTOR_SIZE
                candidate_id = struct.unpack_from(
                    "<H", output, start + SECTOR_FOOTER_OFFSET
                )[0]
                if candidate_id == sector_id:
                    physical_sector = absolute_index
                    break
            if physical_sector is None:
                raise ValueError(
                    f"save slot {slot.physical_index} lacks logical sector {sector_id}"
                )

            start = physical_sector * SECTOR_SIZE
            value_offset = start + sector_offset
            if enabled:
                output[value_offset] |= bit
            else:
                output[value_offset] &= ~bit
            checksum = calculate_checksum(
                output[start : start + SECTOR_SIZE], PAYLOAD_SIZES[sector_id]
            )
            struct.pack_into("<H", output, start + SECTOR_FOOTER_OFFSET + 2, checksum)

    return SaveImage.from_bytes(bytes(output))


def load_fixture_manifest(path: Path) -> tuple[dict[str, Any], SaveImage]:
    document = json.loads(path.read_text())
    fixture = path.parent / document["fixture"]["file"]
    image = SaveImage.from_path(fixture)
    expected_digest = document["fixture"]["sha256"]
    if image.sha256 != expected_digest:
        raise ValueError(
            f"fixture digest mismatch: expected={expected_digest}, actual={image.sha256}"
        )
    expectations = document["semanticExpectations"]
    actual = image.semantics()
    if actual != expectations:
        raise ValueError(
            "fixture semantics no longer match the reviewed manifest: "
            f"expected={expectations!r}, actual={actual!r}"
        )
    return document, image
