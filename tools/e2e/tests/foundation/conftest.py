import pytest


@pytest.fixture
def foundation_game(game):
    # Let crt0 clear BSS and enter AgbMain before committing a host request.
    game.step(2)
    return game
