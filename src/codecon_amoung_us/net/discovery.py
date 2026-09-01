"""Descoberta de partidas na LAN via UDP broadcast.

O host anuncia a partida periodicamente (beacon) enquanto está em LOBBY; o
cliente escuta passivamente por alguns segundos e monta a lista. Broadcast
direto em vez de mDNS/multicast: multicast é frequentemente dropado por
roteadores/APs corporativos e de evento, e o beacon cabe na stdlib.

O beacon envia para todas as formas de broadcast disponíveis (global
``255.255.255.255`` e o dirigido à sub-rede, ex.: ``192.168.1.255``): filtros
de AP/roteador derrubam um e passam o outro — enviar para ambos maximiza a
descoberta sem dependência nova.

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
    DISCOVERY_PROBE_MAGIC,
    DISCOVERY_SWEEP_PPS,
    MAX_DISCOVERY_BYTES,
    PROTOCOL_VERSION,
)

__all__ = [
    "GameAnnouncement",
    "DiscoveredGame",
    "DiscoveryBeacon",
    "DiscoveryProbe",
    "DiscoveryResponder",
    "encode_announcement",
    "decode_announcement",
    "discover_games",
    "sweep_games",
    "local_broadcast_addresses",
    "local_unicast_targets",
]

_BROADCAST_ADDR = "255.255.255.255"
# Endereço TEST-NET-1 (RFC 5737): ``connect`` UDP não gera tráfego; serve só
# para descobrir o IP local da rota padrão via ``getsockname()``.
_ROUTE_PROBE = ("192.0.2.1", 80)


def _local_ip() -> str | None:
    """IP local da rota padrão (sem tráfego); ``None`` se indisponível."""
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(_ROUTE_PROBE)
        return str(sock.getsockname()[0])
    return None


def _subnet_broadcast(local_ip: str) -> str | None:
    """Broadcast dirigido da sub-rede (último octeto ``.255``, /24 assumido).

    A maior parte das LANs domésticas/de evento usa /24; um candidato errado
    só não recebe nada (falha de envio é suprimida), nunca quebra a descoberta.
    """
    octets = local_ip.split(".")
    if len(octets) != 4:
        return None
    try:
        values = [int(octet) for octet in octets]
    except ValueError:
        return None
    if any(value < 0 or value > 255 for value in values):
        return None
    return f"{values[0]}.{values[1]}.{values[2]}.255"


def local_broadcast_addresses() -> list[str]:
    """Todos os destinos de anúncio: broadcast global + dirigido à sub-rede.

    Deduplicado, preservando o global primeiro (sempre tentado).
    """
    addresses = [_BROADCAST_ADDR]
    local_ip = _local_ip()
    if local_ip is not None:
        subnet = _subnet_broadcast(local_ip)
        if subnet is not None:
            addresses.append(subnet)
    return list(dict.fromkeys(addresses))


class GameAnnouncement(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    """Anúncio periódico de uma partida aberta (um datagrama UDP)."""

    magic: str
    protocol_version: int
    host_name: str
    players: int
    max_players: int
    tcp_port: int
    ws_port: int | None = None
    # Fingerprint SHA-256 (hex) do cert TLS do host quando o listener WS está
    # em wss (ver net/tls.py) — o cliente só aceita o cert anunciado (pin).
    tls_fingerprint: str | None = None


@dataclass(frozen=True)
class DiscoveredGame:
    """Partida encontrada na LAN: dados para exibição e conexão."""

    ip: str
    host_name: str
    players: int
    max_players: int
    tcp_port: int
    ws_port: int | None
    tls_fingerprint: str | None


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
        broadcast_addr: str | None = None,
    ) -> None:
        """``broadcast_addr=None`` usa todos os destinos de broadcast locais.

        Um valor explícito restringe o envio a um único endereço (testes).
        """
        self._make_announcement = make_announcement
        self._port = port
        self._interval = interval_seconds
        self._broadcast_addrs = (
            local_broadcast_addresses() if broadcast_addr is None else [broadcast_addr]
        )
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
                    payload = encode_announcement(announcement)
                    for address in self._broadcast_addrs:
                        with contextlib.suppress(OSError):
                            # destino indisponível (ex.: filtro de AP) — segue nos demais
                            sock.sendto(payload, (address, self._port))
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
                tls_fingerprint=announcement.tls_fingerprint,
            )
        return sorted(games.values(), key=lambda g: (g.host_name, g.ip, g.tcp_port))
    finally:
        sock.close()


class DiscoveryProbe(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    """Pedido de anúncio do sweep unicast (o host responde com ``GameAnnouncement``)."""

    magic: str
    protocol_version: int


def encode_probe(probe: DiscoveryProbe) -> bytes:
    """Serializa o probe como JSON (um datagrama)."""
    return msgspec.json.encode(probe)


def decode_probe(data: bytes) -> DiscoveryProbe | None:
    """Decodifica um probe; ``None`` para conteúdo inválido ou alheio."""
    if not data or len(data) > MAX_DISCOVERY_BYTES:
        return None
    try:
        probe = msgspec.json.decode(data, type=DiscoveryProbe)
    except msgspec.DecodeError:
        return None
    if probe.magic != DISCOVERY_PROBE_MAGIC:
        return None
    if probe.protocol_version != PROTOCOL_VERSION:
        return None
    return probe


def local_unicast_targets() -> list[str]:
    """Todos os IPs unicast candidatos da sub-rede local (/24 assumido).

    Broadcast é filtrado entre/por VLANs em redes corporativas, mas unicast
    intra-subnet normalmente passa (docs Cisco/Aruba): o sweep tenta cada
    endereço individualmente. Sub-redes maiores que /24 são truncadas (o
    custo cresce linearmente; /24 cobre as LANs de evento/domésticas).
    """
    local_ip = _local_ip()
    if local_ip is None:
        return []
    octets = local_ip.split(".")
    if len(octets) != 4:
        return []
    try:
        values = [int(octet) for octet in octets]
    except ValueError:
        return []
    if any(value < 0 or value > 255 for value in values):
        return []
    prefix = f"{values[0]}.{values[1]}.{values[2]}"
    return [f"{prefix}.{host}" for host in range(1, 255)]


class DiscoveryResponder:
    """Responde probes unicast do sweep com o anúncio corrente do host.

    O beacon é unidirecional (host → todos); o sweep inverte o fluxo
    (cliente → host). Um único socket em ``0.0.0.0:porta`` recebe broadcast
    e unicast; datagramas que não são probes são ignorados.
    """

    def __init__(
        self,
        make_announcement: Callable[[], GameAnnouncement | None],
        *,
        port: int = DISCOVERY_PORT,
    ) -> None:
        self._make_announcement = make_announcement
        self._port = port
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Inicia a thread de resposta (idempotente)."""
        if self._thread is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with contextlib.suppress(OSError, AttributeError):
            # SO_REUSEPORT não existe no Windows; onde existe, o socket do
            # responder e o listener passivo do cliente local convivem.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", self._port))
        sock.settimeout(0.1)
        self._sock = sock
        self._thread = threading.Thread(target=self._run, name="discovery-responder", daemon=True)
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
                data, addr = sock.recvfrom(MAX_DISCOVERY_BYTES)
            except TimeoutError:
                continue
            except OSError:
                break  # socket fechado no stop
            if decode_probe(data) is None:
                continue
            announcement = self._make_announcement()
            if announcement is None:
                continue
            with contextlib.suppress(OSError):
                sock.sendto(encode_announcement(announcement), addr)


def sweep_games(
    timeout: float | None = None,
    *,
    port: int = DISCOVERY_PORT,
    targets: list[str] | None = None,
) -> list[DiscoveredGame]:
    """Varre a sub-rede com probes unicast e retorna as partidas únicas.

    Fallback da descoberta por broadcast: filtros de VLAN/AP derrubam
    broadcast e passam unicast intra-subnet. Pacing de ~``PPS`` pacotes/s —
    a varredura não deve parecer scan para IDS corporativos. Bloqueante
    (``timeout=None`` = orçamento automático: sub-rede inteira + dreno) —
    chamar fora da thread gráfica. ``targets`` sobrescreve a sub-rede
    derivada (testes).
    """
    if targets is None:
        targets = local_unicast_targets()
    if timeout is None:
        timeout = len(targets) / DISCOVERY_SWEEP_PPS + 0.5 if targets else 0.0
    probe = encode_probe(
        DiscoveryProbe(magic=DISCOVERY_PROBE_MAGIC, protocol_version=PROTOCOL_VERSION)
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("", 0))  # porta efêmera: as respostas voltam direto
        sock.settimeout(0.05)
        games: dict[tuple[str, int], DiscoveredGame] = {}

        def _collect_once() -> None:
            try:
                data, (ip, _src_port) = sock.recvfrom(MAX_DISCOVERY_BYTES)
            except (TimeoutError, OSError):
                return
            announcement = decode_announcement(data)
            if announcement is None:
                return
            games[(ip, announcement.tcp_port)] = DiscoveredGame(
                ip=ip,
                host_name=announcement.host_name,
                players=announcement.players,
                max_players=announcement.max_players,
                tcp_port=announcement.tcp_port,
                ws_port=announcement.ws_port,
                tls_fingerprint=announcement.tls_fingerprint,
            )

        deadline = time.monotonic() + timeout
        for target in targets:
            if time.monotonic() >= deadline:
                break
            with contextlib.suppress(OSError):
                sock.sendto(probe, (target, port))
            # Um recv por envio dá o pacing (~1/0,05 s = 20 pps) e colhe
            # respostas conforme chegam (resposta de rede local é imediata).
            _collect_once()
        while time.monotonic() < deadline:
            _collect_once()
        return sorted(games.values(), key=lambda g: (g.host_name, g.ip, g.tcp_port))
    finally:
        sock.close()
