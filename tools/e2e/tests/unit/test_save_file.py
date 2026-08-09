from pathlib import Path
import copy
import json

import pytest

from tools.e2e.save_file import SaveImage, load_fixture_manifest
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
    assert image.semantics() == document["semanticExpectations"]


def test_populated_historical_fixture_matches_independent_semantics():
    manifest = json.loads((FIXTURES / "hoenn_populated.json").read_text())
    image = SaveImage.from_path(FIXTURES / manifest["fixture"]["file"])
    fields = manifest["generation"]["result"]
    fields["status"] = SaveScenarioStatus(fields["status"])

    assert image.sha256 == manifest["fixture"]["sha256"]
    assert image.sha256 == POPULATED_SAVE_SHA256
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


def test_save_validation_requires_exact_128k_flash():
    data = (FIXTURES / "hoenn_continue.sav").read_bytes()

    with pytest.raises(ValueError, match="exactly 131072 bytes"):
        SaveImage.from_bytes(data[:-1])


def test_complete_newer_slot_survives_partial_older_slot():
    data = bytearray((FIXTURES / "hoenn_continue.sav").read_bytes())
    data[5 * 4096 : 6 * 4096] = b"\xff" * 4096

    image = SaveImage.from_bytes(bytes(data))

    assert image.active_slot.physical_index == 1


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
