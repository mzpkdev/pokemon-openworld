from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import struct

import pytest

from tools.e2e.save_journey import cold_restart_and_continue, save_from_start_menu
from tools.e2e.skyemu import (
    INTEGRITY_REQUEST_STATUS_OFFSET,
    IntegrityLoadError,
    IntegrityLoadPhase,
    IntegrityLoadStatus,
    IntegrityMapLoadRequest,
)
from tools.e2e.tests.integrity.manifest import (
    integrity_manifest_path,
    load_manifest_maps,
)
from tools.e2e.trainer_battle_journey import (
    MOVE_WATER_SPOUT,
    TrainerBattleScenarioRequest,
    disable_battle_animations_through_options,
    run_ordinary_trainer_battle,
    set_battle_party_through_debug_menu,
)


BG_VRAM = 0x06000000
TILE_SIZE_4BPP = 32
TRAINER_CALVIN_1 = 318


@dataclass(frozen=True)
class TransferOracle:
    name: str
    slot: str
    counter: int
    source: str
    destination_tile: int
    tile_count: int
    source_tile: int = 0


@dataclass(frozen=True)
class MapOracle:
    name: str
    primary_callback: str | None
    secondary_callback: str | None
    primary_max: int
    secondary_max: int
    transfers: tuple[TransferOracle, ...]


VISUAL_ORACLES = (
    MapOracle(
        "NewBarkTown",
        "TilesetAnim_JohtoGeneral",
        None,
        256,
        0,
        (
            TransferOracle(
                "outdoor-flower-frame0",
                "primary",
                2,
                "sTilesetAnims_JohtoGeneral_Flower0",
                508,
                4,
            ),
            TransferOracle(
                "outdoor-flower-frame1",
                "primary",
                18,
                "sTilesetAnims_JohtoGeneral_Flower1",
                508,
                4,
            ),
            TransferOracle(
                "outdoor-water-frame0",
                "primary",
                3,
                "sTilesetAnims_JohtoGeneral_Water0",
                450,
                12,
                source_tile=34,
            ),
            TransferOracle(
                "outdoor-water-frame1",
                "primary",
                19,
                "sTilesetAnims_JohtoGeneral_Water1",
                450,
                12,
                source_tile=34,
            ),
        ),
    ),
    MapOracle(
        "NationalPark_Normal",
        "TilesetAnim_General_Frlg",
        "TilesetAnim_JohtoSecondary",
        640,
        960,
        (
            TransferOracle(
                "national-park-small-fountain-frame0",
                "secondary",
                1,
                "sTilesetAnims_NationalParkSmall0",
                640 + 104,
                8,
            ),
            TransferOracle(
                "national-park-small-fountain-frame1",
                "secondary",
                13,
                "sTilesetAnims_NationalParkSmall1",
                640 + 104,
                8,
            ),
            TransferOracle(
                "national-park-large-fountain-frame1",
                "secondary",
                10,
                "sTilesetAnims_NationalParkLarge1",
                640 + 88,
                8,
            ),
            TransferOracle(
                "national-park-large-fountain-frame2",
                "secondary",
                20,
                "sTilesetAnims_NationalParkLarge2",
                640 + 88,
                8,
            ),
        ),
    ),
    MapOracle(
        "EcruteakCity_Theater",
        None,
        "TilesetAnim_JohtoSecondary",
        0,
        960,
        (
            TransferOracle(
                "ecruteak-theater-flower-frame1",
                "secondary",
                10,
                "sTilesetAnims_EcruteakTheater1",
                640 + 104,
                4,
            ),
            TransferOracle(
                "ecruteak-theater-flower-frame2",
                "secondary",
                20,
                "sTilesetAnims_EcruteakTheater2",
                640 + 104,
                4,
            ),
        ),
    ),
    MapOracle(
        "AzaleaTown_Gym",
        None,
        "TilesetAnim_JohtoSecondary",
        0,
        960,
        (
            TransferOracle(
                "azalea-gym-flower-frame1",
                "secondary",
                10,
                "sTilesetAnims_AzaleaGym1",
                640 + 99,
                4,
            ),
            TransferOracle(
                "azalea-gym-flower-frame2",
                "secondary",
                20,
                "sTilesetAnims_AzaleaGym2",
                640 + 99,
                4,
            ),
        ),
    ),
    MapOracle(
        "BlackthornCity_Gym",
        None,
        "TilesetAnim_JohtoSecondary",
        0,
        160,
        (
            TransferOracle(
                "blackthorn-gym-tile-frame0",
                "secondary",
                1,
                "sTilesetAnims_BlackthornGym0",
                640 + 321,
                4,
            ),
            TransferOracle(
                "blackthorn-gym-tile-frame1",
                "secondary",
                17,
                "sTilesetAnims_BlackthornGym1",
                640 + 321,
                4,
            ),
        ),
    ),
    MapOracle(
        "RustboroCity",
        "TilesetAnim_General",
        "TilesetAnim_Rustboro",
        256,
        256,
        (
            TransferOracle(
                "hoenn-water-frame0",
                "primary",
                1,
                "gTilesetAnims_General_Water_Frame0",
                432,
                30,
            ),
            TransferOracle(
                "hoenn-water-frame1",
                "primary",
                17,
                "gTilesetAnims_General_Water_Frame1",
                432,
                30,
            ),
            TransferOracle(
                "hoenn-windy-water-frame7",
                "secondary",
                1,
                "gTilesetAnims_Rustboro_WindyWater_Frame7",
                512 + 132,
                4,
            ),
            TransferOracle(
                "hoenn-windy-water-frame0",
                "secondary",
                9,
                "gTilesetAnims_Rustboro_WindyWater_Frame0",
                512 + 132,
                4,
            ),
        ),
    ),
    MapOracle(
        "MtEmber_RubyPath_B4F_Frlg",
        "TilesetAnim_General_Frlg",
        "TilesetAnim_MtEmber",
        640,
        256,
        (
            TransferOracle(
                "kanto-sevii-water-frame0",
                "primary",
                1,
                "sTilesetAnims_General_Water_Current_LandWatersEdge_Frame0",
                416,
                48,
            ),
            TransferOracle(
                "kanto-sevii-water-frame1",
                "primary",
                17,
                "sTilesetAnims_General_Water_Current_LandWatersEdge_Frame1",
                416,
                48,
            ),
            TransferOracle(
                "kanto-sevii-steam-frame1",
                "secondary",
                16,
                "sTilesetAnims_MtEmber_Steam_Frame1",
                896,
                8,
            ),
            TransferOracle(
                "kanto-sevii-steam-frame2",
                "secondary",
                32,
                "sTilesetAnims_MtEmber_Steam_Frame2",
                896,
                8,
            ),
        ),
    ),
)


LIFECYCLE_ORACLE = MapOracle(
    "NationalPark_Normal",
    "TilesetAnim_General_Frlg",
    "TilesetAnim_JohtoSecondary",
    640,
    960,
    (
        TransferOracle(
            "primary-first-dispatch",
            "primary",
            1,
            "sTilesetAnims_General_Water_Current_LandWatersEdge_Frame0",
            416,
            48,
        ),
        TransferOracle(
            "secondary-first-dispatch",
            "secondary",
            1,
            "sTilesetAnims_NationalParkSmall0",
            640 + 104,
            8,
        ),
    ),
)


def _quickstart(game) -> None:
    game.wait_for_callback("CB2_InitTitleScreen", max_frames=6_000)
    for _ in range(3_000):
        game.press("Select")
        if game.callback_is("CB2_Overworld"):
            game.wait_for_controls_unlocked(max_frames=1_200)
            return
    raise AssertionError("Quickstart did not reach the overworld")


def _maps_by_name():
    return {
        entry.name: entry for entry in load_manifest_maps(integrity_manifest_path())
    }


def _callback_value(game, symbol: str | None) -> int:
    return 0 if symbol is None else game.address(symbol) | 1


def _state(game) -> tuple[int, int, int, int, int, int]:
    return (
        game.read_u16(game.address("sPrimaryTilesetAnimCounter")),
        game.read_u16(game.address("sPrimaryTilesetAnimCounterMax")),
        game.read_u32(game.address("sPrimaryTilesetAnimCallback")),
        game.read_u16(game.address("sSecondaryTilesetAnimCounter")),
        game.read_u16(game.address("sSecondaryTilesetAnimCounterMax")),
        game.read_u32(game.address("sSecondaryTilesetAnimCallback")),
    )


def _read_bytes(game, address: int, size: int) -> bytes:
    return b"".join(
        game.read(address + offset, min(128, size - offset))
        for offset in range(0, size, 128)
    )


def _frame_bytes(game, transfer: TransferOracle) -> bytes:
    size = transfer.tile_count * TILE_SIZE_4BPP
    source = game.address(transfer.source) + transfer.source_tile * TILE_SIZE_4BPP
    return _read_bytes(game, source, size)


def _vram_bytes(game, transfer: TransferOracle) -> bytes:
    return _read_bytes(
        game,
        BG_VRAM + transfer.destination_tile * TILE_SIZE_4BPP,
        transfer.tile_count * TILE_SIZE_4BPP,
    )


def _queue(game) -> tuple[tuple[int, int, int], ...]:
    count = game.read_u8(game.address("sTilesetDMA3TransferBufferSize"))
    assert count <= 20
    payload = game.read(game.address("sTilesetDMA3TransferBuffer"), count * 12)
    return tuple(
        struct.unpack_from("<IIHxx", payload, index * 12) for index in range(count)
    )


def _expected_queue_entry(game, transfer: TransferOracle) -> tuple[int, int, int]:
    return (
        game.address(transfer.source) + transfer.source_tile * TILE_SIZE_4BPP,
        BG_VRAM + transfer.destination_tile * TILE_SIZE_4BPP,
        transfer.tile_count * TILE_SIZE_4BPP,
    )


def _evidence_path(request) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
    output = Path(os.environ["E2E_RESULTS"]) / os.environ["E2E_SUITE"] / safe_name
    output.mkdir(parents=True, exist_ok=True)
    return output / "tileset-animation-evidence.json"


def _write_evidence(path: Path, evidence: dict) -> None:
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")


def _load_with_reset_and_transfers(game, request_id: int, oracle: MapOracle) -> dict:
    map_entry = _maps_by_name()[oracle.name]
    request = IntegrityMapLoadRequest(
        request_id=request_id,
        map_group=map_entry.group,
        map_num=map_entry.number,
        suppress_scripts=True,
        suppress_events=True,
    )
    address = game.address("gIntegrityMapLoadRequest")
    game.write(address, request.payload())
    game.write_u8(
        address + INTEGRITY_REQUEST_STATUS_OFFSET,
        IntegrityLoadStatus.PENDING,
    )

    expected_callbacks = (
        _callback_value(game, oracle.primary_callback),
        _callback_value(game, oracle.secondary_callback),
    )
    reset = None
    observed: dict[str, dict] = {}
    categories: dict[str, list[TransferOracle]] = {}
    for transfer in oracle.transfers:
        if "-frame" not in transfer.name:
            continue
        category = transfer.name.rsplit("-frame", 1)[0]
        categories.setdefault(category, []).append(transfer)
    dma_timeline = []
    result = game.integrity_result()
    for elapsed in range(2_400):
        game.step()
        result = game.integrity_result()
        (
            primary,
            primary_max,
            primary_callback,
            secondary,
            secondary_max,
            secondary_callback,
        ) = _state(game)
        callbacks = (primary_callback, secondary_callback)
        if (
            reset is None
            and result.status is not IntegrityLoadStatus.ERROR
            and game.map_id() == map_entry.map_id
            and callbacks == expected_callbacks
            and primary == 0
            and secondary == 0
        ):
            reset = {
                "elapsedFrame": elapsed + 1,
                "phase": result.phase.name,
                "status": result.status.name,
                "primaryCounter": primary,
                "secondaryCounter": secondary,
                "primaryCallback": f"0x{primary_callback:08x}",
                "secondaryCallback": f"0x{secondary_callback:08x}",
            }
        if reset is not None:
            queue = _queue(game)
            dma_timeline.append(
                {
                    "elapsedFrame": elapsed + 1,
                    "primaryCounter": primary,
                    "secondaryCounter": secondary,
                    "entries": [
                        {
                            "source": f"0x{source:08x}",
                            "destination": f"0x{destination:08x}",
                            "size": size,
                        }
                        for source, destination, size in queue
                    ],
                }
            )
            for category, transfers in categories.items():
                slot = transfers[0].slot
                counter = primary if slot == "primary" else secondary
                last_reviewed_counter = max(transfer.counter for transfer in transfers)
                destination = BG_VRAM + transfers[0].destination_tile * TILE_SIZE_4BPP
                destination_entries = tuple(
                    entry for entry in queue if entry[1] == destination
                )
                expected_now = tuple(
                    _expected_queue_entry(game, transfer)
                    for transfer in transfers
                    if transfer.counter == counter
                )
                if counter <= last_reviewed_counter:
                    assert destination_entries == expected_now, (
                        f"{oracle.name} {category} DMA at counter {counter} "
                        f"expected={expected_now!r}, actual={destination_entries!r}"
                    )
            for transfer in oracle.transfers:
                counter = primary if transfer.slot == "primary" else secondary
                counter_max = (
                    oracle.primary_max
                    if transfer.slot == "primary"
                    else oracle.secondary_max
                )
                visible_counter = (transfer.counter + 1) % counter_max
                if transfer.name in observed or counter != visible_counter:
                    continue
                expected = _frame_bytes(game, transfer)
                actual = _vram_bytes(game, transfer)
                assert actual == expected, (
                    f"{oracle.name} {transfer.name} VRAM differs at "
                    f"{transfer.slot} visible counter {counter}"
                )
                observed[transfer.name] = {
                    "slot": transfer.slot,
                    "scheduledCounter": transfer.counter,
                    "visibleCounter": counter,
                    "sourceSymbol": transfer.source,
                    "sourceAddress": f"0x{game.address(transfer.source):08x}",
                    "sourceTile": transfer.source_tile,
                    "destinationTile": transfer.destination_tile,
                    "byteCount": len(expected),
                    "exactBytes": expected.hex(),
                    "elapsedFrame": elapsed + 1,
                }
        if result.status in (
            IntegrityLoadStatus.SUCCESS,
            IntegrityLoadStatus.ERROR,
        ) and len(observed) == len(oracle.transfers):
            break
    assert result.status is IntegrityLoadStatus.SUCCESS, result
    assert result.phase is IntegrityLoadPhase.FIELD_READY
    assert result.error is IntegrityLoadError.NONE
    assert reset is not None, f"{oracle.name} scheduler reset was not observed"
    assert (primary_max, secondary_max) == (oracle.primary_max, oracle.secondary_max)
    assert callbacks == expected_callbacks
    assert set(observed) == {transfer.name for transfer in oracle.transfers}
    for category, transfers in categories.items():
        assert len(transfers) >= 2, f"{category} has only one reviewed frame oracle"
        assert len({_frame_bytes(game, transfer) for transfer in transfers}) >= 2, (
            f"{category} reviewed frames are not byte-distinct"
        )
    game.wait_for_controls_unlocked(max_frames=1_200)
    return {
        "map": oracle.name,
        "mapId": {"group": map_entry.group, "number": map_entry.number},
        "callbacks": {
            "primary": oracle.primary_callback,
            "secondary": oracle.secondary_callback,
        },
        "counterMax": {
            "primary": oracle.primary_max,
            "secondary": oracle.secondary_max,
        },
        "reset": reset,
        "dmaTimeline": dma_timeline,
        "transfers": observed,
    }


class LifecycleRecorder:
    def __init__(self, game, oracle: MapOracle):
        self.game = game
        self.oracle = oracle
        self.samples: list[dict] = []
        self._step = game.step
        self.capture_queue = False
        self.watched_transfers: tuple[TransferOracle, ...] = ()

    def __enter__(self):
        def traced_step(frames: int = 1):
            for _ in range(frames):
                self._step()
                self._sample()

        self.game.step = traced_step
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.game.step = self._step

    def _sample(self) -> None:
        (
            primary,
            primary_max,
            primary_callback,
            secondary,
            secondary_max,
            secondary_callback,
        ) = _state(self.game)
        sample = {
            "primary": primary,
            "primaryMax": primary_max,
            "primaryCallback": primary_callback,
            "secondary": secondary,
            "secondaryMax": secondary_max,
            "secondaryCallback": secondary_callback,
            "callback2": self.game.read_u32(self.game.address("gMain") + 4),
            "queue": None,
            "transfers": {},
        }
        expected_callbacks = (
            _callback_value(self.game, self.oracle.primary_callback),
            _callback_value(self.game, self.oracle.secondary_callback),
        )
        if self.capture_queue or (
            (primary_callback, secondary_callback) == expected_callbacks
            and primary == 1
            and secondary == 1
        ):
            sample["queue"] = _queue(self.game)
        for transfer in (*self.oracle.transfers, *self.watched_transfers):
            counter = primary if transfer.slot == "primary" else secondary
            counter_max = (
                self.oracle.primary_max
                if transfer.slot == "primary"
                else self.oracle.secondary_max
            )
            if counter == (transfer.counter + 1) % counter_max:
                sample["transfers"][transfer.name] = _vram_bytes(
                    self.game, transfer
                ) == _frame_bytes(self.game, transfer)
        self.samples.append(sample)

    def mark(self) -> int:
        return len(self.samples)

    def assert_return_cycle(self, mark: int, label: str, reset_callback: str) -> dict:
        expected_callbacks = (
            _callback_value(self.game, self.oracle.primary_callback),
            _callback_value(self.game, self.oracle.secondary_callback),
        )
        expected_max = self.oracle.primary_max, self.oracle.secondary_max
        reset_callback_value = _callback_value(self.game, reset_callback)
        overworld_callback = _callback_value(self.game, "CB2_Overworld")
        try:
            return_entry = next(
                index
                for index in range(mark, len(self.samples))
                if self.samples[index]["callback2"] == reset_callback_value
            )
        except StopIteration as error:
            observed = sorted({sample["callback2"] for sample in self.samples[mark:]})
            raise AssertionError(
                f"{label} never entered {reset_callback} "
                f"({reset_callback_value:#x}); callback2={observed!r}"
            ) from error

        reset_index = None
        field_index = None
        for index in range(return_entry, len(self.samples)):
            sample = self.samples[index]
            callbacks = sample["primaryCallback"], sample["secondaryCallback"]
            maxima = sample["primaryMax"], sample["secondaryMax"]
            if sample["callback2"] == overworld_callback:
                field_index = index
                if (
                    callbacks == expected_callbacks
                    and maxima == expected_max
                    and sample["primary"] == 0
                    and sample["secondary"] == 0
                ):
                    reset_index = index
                break
            if (
                sample["callback2"] == reset_callback_value
                and callbacks == expected_callbacks
                and maxima == expected_max
                and sample["primary"] == 0
                and sample["secondary"] == 0
            ):
                reset_index = index
        assert reset_index is not None, (
            f"{label} left {reset_callback} without an exact zero-counter reset"
        )
        assert field_index is not None, f"{label} never returned to CB2_Overworld"

        field_sample = self.samples[field_index]
        assert (
            field_sample["primaryCallback"],
            field_sample["secondaryCallback"],
        ) == expected_callbacks
        assert (
            field_sample["primaryMax"],
            field_sample["secondaryMax"],
        ) == expected_max
        assert field_sample["primary"] == field_sample["secondary"]
        assert field_sample["primary"] in (0, 1)
        queue_index = field_index + (field_sample["primary"] == 0)
        assert queue_index < len(self.samples), f"{label} ended before first dispatch"
        queue_sample = self.samples[queue_index]
        assert queue_sample["callback2"] == overworld_callback
        assert (queue_sample["primary"], queue_sample["secondary"]) == (1, 1)
        expected_queue = tuple(
            _expected_queue_entry(self.game, transfer)
            for transfer in self.oracle.transfers
        )
        assert queue_sample["queue"] == expected_queue, (
            f"{label} first eligible queue was wrong, missing, extra, or stale: "
            f"expected={expected_queue!r}, actual={queue_sample['queue']!r}"
        )

        visible_index = queue_index + 1
        assert visible_index < len(self.samples), f"{label} ended before first VBlank"
        visible_sample = self.samples[visible_index]
        assert visible_sample["callback2"] == overworld_callback
        assert (visible_sample["primary"], visible_sample["secondary"]) == (2, 2)
        transfers = {}
        for transfer in self.oracle.transfers:
            assert visible_sample["transfers"].get(transfer.name), (
                f"{label} first {transfer.slot} VBlank transfer was missing or stale"
            )
            transfers[transfer.name] = {
                "queueSample": queue_index,
                "visibleSample": visible_index,
                "slot": transfer.slot,
                "scheduledCounter": transfer.counter,
                "visibleCounter": transfer.counter + 1,
                "sourceSymbol": transfer.source,
                "destinationTile": transfer.destination_tile,
                "byteCount": transfer.tile_count * TILE_SIZE_4BPP,
            }
        return {
            "resetCallback": reset_callback,
            "resetCallbackAddress": f"0x{reset_callback_value:08x}",
            "fieldCallback": "CB2_Overworld",
            "fieldCallbackAddress": f"0x{overworld_callback:08x}",
            "returnEntrySample": return_entry,
            "resetSample": reset_index,
            "engineResetCounter": 0,
            "firstFieldSample": field_index,
            "firstTransfers": transfers,
        }


def _next_primary_transfer(counter: int) -> TransferOracle:
    for delta in range(1, 641):
        scheduled = (counter + delta) % 640
        if scheduled % 8 == 0:
            frame = (scheduled // 8) % 8
            return TransferOracle(
                "save-primary-next",
                "primary",
                scheduled,
                f"sTilesetAnims_General_SandWatersEdge_Frame{frame}",
                464,
                18,
            )
        if scheduled % 16 == 1:
            frame = (scheduled // 16) % 8
            return TransferOracle(
                "save-primary-next",
                "primary",
                scheduled,
                f"sTilesetAnims_General_Water_Current_LandWatersEdge_Frame{frame}",
                416,
                48,
            )
        if scheduled % 16 == 2:
            frame = (scheduled // 16) % 5
            return TransferOracle(
                "save-primary-next",
                "primary",
                scheduled,
                f"sTilesetAnims_General_Flower_Frame{frame}",
                508,
                4,
            )
    raise AssertionError("primary scheduler has no subsequent transfer")


def _next_secondary_transfer(counter: int) -> TransferOracle:
    red_frames = (0, 1, 2, 1)
    yellow_frames = (2, 1, 0, 1)
    for delta in range(1, 961):
        scheduled = (counter + delta) % 960
        if scheduled % 10 == 0:
            frame = (scheduled // 10) % 4
            return TransferOracle(
                "save-secondary-next",
                "secondary",
                scheduled,
                f"sTilesetAnims_NationalParkLarge{frame}",
                640 + 88,
                8,
            )
        if scheduled % 12 == 1:
            frame = (scheduled // 12) % 5
            return TransferOracle(
                "save-secondary-next",
                "secondary",
                scheduled,
                f"sTilesetAnims_NationalParkSmall{frame}",
                640 + 104,
                8,
            )
        if scheduled % 16 == 2:
            frame = red_frames[(scheduled // 16) % 4]
            return TransferOracle(
                "save-secondary-next",
                "secondary",
                scheduled,
                f"sTilesetAnims_NationalParkRed{frame}",
                640 + 96,
                4,
            )
        if scheduled % 16 == 12:
            frame = yellow_frames[(scheduled // 16) % 4]
            return TransferOracle(
                "save-secondary-next",
                "secondary",
                scheduled,
                f"sTilesetAnims_NationalParkYellow{frame}",
                640 + 100,
                4,
            )
    raise AssertionError("secondary scheduler has no subsequent transfer")


def _prove_next_live_transfers(
    game,
    recorder: LifecycleRecorder,
    transfers: tuple[TransferOracle, ...],
) -> dict[str, dict]:
    start = _state(game)
    distances = {}
    for transfer in transfers:
        current = start[0] if transfer.slot == "primary" else start[3]
        counter_max = 640 if transfer.slot == "primary" else 960
        distances[transfer.name] = (transfer.counter - current) % counter_max
        assert distances[transfer.name] > 0

    mark = recorder.mark()
    recorder.capture_queue = True
    recorder.watched_transfers = transfers
    try:
        game.step(max(distances.values()) + 1)
    finally:
        recorder.capture_queue = False
        recorder.watched_transfers = ()

    overworld_callback = _callback_value(game, "CB2_Overworld")
    expected_callbacks = (
        _callback_value(game, LIFECYCLE_ORACLE.primary_callback),
        _callback_value(game, LIFECYCLE_ORACLE.secondary_callback),
    )
    for sample in recorder.samples[mark:]:
        assert sample["callback2"] == overworld_callback
        assert (
            sample["primaryCallback"],
            sample["secondaryCallback"],
        ) == expected_callbacks

    evidence = {}
    for transfer in transfers:
        distance = distances[transfer.name]
        scheduled_index = mark + distance - 1
        visible_index = scheduled_index + 1
        scheduled_sample = recorder.samples[scheduled_index]
        visible_sample = recorder.samples[visible_index]
        slot_start = BG_VRAM if transfer.slot == "primary" else BG_VRAM + 640 * 32
        slot_end = (
            BG_VRAM + 640 * 32 if transfer.slot == "primary" else BG_VRAM + 1024 * 32
        )
        for sample in recorder.samples[mark:scheduled_index]:
            assert not any(
                slot_start <= entry[1] < slot_end for entry in sample["queue"]
            ), f"{transfer.slot} queued an earlier transfer than reviewed"

        scheduled_counter = (
            scheduled_sample["primary"]
            if transfer.slot == "primary"
            else scheduled_sample["secondary"]
        )
        assert scheduled_counter == transfer.counter
        slot_queue = tuple(
            entry
            for entry in scheduled_sample["queue"]
            if slot_start <= entry[1] < slot_end
        )
        expected_entry = _expected_queue_entry(game, transfer)
        assert slot_queue == (expected_entry,)

        counter_max = 640 if transfer.slot == "primary" else 960
        visible_counter = (
            visible_sample["primary"]
            if transfer.slot == "primary"
            else visible_sample["secondary"]
        )
        assert visible_counter == (transfer.counter + 1) % counter_max
        assert visible_sample["transfers"].get(transfer.name)
        current = start[0] if transfer.slot == "primary" else start[3]
        evidence[transfer.slot] = {
            "slot": transfer.slot,
            "fieldCallback": "CB2_Overworld",
            "counterBefore": current,
            "scheduledCounter": transfer.counter,
            "visibleCounter": visible_counter,
            "sourceSymbol": transfer.source,
            "destinationTile": transfer.destination_tile,
            "byteCount": transfer.tile_count * TILE_SIZE_4BPP,
            "queueEntry": {
                "source": f"0x{expected_entry[0]:08x}",
                "destination": f"0x{expected_entry[1]:08x}",
                "size": expected_entry[2],
            },
            "exactBytes": _frame_bytes(game, transfer).hex(),
        }
    return evidence


def _prove_save_continuity(
    game,
    recorder: LifecycleRecorder,
    mark: int,
    before: tuple[int, int, int, int, int, int],
    after: tuple[int, int, int, int, int, int],
) -> dict:
    expected_callback2 = _callback_value(game, "CB2_Overworld")
    expected_callbacks = (
        _callback_value(game, LIFECYCLE_ORACLE.primary_callback),
        _callback_value(game, LIFECYCLE_ORACLE.secondary_callback),
    )
    expected_maxima = (
        LIFECYCLE_ORACLE.primary_max,
        LIFECYCLE_ORACLE.secondary_max,
    )
    samples = recorder.samples[mark:]
    assert samples, "real save produced no lifecycle samples"

    previous_primary = before[0]
    previous_secondary = before[3]
    primary_wraps = 0
    secondary_wraps = 0
    scheduler_samples = 0
    vblank_only_samples = 0
    for index, sample in enumerate(samples, mark):
        assert sample["callback2"] == expected_callback2, (
            f"real save sample {index} left CB2_Overworld"
        )
        assert (
            sample["primaryCallback"],
            sample["secondaryCallback"],
        ) == expected_callbacks, f"real save sample {index} changed scheduler callbacks"
        assert (
            sample["primaryMax"],
            sample["secondaryMax"],
        ) == expected_maxima, f"real save sample {index} changed scheduler maxima"

        current = sample["primary"], sample["secondary"]
        previous = previous_primary, previous_secondary
        if current == previous:
            # A flash write can occupy the CPU across a video frame. SkyEmu still
            # returns that VBlank from /step, but no main-loop scheduler sample
            # exists for it; both counters and identities must remain untouched.
            vblank_only_samples += 1
            continue

        expected_primary = (previous_primary + 1) % LIFECYCLE_ORACLE.primary_max
        expected_secondary = (previous_secondary + 1) % LIFECYCLE_ORACLE.secondary_max
        assert sample["primary"] == expected_primary, (
            f"real save sample {index} primary discontinuity: "
            f"expected {expected_primary}, got {sample['primary']}"
        )
        assert sample["secondary"] == expected_secondary, (
            f"real save sample {index} secondary discontinuity: "
            f"expected {expected_secondary}, got {sample['secondary']}"
        )
        primary_wraps += expected_primary < previous_primary
        secondary_wraps += expected_secondary < previous_secondary
        previous_primary = expected_primary
        previous_secondary = expected_secondary
        scheduler_samples += 1

    assert (previous_primary, previous_secondary) == (after[0], after[3])
    return {
        "sampleCount": len(samples),
        "schedulerSampleCount": scheduler_samples,
        "vblankOnlySampleCount": vblank_only_samples,
        "primary": {
            "startCounter": before[0],
            "endCounter": after[0],
            "counterMax": LIFECYCLE_ORACLE.primary_max,
            "wraps": primary_wraps,
        },
        "secondary": {
            "startCounter": before[3],
            "endCounter": after[3],
            "counterMax": LIFECYCLE_ORACLE.secondary_max,
            "wraps": secondary_wraps,
        },
    }


def test_required_visual_categories_and_regional_coexistence(integrity_game, request):
    evidence_path = _evidence_path(request)
    evidence = {"schemaVersion": 1, "maps": []}
    _write_evidence(evidence_path, evidence)
    _quickstart(integrity_game)
    for index, oracle in enumerate(VISUAL_ORACLES, 1):
        evidence["maps"].append(
            _load_with_reset_and_transfers(
                integrity_game,
                0xA7000000 | index,
                oracle,
            )
        )
        _write_evidence(evidence_path, evidence)


@pytest.mark.long_journey
def test_both_slots_restart_after_field_menu_battle_save_and_continue(
    integrity_game, request
):
    evidence_path = _evidence_path(request)
    evidence = {"schemaVersion": 1, "lifecycles": {}}
    _write_evidence(evidence_path, evidence)
    _quickstart(integrity_game)
    set_battle_party_through_debug_menu(integrity_game)

    with LifecycleRecorder(integrity_game, LIFECYCLE_ORACLE) as recorder:
        mark = recorder.mark()
        _load_with_reset_and_transfers(
            integrity_game,
            0xA7100001,
            LIFECYCLE_ORACLE,
        )
        evidence["lifecycles"]["mapTransition"] = recorder.assert_return_cycle(
            mark, "map transition", "CB2_LoadMap2"
        )
        _write_evidence(evidence_path, evidence)

        mark = recorder.mark()
        disable_battle_animations_through_options(integrity_game)
        evidence["lifecycles"]["menuReturn"] = recorder.assert_return_cycle(
            mark, "menu return", "CB2_ReturnToFieldLocal"
        )
        _write_evidence(evidence_path, evidence)

        mark = recorder.mark()
        run_ordinary_trainer_battle(
            integrity_game,
            TrainerBattleScenarioRequest(0xA7100002, TRAINER_CALVIN_1),
            move_id=MOVE_WATER_SPOUT,
        )
        evidence["lifecycles"]["battleReturn"] = recorder.assert_return_cycle(
            mark, "battle return", "CB2_ReturnToFieldLocal"
        )
        _write_evidence(evidence_path, evidence)

        save_mark = recorder.mark()
        before_save = _state(integrity_game)
        saved = save_from_start_menu(integrity_game)
        integrity_game.advance_until(
            lambda: (
                integrity_game.callback_is("CB2_Overworld")
                and not integrity_game.controls_locked()
                and integrity_game.script_status() == 2
            ),
            description="field return after real save",
            max_pulses=600,
            button="B",
            pulse_frames=4,
        )
        after_save = _state(integrity_game)
        assert after_save[2] == _callback_value(
            integrity_game, LIFECYCLE_ORACLE.primary_callback
        )
        assert after_save[5] == _callback_value(
            integrity_game, LIFECYCLE_ORACLE.secondary_callback
        )
        assert after_save[:2] != before_save[:2]
        save_continuity = _prove_save_continuity(
            integrity_game,
            recorder,
            save_mark,
            before_save,
            after_save,
        )
        primary_next = _next_primary_transfer(after_save[0])
        secondary_next = _next_secondary_transfer(after_save[3])
        live_evidence = _prove_next_live_transfers(
            integrity_game,
            recorder,
            (primary_next, secondary_next),
        )
        evidence["lifecycles"]["realSave"] = {
            "saveCounter": saved.active_slot.counter,
            "saveSlot": saved.active_slot.physical_index,
            "schedulerStayedLive": True,
            "continuity": save_continuity,
            "primaryCounterBefore": before_save[0],
            "primaryCounterAfter": after_save[0],
            "secondaryCounterBefore": before_save[3],
            "secondaryCounterAfter": after_save[3],
            "primaryCallback": LIFECYCLE_ORACLE.primary_callback,
            "secondaryCallback": LIFECYCLE_ORACLE.secondary_callback,
            "nextPrimaryTransfer": live_evidence["primary"],
            "nextSecondaryTransfer": live_evidence["secondary"],
        }
        _write_evidence(evidence_path, evidence)

        mark = recorder.mark()
        cold_restart_and_continue(integrity_game)
        assert integrity_game.map_id() == _maps_by_name()[LIFECYCLE_ORACLE.name].map_id
        evidence["lifecycles"]["coldRestartContinue"] = {
            **recorder.assert_return_cycle(
                mark, "cold restart and Continue", "CB2_ReturnToFieldLocal"
            ),
            "oldProcessExited": True,
            "continuedMap": LIFECYCLE_ORACLE.name,
        }
        _write_evidence(evidence_path, evidence)
