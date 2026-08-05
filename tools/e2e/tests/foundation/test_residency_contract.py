from types import SimpleNamespace

from tools.e2e.tests.foundation.test_three_region_residency import (
    _capture_map_failure,
    _request_for,
)


class EvidenceGame:
    def map_id(self):
        return 0, 9

    def position(self):
        return 10, 10

    def controls_locked(self):
        return False

    def script_status(self):
        return 2

    def movement_idle(self):
        return True

    def foundation_result(self):
        return "success"

    def address(self, symbol):
        assert symbol == "gMain"
        return 0x03000000

    def read_u32(self, address):
        return address

    def screenshot(self, output):
        output.write_bytes(b"screen")

    def save_state(self, output):
        output.write_bytes(b"state")


def test_structural_and_representative_evidence_do_not_collide(monkeypatch, tmp_path):
    monkeypatch.setenv("E2E_RESULTS", str(tmp_path))
    entry = SimpleNamespace(name="LittlerootTown", group=0, number=9)
    game = EvidenceGame()

    structural = _capture_map_failure(
        game,
        tmp_path,
        entry,
        1,
        AssertionError("structural"),
        phase="structural",
    )
    representative = _capture_map_failure(
        game,
        tmp_path,
        entry,
        1,
        AssertionError("representative"),
        phase="representative",
    )

    assert structural != representative
    assert structural.parent.name == "structural"
    assert representative.parent.name == "representative"
    assert (structural / "diagnostics.json").is_file()
    assert (representative / "diagnostics.json").is_file()


def test_only_structural_requests_suppress_scripts_and_events():
    entry = SimpleNamespace(group=1, number=2, width=20, height=12)

    structural = _request_for(entry, 1, structural=True)
    representative = _request_for(entry, 2, structural=False)

    assert structural.suppress_scripts and structural.suppress_events
    assert not representative.suppress_scripts and not representative.suppress_events
    assert (structural.x, structural.y) == (10, 6)
    assert (representative.x, representative.y) == (10, 6)
