"""Transporte WebSocket: o mesmo protocolo msgspec dentro de frames WS.

WebSocket atravessa proxies e firewalls corporativos que bloqueiam TCP cru em
portas arbitrárias: o handshake é um HTTP GET + Upgrade, indistinguível de
tráfego web para firewalls baseados em porta/protocolo. Cada mensagem WS de
texto carrega exatamente uma mensagem do protocolo — a validação permanece
centralizada em ``framing.FrameDecoder``/``protocol``, sem duplicação.

Implementação sobre ``websockets.sync`` (threads), a mesma concorrência do
resto do servidor — nenhum asyncio é introduzido.
"""

from __future__ import annotations

import contextlib
import socket
import ssl
import threading
from typing import TYPE_CHECKING

from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from ..framing import FrameDecoder, FrameError, encode_frame
from ..protocol import Message, ProtocolError

if TYPE_CHECKING:
    from .server import GameServer

__all__ = ["WSClientConnection", "WSListener"]


class WSClientConnection:
    """Conexão WebSocket vista pelo servidor — mesma interface de ``ClientConnection``.

    Diferente do TCP, o recv loop roda na thread do handler do
    ``websockets.sync`` (uma por conexão): ``run`` é chamado pelo
    ``WSListener`` e bloqueia até o fechamento, dispensando thread própria.
    """

    def __init__(self, server: GameServer, ws: ServerConnection) -> None:
        self._server = server
        self._ws = ws
        self._decoder = FrameDecoder()
        self._send_lock = threading.Lock()
        self.player_id: int | None = None
        self.nickname: str = ""
        self._thread: threading.Thread | None = None

    def run(self) -> None:
        """Loop de recepção (bloqueante) — executado na thread do handler WS."""
        self._thread = threading.current_thread()
        try:
            for data in self._ws:
                payload = data.encode() if isinstance(data, str) else data
                try:
                    # O \n repõe o delimitador do framing JSON Lines: cada
                    # mensagem WS vira exatamente um frame para o decoder.
                    messages = self._decoder.feed(payload + b"\n")
                except FrameError as exc:
                    self.send(ProtocolError(code="bad_frame", message=str(exc)))
                    break
                for message in messages:
                    self._server.enqueue(self, message)
        except ConnectionClosed:
            pass
        finally:
            # Mesmo contrato do ClientConnection: fechamento determinístico e
            # notificação do servidor em todos os caminhos de saída.
            self.close()
            self._server.on_disconnect(self)

    def send(self, message: Message) -> None:
        """Envia uma mensagem como frame WS de texto (thread-safe)."""
        try:
            frame = encode_frame(message)
        except FrameError:
            return
        with self._send_lock, contextlib.suppress(ConnectionClosed, OSError):
            # frame[:-1] remove o \n: o WS já delimita mensagens. O JSON do
            # msgspec é UTF-8 puro, então o decode é total.
            self._ws.send(frame[:-1].decode())

    def close(self) -> None:
        with contextlib.suppress(ConnectionClosed, OSError):
            self._ws.close()

    def join(self, timeout: float) -> None:
        # A thread pertence ao handler do websockets; nunca se junta a si mesma
        # (close pode vir do próprio handler via broadcast/shutdown).
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)


class WSListener:
    """Listener WebSocket do servidor: accept loop em thread daemon.

    Espelha o papel do ``_accept_loop`` TCP: cada conexão aceita vira uma
    ``WSClientConnection`` registrada no ``GameServer``.
    """

    def __init__(
        self,
        server: GameServer,
        host: str,
        port: int,
        *,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        """``ssl_context`` presente → a porta serve **apenas wss** (net/tls.py)."""
        self._server = server
        # Socket próprio (e não o interno do serve) para introspecção da
        # porta efêmera em testes: bind/listen antes de passar ao servidor WS.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen()
        self.port: int = int(listener.getsockname()[1])
        self._ws_server: Server = serve(self._handle, sock=listener, ssl=ssl_context)
        self._thread = threading.Thread(
            target=self._ws_server.serve_forever, name="ws-listener", daemon=True
        )
        self._thread.start()

    def _handle(self, ws: ServerConnection) -> None:
        conn = WSClientConnection(self._server, ws)
        self._server.register_connection(conn)
        conn.run()

    def stop(self, timeout: float = 3.0) -> None:
        """Encerra o accept loop e aguarda os handlers (idempotente).

        Deve ser chamado DEPOIS de fechar as conexões: handlers bloqueados em
        recv só retornam quando a conexão fecha.
        """
        self._ws_server.shutdown()
        self._thread.join(timeout)
