import os
from pathlib import Path
import re
import shutil

import pytest

from tools.e2e.skyemu import SkyEmuSession, Symbols


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"report_{report.when}", report)


def _failure_output(request) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
    return Path(os.environ["E2E_RESULTS"]) / os.environ["E2E_SUITE"] / safe_name


def capture_failure_evidence(session, output: Path) -> None:
    """Capture the same useful bundle for every kind of E2E session."""
    output.mkdir(parents=True, exist_ok=True)
    errors = []
    operations = (
        ("game.sav", lambda: shutil.copy2(session.battery_path, output / "game.sav")),
        ("skyemu.log", lambda: shutil.copy2(session.log_path, output / "skyemu.log")),
        ("screen.png", lambda: session.screenshot(output / "screen.png")),
        ("game.state", lambda: session.save_state(output / "game.state")),
    )
    for name, operation in operations:
        try:
            operation()
        except (OSError, RuntimeError) as error:
            errors.append(f"{name}: {error}")
    if errors:
        (output / "capture-errors.txt").write_text("\n".join(errors) + "\n")


@pytest.fixture
def session_factory(request, tmp_path):
    sessions = []

    def create(*, battery_save=None):
        session_workdir = tmp_path / f"session-{len(sessions)}"
        session = SkyEmuSession(
            binary=Path(os.environ["SKYEMU"]),
            rom=Path(os.environ["E2E_ROM"]),
            symbols=Symbols(Path(os.environ["E2E_SYMS"])),
            workdir=session_workdir,
            battery_save=battery_save,
        )
        sessions.append(session)
        return session

    yield create

    report = getattr(request.node, "report_call", None)
    failed = report is not None and report.failed
    try:
        if failed and sessions:
            capture_failure_evidence(sessions[-1], _failure_output(request))
    finally:
        for session in reversed(sessions):
            session.close()


@pytest.fixture
def game(session_factory):
    return session_factory()
