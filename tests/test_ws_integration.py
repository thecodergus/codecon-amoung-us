"""Integração WebSocket: join, movimento, snapshot e fallback de transporte.

Cobre o transporte preferencial (WS, padrão ouro) convivendo com o TCP cru
(fallback) no mesmo servidor, e a seleção automática do cliente.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest
from websockets.sync.client import connect as ws_connect

from codecon_amoung_us.config import GameConfig
from codecon_amoung_us.net.client import GameClient
from codecon_amoung_us.net.server import GameServer
from codecon_amoung_us.protocol import (
    JoinAccepted,
    PlayerJoined,
    ProtocolError,
    RoleAssigned,
    decode,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def plain_ws(monkeypatch: pytest.MonkeyPatch) -> None:
    """Desativa o TLS self-signed (padrão do host desde a Etapa wss).

    Estes testes cobrem o transporte ``ws://`` puro — caminho efetivo quando
    a geração do cert falha no host (fallback documentado). A cobertura wss
    com pin fica em ``tests/test_tls.py``.
    """
    monkeypatch.setattr("codecon_amoung_us.net.server.generate_server_tls", lambda: None)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def ws_server() -> Iterator[tuple[GameServer, int]]:
    """Servidor com listener WS (padrão ouro) + TCP (fallback) em portas efêmeras."""
    ws_port = _free_port()
    server = GameServer(host="127.0.0.1", port=0, config=GameConfig(ws_port=ws_port))
    server.start()
    yield server, ws_port
    server.stop()


def test_ws_join_and_snapshot(ws_server: tuple[GameServer, int]) -> None:
    server, ws_port = ws_server
    with GameClient() as client:
        client.connect_ws("127.0.0.1", ws_port, "patows")
        assert client.transport == "ws"
        assert client.player_id is not None
        client.start_game()
        client.wait_for(RoleAssigned)
        client.move(1.0, 0.0)
        snapshot = client.wait_for_snapshot()
        assert any(p.player_id == client.player_id for p in snapshot.players)


def test_ws_and_tcp_coexist_in_same_lobby(ws_server: tuple[GameServer, int]) -> None:
    server, ws_port = ws_server
    with GameClient() as tcp_client, GameClient() as ws_client:
        tcp_client.connect("127.0.0.1", server.port, "tcp")
        ws_client.connect_ws("127.0.0.1", ws_port, "ws")
        joined = tcp_client.wait_for(PlayerJoined)
        assert joined.player.player_id == ws_client.player_id
        join = ws_client.join_accepted
        assert join is not None
        assert isinstance(join, JoinAccepted)
        assert len(join.players) == 2


def test_ws_bad_frame_gets_protocol_error(ws_server: tuple[GameServer, int]) -> None:
    _server, ws_port = ws_server
    with ws_connect(f"ws://127.0.0.1:{ws_port}/", open_timeout=5.0) as ws:
        ws.send("isto nao e json do protocolo")
        message = decode(str(ws.recv(timeout=5.0)).encode())
        assert isinstance(message, ProtocolError)
        assert message.code == "bad_frame"


def test_connect_auto_prefers_websocket(ws_server: tuple[GameServer, int]) -> None:
    server, ws_port = ws_server
    with GameClient() as client:
        client.connect_auto("127.0.0.1", tcp_port=server.port, ws_port=ws_port, nickname="auto")
        assert client.transport == "ws"
        assert client.player_id is not None


def test_connect_auto_falls_back_to_tcp_when_ws_port_is_tcp() -> None:
    """WS na porta errada falha o handshake; o fallback TCP assume."""
    with GameServer(host="127.0.0.1", port=0) as server, GameClient() as client:
        client.connect_auto("127.0.0.1", tcp_port=server.port, ws_port=server.port, nickname="fb")
        assert client.transport == "tcp"
        assert client.player_id is not None


def test_connect_auto_raises_when_everything_fails() -> None:
    dead_port = _free_port()  # porta livre: nada escutando
    with GameClient() as client, pytest.raises(ConnectionError):
        client.connect_auto(
            "127.0.0.1", tcp_port=dead_port, ws_port=dead_port, nickname="x", timeout=1.0
        )
