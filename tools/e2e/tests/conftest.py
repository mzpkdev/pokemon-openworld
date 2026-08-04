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


@pytest.fixture
def game(request, tmp_path):
    try:
        session = SkyEmuSession(
            binary=Path(os.environ["SKYEMU"]),
            rom=Path(os.environ["E2E_ROM"]),
            symbols=Symbols(Path(os.environ["E2E_SYMS"])),
            workdir=tmp_path,
        )
    except BaseException:
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
        output = Path(os.environ["E2E_RESULTS"]) / os.environ["E2E_SUITE"] / safe_name
        output.mkdir(parents=True, exist_ok=True)
        log_path = tmp_path / "skyemu.log"
        if log_path.is_file():
            shutil.copy2(log_path, output / "skyemu.log")
        raise
    yield session

    report = getattr(request.node, "report_call", None)
    failed = report is not None and report.failed
    output = None
    try:
        if failed:
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.nodeid)
            output = (
                Path(os.environ["E2E_RESULTS"]) / os.environ["E2E_SUITE"] / safe_name
            )
            output.mkdir(parents=True, exist_ok=True)
            session.screenshot(output / "screen.png")
            session.save_state(output / "state.png")
    finally:
        session.close()
        if failed and output is not None:
            shutil.copy2(session.log_path, output / "skyemu.log")
