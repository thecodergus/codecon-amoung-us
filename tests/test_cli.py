"""Testes da validação de argumentos da CLI do servidor (A-22)."""

from __future__ import annotations

import argparse

import pytest

from codecon_amoung_us.config import MAX_PLAYERS, GameConfig
from codecon_amoung_us.net.server import _server_config, main


def _args(**kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "port": 5555,
        "ws_port": None,
        "tick_rate": None,
        "max_players": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_server_config_defaults() -> None:
    config = _server_config(_args())
    assert isinstance(config, GameConfig)
    assert config.tick_rate == 20
    assert config.max_players == MAX_PLAYERS


def test_server_config_accepts_valid_overrides() -> None:
    config = _server_config(_args(tick_rate=10, max_players=5, ws_port=8080))
    assert config.tick_rate == 10
    assert config.max_players == 5
    assert config.ws_port == 8080


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tick_rate": 0},
        {"tick_rate": -1},
        {"max_players": 0},
        {"max_players": MAX_PLAYERS + 1},
        {"port": 0},
        {"port": 70000},
        {"port": -1},
        {"ws_port": 0},
        {"ws_port": 70000},
        {"ws_port": 5555},  # igual à porta TCP
    ],
)
def test_server_config_rejects_invalid(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _server_config(_args(**kwargs))


@pytest.mark.parametrize(
    "argv",
    [
        ["--tick-rate", "0"],
        ["--max-players", "0"],
        ["--max-players", "11"],
        ["--port", "70000"],
    ],
)
def test_main_exits_with_error_on_invalid_args(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(argv)
    assert excinfo.value.code == 2
