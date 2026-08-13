from __future__ import annotations

import os
from unittest import mock

from tools.e2e import run


def _invoke_integrity(*, full: bool = False, sweep: str | None = None):
    environment = {}
    if full:
        environment["E2E_FULL"] = "1"
    if sweep is not None:
        environment["E2E_MAP_SWEEP"] = sweep
    with (
        mock.patch.object(run.sys, "argv", ["run.py", "integrity"]),
        mock.patch.dict(os.environ, environment, clear=True),
        mock.patch.object(run.subprocess, "call", return_value=0) as call,
    ):
        assert run.main() == 0
    return call.call_args


def test_integrity_defaults_to_frontages_without_long_journeys():
    call = _invoke_integrity()
    assert call.kwargs["env"]["E2E_MAP_SWEEP"] == "frontages"
    assert call.args[0][4:6] == ["-m", "not long_journey"]


def test_full_integrity_couples_all_maps_and_all_journeys():
    call = _invoke_integrity(full=True, sweep="frontages")
    assert call.kwargs["env"]["E2E_MAP_SWEEP"] == "all"
    assert "not long_journey" not in call.args[0]


def test_explicit_map_sweep_is_preserved():
    call = _invoke_integrity(sweep="all")
    assert call.kwargs["env"]["E2E_MAP_SWEEP"] == "all"
