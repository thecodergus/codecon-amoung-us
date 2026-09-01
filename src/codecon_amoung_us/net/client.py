"""Cliente simulado (sem pygame) e base do cliente de UI.

Usado por testes de integração e pela interface Pygame. Nunca bloqueia a
suíte: recv loop com timeout curto e ``wait_for`` com timeout configurável.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import Literal, TypeVar, cast

from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection as SyncWSConnection
from websockets.sync.client import connect as ws_connect

from ..config import PROTOCOL_VERSION
from ..framing import FrameDecoder, FrameError, encode_frame
from ..game.model import Role
from ..protocol import (
    JoinAccepted,
    Message,
    RoleAssigned,
    TaskState,
    WorldSnapshot,
)
from .tls import client_ssl_context, fingerprint_of_der

__all__ = ["GameClient"]

_M = TypeVar("_M", bound=Message)
Transport = Literal["", "tcp", "ws", "wss"]


class GameClient:
    """Cliente TCP não-bloqueante: recebe frames em thread própria.

    É o cliente de produção usado pela UI (``ui/app.py``). Os helpers de
    sincronização (``wait_for``/``wait_for_any``/``peek``/``drain``) existem
    para testes e smoke: consomem mensagens da fila interna e lançam
    ``TimeoutError`` se o prazo expirar — nenhum teste fica preso.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._ws: SyncWSConnection | None = None
        self._decoder = FrameDecoder()
        self._stop = threading.Event()
        self._recv_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._messages: list[Message] = []
        self._join: JoinAccepted | None = None
        self.player_id: int | None = None
        self.host_player_id: int | None = None
        self.transport: Transport = ""
        self._role: Role | None = None
        self._snapshot: WorldSnapshot | None = None
        self._tasks: TaskState | None = None
        self._tick = 0

    # ------------------------------------------------------------------ conexão

    def connect(self, host: str, port: int, nickname: str, timeout: float = 5.0) -> None:
        """Conecta via TCP cru e envia JoinRequest; aguarda JoinAccepted."""
        self._reset_transport()
        sock = socket.create_connection((host, port), timeout=timeout)
        self._sock = sock
        self.transport = "tcp"
        sock.settimeout(0.2)
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="client-recv", daemon=True
        )
        self._recv_thread.start()
        self.send_join(nickname)
        self.wait_for(JoinAccepted, timeout=timeout)

    def connect_ws(self, host: str, port: int, nickname: str, timeout: float = 5.0) -> None:
        """Conecta via WebSocket (transporte preferencial) e envia JoinRequest."""
        self._reset_transport()
        # legacy=True: ciclo de vida gerenciado pela própria classe (close()),
        # sem context manager — modo suportado para esse uso no websockets
        # >=17.1 (o parâmetro não existe na 17.0 — ver pyproject, piso 17.1).
        self._ws = ws_connect(f"ws://{host}:{port}/", open_timeout=timeout, legacy=True)
        self.transport = "ws"
        self._recv_thread = threading.Thread(
            target=self._ws_recv_loop, name="client-ws-recv", daemon=True
        )
        self._recv_thread.start()
        self.send_join(nickname)
        self.wait_for(JoinAccepted, timeout=timeout)

    def connect_wss(
        self,
        host: str,
        port: int,
        nickname: str,
        *,
        tls_fingerprint: str,
        timeout: float = 5.0,
    ) -> None:
        """Conecta via WebSocket sobre TLS self-signed (pin) e envia JoinRequest.

        O handshake TLS é feito aqui (e não pelo websockets) para validar o
        pin ANTES do handshake WS: o certificado apresentado precisa ter o
        fingerprint anunciado no beacon (``net/tls.py``); divergência aborta
        sem enviar nada.
        """
        self._reset_transport()
        context = client_ssl_context()
        raw = socket.create_connection((host, port), timeout=timeout)
        try:
            tls_sock = context.wrap_socket(raw, server_hostname=host)
        except OSError:
            raw.close()
            raise
        der = tls_sock.getpeercert(binary_form=True)
        if der is None or fingerprint_of_der(der) != tls_fingerprint:
            tls_sock.close()
            raise ConnectionError(f"fingerprint TLS divergente para {host}:{port}")
        try:
            # Socket já cifrado: o handshake WS corre como ws:// sobre o
            # transporte TLS pronto (websockets não toca no socket fornecido).
            self._ws = ws_connect(
                f"ws://{host}:{port}/",
                sock=tls_sock,
                open_timeout=timeout,
                legacy=True,
            )
        except BaseException:
            tls_sock.close()
            raise
        self.transport = "wss"
        self._recv_thread = threading.Thread(
            target=self._ws_recv_loop, name="client-wss-recv", daemon=True
        )
        self._recv_thread.start()
        self.send_join(nickname)
        self.wait_for(JoinAccepted, timeout=timeout)

    def connect_auto(
        self,
        host: str,
        *,
        tcp_port: int | None,
        ws_port: int | None,
        nickname: str,
        timeout: float = 5.0,
        tls_fingerprint: str | None = None,
    ) -> None:
        """Conecta pelo melhor transporte: wss (pin) → ws → TCP cru.

        ``tls_fingerprint`` presente (anunciado no beacon) → a porta WS está
        em wss (net/tls.py). A falha de um transporte cai para o seguinte; se
        todos falharem, propaga ``ConnectionError`` encadeada à última falha.
        """
        attempts: list[tuple[Transport, int, str | None]] = []
        if ws_port is not None:
            if tls_fingerprint is not None:
                attempts.append(("wss", ws_port, tls_fingerprint))
            else:
                attempts.append(("ws", ws_port, None))
        if tcp_port is not None:
            attempts.append(("tcp", tcp_port, None))
        if not attempts:
            raise ValueError("connect_auto exige ao menos uma porta (tcp_port ou ws_port)")
        last_error: Exception | None = None
        for transport, port, fingerprint in attempts:
            try:
                if transport == "wss":
                    # O fingerprint viaja na tupla do attempt (sempre presente
                    # para wss) — cast local evita checagem redundante.
                    self.connect_wss(
                        host,
                        port,
                        nickname,
                        tls_fingerprint=cast(str, fingerprint),
                        timeout=timeout,
                    )
                elif transport == "ws":
                    self.connect_ws(host, port, nickname, timeout=timeout)
                else:
                    self.connect(host, port, nickname, timeout=timeout)
                return
            except (OSError, TimeoutError, WebSocketException) as exc:
                last_error = exc
        raise ConnectionError(
            f"falha em todos os transportes para {host} "
            f"({', '.join(f'{t}:{p}' for t, p, _f in attempts)})"
        ) from last_error

    def _reset_transport(self) -> None:
        """Fecha o transporte anterior e reinicia o estado de recepção (reuso)."""
        self.close()
        self._sock = None
        self._ws = None
        self._recv_thread = None
        self._stop = threading.Event()
        self._decoder = FrameDecoder()
        with self._lock:
            self._messages.clear()
        self.transport = ""

    def send_join(self, nickname: str) -> None:
        from ..protocol import JoinRequest

        self.send(JoinRequest(nickname=nickname, protocol_version=PROTOCOL_VERSION))

    def close(self) -> None:
        """Fecha o transporte e encerra a thread de recv (idempotente)."""
        self._stop.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
        if self._ws is not None:
            with contextlib.suppress(ConnectionClosed, OSError):
                self._ws.close()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=3.0)

    def __enter__(self) -> GameClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _recv_loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        while not self._stop.is_set():
            try:
                data = sock.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not data:
                break
            try:
                self._ingest(data)
            except FrameError:
                break

    def _ws_recv_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        while not self._stop.is_set():
            try:
                data = ws.recv(timeout=0.2)
            except TimeoutError:
                continue
            except (ConnectionClosed, OSError):
                break
            payload = data.encode() if isinstance(data, str) else data
            try:
                # O \n repõe o delimitador do JSON Lines: cada mensagem WS
                # vira exatamente um frame para o decoder compartilhado.
                self._ingest(payload + b"\n")
            except FrameError:
                break

    def _ingest(self, data: bytes) -> None:
        """Decodifica bytes recebidos e registra mensagens (qualquer transporte)."""
        messages = self._decoder.feed(data)
        with self._lock:
            for message in messages:
                self._messages.append(message)
                if isinstance(message, JoinAccepted):
                    self.player_id = message.player_id
                    self.host_player_id = message.host_player_id
                    self._join = message
                elif isinstance(message, RoleAssigned):
                    self._role = message.role
                elif isinstance(message, WorldSnapshot):
                    self._snapshot = message
                elif isinstance(message, TaskState):
                    self._tasks = message

    # ------------------------------------------------------------------ envio

    def send(self, message: Message) -> None:
        frame = encode_frame(message)
        if self._ws is not None:
            # frame[:-1] remove o \n: o WS já delimita mensagens.
            self._ws.send(frame[:-1].decode())
            return
        sock = self._sock
        if sock is None:
            raise ConnectionError("cliente não conectado")
        sock.sendall(frame)

    def move(self, dx: float, dy: float) -> None:
        from ..protocol import MovementInput

        self._tick += 1
        self.send(MovementInput(dx=dx, dy=dy, tick=self._tick))

    def start_game(self) -> None:
        from ..protocol import StartGameRequest

        self.send(StartGameRequest())

    def kill(self, target_id: int) -> None:
        from ..protocol import KillRequest

        self.send(KillRequest(target_id=target_id))

    def report(self, body_id: int) -> None:
        from ..protocol import BodyReported

        self.send(BodyReported(body_id=body_id))

    def emergency(self) -> None:
        from ..protocol import EmergencyMeetingRequest

        self.send(EmergencyMeetingRequest())

    def vote(self, meeting_id: int, target_id: int | None) -> None:
        from ..protocol import VoteRequest

        self.send(VoteRequest(meeting_id=meeting_id, target_id=target_id))

    def complete_task(self, task_id: int) -> None:
        from ..protocol import TaskActionRequest

        self.send(TaskActionRequest(task_id=task_id))

    # ------------------------------------------------------------------ recepção

    def wait_for(self, message_type: type[_M], timeout: float = 5.0) -> _M:
        """Consome a primeira mensagem do tipo dado; TimeoutError se expirar."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for i, message in enumerate(self._messages):
                    if isinstance(message, message_type):
                        del self._messages[i]
                        return message
            time.sleep(0.005)
        raise TimeoutError(f"não recebeu {message_type.__name__} em {timeout}s")

    def wait_for_any(self, message_types: tuple[type[_M], ...], timeout: float = 5.0) -> _M:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for i, message in enumerate(self._messages):
                    if isinstance(message, message_types):
                        del self._messages[i]
                        return cast(_M, message)
            time.sleep(0.005)
        raise TimeoutError(
            f"não recebeu nenhum de {[t.__name__ for t in message_types]} em {timeout}s"
        )

    def peek(self, message_type: type[Message]) -> Message | None:
        """Retorna a primeira mensagem do tipo dado sem consumir."""
        with self._lock:
            for message in self._messages:
                if isinstance(message, message_type):
                    return message
        return None

    def drain(self) -> list[Message]:
        """Consome e retorna todas as mensagens pendentes."""
        with self._lock:
            messages = self._messages
            self._messages = []
            return messages

    # ------------------------------------------------------------------ estado

    @property
    def role(self) -> Role | None:
        return self._role

    @property
    def join_accepted(self) -> JoinAccepted | None:
        """Último ``JoinAccepted`` recebido (róster do lobby, incluindo o próprio)."""
        with self._lock:
            return self._join

    @property
    def snapshot(self) -> WorldSnapshot | None:
        with self._lock:
            return self._snapshot

    @property
    def tasks(self) -> TaskState | None:
        with self._lock:
            return self._tasks

    def wait_for_snapshot(self, timeout: float = 5.0) -> WorldSnapshot:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            snapshot = self.snapshot
            if snapshot is not None:
                return snapshot
            time.sleep(0.005)
        raise TimeoutError(f"nenhum snapshot recebido em {timeout}s")
