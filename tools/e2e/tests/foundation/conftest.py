import os
from pathlib import Path

import pytest

from tools.e2e.skyemu import SkyEmuSession, Symbols


@pytest.fixture
def foundation_game(game):
    # Let crt0 clear BSS and enter AgbMain before committing a host request.
    game.step(2)
    return game


@pytest.fixture
def game_from_hoenn_save(tmp_path):
    save = Path(__file__).parents[2] / "fixtures" / "hoenn_continue.sav"
    if not save.is_file():
        pytest.fail(
            "existing-save regression requires tools/e2e/fixtures/hoenn_continue.sav; "
            "generate and review it from the completed all-regions product ROM"
        )
    session = SkyEmuSession(
        binary=Path(os.environ["SKYEMU"]),
        rom=Path(os.environ["E2E_ROM"]),
        symbols=Symbols(Path(os.environ["E2E_SYMS"])),
        workdir=tmp_path,
        battery_save=save,
    )
    yield session
    session.close()
