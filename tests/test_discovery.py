"""Descoberta LAN: encode/decode do anúncio, listener e beacon."""

from __future__ import annotations

import socket
import threading
import time

import pytest

from codecon_amoung_us.config import (
    DISCOVERY_MAGIC,
    MAX_DISCOVERY_BYTES,
    PROTOCOL_VERSION,
    GameConfig,
)
from codecon_amoung_us.net.client import GameClient
from codecon_amoung_us.net.discovery import (
    DiscoveredGame,
    DiscoveryBeacon,
    GameAnnouncement,
    decode_announcement,
    discover_games,
    encode_announcement,
)
from codecon_amoung_us.net.server import GameServer


def _announcement(
    *,
    magic: str = DISCOVERY_MAGIC,
    protocol_version: int = PROTOCOL_VERSION,
    host_name: str = "host",
    players: int = 1,
    max_players: int = 10,
    tcp_port: int = 5555,
    ws_port: int | None = None,
) -> GameAnnouncement:
    return GameAnnouncement(
        magic=magic,
        protocol_version=protocol_version,
        host_name=host_name,
        players=players,
        max_players=max_players,
        tcp_port=tcp_port,
        ws_port=ws_port,
    )


def _free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _send_announcement(port: int, announcement: GameAnnouncement, *, count: int = 3) -> None:
    payload = encode_announcement(announcement)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        for _ in range(count):
            s.sendto(payload, ("127.0.0.1", port))
            time.sleep(0.05)


# ---------------------------------------------------------------------- decode


def test_announcement_roundtrip() -> None:
    announcement = _announcement(host_name="pato", players=3, ws_port=8080)
    decoded = decode_announcement(encode_announcement(announcement))
    assert decoded == announcement


def test_decode_rejects_garbage() -> None:
    assert decode_announcement(b"\x00\x01\x02 nao e json") is None


def test_decode_rejects_empty() -> None:
    assert decode_announcement(b"") is None


def test_decode_rejects_wrong_schema() -> None:
    assert decode_announcement(b'{"magic": "x"}') is None


def test_decode_rejects_wrong_magic() -> None:
    payload = encode_announcement(_announcement(magic="outro-jogo/9"))
    assert decode_announcement(payload) is None


def test_decode_rejects_incompatible_version() -> None:
    payload = encode_announcement(_announcement(protocol_version=PROTOCOL_VERSION + 1))
    assert decode_announcement(payload) is None


def test_decode_rejects_oversized() -> None:
    payload = encode_announcement(_announcement())
    assert decode_announcement(payload + b" " * MAX_DISCOVERY_BYTES) is None


# ---------------------------------------------------------------------- listener


@pytest.mark.integration
def test_discover_games_collects_and_deduplicates() -> None:
    port = _free_udp_port()
    ann_a = _announcement(host_name="ana", tcp_port=5555)
    ann_b = _announcement(host_name="bob", tcp_port=6666, ws_port=8080)

    games: list[DiscoveredGame] = []

    def _listen() -> None:
        games.extend(discover_games(timeout=1.0, port=port))

    listener = threading.Thread(target=_listen)
    listener.start()
    time.sleep(0.1)  # garante o bind antes do envio
    _send_announcement(port, ann_a)  # duplicatas propositalmente
    _send_announcement(port, ann_b, count=1)
    # datagrama alheio na mesma porta não pode quebrar a coleta
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"lixo de outro servico", ("127.0.0.1", port))
    listener.join(timeout=5.0)

    assert [(g.host_name, g.tcp_port) for g in games] == [("ana", 5555), ("bob", 6666)]
    bob = next(g for g in games if g.host_name == "bob")
    assert bob.ws_port == 8080
    assert bob.ip == "127.0.0.1"


@pytest.mark.integration
def test_discover_games_empty_when_nobody_announces() -> None:
    assert discover_games(timeout=0.3, port=_free_udp_port()) == []


# ---------------------------------------------------------------------- beacon


@pytest.mark.integration
def test_beacon_announces_until_stopped() -> None:
    port = _free_udp_port()
    beacon = DiscoveryBeacon(
        lambda: _announcement(host_name="carol", tcp_port=7777),
        port=port,
        interval_seconds=0.1,
        broadcast_addr="127.0.0.1",  # unicast: loopback não tem broadcast
    )
    beacon.start()
    try:
        games = discover_games(timeout=1.0, port=port)
    finally:
        beacon.stop()
    assert [(g.host_name, g.tcp_port) for g in games] == [("carol", 7777)]


@pytest.mark.integration
def test_beacon_silent_when_no_announcement() -> None:
    port = _free_udp_port()
    beacon = DiscoveryBeacon(lambda: None, port=port, interval_seconds=0.05)
    beacon.start()
    try:
        assert discover_games(timeout=0.4, port=port) == []
    finally:
        beacon.stop()
        beacon.stop()  # stop idempotente


# ---------------------------------------------------------------------- servidor


@pytest.mark.integration
def test_server_announces_lobby_via_broadcast() -> None:
    """Servidor real aparece na descoberta enquanto está em lobby."""
    with GameServer(host="127.0.0.1", port=0) as server, GameClient() as host:
        host.connect("127.0.0.1", server.port, "dono")
        games = discover_games(timeout=3.0)
        mine = [g for g in games if g.tcp_port == server.port]
        assert len(mine) == 1
        assert mine[0].host_name == "dono"
        assert mine[0].players == 1


@pytest.mark.integration
def test_server_stops_announcing_when_game_starts() -> None:
    """Fora do lobby o beacon fica em silêncio (partida em andamento)."""
    config = GameConfig(min_players_to_start=1)
    with GameServer(host="127.0.0.1", port=0, config=config) as server, GameClient() as host:
        host.connect("127.0.0.1", server.port, "dono")
        host.start_game()
        # drena qualquer anúncio em voo e escuta uma janela limpa
        time.sleep(0.2)
        games = discover_games(timeout=2.5)
        assert [g for g in games if g.tcp_port == server.port] == []


@pytest.mark.integration
def test_server_without_announce_does_not_advertise() -> None:
    config = GameConfig(announce=False)
    with GameServer(host="127.0.0.1", port=0, config=config) as server:
        time.sleep(0.2)
        games = discover_games(timeout=2.5)
        assert [g for g in games if g.tcp_port == server.port] == []
