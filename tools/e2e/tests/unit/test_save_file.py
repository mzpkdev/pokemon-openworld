from pathlib import Path
import copy
import json
import struct

import pytest

from tools.e2e.save_file import (
    SAVE_BLOCK1_SIZE,
    SECTOR_FOOTER_OFFSET,
    SECTOR_SIZE,
    TRAINER_DEFEATED_OFFSET,
    TRAINER_DEFEATED_SIZE,
    SaveImage,
    load_fixture_manifest,
    with_saved_flags,
)
from tools.e2e.skyemu import SkyEmuSession
from tools.e2e.save_journey import (
    SaveScenarioResult,
    SaveScenarioStatus,
)
from tools.e2e.generate_populated_fixture import (
    INSTRUMENTATION_PATCH_SHA256,
    INSTRUMENTED_ROM_SHA256,
    POPULATED_SAVE_SHA256,
    publish_fixture,
    verify_reviewed_oracle,
)
from tools.e2e.tests.conftest import capture_failure_evidence


FIXTURES = Path(__file__).parents[2] / "fixtures"


def test_reviewed_fixture_has_valid_flash_and_provenance():
    document, image = load_fixture_manifest(FIXTURES / "hoenn_continue.json")

    assert document["fixture"]["sourceCommit"] == "135b32ca92"
    assert image.sha256 == document["fixture"]["sha256"]
    assert image.active_slot.counter == 1
    assert image.active_slot.physical_index == 1
    assert len(image.active_slot.save_block1) == SAVE_BLOCK1_SIZE
    assert image.active_slot.trainer_defeated_bitmap == bytes(TRAINER_DEFEATED_SIZE)
    assert image.semantics() == document["semanticExpectations"]


def test_populated_historical_fixture_matches_independent_semantics():
    manifest = json.loads((FIXTURES / "hoenn_populated.json").read_text())
    image = SaveImage.from_path(FIXTURES / manifest["fixture"]["file"])
    fields = manifest["generation"]["result"]
    fields["status"] = SaveScenarioStatus(fields["status"])

    assert image.sha256 == manifest["fixture"]["sha256"]
    assert image.sha256 == POPULATED_SAVE_SHA256
    assert len(image.active_slot.save_block1) == SAVE_BLOCK1_SIZE
    assert image.active_slot.trainer_defeated_bitmap == bytes(TRAINER_DEFEATED_SIZE)
    assert manifest["fixture"]["instrumentationPatchSha256"] == (
        INSTRUMENTATION_PATCH_SHA256
    )
    assert manifest["fixture"]["sourceRomSha256"] == INSTRUMENTED_ROM_SHA256
    result = SaveScenarioResult(**fields)
    oracle = json.loads((FIXTURES / "hoenn_populated_oracle.json").read_text())
    assert (
        verify_reviewed_oracle(image, result, oracle)
        == manifest["semanticExpectations"]
    )


def test_parser_drift_cannot_rewrite_reviewed_historical_oracle():
    manifest = json.loads((FIXTURES / "hoenn_populated.json").read_text())
    oracle = json.loads((FIXTURES / "hoenn_populated_oracle.json").read_text())
    immutable_copy = copy.deepcopy(oracle)
    image = SaveImage.from_path(FIXTURES / manifest["fixture"]["file"])
    fields = manifest["generation"]["result"]
    fields["status"] = SaveScenarioStatus(fields["status"])

    with pytest.raises(ValueError, match="semantic decoder disagrees"):
        verify_reviewed_oracle(
            image,
            SaveScenarioResult(**fields),
            oracle,
            semantic_decoder=lambda image, result: {"drifted": True},
        )

    assert oracle == immutable_copy


def test_failed_oracle_validation_never_overwrites_published_fixture(tmp_path):
    image = SaveImage.from_path(FIXTURES / "hoenn_continue.sav")
    oracle = json.loads((FIXTURES / "hoenn_populated_oracle.json").read_text())
    oracle["rawSerializedExpectations"][0]["hex"] = "ff" * 8
    output = tmp_path / "fixture.json"
    save = output.with_suffix(".sav")
    output.write_bytes(b"published-manifest")
    save.write_bytes(b"published-save")

    with pytest.raises(ValueError, match="raw oracle mismatch"):
        publish_fixture(output, image, None, oracle)

    assert output.read_bytes() == b"published-manifest"
    assert save.read_bytes() == b"published-save"


def test_save_validation_rejects_a_corrupt_sector_checksum():
    data = bytearray((FIXTURES / "hoenn_continue.sav").read_bytes())
    data[14 * 4096] ^= 0x01

    with pytest.raises(ValueError, match="checksum mismatch"):
        SaveImage.from_bytes(bytes(data))


def test_sector_4_checksum_covers_the_new_trainer_bitmap():
    image = SaveImage.from_path(FIXTURES / "hoenn_continue.sav")
    data = bytearray(image.data)
    sector = image.active_slot.logical_sector(4)
    physical_offset = data.find(sector)

    assert physical_offset >= 0
    bitmap_sector_offset = TRAINER_DEFEATED_OFFSET - 3 * 3968
    data[physical_offset + bitmap_sector_offset] ^= 1

    with pytest.raises(ValueError, match="logical sector 4 checksum mismatch"):
        SaveImage.from_bytes(bytes(data))


def test_save_validation_requires_exact_128k_flash():
    data = (FIXTURES / "hoenn_continue.sav").read_bytes()

    with pytest.raises(ValueError, match="exactly 131072 bytes"):
        SaveImage.from_bytes(data[:-1])


def test_complete_newer_slot_survives_partial_older_slot():
    data = bytearray((FIXTURES / "hoenn_continue.sav").read_bytes())
    data[5 * 4096 : 6 * 4096] = b"\xff" * 4096

    image = SaveImage.from_bytes(bytes(data))

    assert image.active_slot.physical_index == 1


def test_battery_wait_rejects_partial_target_slot_with_changed_bytes():
    before = SaveImage.from_path(FIXTURES / "hoenn_continue.sav")
    partial_data = bytearray(before.data)
    for sector_index in range(14):
        struct.pack_into(
            "<I",
            partial_data,
            sector_index * SECTOR_SIZE + SECTOR_FOOTER_OFFSET + 8,
            before.active_slot.counter + 1,
        )
    partial_data[5 * SECTOR_SIZE : 6 * SECTOR_SIZE] = b"\xff" * SECTOR_SIZE
    partial = SaveImage.from_bytes(bytes(partial_data))
    assert partial.data != before.data
    assert partial.active_slot.counter == before.active_slot.counter

    class Session:
        def press(self, _button, *, release_frames):
            assert release_frames == 4

        def battery_snapshot(self):
            return partial

    with pytest.raises(AssertionError, match="battery save did not change"):
        SkyEmuSession.wait_for_battery_change(Session(), before, max_pulses=1)


def test_saved_flag_variants_are_checksum_valid_and_do_not_change_other_bytes():
    original = SaveImage.from_path(FIXTURES / "hoenn_continue.sav")
    variant = with_saved_flags(original, {0x867: True, 0x868: False})
    block = variant.active_slot.save_block1

    assert block[0x1270 + 0x867 // 8] & (1 << (0x867 % 8))
    assert not block[0x1270 + 0x868 // 8] & (1 << (0x868 % 8))
    restored = with_saved_flags(variant, {0x867: False})
    assert restored.data == original.data


def test_saved_flag_variants_reject_nonserialized_flags():
    original = SaveImage.from_path(FIXTURES / "hoenn_continue.sav")

    with pytest.raises(ValueError, match="outside the serialized range"):
        with_saved_flags(original, {0x960: True})


class _FakeProcess:
    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode


class _FakeRestartSession:
    def __init__(self, battery_path):
        self.battery_path = battery_path
        self.process = _FakeProcess()
        self.exited_processes = []
        self._generation = 0
        self.launched = False

    def close(self):
        # Deliberately do not touch the save. Closing is only a process invariant.
        self.process.returncode = -15

    def _launch(self):
        self.launched = True


def test_cold_restart_proves_exit_without_requiring_close_to_flush(tmp_path):
    save = tmp_path / "game.sav"
    save.write_bytes((FIXTURES / "hoenn_continue.sav").read_bytes())
    session = _FakeRestartSession(save)
    before = save.read_bytes()

    old_process = SkyEmuSession.cold_restart(session)

    assert old_process.poll() == -15
    assert session.exited_processes == [old_process]
    assert session._generation == 1
    assert session.launched
    assert save.read_bytes() == before


class _FakeEvidenceSession:
    def __init__(self, root):
        self.battery_path = root / "game.sav"
        self.log_path = root / "skyemu.log"
        self.battery_path.write_bytes(b"battery")
        self.log_path.write_bytes(b"log")

    def screenshot(self, output):
        output.write_bytes(b"png")

    def save_state(self, output):
        output.write_bytes(b"state")


def test_failure_evidence_includes_save_screen_state_and_log(tmp_path):
    session = _FakeEvidenceSession(tmp_path)
    output = tmp_path / "evidence"

    capture_failure_evidence(session, output)

    assert (output / "game.sav").read_bytes() == b"battery"
    assert (output / "screen.png").read_bytes() == b"png"
    assert (output / "game.state").read_bytes() == b"state"
    assert (output / "skyemu.log").read_bytes() == b"log"
