"""Sweep unicast (net/discovery.py): alvos, responder e varredura."""

from __future__ import annotations

import contextlib
import socket

import pytest

from codecon_amoung_us.config import DISCOVERY_PROBE_MAGIC, PROTOCOL_VERSION
from codecon_amoung_us.net.discovery import (
    DiscoveredGame,
    DiscoveryProbe,
    DiscoveryResponder,
    decode_probe,
    encode_probe,
    local_unicast_targets,
    sweep_games,
)


def test_decode_probe_rejects_foreign_or_stale() -> None:
    assert decode_probe(b"") is None
    assert decode_probe(b"nao-json") is None
    assert decode_probe(encode_probe(DiscoveryProbe(magic="outro", protocol_version=1))) is None
    probe = DiscoveryProbe(magic=DISCOVERY_PROBE_MAGIC, protocol_version=PROTOCOL_VERSION)
    assert decode_probe(encode_probe(probe)) == probe


def test_local_unicast_targets_covers_slash24(monkeypatch: pytest.MonkeyPatch) -> None:
    from codecon_amoung_us.net import discovery

    monkeypatch.setattr(discovery, "_local_ip", lambda: "192.168.1.7")
    targets = local_unicast_targets()
    assert len(targets) == 254
    assert targets[0] == "192.168.1.1"
    assert targets[-1] == "192.168.1.254"
    assert "192.168.1.7" in targets

    monkeypatch.setattr(discovery, "_local_ip", lambda: None)
    assert local_unicast_targets() == []


@pytest.mark.integration
def test_sweep_finds_responder_on_loopback() -> None:
    """Responder responde probe unicast; sweep descobre a partida dele."""
    from codecon_amoung_us.net.discovery import GameAnnouncement

    announcement = GameAnnouncement(
        magic="codecon-amoung-us/1",
        protocol_version=PROTOCOL_VERSION,
        host_name="dono",
        players=1,
        max_players=10,
        tcp_port=5555,
        ws_port=5556,
    )
    # Porta UDP livre: bind/consulta/fecha (TOCTOU aceitável em teste).
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    responder = DiscoveryResponder(lambda: announcement, port=port)
    responder.start()
    try:
        games = sweep_games(port=port, targets=["127.0.0.1"], timeout=2.0)
    finally:
        responder.stop()
    assert games == [
        DiscoveredGame(
            ip="127.0.0.1",
            host_name="dono",
            players=1,
            max_players=10,
            tcp_port=5555,
            ws_port=5556,
            tls_fingerprint=None,
        )
    ]
