"""Cliente simulado (sem pygame) e base do cliente de UI.

Usado por testes de integração e pela interface Pygame. Nunca bloqueia a
suíte: recv loop com timeout curto e ``wait_for`` com timeout configurável.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import TypeVar, cast

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

__all__ = ["SimulatedClient"]

_M = TypeVar("_M", bound=Message)


class SimulatedClient:
    """Cliente TCP não-bloqueante: recebe frames em thread própria.

    ``wait_for``/``wait_for_any`` consomem mensagens da fila interna e
    lançam ``TimeoutError`` se o prazo expirar — nenhum teste fica preso.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None
        self._decoder = FrameDecoder()
        self._stop = threading.Event()
        self._recv_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._messages: list[Message] = []
        self._join: JoinAccepted | None = None
        self.player_id: int | None = None
        self.host_player_id: int | None = None
        self._role: Role | None = None
        self._snapshot: WorldSnapshot | None = None
        self._tasks: TaskState | None = None
        self._tick = 0

    # ------------------------------------------------------------------ conexão

    def connect(self, host: str, port: int, nickname: str, timeout: float = 5.0) -> None:
        """Conecta e envia JoinRequest; aguarda JoinAccepted."""
        sock = socket.create_connection((host, port), timeout=timeout)
        self._sock = sock
        sock.settimeout(0.2)
        self._recv_thread = threading.Thread(
            target=self._recv_loop, name="client-recv", daemon=True
        )
        self._recv_thread.start()
        self.send_join(nickname)
        self.wait_for(JoinAccepted, timeout=timeout)

    def send_join(self, nickname: str) -> None:
        from ..protocol import JoinRequest

        self.send(JoinRequest(nickname=nickname, protocol_version=PROTOCOL_VERSION))

    def close(self) -> None:
        """Fecha socket e encerra a thread de recv (idempotente)."""
        self._stop.set()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=3.0)

    def __enter__(self) -> SimulatedClient:
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
                messages = self._decoder.feed(data)
            except FrameError:
                break
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
        sock = self._sock
        if sock is None:
            raise ConnectionError("cliente não conectado")
        sock.sendall(encode_frame(message))

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
