"""TLS self-signed (net/tls.py): geração, pin wss e cascata do cliente."""

from __future__ import annotations

import pytest

from codecon_amoung_us.net.client import GameClient
from codecon_amoung_us.net.server import start_host_server
from codecon_amoung_us.net.tls import fingerprint_of_der, generate_server_tls


def test_generate_server_tls_returns_distinct_fingerprints() -> None:
    """Cert efêmero por boot: fingerprint SHA-256 (hex) distinto a cada geração."""
    first = generate_server_tls()
    second = generate_server_tls()
    assert first is not None and second is not None
    assert len(first.fingerprint) == 64
    assert first.fingerprint != second.fingerprint


def test_fingerprint_of_der_is_sha256_hex() -> None:
    assert fingerprint_of_der(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


@pytest.mark.integration
def test_wss_pin_join() -> None:
    """Cliente com o fingerprint anunciado conecta e entra no lobby via wss."""
    server = start_host_server(0, 0)
    try:
        assert server.ws_port is not None
        assert server.tls_fingerprint is not None
        with GameClient() as client:
            client.connect_wss(
                "127.0.0.1",
                server.ws_port,
                "cli",
                tls_fingerprint=server.tls_fingerprint,
            )
            assert client.transport == "wss"
            assert client.player_id is not None
    finally:
        server.stop()


@pytest.mark.integration
def test_wss_rejects_wrong_fingerprint() -> None:
    """Cert sem o fingerprint anunciado é rejeitado ANTES do handshake WS."""
    server = start_host_server(0, 0)
    try:
        assert server.ws_port is not None
        with GameClient() as client:
            with pytest.raises(ConnectionError, match="fingerprint TLS divergente"):
                client.connect_wss(
                    "127.0.0.1",
                    server.ws_port,
                    "cli",
                    tls_fingerprint="0" * 64,
                )
            assert client.player_id is None
    finally:
        server.stop()


@pytest.mark.integration
def test_connect_auto_falls_back_to_tcp_on_bad_pin() -> None:
    """Pin errado na wss → cascata cai para TCP cru transparentemente."""
    server = start_host_server(0, 0)
    try:
        assert server.ws_port is not None
        with GameClient() as client:
            client.connect_auto(
                "127.0.0.1",
                tcp_port=server.port,
                ws_port=server.ws_port,
                nickname="cli",
                tls_fingerprint="0" * 64,
            )
            assert client.transport == "tcp"
            assert client.player_id is not None
    finally:
        server.stop()
