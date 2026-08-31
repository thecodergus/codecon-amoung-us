"""Cascata de portas do host (start_host_server): pedida → sem WS → efêmera."""

from __future__ import annotations

import socket

import pytest

from codecon_amoung_us.net.server import GameServer, start_host_server


def _free_tcp_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.integration
def test_start_host_server_prefers_requested_ports() -> None:
    tcp_port = _free_tcp_port()
    server = start_host_server(tcp_port, tcp_port + 1)
    try:
        assert server.port == tcp_port
        assert server.ws_port == tcp_port + 1
    finally:
        server.stop()


@pytest.mark.integration
def test_start_host_server_drops_ws_when_adjacent_port_taken() -> None:
    tcp_port = _free_tcp_port()
    with socket.socket() as squatter:
        squatter.bind(("0.0.0.0", tcp_port + 1))
        squatter.listen(1)
        server = start_host_server(tcp_port, tcp_port + 1)
        try:
            assert server.port == tcp_port
            assert server.ws_port is None
        finally:
            server.stop()


@pytest.mark.integration
def test_start_host_server_falls_back_to_ephemeral_when_port_taken() -> None:
    busy = _free_tcp_port()
    with socket.socket() as squatter:
        squatter.bind(("0.0.0.0", busy))
        squatter.listen(1)
        server = start_host_server(busy, None)
        try:
            assert server.port != busy  # porta efêmera real
            assert server.port > 0
        finally:
            server.stop()


@pytest.mark.integration
def test_start_host_server_ephemeral_is_reachable_via_gameclient() -> None:
    """A porta efetiva da cascata funciona de ponta a ponta (join real)."""
    from codecon_amoung_us.net.client import GameClient

    server = start_host_server(0, None)
    try:
        with GameClient() as client:
            client.connect("127.0.0.1", server.port, "dono")
            assert client.player_id is not None
    finally:
        server.stop()


@pytest.mark.integration
def test_start_host_server_absorbs_invalid_user_port() -> None:
    """Porta pedida inválida: as duas primeiras tentativas falham, a efêmera sobe."""
    server = start_host_server(70000, None)
    try:
        assert server.port > 0
    finally:
        server.stop()


def test_start_host_server_raises_last_error_when_all_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nenhuma tentativa sobe: propaga a última OSError (contrato do for-else)."""
    failures = 0

    def _boom(self: GameServer) -> None:
        nonlocal failures
        failures += 1
        raise OSError(f"falha simulada {failures}")

    monkeypatch.setattr(GameServer, "start", _boom)
    with pytest.raises(OSError, match="falha simulada 3"):
        start_host_server(5555, None)
    assert failures == 3  # as três tentativas da cascata
