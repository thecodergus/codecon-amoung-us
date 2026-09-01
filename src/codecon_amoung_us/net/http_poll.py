"""Transporte HTTP long polling: o mesmo protocolo msgspec sobre HTTP puro.

Último degrau da cascata de transportes: proxies corporativos com inspeção
de conteúdo removem o ``Upgrade`` do WebSocket, mas raramente bloqueiam HTTP
simples. O downstream é um ``GET /poll`` que o servidor segura até haver
mensagens (long poll, sem polling cego); o upstream é ``POST /send`` com o
corpo em JSON Lines — os mesmos frames do TCP. Latência maior que ws/TCP:
modo compatibilidade, jogável e não competitivo.

Implementação sobre ``ThreadingHTTPServer`` (stdlib) — nenhuma dependência
nova; sessões expiram por inatividade (GC) e nenhuma thread dedicada por
conexão.
"""

from __future__ import annotations

import contextlib
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import msgspec

from ..config import (
    HTTP_POLL_HOLD_SECONDS,
    HTTP_POLL_MAX_BODY_BYTES,
    HTTP_POLL_MAX_SESSIONS,
    HTTP_POLL_SESSION_TIMEOUT_SECONDS,
)
from ..framing import FrameDecoder, FrameError, encode_frame
from ..protocol import Message, ProtocolError

if TYPE_CHECKING:
    from .server import GameServer

__all__ = ["HttpPollClientConnection", "HttpPollListener"]

_GC_INTERVAL_SECONDS = 5.0


class _SessionCreated(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    """Resposta do ``POST /connect``: identificação da sessão long polling."""

    session: str


class HttpPollClientConnection:
    """Conexão HTTP vista pelo servidor — mesma interface de ``ClientConnection``.

    Sem thread dedicada: o downstream é o ``GET /poll`` (drain do outbox) e
    o upstream o ``POST /send`` (ingest). A sessão morre por inatividade
    (GC do listener) ou ``POST /close``.
    """

    def __init__(self, server: GameServer, session_id: str) -> None:
        self._server = server
        self.session_id = session_id
        self.player_id: int | None = None
        self.nickname: str = ""
        self._decoder = FrameDecoder()
        self._lock = threading.Lock()
        self._outbox: list[bytes] = []
        self._event = threading.Event()
        self._closed = False
        self._last_seen = time.monotonic()

    # ------------------------------------------------------------- upstream

    def ingest(self, data: bytes) -> None:
        """Frames do ``POST /send``: decodifica e enfileira no servidor."""
        self.touch()
        try:
            messages = self._decoder.feed(data)
        except FrameError as exc:
            self.send(ProtocolError(code="bad_frame", message=str(exc)))
            return
        for message in messages:
            self._server.enqueue(self, message)

    # ------------------------------------------------------------ downstream

    def send(self, message: Message) -> None:
        """Enfileira o frame para o próximo ``GET /poll`` (thread-safe)."""
        try:
            frame = encode_frame(message)
        except FrameError:
            return
        with self._lock:
            if self._closed:
                return
            self._outbox.append(frame)
        self._event.set()

    def drain(self, hold_seconds: float) -> bytes:
        """Espera (long poll) e devolve os frames acumulados (JSON Lines)."""
        self.touch()
        self._event.wait(hold_seconds)
        with self._lock:
            frames = self._outbox
            self._outbox = []
            if not self._outbox:
                self._event.clear()
        self.touch()
        return b"".join(frames)

    # ------------------------------------------------------------- lifecycle

    def close(self) -> None:
        """Fecha a sessão e acorda polls em espera (idempotente)."""
        with self._lock:
            self._closed = True
        self._event.set()

    def join(self, timeout: float) -> None:
        """Sem thread dedicada — handlers pertencem ao ``ThreadingHTTPServer``."""

    def touch(self) -> None:
        """Renova a sessão (chamado por /send e /poll)."""
        self._last_seen = time.monotonic()

    def expired(self) -> bool:
        """Sessão sem atividade além do timeout de inatividade."""
        return time.monotonic() - self._last_seen > HTTP_POLL_SESSION_TIMEOUT_SECONDS


class _PollHTTPServer(ThreadingHTTPServer):
    """HTTP server com referência ao listener (para os handlers)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        listener: HttpPollListener,
    ) -> None:
        super().__init__(address, handler)
        self.poll_listener = listener


class _Handler(BaseHTTPRequestHandler):
    """Rotas: ``POST /connect``, ``POST /send``, ``POST /close``, ``GET /poll``."""

    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        """Silencioso: logs de acesso poluem CI e console do host."""

    def _listener(self) -> HttpPollListener:
        server = self.server
        if isinstance(server, _PollHTTPServer):
            return server.poll_listener
        raise RuntimeError("handler HTTP fora do _PollHTTPServer")

    def _respond(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _session(self) -> HttpPollClientConnection | None:
        query = parse_qs(urlparse(self.path).query)
        values = query.get("session")
        session_id = values[0] if values else None
        if session_id is None:
            return None
        return self._listener().session(session_id)

    def _content_length(self) -> int | None:
        """``Content-Length`` validado; ``None`` = ausente/malformado/negativo."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            return 0
        try:
            length = int(raw)
        except ValueError:
            return None
        return length if length >= 0 else None

    def _reject(self, status: int, message: str) -> None:
        """Resposta de rejeição: encerra a conexão (corpo pode ter sobrado)."""
        self.close_connection = True
        self._respond(status, f'{{"error":"{message}"}}'.encode())

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        listener = self._listener()
        if path == "/connect":
            if not listener.can_accept_session():
                self._reject(503, "limite de sessoes simultaneas")
                return
            created = listener.create_session()
            self._respond(200, msgspec.json.encode(_SessionCreated(session=created.session_id)))
            return
        if path == "/send":
            # Corpo validado ANTES da leitura e antes do lookup de sessão
            # (RFC 9110: 400/413) — rejeita requisição malformada cedo.
            length = self._content_length()
            if length is None:
                self._reject(400, "content-length invalido")
                return
            if length > HTTP_POLL_MAX_BODY_BYTES:
                self._reject(413, "corpo excede o teto")
                return
            conn = self._session()
            if conn is None:
                self._respond(404, b'{"error":"sessao desconhecida"}')
                return
            conn.ingest(self.rfile.read(length))
            self._respond(200, b"")
            return
        conn = self._session()
        if conn is None:
            self._respond(404, b'{"error":"sessao desconhecida"}')
            return
        if path == "/close":
            listener.drop_session(conn.session_id)
            self._respond(200, b"")
            return
        self._respond(404, b'{"error":"rota desconhecida"}')

    def do_GET(self) -> None:
        if urlparse(self.path).path != "/poll":
            self._respond(404, b'{"error":"rota desconhecida"}')
            return
        conn = self._session()
        if conn is None:
            self._respond(404, b'{"error":"sessao desconhecida"}')
            return
        try:
            body = conn.drain(HTTP_POLL_HOLD_SECONDS)
        except (ConnectionError, OSError):
            return  # cliente sumiu: a resposta é irrelevante
        self._respond(200, body)


class HttpPollListener:
    """Listener HTTP do servidor: accept loop + GC de sessões em threads daemon."""

    def __init__(self, server: GameServer, host: str, port: int) -> None:
        self._server = server
        self._sessions: dict[str, HttpPollClientConnection] = {}
        self._lock = threading.Lock()
        self._httpd = _PollHTTPServer((host, port), _Handler, self)
        self.port: int = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="http-poll-listener", daemon=True
        )
        self._gc_stop = threading.Event()
        self._gc_thread = threading.Thread(target=self._gc_loop, name="http-poll-gc", daemon=True)

    def start(self) -> None:
        """Inicia accept loop e GC (idempotente)."""
        self._thread.start()
        self._gc_thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Encerra accept loop, GC e sessões (idempotente)."""
        self._gc_stop.set()
        with self._lock:
            conns = list(self._sessions.values())
        for conn in conns:
            conn.close()
        with contextlib.suppress(OSError):
            self._httpd.shutdown()
            self._httpd.server_close()
        for thread in (self._thread, self._gc_thread):
            if thread is not None and thread.is_alive():
                thread.join(timeout)

    # -------------------------------------------------------------- sessões

    def can_accept_session(self) -> bool:
        """Há vaga dentro do teto de sessões simultâneas?"""
        with self._lock:
            return len(self._sessions) < HTTP_POLL_MAX_SESSIONS

    def create_session(self) -> HttpPollClientConnection:
        """Nova sessão registrada no servidor (o join chega pelo /send)."""
        conn = HttpPollClientConnection(self._server, secrets.token_hex(16))
        with self._lock:
            self._sessions[conn.session_id] = conn
        self._server.register_connection(conn)
        return conn

    def session(self, session_id: str) -> HttpPollClientConnection | None:
        with self._lock:
            return self._sessions.get(session_id)

    def drop_session(self, session_id: str) -> None:
        """Remove a sessão e notifica o servidor (desconexão explícita/GC)."""
        with self._lock:
            conn = self._sessions.pop(session_id, None)
        if conn is not None:
            conn.close()
            self._server.on_disconnect(conn)

    def _gc_loop(self) -> None:
        while not self._gc_stop.wait(_GC_INTERVAL_SECONDS):
            with self._lock:
                expired = [conn.session_id for conn in self._sessions.values() if conn.expired()]
            for session_id in expired:
                self.drop_session(session_id)
