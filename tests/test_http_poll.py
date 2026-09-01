"""HTTP long polling (net/http_poll.py): sessão, join e ciclo completo."""

from __future__ import annotations

import time

import pytest

from codecon_amoung_us.config import PROTOCOL_VERSION, GameConfig
from codecon_amoung_us.framing import encode_frame
from codecon_amoung_us.net.client import GameClient
from codecon_amoung_us.net.server import GameServer, start_host_server
from codecon_amoung_us.protocol import RoleAssigned, StartGame


@pytest.mark.integration
def test_http_poll_join_and_game_start() -> None:
    """Join por HTTP long polling e receba StartGame/RoleAssigned no poll."""
    server = start_host_server(0, None, 0)
    try:
        assert server.http_port is not None
        with GameClient() as client:
            client.connect_http_poll("127.0.0.1", server.http_port, "cli")
            assert client.transport == "http"
            assert client.player_id is not None
            client.start_game()
            client.wait_for(StartGame, timeout=5.0)
            client.wait_for(RoleAssigned, timeout=5.0)
    finally:
        server.stop()


@pytest.mark.integration
def test_http_poll_send_to_unknown_session_fails() -> None:
    """POST /send com sessão inexistente → ConnectionError (HTTP 404)."""
    from codecon_amoung_us.protocol import JoinRequest

    server = start_host_server(0, None, 0)
    try:
        assert server.http_port is not None
        with GameClient() as client:
            client.connect_http_poll("127.0.0.1", server.http_port, "cli")
            frame = encode_frame(JoinRequest(nickname="x", protocol_version=PROTOCOL_VERSION))
            with pytest.raises(ConnectionError):
                client._http_send(("127.0.0.1", server.http_port, "sessao-inexistente"), frame)
    finally:
        server.stop()


@pytest.mark.integration
def test_http_poll_session_gc_disconnects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sessão sem atividade além do timeout é removida pelo GC do listener.

    Sessão fantasma: criada via ``POST /connect`` sem cliente fazendo poll —
    um cliente ativo renovaria a sessão a cada ``GET /poll`` (touch).
    """
    from codecon_amoung_us.net import http_poll
    from codecon_amoung_us.net.client import _http_session_create

    monkeypatch.setattr(http_poll, "_GC_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(http_poll, "HTTP_POLL_SESSION_TIMEOUT_SECONDS", 0.5)
    server = GameServer(host="127.0.0.1", port=0, config=GameConfig(announce=False))
    listener = http_poll.HttpPollListener(server, "127.0.0.1", 0)
    listener.start()
    try:
        session = _http_session_create("127.0.0.1", listener.port, 2.0)
        assert listener.session(session) is not None
        time.sleep(1.0)  # GC roda (~50 ms de intervalo) após o timeout (0,5 s)
        assert listener.session(session) is None
    finally:
        listener.stop()
        server.stop()
