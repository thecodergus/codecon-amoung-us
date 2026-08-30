"""Descoberta de partidas na LAN via UDP broadcast.

O host anuncia a partida periodicamente (beacon) enquanto está em LOBBY; o
cliente escuta passivamente por alguns segundos e monta a lista. Broadcast
direto em vez de mDNS/multicast: multicast é frequentemente dropado por
roteadores/APs corporativos e de evento, e o beacon cabe na stdlib.

Limitação conhecida: Wi-Fi com "client isolation" bloqueia TODO tráfego
ponto-a-ponto — nem o beacon nem a conexão direta funcionam; o campo de IP
manual continua sendo o fallback nesse cenário.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import msgspec

from ..config import (
    DISCOVERY_BEACON_INTERVAL_SECONDS,
    DISCOVERY_LISTEN_SECONDS,
    DISCOVERY_MAGIC,
    DISCOVERY_PORT,
    MAX_DISCOVERY_BYTES,
    PROTOCOL_VERSION,
)

__all__ = [
    "GameAnnouncement",
    "DiscoveredGame",
    "DiscoveryBeacon",
    "encode_announcement",
    "decode_announcement",
    "discover_games",
]

_BROADCAST_ADDR = "255.255.255.255"


class GameAnnouncement(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    """Anúncio periódico de uma partida aberta (um datagrama UDP)."""

    magic: str
    protocol_version: int
    host_name: str
    players: int
    max_players: int
    tcp_port: int
    ws_port: int | None = None


@dataclass(frozen=True)
class DiscoveredGame:
    """Partida encontrada na LAN: dados para exibição e conexão."""

    ip: str
    host_name: str
    players: int
    max_players: int
    tcp_port: int
    ws_port: int | None


def encode_announcement(announcement: GameAnnouncement) -> bytes:
    """Serializa o anúncio como JSON (um datagrama)."""
    return msgspec.json.encode(announcement)


def decode_announcement(data: bytes) -> GameAnnouncement | None:
    """Decodifica um datagrama; ``None`` para conteúdo inválido ou alheio.

    A porta de descoberta é compartilhada e a rede é hostil por definição:
    datagramas malformados, de outro serviço ou de versão incompatível nunca
    propagam exceção para a UI.
    """
    if not data or len(data) > MAX_DISCOVERY_BYTES:
        return None
    try:
        announcement = msgspec.json.decode(data, type=GameAnnouncement)
    except msgspec.DecodeError:
        return None
    if announcement.magic != DISCOVERY_MAGIC:
        return None
    if announcement.protocol_version != PROTOCOL_VERSION:
        return None
    return announcement


class DiscoveryBeacon:
    """Anuncia a partida em broadcast enquanto houver anúncio a fazer.

    ``make_announcement`` retorna ``None`` quando não há o que anunciar (ex.:
    partida fora do lobby) — o beacon segue vivo e volta a anunciar sozinho.
    Falhas de envio (rede transitória) são suprimidas por iteração.
    """

    def __init__(
        self,
        make_announcement: Callable[[], GameAnnouncement | None],
        *,
        port: int = DISCOVERY_PORT,
        interval_seconds: float = DISCOVERY_BEACON_INTERVAL_SECONDS,
        broadcast_addr: str = _BROADCAST_ADDR,
    ) -> None:
        self._make_announcement = make_announcement
        self._port = port
        self._interval = interval_seconds
        self._broadcast_addr = broadcast_addr
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Inicia a thread de anúncio (idempotente)."""
        if self._thread is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="discovery-beacon", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Encerra a thread e fecha o socket (idempotente)."""
        self._stop.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _run(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                announcement = self._make_announcement()
                if announcement is not None:
                    sock.sendto(
                        encode_announcement(announcement), (self._broadcast_addr, self._port)
                    )
            except OSError:
                pass  # rede transitória (interface caiu, etc.) — tenta no próximo ciclo
            self._stop.wait(self._interval)


def discover_games(
    timeout: float = DISCOVERY_LISTEN_SECONDS, *, port: int = DISCOVERY_PORT
) -> list[DiscoveredGame]:
    """Escuta anúncios por ``timeout`` segundos e retorna as partidas únicas.

    Bloqueante por até ``timeout`` — chamar fora da thread gráfica.
    ``SO_REUSEADDR``/``SO_REUSEPORT`` permitem múltiplos clientes na mesma
    porta de uma máquina (ex.: host e cliente no mesmo computador).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with contextlib.suppress(OSError, AttributeError):
            # SO_REUSEPORT não existe no Windows; onde existe (Linux/macOS),
            # garante a entrega do broadcast a todos os sockets locais.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", port))
        sock.settimeout(0.1)
        games: dict[tuple[str, int], DiscoveredGame] = {}
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _src_port) = sock.recvfrom(MAX_DISCOVERY_BYTES)
            except TimeoutError:
                continue
            announcement = decode_announcement(data)
            if announcement is None:
                continue
            games[(ip, announcement.tcp_port)] = DiscoveredGame(
                ip=ip,
                host_name=announcement.host_name,
                players=announcement.players,
                max_players=announcement.max_players,
                tcp_port=announcement.tcp_port,
                ws_port=announcement.ws_port,
            )
        return sorted(games.values(), key=lambda g: (g.host_name, g.ip, g.tcp_port))
    finally:
        sock.close()
