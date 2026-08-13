"""Reviewed Johto tileset-animation inventory and payload ownership."""

from __future__ import annotations

import hashlib
import json
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType

from .errors import ContentPortError
from .ownership import safe_repo_path, validate_relative_path


DISPOSITIONS = frozenset({"required", "intentionally-unused", "blocked"})
MANDATORY_BINDINGS = frozenset(
    {
        "Johto_General",
        "Johto_NorthEast",
        "Johto_South",
        "Johto_NorthWest",
        "NationalPark",
        "EcruteakTheater",
        "AzaleaTown_Gym",
        "BlackthornGym",
    }
)
EXPECTED_CALLBACKS = frozenset(
    {
        "InitTilesetAnim_JohtoGeneral",
        "InitTilesetAnim_NationalPark",
        "InitTilesetAnim_ecruteak_theater",
        "InitTilesetAnim_AzaleaTown_Gym",
        "InitTilesetAnim_Lavaridge",
    }
)
EXPECTED_FRAME_SETS = {
    "johto_general.flower": (
        "data/tilesets/primary/johto_general/anim/flower",
        "data/tilesets/primary/johto_general/anim/flower",
        (0, 1, 2, 3, 4),
        (),
    ),
    "johto_general.sandwatersedge": (
        "data/tilesets/primary/johto_general/anim/sandwatersedge",
        "data/tilesets/primary/johto_general/anim/sandwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_general.water_current_landwatersedge": (
        "data/tilesets/primary/johto_general/anim/water_current_landwatersedge",
        "data/tilesets/primary/johto_general/anim/water_current_landwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_north_east.flower": (
        "data/tilesets/primary/johto_north_east/anim/flower",
        "data/tilesets/primary/johto_north_east/anim/flower",
        tuple(range(5)),
        (),
    ),
    "johto_north_east.sandwatersedge": (
        "data/tilesets/primary/johto_north_east/anim/sandwatersedge",
        "data/tilesets/primary/johto_north_east/anim/sandwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_north_east.water_current_landwatersedge": (
        "data/tilesets/primary/johto_north_east/anim/water_current_landwatersedge",
        "data/tilesets/primary/johto_north_east/anim/water_current_landwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_south.flower": (
        "data/tilesets/primary/johto_south/anim/flower",
        "data/tilesets/primary/johto_south/anim/flower",
        tuple(range(5)),
        (),
    ),
    "johto_south.sandwatersedge": (
        "data/tilesets/primary/johto_south/anim/sandwatersedge",
        "data/tilesets/primary/johto_south/anim/sandwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_south.water_current_landwatersedge": (
        "data/tilesets/primary/johto_south/anim/water_current_landwatersedge",
        "data/tilesets/primary/johto_south/anim/water_current_landwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_north_west.flower": (
        "data/tilesets/primary/johto_north_west/anim/flower",
        "data/tilesets/primary/johto_north_west/anim/flower",
        tuple(range(5)),
        (),
    ),
    "johto_north_west.sandwatersedge": (
        "data/tilesets/primary/johto_north_west/anim/sandwatersedge",
        "data/tilesets/primary/johto_north_west/anim/sandwatersedge",
        tuple(range(8)),
        (),
    ),
    "johto_north_west.water_current_landwatersedge": (
        "data/tilesets/primary/johto_north_west/anim/water_current_landwatersedge",
        "data/tilesets/primary/johto_north_west/anim/water_current_landwatersedge",
        tuple(range(8)),
        (),
    ),
    "national_park.large_fountain": (
        "data/tilesets/secondary/national_park/anim/large_fountain",
        "data/tilesets/secondary/national_park/anim/large_fountain",
        tuple(range(4)),
        (),
    ),
    "national_park.small_fountain": (
        "data/tilesets/secondary/national_park/anim/small_fountain",
        "data/tilesets/secondary/national_park/anim/small_fountain",
        tuple(range(5)),
        (),
    ),
    "national_park.red_flower": (
        "data/tilesets/secondary/national_park/anim/red_flower",
        "data/tilesets/secondary/national_park/anim/red_flower",
        tuple(range(3)),
        (),
    ),
    "national_park.yellow_flower": (
        "data/tilesets/secondary/national_park/anim/yellow_flower",
        "data/tilesets/secondary/national_park/anim/yellow_flower",
        tuple(range(3)),
        (),
    ),
    "ecruteak_theater.flower": (
        "data/tilesets/secondary/ecruteak_theater/anim/flower",
        "data/tilesets/secondary/ecruteak_theater/anim/flower",
        tuple(range(5)),
        (),
    ),
    "azalea_town_gym.yellow_flower": (
        "data/tilesets/secondary/azalea_town_gym/anim/yellow_flower",
        "data/tilesets/secondary/azalea_town_gym/anim/yellow_flower",
        tuple(range(3)),
        (),
    ),
    "azalea_town_gym.red_flower": (
        "data/tilesets/secondary/azalea_town_gym/anim/red_flower",
        "data/tilesets/secondary/azalea_town_gym/anim/red_flower",
        (),
        tuple(range(3)),
    ),
    "goldenrod.fountain": (
        "data/tilesets/secondary/goldenrod/anim/fountain",
        "data/tilesets/secondary/goldenrod/anim/fountain",
        (),
        tuple(range(2)),
    ),
    "goldenrod.windy_water": (
        "data/tilesets/secondary/goldenrod/anim/windy_water",
        "data/tilesets/secondary/goldenrod/anim/windy_water",
        (),
        tuple(range(8)),
    ),
    "pokemon_day_care.red_flower": (
        "data/tilesets/secondary/pokemon_day_care/anim/red_flower",
        "data/tilesets/secondary/pokemon_day_care/anim/red_flower",
        (),
        tuple(range(3)),
    ),
    "pokemon_day_care.yellow_flower": (
        "data/tilesets/secondary/pokemon_day_care/anim/yellow_flower",
        "data/tilesets/secondary/pokemon_day_care/anim/yellow_flower",
        (),
        tuple(range(3)),
    ),
    "ruins_of_alph_outside.flag": (
        "data/tilesets/secondary/ruins_of_alph_outside/anim/flag",
        "data/tilesets/secondary/ruins_of_alph_outside/anim/flag",
        (),
        tuple(range(4)),
    ),
    "blackthorn_gym.cave_lava": (
        "data/tilesets/secondary/cave/anim/lava",
        "data/tilesets/secondary/blackthorn_gym/anim/lava",
        tuple(range(4)),
        tuple(range(4, 8)),
    ),
    "blackthorn_gym.lavaridge_steam": (
        "data/tilesets/secondary/lavaridge/anim/steam",
        "data/tilesets/secondary/lavaridge/anim/steam",
        (),
        tuple(range(4)),
    ),
}
EXPECTED_INACTIVE_TRANSFERS = frozenset(
    {
        "primary.full-water-416-445",
        "primary.dormant-land-water-edge-480-489",
        "goldenrod.fountain-and-windy-water",
        "azalea-gym.red-flowers",
        "day-care.flowers",
        "ruins-of-alph.flags",
        "blackthorn.lavaridge-steam",
        "blackthorn.cave-lava-frames-4-7",
    }
)
ISSUE_OWNED_VARIANT_CANDIDATES = frozenset(
    frame_set
    for frame_set in EXPECTED_FRAME_SETS
    if frame_set.startswith(("johto_north_east.", "johto_south.", "johto_north_west."))
)
INACTIVE_FRAME_SETS = frozenset(
    frame_set
    for frame_set, (_, _, required_frames, _) in EXPECTED_FRAME_SETS.items()
    if not required_frames
)
EXPECTED_SOURCE_TILES = {
    **{
        frame_set: 4
        for frame_set in EXPECTED_FRAME_SETS
        if frame_set.endswith(".flower")
        or frame_set.endswith(".red_flower")
        or frame_set.endswith(".yellow_flower")
        or frame_set.endswith(".cave_lava")
        or frame_set.endswith(".lavaridge_steam")
    },
    **{
        frame_set: 18
        for frame_set in EXPECTED_FRAME_SETS
        if frame_set.endswith(".sandwatersedge")
    },
    **{
        frame_set: 48
        for frame_set in EXPECTED_FRAME_SETS
        if frame_set.endswith(".water_current_landwatersedge")
    },
    "national_park.large_fountain": 8,
    "national_park.small_fountain": 8,
    "goldenrod.fountain": 4,
    "goldenrod.windy_water": 4,
    "ruins_of_alph_outside.flag": 6,
}


def _primary_transfers(prefix: str) -> tuple[tuple[object, ...], ...]:
    return (
        (f"{prefix}.sandwatersedge", 8, 0, 0, 416, 18),
        (f"{prefix}.flower", 16, 2, 0, 508, 4),
        (f"{prefix}.water_current_landwatersedge", 16, 3, 34, 450, 12),
    )


EXPECTED_SCHEDULES = {
    "Johto_General": (
        "InitTilesetAnim_JohtoGeneral",
        256,
        _primary_transfers("johto_general"),
    ),
    "Johto_NorthEast": (
        "InitTilesetAnim_JohtoGeneral",
        256,
        _primary_transfers("johto_general"),
    ),
    "Johto_South": (
        "InitTilesetAnim_JohtoGeneral",
        256,
        _primary_transfers("johto_general"),
    ),
    "Johto_NorthWest": (
        "InitTilesetAnim_JohtoGeneral",
        256,
        _primary_transfers("johto_general"),
    ),
    "NationalPark": (
        "InitTilesetAnim_NationalPark",
        960,
        (
            ("national_park.large_fountain", 10, 0, 0, 728, 8),
            ("national_park.small_fountain", 12, 1, 0, 744, 8),
            ("national_park.red_flower", 16, 2, 0, 736, 4),
            ("national_park.yellow_flower", 16, 12, 0, 740, 4),
        ),
    ),
    "EcruteakTheater": (
        "InitTilesetAnim_ecruteak_theater",
        960,
        (("ecruteak_theater.flower", 10, 0, 0, 744, 4),),
    ),
    "AzaleaTown_Gym": (
        "InitTilesetAnim_AzaleaTown_Gym",
        960,
        (("azalea_town_gym.yellow_flower", 10, 0, 0, 739, 4),),
    ),
    "BlackthornGym": (
        "InitTilesetAnim_Lavaridge",
        160,
        (("blackthorn_gym.cave_lava", 16, 1, 0, 961, 4),),
    ),
}


def _record(value: object, pointer: str, required: set[str]) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ContentPortError(f"{pointer}: expected an object")
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required)
    if missing:
        raise ContentPortError(f"{pointer}: missing field {missing[0]!r}")
    if unknown:
        raise ContentPortError(f"{pointer}: unknown field {unknown[0]!r}")
    return value


def _records(document: Mapping[str, object], field: str) -> Sequence[object]:
    value = document.get(field)
    if not isinstance(value, list):
        raise ContentPortError(f"$.{field}: expected an array")
    return value


def _text(value: object, pointer: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContentPortError(f"{pointer}: expected a non-empty, trimmed string")
    return value


def _digest(value: object, pointer: str) -> str:
    result = _text(value, pointer)
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise ContentPortError(f"{pointer}: expected a lowercase SHA-256 digest")
    return result


def _disposition(value: object, pointer: str) -> str:
    result = _text(value, pointer)
    if result not in DISPOSITIONS:
        raise ContentPortError(f"{pointer}: unknown disposition {result!r}")
    if result == "blocked":
        raise ContentPortError(f"{pointer}: unresolved blocked disposition")
    return result


def _unique(
    records: Sequence[object], field: str, family: str
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(records):
        pointer = f"$.{family}[{index}]"
        if not isinstance(raw, dict):
            raise ContentPortError(f"{pointer}: expected an object")
        key = _text(raw.get(field), f"{pointer}.{field}")
        if key in result:
            raise ContentPortError(f"{pointer}.{field}: duplicate identity {key!r}")
        result[key] = raw
    return result


def _png_tile_count(path: Path, pointer: str) -> int:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ContentPortError(f"{pointer}: expected a PNG frame")
    width, height = struct.unpack(">II", header[16:24])
    if width == 0 or height == 0 or width % 8 or height % 8:
        raise ContentPortError(f"{pointer}: frame dimensions are not whole 8x8 tiles")
    return (width // 8) * (height // 8)


def _directory_inventory(root: Path, directory: str) -> tuple[list[Path], str, int]:
    relative = validate_relative_path(directory)
    path = root.resolve(strict=True)
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ContentPortError(f"animation frame set crosses symlink: {directory}")
    if not path.is_dir():
        raise ContentPortError(f"animation frame set is not a directory: {directory}")
    files = sorted(path.glob("*.png"), key=lambda item: item.name)
    if not files or [item.name for item in files] != [
        f"{i}.png" for i in range(len(files))
    ]:
        raise ContentPortError(
            f"animation frame set is empty or not contiguous: {directory}"
        )
    digest = hashlib.sha256()
    tile_counts = {
        _png_tile_count(item, f"animation frame {directory}/{item.name}")
        for item in files
    }
    if len(tile_counts) != 1:
        raise ContentPortError(
            f"animation frames have inconsistent tile counts: {directory}"
        )
    for item in files:
        digest.update(item.name.encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(item.read_bytes()).digest())
    return files, digest.hexdigest(), tile_counts.pop()


def verify_preserved_runtime_payloads(
    policy: Mapping[str, object], *, target_root: Path
) -> None:
    """Authenticate reviewed hand-maintained runtime files without owning them."""
    for index, raw in enumerate(policy["codePayloads"]):  # type: ignore[index]
        pointer = f"$.codePayloads[{index}]"
        target = safe_repo_path(
            target_root,
            str(raw["targetPath"]),
            allow_missing=False,
        )
        expected = str(raw["targetSha256"])
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            raise ContentPortError(
                f"{pointer}.targetSha256: preserved runtime code digest mismatch"
            )


def load_animation_policy(
    path: Path,
    *,
    donor_root: Path,
    target_root: Path,
    resident_tilesets: set[str],
) -> Mapping[str, object]:
    """Load and authenticate the one reviewed animation policy."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContentPortError(
            f"cannot read animation policy {path}: {error}"
        ) from error
    root = _record(
        document,
        "$",
        {
            "schemaVersion",
            "ownershipBoundary",
            "codePayloads",
            "residentTilesets",
            "callbacks",
            "frameSets",
            "schedules",
            "inactiveTransfers",
        },
    )
    if root["schemaVersion"] != 1:
        raise ContentPortError("$.schemaVersion: unsupported animation policy schema")
    boundary = _record(
        root["ownershipBoundary"],
        "$.ownershipBoundary",
        {"runtimeCode", "requiredFrames", "policyAuthority"},
    )
    if boundary != {
        "runtimeCode": "preserved-and-digest-checked",
        "requiredFrames": "content-port-generated",
        "policyAuthority": "animation_policy.json",
    }:
        raise ContentPortError("$.ownershipBoundary: unsupported ownership boundary")

    residents = _unique(
        _records(root, "residentTilesets"), "tileset", "residentTilesets"
    )
    for index, item in enumerate(residents.values()):
        _record(
            item, f"$.residentTilesets[{index}]", {"tileset", "disposition", "reason"}
        )
        _disposition(item["disposition"], f"$.residentTilesets[{index}].disposition")
        _text(item["reason"], f"$.residentTilesets[{index}].reason")
    if set(residents) != resident_tilesets:
        missing = sorted(resident_tilesets - set(residents))
        extra = sorted(set(residents) - resident_tilesets)
        raise ContentPortError(
            "animation resident inventory differs from tileset policy: "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    required_residents = {
        name for name, item in residents.items() if item["disposition"] == "required"
    }
    if required_residents != MANDATORY_BINDINGS:
        raise ContentPortError(
            "animation resident inventory must require exactly the reviewed bindings"
        )

    callbacks = _unique(_records(root, "callbacks"), "callback", "callbacks")
    for index, item in enumerate(callbacks.values()):
        _record(item, f"$.callbacks[{index}]", {"callback", "disposition", "reason"})
        _disposition(item["disposition"], f"$.callbacks[{index}].disposition")
        _text(item["reason"], f"$.callbacks[{index}].reason")

    code_payloads = _records(root, "codePayloads")
    if len(code_payloads) != 1:
        raise ContentPortError(
            "$.codePayloads: required runtime code is unauthenticated"
        )
    for index, raw in enumerate(code_payloads):
        pointer = f"$.codePayloads[{index}]"
        item = _record(
            raw,
            pointer,
            {
                "donor",
                "path",
                "sha256",
                "targetPath",
                "targetSha256",
                "targetOwnership",
                "disposition",
                "reason",
            },
        )
        if _text(item["donor"], f"{pointer}.donor") != "content":
            raise ContentPortError(
                f"{pointer}.donor: runtime code must use content donor"
            )
        relative = _text(item["path"], f"{pointer}.path")
        if (
            relative != "src/tileset_anims.c"
            or _text(item["targetPath"], f"{pointer}.targetPath")
            != "src/tileset_anims.c"
            or _text(item["targetOwnership"], f"{pointer}.targetOwnership")
            != "preserved"
        ):
            raise ContentPortError(
                f"{pointer}: runtime authority must be content:src/tileset_anims.c "
                "and the target adaptation must remain preserved"
            )
        expected = _digest(item["sha256"], f"{pointer}.sha256")
        _digest(item["targetSha256"], f"{pointer}.targetSha256")
        source = (
            safe_repo_path(donor_root, relative, allow_missing=False)
            if donor_root.exists()
            else None
        )
        if (
            source is not None
            and hashlib.sha256(source.read_bytes()).hexdigest() != expected
        ):
            raise ContentPortError(
                f"{pointer}.sha256: authenticated runtime code digest mismatch"
            )
        if _disposition(item["disposition"], f"{pointer}.disposition") != "required":
            raise ContentPortError(
                f"{pointer}.disposition: runtime code authority must be required"
            )
        _text(item["reason"], f"{pointer}.reason")

    frame_sets = _unique(_records(root, "frameSets"), "id", "frameSets")
    if set(frame_sets) != set(EXPECTED_FRAME_SETS):
        missing = sorted(set(EXPECTED_FRAME_SETS) - set(frame_sets))
        extra = sorted(set(frame_sets) - set(EXPECTED_FRAME_SETS))
        raise ContentPortError(
            "animation frame-set inventory differs from reviewed authority: "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    required_assets = 0
    target_paths: set[str] = set()
    for index, item in enumerate(frame_sets.values()):
        pointer = f"$.frameSets[{index}]"
        item = _record(
            item,
            pointer,
            {
                "id",
                "sourceDirectory",
                "targetDirectory",
                "frameCount",
                "sourceTilesPerFrame",
                "inventorySha256",
                "requiredFrames",
                "unusedFrames",
                "disposition",
                "evidenceKind",
                "targetSelection",
                "reason",
            },
        )
        disposition = _disposition(item["disposition"], f"{pointer}.disposition")
        directory = _text(item["sourceDirectory"], f"{pointer}.sourceDirectory")
        if donor_root.exists():
            files, actual_digest, actual_source_tiles = _directory_inventory(
                donor_root, directory
            )
        else:
            files = [Path(f"{i}.png") for i in range(int(item["frameCount"]))]
            actual_digest = str(item["inventorySha256"])
            actual_source_tiles = item["sourceTilesPerFrame"]
        count = item["frameCount"]
        if isinstance(count, bool) or not isinstance(count, int) or count != len(files):
            raise ContentPortError(f"{pointer}.frameCount: donor frame count mismatch")
        if (
            _digest(item["inventorySha256"], f"{pointer}.inventorySha256")
            != actual_digest
        ):
            raise ContentPortError(
                f"{pointer}.inventorySha256: donor frame inventory mismatch"
            )
        source_tiles = item["sourceTilesPerFrame"]
        if (
            isinstance(source_tiles, bool)
            or not isinstance(source_tiles, int)
            or source_tiles <= 0
            or source_tiles != actual_source_tiles
            or source_tiles != EXPECTED_SOURCE_TILES[str(item["id"])]
        ):
            raise ContentPortError(
                f"{pointer}.sourceTilesPerFrame: donor frame tile count mismatch"
            )
        required_frames, unused_frames = item["requiredFrames"], item["unusedFrames"]
        if (
            not isinstance(required_frames, list)
            or not isinstance(unused_frames, list)
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (*required_frames, *unused_frames)
            )
        ):
            raise ContentPortError(
                f"{pointer}: frame classifications must be integer arrays"
            )
        if len(required_frames) != len(set(required_frames)) or len(
            unused_frames
        ) != len(set(unused_frames)):
            raise ContentPortError(f"{pointer}: duplicate frame index")
        classified = set(required_frames) | set(unused_frames)
        if set(required_frames) & set(unused_frames) or classified != set(
            range(len(files))
        ):
            raise ContentPortError(f"{pointer}: unclassified donor frame")
        if (disposition == "required") != bool(required_frames):
            raise ContentPortError(
                f"{pointer}: disposition disagrees with required frames"
            )
        frame_set_id = str(item["id"])
        expected_evidence = (
            "issue-owned-candidate"
            if frame_set_id in ISSUE_OWNED_VARIANT_CANDIDATES
            else "donor-inactive"
            if frame_set_id in INACTIVE_FRAME_SETS
            else "donor-executable"
        )
        expected_selection = (
            "not-selected"
            if frame_set_id in INACTIVE_FRAME_SETS
            else "deferred-phase-2"
        )
        if (
            item["evidenceKind"] != expected_evidence
            or item["targetSelection"] != expected_selection
        ):
            raise ContentPortError(
                f"{pointer}: frame evidence or target selection differs from reviewed authority"
            )
        _text(item["reason"], f"{pointer}.reason")
        required_assets += len(required_frames)
        target_directory = _text(item["targetDirectory"], f"{pointer}.targetDirectory")
        if not target_directory.startswith("data/tilesets/"):
            raise ContentPortError(
                f"{pointer}.targetDirectory: unsafe animation target"
            )
        expected_source, expected_target, expected_required, expected_unused = (
            EXPECTED_FRAME_SETS[str(item["id"])]
        )
        if (
            directory != expected_source
            or target_directory != expected_target
            or tuple(required_frames) != expected_required
            or tuple(unused_frames) != expected_unused
        ):
            raise ContentPortError(
                f"{pointer}: frame-set classification differs from reviewed authority"
            )
        for frame in required_frames:
            target = f"{target_directory}/{frame}.png"
            if target in target_paths:
                raise ContentPortError(f"{pointer}: duplicate target path {target}")
            target_paths.add(target)
    if required_assets == 0:
        raise ContentPortError("$.frameSets: required frame assets are unauthenticated")

    schedules = _unique(_records(root, "schedules"), "tileset", "schedules")
    if set(schedules) != MANDATORY_BINDINGS:
        raise ContentPortError("animation schedules must cover every mandatory binding")
    for index, item in enumerate(schedules.values()):
        pointer = f"$.schedules[{index}]"
        item = _record(
            item,
            pointer,
            {
                "tileset",
                "callback",
                "counterMax",
                "transfers",
                "evidenceKind",
                "runtimeDisposition",
                "reason",
            },
        )
        callback = _text(item["callback"], f"{pointer}.callback")
        if callback not in callbacks:
            raise ContentPortError(f"{pointer}.callback: unclassified donor callback")
        if callbacks[callback]["disposition"] != "required":
            raise ContentPortError(f"{pointer}.callback: callback is not required")
        if item["evidenceKind"] != "donor-executable":
            raise ContentPortError(
                f"{pointer}.evidenceKind: schedule is not donor evidence"
            )
        if item["runtimeDisposition"] != "deferred-phase-2":
            raise ContentPortError(
                f"{pointer}.runtimeDisposition: target runtime choice is not deferred"
            )
        _text(item["reason"], f"{pointer}.reason")
        counter_max = item["counterMax"]
        if (
            isinstance(counter_max, bool)
            or not isinstance(counter_max, int)
            or counter_max <= 0
        ):
            raise ContentPortError(f"{pointer}.counterMax: expected a positive integer")
        transfers = item["transfers"]
        if not isinstance(transfers, list) or not transfers:
            raise ContentPortError(f"{pointer}.transfers: expected a non-empty array")
        for transfer_index, transfer in enumerate(transfers):
            tp = f"{pointer}.transfers[{transfer_index}]"
            transfer = _record(
                transfer,
                tp,
                {
                    "frameSet",
                    "period",
                    "phase",
                    "sourceTileOffset",
                    "destinationTile",
                    "tileCount",
                },
            )
            if _text(transfer["frameSet"], f"{tp}.frameSet") not in frame_sets:
                raise ContentPortError(f"{tp}.frameSet: unknown frame set")
            frame_set = _text(transfer["frameSet"], f"{tp}.frameSet")
            if frame_sets[frame_set]["disposition"] != "required":
                raise ContentPortError(f"{tp}.frameSet: frame set is not required")
            for field in ("period", "tileCount"):
                value = transfer[field]
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    raise ContentPortError(f"{tp}.{field}: expected a positive integer")
            destination = transfer["destinationTile"]
            if (
                isinstance(destination, bool)
                or not isinstance(destination, int)
                or destination < 0
            ):
                raise ContentPortError(
                    f"{tp}.destinationTile: expected a non-negative integer"
                )
            source_offset = transfer["sourceTileOffset"]
            if (
                isinstance(source_offset, bool)
                or not isinstance(source_offset, int)
                or source_offset < 0
            ):
                raise ContentPortError(
                    f"{tp}.sourceTileOffset: expected a non-negative integer"
                )
            if (
                source_offset + transfer["tileCount"]
                > frame_sets[frame_set]["sourceTilesPerFrame"]
            ):
                raise ContentPortError(f"{tp}: source tile slice exceeds donor frame")
            phase = transfer["phase"]
            if (
                isinstance(phase, bool)
                or not isinstance(phase, int)
                or not 0 <= phase < transfer["period"]
            ):
                raise ContentPortError(f"{tp}.phase: expected an integer within period")
        actual_transfers = tuple(
            (
                transfer["frameSet"],
                transfer["period"],
                transfer["phase"],
                transfer["sourceTileOffset"],
                transfer["destinationTile"],
                transfer["tileCount"],
            )
            for transfer in transfers
        )
        expected_callback, expected_counter, expected_transfers = EXPECTED_SCHEDULES[
            str(item["tileset"])
        ]
        if (
            callback != expected_callback
            or counter_max != expected_counter
            or actual_transfers != expected_transfers
        ):
            raise ContentPortError(
                f"{pointer}: donor schedule differs from reviewed authority"
            )
    inactive = _records(root, "inactiveTransfers")
    if not inactive:
        raise ContentPortError(
            "$.inactiveTransfers: ambiguous donor transfers remain unclassified"
        )
    inactive_by_id = _unique(inactive, "id", "inactiveTransfers")
    if set(inactive_by_id) != EXPECTED_INACTIVE_TRANSFERS:
        missing = sorted(EXPECTED_INACTIVE_TRANSFERS - set(inactive_by_id))
        extra = sorted(set(inactive_by_id) - EXPECTED_INACTIVE_TRANSFERS)
        raise ContentPortError(
            "inactive transfer inventory differs from reviewed authority: "
            f"missing={missing[:1]}, extra={extra[:1]}"
        )
    for index, raw in enumerate(inactive_by_id.values()):
        pointer = f"$.inactiveTransfers[{index}]"
        item = _record(raw, pointer, {"id", "disposition", "reason"})
        if (
            _disposition(item["disposition"], f"{pointer}.disposition")
            != "intentionally-unused"
        ):
            raise ContentPortError(
                f"{pointer}.disposition: inactive transfer must be intentionally unused"
            )
        _text(item["reason"], f"{pointer}.reason")
    if set(callbacks) != EXPECTED_CALLBACKS:
        raise ContentPortError(
            "animation callback inventory differs from reviewed authority"
        )
    policy = MappingProxyType(document)
    verify_preserved_runtime_payloads(policy, target_root=target_root)
    return policy


def required_frame_payloads(
    policy: Mapping[str, object],
) -> tuple[tuple[str, str], ...]:
    """Return (donor source, generated target) pairs owned by content-port."""
    result: list[tuple[str, str]] = []
    for raw in policy["frameSets"]:  # type: ignore[index]
        for frame in raw["requiredFrames"]:
            result.append(
                (
                    f"{raw['sourceDirectory']}/{frame}.png",
                    f"{raw['targetDirectory']}/{frame}.png",
                )
            )
    return tuple(sorted(result))
