import pytest

from space_online.game.helper_methods import game_clock
from space_online.webapp import create_app


@pytest.fixture(autouse=True)
def uncapped_clock(monkeypatch):
    """Tests pass time by backdating the clock, so a tick here takes however long they say."""
    monkeypatch.setattr(game_clock, "MAX_TICK_SECONDS", float("inf"))


@pytest.fixture
def make_app(tmp_path):
    def build(**config):
        return create_app({
            "TESTING": True,
            "SECRET_KEY": "test",
            "DATABASE": str(tmp_path / "space_online.sqlite3"),
            **config,
        })
    return build


@pytest.fixture
def app(make_app):
    return make_app()


@pytest.fixture
def client(app):
    return app.test_client()
