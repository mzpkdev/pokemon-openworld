from pathlib import Path
import json

import pytest

from tools.e2e.save_file import load_fixture_manifest


@pytest.fixture
def integrity_game(game):
    # Let crt0 clear BSS and enter AgbMain before committing a host request.
    game.step(2)
    return game


@pytest.fixture
def game_from_hoenn_save(session_factory):
    manifest = Path(__file__).parents[2] / "fixtures" / "hoenn_continue.json"
    if not manifest.is_file():
        pytest.fail(
            "existing-save regression requires the reviewed "
            "tools/e2e/fixtures/hoenn_continue.json manifest"
        )
    document, _ = load_fixture_manifest(manifest)
    save = manifest.parent / document["fixture"]["file"]
    return session_factory(battery_save=save)


@pytest.fixture
def game_from_populated_hoenn_save(session_factory):
    manifest = Path(__file__).parents[2] / "fixtures" / "hoenn_populated.json"
    document = json.loads(manifest.read_text())
    save = manifest.parent / document["fixture"]["file"]
    return session_factory(battery_save=save)
