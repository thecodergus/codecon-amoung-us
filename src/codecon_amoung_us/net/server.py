"""Servidor autoritativo: socket TCP, thread por conexão, game loop a 20 Hz.

Concorrência: threads de conexão apenas decodificam e enfileiram comandos;
SOMENTE o game loop muta o estado (fila de comandos). Sends são protegidos
por lock por conexão. Shutdown é idempotente e fecha todas as threads.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import logging
import math
import queue
import random
import socket
import threading
import time
from pathlib import Path

from ..config import DISCOVERY_MAGIC, MAX_PLAYERS, PROTOCOL_VERSION, GameConfig
from ..framing import FrameDecoder, FrameError, encode_frame
from ..game._native_collision import FlatWalls, flatten_walls, resolve_movement_steps_flat
from ..game.meeting import Meeting, MeetingOutcome, MeetingReason
from ..game.model import GameState, Phase, PlayerState, Role, Task
from ..game.rules import apply_kill, can_report, check_win, complete_task
from ..game.tasks import assign_tasks
from ..map.generator import generate_map
from ..map.loader import load_map
from ..map.model import GameMap
from ..protocol import (
    ActionAccepted,
    ActionDenied,
    ActionKind,
    BodyReported,
    DenialCode,
    EmergencyMeetingRequest,
    GameOver,
    JoinAccepted,
    JoinRequest,
    KillRequest,
    LobbyPlayer,
    MeetingStarted,
    Message,
    MovementInput,
    PlayerDisconnected,
    PlayerInfo,
    PlayerJoined,
    ProtocolError,
    RoleAssigned,
    SnapshotBody,
    SnapshotPlayer,
    StartGame,
    StartGameRequest,
    TaskActionRequest,
    TaskInfo,
    TaskState,
    VoteRequest,
    WorldSnapshot,
)
from .discovery import DiscoveryBeacon, GameAnnouncement
from .dispatch import dispatch_ejection
from .ws import WSClientConnection, WSListener

__all__ = ["GameServer", "main"]

# fila de comandos -> (conexão, mensagem); None em broadcast de saída
_Command = tuple["Connection", Message]
_OutboxItem = tuple["Connection | None", Message]

# Teto da fila de comandos: backpressure estrutural (A-07). O ``put`` do
# recv thread bloqueia quando cheia e o TCP regula o produtor; o game loop
# drena a fila inteira a cada tick (20Hz), então o bloqueio é ≤ ~1 tick.
# Medição A-06 (2026-08): flood cru de ~133k msg/s em loopback manteve
# 20 ticks/s com profundidade ≤ ~1.8k — 50k é ~25x de folga sobre o ponto
# de equilíbrio observado e ordens de magnitude acima do tráfego legítimo
# (10 jogadores × 20 inputs/s ≈ 200 msg/s).
COMMAND_QUEUE_MAXSIZE = 50_000

_log = logging.getLogger(__name__)


class ClientConnection:
    """Uma conexão TCP: decodifica frames e enfileira comandos no servidor."""

    def __init__(self, server: GameServer, sock: socket.socket) -> None:
        self._server = server
        self._sock = sock
        self._sock.settimeout(server.config.socket_timeout_seconds)
        self._decoder = FrameDecoder()
        self._send_lock = threading.Lock()
        self._stop = threading.Event()
        self.player_id: int | None = None
        self.nickname: str = ""
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="client-conn", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    data = self._sock.recv(4096)
                except TimeoutError:
                    continue
                except OSError:
                    break
                if not data:
                    break
                try:
                    messages = self._decoder.feed(data)
                except FrameError as exc:
                    self.send(ProtocolError(code="bad_frame", message=str(exc)))
                    break
                for message in messages:
                    self._server.enqueue(self, message)
        finally:
            # Fechamento explícito e determinístico do socket em todos os
            # caminhos de saída (FrameError, EOF, OSError) — não depender de GC.
            self.close()
            self._server.on_disconnect(self)

    def send(self, message: Message) -> None:
        """Envia uma mensagem emoldurada (thread-safe)."""
        try:
            frame = encode_frame(message)
        except FrameError:
            return
        with self._send_lock, contextlib.suppress(OSError):
            self._sock.sendall(frame)

    def close(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            self._sock.close()

    def join(self, timeout: float) -> None:
        if self.thread is not None:
            self.thread.join(timeout)


# Uma conexão de cliente, por qualquer transporte (TCP cru ou WebSocket).
# O game loop e o despacho só dependem desta interface pública comum.
Connection = ClientConnection | WSClientConnection


class GameServer:
    """Servidor autoritativo de partidas estilo Among Us."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        config: GameConfig | None = None,
        map_path: str | Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        if map_path is not None:
            base = config if config is not None else GameConfig()
            self.config = dataclasses.replace(base, map_path=Path(map_path))
        else:
            self.config = config if config is not None else GameConfig()
        self._game_map: GameMap = load_map(self.config.resolve_map_path())
        self._map_seed: int | None = None
        if self.config.map_path is None:
            # Mapa procedural: o asset Tiled só é usado quando configurado
            # explicitamente; o padrão é gerar por seed (uma por partida).
            self._map_seed = self._match_map_seed()
            self._game_map = generate_map(self._map_seed)
        # Paredes achatadas uma única vez: o kernel de colisão
        # (game/_native_collision.py, equivalência property-tested com
        # game/physics.py) não toca objetos Rect no hot loop do tick.
        self._flat_walls: FlatWalls = flatten_walls(self._game_map.walls)

        self._state = GameState(game_id="game-1")
        self._state.tasks = self._tasks_from_map(self._game_map)

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._stopped = False
        self._commands: queue.Queue[_Command] = queue.Queue(maxsize=COMMAND_QUEUE_MAXSIZE)
        self._inputs: dict[int, tuple[float, float]] = {}
        self._conns: list[Connection] = []
        self._connections: dict[int, Connection] = {}
        self._host_id: int | None = None
        self._next_player_id = 0
        self._next_meeting_id = 1
        self._spawn_cursor = 0

        self._listener: socket.socket | None = None
        self._listener_thread: threading.Thread | None = None
        self._game_thread: threading.Thread | None = None
        self._beacon: DiscoveryBeacon | None = None
        self._ws_listener: WSListener | None = None

    # ------------------------------------------------------------------ lifecycle

    def _match_map_seed(self) -> int:
        """Seed da partida: fixa da config (testes/demo) ou aleatória."""
        if self.config.map_seed is not None:
            return self.config.map_seed
        return random.SystemRandom().randrange(2**63)

    @staticmethod
    def _tasks_from_map(game_map: GameMap) -> list[Task]:
        return [
            Task(
                task_id=t.task_id,
                task_type=t.task_type,
                x=t.x,
                y=t.y,
                interaction_radius=t.interaction_radius,
            )
            for t in game_map.task_points
        ]

    def _regenerate_match_map(self) -> None:
        """(Re)gera o mapa procedural da partida que vai começar.

        Sem efeito para mapas de asset (``map_path`` configurado) nem quando
        a seed já está em uso (primeira partida, ou seed fixa repetida).
        Reposiciona os jogadores do lobby nos spawns do mapa novo: posições
        de lobby nunca foram transmitidas (snapshot só na fase PLAYING).
        """
        if self._map_seed is None:
            return
        seed = self._match_map_seed()
        if seed != self._map_seed:
            self._map_seed = seed
            self._game_map = generate_map(seed)
            self._flat_walls = flatten_walls(self._game_map.walls)
            self._state.tasks = self._tasks_from_map(self._game_map)
        spawn_points = self._game_map.spawn_points
        for index, player in enumerate(
            sorted(self._state.players.values(), key=lambda p: p.player_id)
        ):
            spawn = spawn_points[index % max(1, len(spawn_points))]
            player.x, player.y = spawn.x, spawn.y

    @property
    def ws_port(self) -> int | None:
        """Porta efetiva do listener WebSocket (None quando desligado)."""
        return self._ws_listener.port if self._ws_listener is not None else None

    def start(self) -> None:
        """Inicia listener e game loop (idempotente)."""
        if self._listener is not None:
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen()
        listener.settimeout(self.config.socket_timeout_seconds)
        self._listener = listener
        self.port = listener.getsockname()[1]

        self._listener_thread = threading.Thread(
            target=self._accept_loop, name="listener", daemon=True
        )
        self._game_thread = threading.Thread(target=self._game_loop, name="game-loop", daemon=True)
        self._listener_thread.start()
        self._game_thread.start()
        if self.config.ws_port is not None:
            self._ws_listener = WSListener(self, self.host, self.config.ws_port)
        if self.config.announce:
            self._beacon = DiscoveryBeacon(self._make_announcement)
            self._beacon.start()

    def _make_announcement(self) -> GameAnnouncement | None:
        """Anúncio da partida para o beacon de descoberta (None fora do lobby)."""
        with self._lock:
            if self._state.phase is not Phase.LOBBY:
                return None
            host = self._state.player(self._host_id) if self._host_id is not None else None
            return GameAnnouncement(
                magic=DISCOVERY_MAGIC,
                protocol_version=PROTOCOL_VERSION,
                host_name=host.nickname if host is not None else "",
                players=len(self._state.players),
                max_players=self.config.max_players,
                tcp_port=self.port,
                ws_port=self.config.ws_port,
            )

    def stop(self) -> None:
        """Encerra servidor e todas as threads (idempotente)."""
        if self._stopped:
            return
        self._stopped = True
        self._stop.set()
        if self._beacon is not None:
            self._beacon.stop()
            self._beacon = None
        if self._listener is not None:
            with contextlib.suppress(OSError):
                self._listener.close()
        with self._lock:
            conns = list(self._conns)
        for conn in conns:
            conn.close()
        # Depois das conexões fechadas: handlers WS bloqueados em recv só
        # retornam quando a conexão fecha (shutdown aguarda os handlers).
        if self._ws_listener is not None:
            self._ws_listener.stop(self.config.shutdown_join_timeout_seconds)
            self._ws_listener = None
        for thread in (self._listener_thread, self._game_thread):
            if thread is not None:
                thread.join(self.config.shutdown_join_timeout_seconds)
        for conn in conns:
            conn.join(self.config.shutdown_join_timeout_seconds)

    def __enter__(self) -> GameServer:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _accept_loop(self) -> None:
        listener = self._listener
        if listener is None:
            return
        while not self._stop.is_set():
            try:
                sock, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            conn = ClientConnection(self, sock)
            self.register_connection(conn)
            conn.start()

    def _game_loop(self) -> None:
        last = time.monotonic()
        tick_duration = 1.0 / self.config.tick_rate
        while not self._stop.is_set():
            now = time.monotonic()
            dt = min(now - last, 0.5)
            last = now
            outbox: list[_OutboxItem] = []
            snapshot: WorldSnapshot | None = None
            try:
                with self._lock:
                    self._drain_commands(outbox)
                    if self._state.phase is Phase.PLAYING:
                        self._advance_physics(dt)
                        self._check_win(outbox)
                    elif self._state.phase is Phase.MEETING and self._state.meeting is not None:
                        self._check_meeting_timeout(now, outbox)
                    if self._state.phase is Phase.PLAYING:
                        snapshot = self._build_snapshot()
            except Exception:
                # Contenção (A-08): um tick defeituoso não derruba o loop nem
                # encerra as conexões; o lock é liberado pelo with e o tick
                # seguinte parte do último estado íntegro.
                _log.exception("erro contido no tick do game loop")
            # Flush fora do try: mensagens produzidas antes da falha (ex.:
            # StartGame no tick de início) são entregues mesmo assim; send
            # suprime OSError por conexão, então o flush não relança.
            self._flush(outbox)
            if snapshot is not None:
                self._broadcast(snapshot)
            sleep_for = last + tick_duration - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)

    # ------------------------------------------------------------------ entrada

    def register_connection(self, conn: Connection) -> None:
        """Registra uma conexão aceita por um listener (TCP ou WebSocket)."""
        with self._lock:
            self._conns.append(conn)

    def enqueue(self, conn: Connection, message: Message) -> None:
        self._commands.put((conn, message))

    def on_disconnect(self, conn: Connection) -> None:
        """Remove a conexão e trata a saída do jogador."""
        with self._lock:
            if conn in self._conns:
                self._conns.remove(conn)
            player_id = conn.player_id
            if player_id is not None:
                self._connections.pop(player_id, None)
        if player_id is None:
            return
        outbox: list[_OutboxItem] = []
        with self._lock:
            player = self._state.player(player_id)
            if player is None:
                return
            if self._state.phase is Phase.LOBBY:
                del self._state.players[player_id]
                outbox.append((None, PlayerDisconnected(player_id=player_id)))
                self._maybe_promote_host(outbox)
            else:
                player.alive = False
                outbox.append((None, PlayerDisconnected(player_id=player_id)))
                if self._state.phase is Phase.MEETING and self._state.meeting is not None:
                    meeting = self._state.meeting
                    if meeting.remove_voter(player_id) and meeting.all_voted:
                        self._finish_meeting(outbox)
        self._flush(outbox)

    # ------------------------------------------------------------------ comandos

    def _drain_commands(self, outbox: list[_OutboxItem]) -> None:
        while True:
            try:
                conn, message = self._commands.get_nowait()
            except queue.Empty:
                return
            self._dispatch(conn, message, outbox)

    def _dispatch(self, conn: Connection, message: Message, outbox: list[_OutboxItem]) -> None:
        # match por tipo: cada branch é tipada estaticamente (sem dict de
        # handlers nem supressão de tipo) e o custo linear é irrisório no
        # volume de comandos por tick.
        match message:
            case JoinRequest():
                self._on_join(conn, message, outbox)
            case StartGameRequest():
                self._on_start_request(conn, message, outbox)
            case MovementInput():
                self._on_movement(conn, message, outbox)
            case KillRequest():
                self._on_kill(conn, message, outbox)
            case BodyReported():
                self._on_report(conn, message, outbox)
            case EmergencyMeetingRequest():
                self._on_emergency(conn, message, outbox)
            case VoteRequest():
                self._on_vote(conn, message, outbox)
            case TaskActionRequest():
                self._on_task(conn, message, outbox)

    def _reject_connection(self, conn: Connection, message: Message) -> None:
        """Envia a rejeição diretamente e fecha a conexão.

        Usado nos erros de protocolo do join: a resposta precisa chegar antes
        do fechamento (via outbox ela se perderia, pois o close imediato
        invalida o socket antes do flush).
        """
        conn.send(message)
        conn.close()

    def _on_join(self, conn: Connection, msg: JoinRequest, outbox: list[_OutboxItem]) -> None:
        if conn.player_id is not None:
            # Cliente conforme nunca envia JoinRequest duas vezes: apenas
            # informa o erro sem fechar, para não expulsar o jogador legítimo
            # da mesma conexão nem criar um fantasma.
            outbox.append((conn, ProtocolError(code="already_joined", message="já conectado")))
            return
        if self._state.phase is not Phase.LOBBY:
            self._reject_connection(
                conn, ProtocolError(code="game_in_progress", message="partida já em andamento")
            )
            return
        if msg.protocol_version != PROTOCOL_VERSION:
            # Inalcançável via wire: a constraint do protocolo (ge=1, le=2) faz
            # o decode aceitar v1 e v2; clientes v1 (que não conhecem o schema
            # v2) são rejeitados aqui com bad_version. Defesa em profundidade
            # testada por chamada direta (A-24).
            self._reject_connection(
                conn,
                ProtocolError(code="bad_version", message="versão de protocolo incompatível"),
            )
            return
        if len(self._state.players) >= self.config.max_players:
            self._reject_connection(conn, ProtocolError(code="lobby_full", message="lobby cheio"))
            return
        player_id = self._next_player_id
        self._next_player_id += 1
        spawn = self._game_map.spawn_points[
            self._spawn_cursor % max(1, len(self._game_map.spawn_points))
        ]
        self._spawn_cursor += 1
        player = PlayerState(player_id=player_id, nickname=msg.nickname, x=spawn.x, y=spawn.y)
        self._state.players[player_id] = player
        conn.player_id = player_id
        conn.nickname = msg.nickname
        self._connections[player_id] = conn
        if self._host_id is None:
            self._host_id = player_id

        outbox.append((conn, self._lobby_accepted(player_id)))
        others = [c for c in self._conns if c.player_id != player_id]
        for other in others:
            outbox.append(
                (
                    other,
                    PlayerJoined(player=LobbyPlayer(player_id=player_id, nickname=msg.nickname)),
                )
            )

    def _on_start_request(
        self, conn: Connection, _msg: StartGameRequest, outbox: list[_OutboxItem]
    ) -> None:
        if self._state.phase is not Phase.LOBBY:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.START_GAME,
                        code=DenialCode.INVALID_PHASE,
                        reason="partida já iniciada",
                    ),
                )
            )
            return
        if conn.player_id != self._host_id:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.START_GAME,
                        code=DenialCode.NOT_HOST,
                        reason="somente o host pode iniciar",
                    ),
                )
            )
            return
        if len(self._state.players) < self.config.min_players_to_start:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.START_GAME,
                        code=DenialCode.INSUFFICIENT_PLAYERS,
                        reason="jogadores insuficientes",
                    ),
                )
            )
            return
        self._start_game(outbox)

    def _start_game(self, outbox: list[_OutboxItem]) -> None:
        # Mapa da partida: (re)gera pela seed e reposiciona os jogadores nos
        # spawns ANTES de qualquer mensagem (StartGame carrega a seed para os
        # clientes reconstruírem a mesma geometria).
        self._regenerate_match_map()
        players = sorted(self._state.players.values(), key=lambda p: p.player_id)
        impostor_count = min(self.config.impostor_count, len(players) - 1)
        shuffled = list(players)
        random.shuffle(shuffled)
        for player in players:
            player.role = Role.IMPOSTOR if player in shuffled[:impostor_count] else Role.CREW
        self._state.task_assignments = assign_tasks(self._state)
        self._state.done_tasks = {p.player_id: set() for p in players}

        self._state.phase = Phase.PLAYING
        outbox.append(
            (
                None,
                StartGame(
                    map_name=self._game_map.name,
                    map_seed=self._map_seed if self._map_seed is not None else 0,
                    players=[
                        PlayerInfo(player_id=p.player_id, nickname=p.nickname) for p in players
                    ],
                ),
            )
        )
        for player in players:
            role = player.role
            assert role is not None  # papéis atribuídos acima
            conn = self._connections[player.player_id]
            outbox.append(
                (
                    conn,
                    RoleAssigned(
                        role=role,
                        task_ids=self._state.task_assignments.get(player.player_id, []),
                    ),
                )
            )
            tasks = [
                TaskInfo(task_id=t.task_id, task_type=t.task_type, done=False)
                for t in self._state.tasks
                if t.task_id in self._state.task_assignments.get(player.player_id, [])
            ]
            outbox.append((conn, TaskState(tasks=tasks)))

    def _on_movement(
        self, conn: Connection, msg: MovementInput, _outbox: list[_OutboxItem]
    ) -> None:
        if self._state.phase is not Phase.PLAYING:
            return
        if conn.player_id is None:
            return
        self._inputs[conn.player_id] = (msg.dx, msg.dy)

    def _kill_denial(
        self,
        attacker_id: int,
        target_id: int,
        now: float,
    ) -> tuple[DenialCode, str, float | None] | None:
        """Classifica a recusa de um kill (None = kill válido).

        Retorna (code, reason, retry_after_seconds) seguindo a mesma ordem de
        validação de ``can_kill``; o motivo textual preserva a substring
        "kill" para compatibilidade com os testes existentes.
        """
        attacker = self._state.player(attacker_id)
        target = self._state.player(target_id)
        if attacker is None or target is None:
            return DenialCode.INVALID_TARGET, "kill inválido: alvo inexistente", None
        if not attacker.alive or not target.alive:
            return DenialCode.NOT_ALIVE, "kill inválido: jogador morto", None
        if attacker.role is not Role.IMPOSTOR or attacker_id == target_id:
            return DenialCode.INVALID_TARGET, "kill inválido", None
        if math.hypot(attacker.x - target.x, attacker.y - target.y) > self.config.kill_radius:
            return DenialCode.OUT_OF_RANGE, "kill fora de alcance", None
        last_kill = self._state.last_kill_at.get(attacker_id, -math.inf)
        remaining = self.config.kill_cooldown_seconds - (now - last_kill)
        if remaining > 0:
            return DenialCode.COOLDOWN, "kill em recarga", max(0.0, remaining)
        return None

    def _on_kill(self, conn: Connection, msg: KillRequest, outbox: list[_OutboxItem]) -> None:
        if self._state.phase is not Phase.PLAYING or conn.player_id is None:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.KILL,
                        code=DenialCode.INVALID_PHASE,
                        reason="ação inválida nesta fase",
                    ),
                )
            )
            return
        now = time.monotonic()
        denial = self._kill_denial(conn.player_id, msg.target_id, now)
        if denial is not None:
            code, reason, retry_after = denial
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.KILL,
                        code=code,
                        reason=reason,
                        retry_after_seconds=retry_after,
                    ),
                )
            )
            return
        apply_kill(self._state, conn.player_id, msg.target_id, now)
        # Confirmação privada ao assassino: inicia o contador local de cooldown.
        outbox.append(
            (
                conn,
                ActionAccepted(
                    action=ActionKind.KILL,
                    cooldown_seconds=self.config.kill_cooldown_seconds,
                ),
            )
        )
        self._check_win(outbox)

    def _on_report(self, conn: Connection, msg: BodyReported, outbox: list[_OutboxItem]) -> None:
        if self._state.phase is not Phase.PLAYING or conn.player_id is None:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.REPORT,
                        code=DenialCode.INVALID_PHASE,
                        reason="ação inválida nesta fase",
                    ),
                )
            )
            return
        body = self._state.body_by_id(msg.body_id)
        if body is None or body.reported:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.REPORT,
                        code=DenialCode.INVALID_TARGET,
                        reason="corpo não encontrado",
                    ),
                )
            )
            return
        reporter = self._state.player(conn.player_id)
        if reporter is None or not reporter.alive:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.REPORT,
                        code=DenialCode.NOT_ALIVE,
                        reason="jogador morto não pode reportar",
                    ),
                )
            )
            return
        if not can_report(self._state, conn.player_id, msg.body_id, self.config.report_radius):
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.REPORT,
                        code=DenialCode.OUT_OF_RANGE,
                        reason="corpo fora de alcance",
                    ),
                )
            )
            return
        self._state.bodies.remove(body)
        self._start_meeting(MeetingReason.KILL_REPORTED, outbox)

    def _on_emergency(
        self, conn: Connection, _msg: EmergencyMeetingRequest, outbox: list[_OutboxItem]
    ) -> None:
        if self._state.phase is not Phase.PLAYING or conn.player_id is None:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.EMERGENCY,
                        code=DenialCode.INVALID_PHASE,
                        reason="ação inválida nesta fase",
                    ),
                )
            )
            return
        player = self._state.player(conn.player_id)
        emergency = self._game_map.emergency_meeting
        if player is None or not player.alive or emergency is None:
            code = (
                DenialCode.NOT_ALIVE
                if player is not None and not player.alive
                else DenialCode.INVALID_TARGET
            )
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.EMERGENCY,
                        code=code,
                        reason="botão de reunião indisponível",
                    ),
                )
            )
            return
        if (
            math.hypot(player.x - emergency[0], player.y - emergency[1])
            > self._game_map.emergency_meeting_radius
        ):
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.EMERGENCY,
                        code=DenialCode.OUT_OF_RANGE,
                        reason="fora do alcance do botão",
                    ),
                )
            )
            return
        self._start_meeting(MeetingReason.EMERGENCY, outbox)

    def _on_vote(self, conn: Connection, msg: VoteRequest, outbox: list[_OutboxItem]) -> None:
        if self._state.phase is not Phase.MEETING or conn.player_id is None:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.VOTE,
                        code=DenialCode.INVALID_PHASE,
                        reason="não há reunião em andamento",
                    ),
                )
            )
            return
        meeting = self._state.meeting
        if meeting is None or meeting.meeting_id != msg.meeting_id:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.VOTE,
                        code=DenialCode.INVALID_TARGET,
                        reason="reunião inválida",
                    ),
                )
            )
            return
        if msg.target_id is not None and msg.target_id not in self._state.players:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.VOTE,
                        code=DenialCode.INVALID_TARGET,
                        reason="alvo inexistente",
                    ),
                )
            )
            return
        if msg.target_id is not None and not self._state.players[msg.target_id].alive:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.VOTE,
                        code=DenialCode.NOT_ALIVE,
                        reason="alvo morto",
                    ),
                )
            )
            return
        if not meeting.add_vote(conn.player_id, msg.target_id):
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.VOTE,
                        code=DenialCode.ALREADY_VOTED,
                        reason="voto não aceito",
                    ),
                )
            )
            return
        # Confirmação privada ao votante: a UI só mostra "VOTO REGISTRADO" aqui.
        outbox.append((conn, ActionAccepted(action=ActionKind.VOTE)))
        if meeting.all_voted:
            self._finish_meeting(outbox)

    def _on_task(self, conn: Connection, msg: TaskActionRequest, outbox: list[_OutboxItem]) -> None:
        if self._state.phase is not Phase.PLAYING or conn.player_id is None:
            outbox.append(
                (
                    conn,
                    ActionDenied(
                        action=ActionKind.TASK,
                        code=DenialCode.INVALID_PHASE,
                        reason="ação inválida nesta fase",
                    ),
                )
            )
            return
        player = self._state.player(conn.player_id)
        if player is None:
            return
        if not complete_task(self._state, conn.player_id, msg.task_id, player.x, player.y):
            # Nenhuma recusa silenciosa: o jogador descobre por que a tarefa
            # não foi concluída (não atribuída, já feita, fora do raio, morto).
            task = self._state.task_by_id(msg.task_id)
            if task is None:
                code, reason = DenialCode.INVALID_TARGET, "tarefa inexistente"
            elif not player.alive:
                code, reason = DenialCode.NOT_ALIVE, "jogador morto não realiza tarefas"
            elif msg.task_id not in self._state.task_assignments.get(conn.player_id, []):
                code, reason = DenialCode.NOT_ASSIGNED, "tarefa não atribuída"
            elif msg.task_id in self._state.done_tasks.get(conn.player_id, set()):
                code, reason = DenialCode.ALREADY_DONE, "tarefa já concluída"
            else:
                code, reason = DenialCode.OUT_OF_RANGE, "fora do alcance da tarefa"
            outbox.append(
                (
                    conn,
                    ActionDenied(action=ActionKind.TASK, code=code, reason=reason),
                )
            )
            return
        self._check_win(outbox)
        for pid, other in self._connections.items():
            tasks = self._state.task_assignments.get(pid, [])
            done = self._state.done_tasks.get(pid, set())
            outbox.append(
                (
                    other,
                    TaskState(
                        tasks=[
                            TaskInfo(
                                task_id=t.task_id, task_type=t.task_type, done=t.task_id in done
                            )
                            for t in self._state.tasks
                            if t.task_id in tasks
                        ]
                    ),
                )
            )

    # ------------------------------------------------------------------ reunião

    def _start_meeting(self, reason: MeetingReason, outbox: list[_OutboxItem]) -> None:
        voters = [p.player_id for p in self._state.players.values() if p.alive]
        meeting = Meeting(
            meeting_id=self._next_meeting_id,
            reason=reason,
            started_at=time.monotonic(),
            vote_timeout_seconds=self.config.meeting_vote_timeout_seconds,
            voters=set(voters),
        )
        self._next_meeting_id += 1
        self._state.meeting = meeting
        self._state.phase = Phase.MEETING
        outbox.append(
            (
                None,
                MeetingStarted(
                    meeting_id=meeting.meeting_id,
                    reason=reason,
                    voters=voters,
                    vote_timeout_seconds=meeting.vote_timeout_seconds,
                ),
            )
        )

    def _check_meeting_timeout(self, now: float, outbox: list[_OutboxItem]) -> None:
        meeting = self._state.meeting
        if meeting is not None and meeting.timeout_expired(now):
            self._finish_meeting(outbox)

    def _finish_meeting(self, outbox: list[_OutboxItem]) -> None:
        meeting = self._state.meeting
        if meeting is None:
            return
        result = meeting.result()
        ejected_role = None
        if result.ejected_id is not None:
            ejected_player = self._state.player(result.ejected_id)
            if ejected_player is not None:
                ejected_role = ejected_player.role
        outcome: MeetingOutcome = meeting.outcome(ejected_role)
        self._state.meeting = None
        self._state.phase = Phase.PLAYING

        if outcome.ejected_id is not None:
            ejected_player = self._state.player(outcome.ejected_id)
            if ejected_player is not None:
                ejected_player.alive = False
        recipient_ids = [p.player_id for p in self._state.players.values()]
        for recipient_id, messages in dispatch_ejection(outcome, recipient_ids).items():
            conn = self._connections.get(recipient_id)
            if conn is None:
                continue
            for message in messages:
                outbox.append((conn, message))
        self._check_win(outbox)

    # ------------------------------------------------------------------ vitória / snapshot

    def _check_win(self, outbox: list[_OutboxItem]) -> None:
        winner = check_win(self._state)
        if winner is None:
            return
        self._state.phase = Phase.ENDED
        players = sorted(self._state.players.values(), key=lambda p: p.player_id)
        outbox.append(
            (
                None,
                GameOver(
                    winner=winner,
                    players=[
                        PlayerInfo(player_id=p.player_id, nickname=p.nickname) for p in players
                    ],
                    roles={p.player_id: p.role for p in players if p.role is not None},
                ),
            )
        )

    def _build_snapshot(self) -> WorldSnapshot:
        self._state.tick += 1
        players = [
            SnapshotPlayer(player_id=p.player_id, x=p.x, y=p.y, alive=p.alive)
            for p in sorted(self._state.players.values(), key=lambda p: p.player_id)
        ]
        bodies = [
            SnapshotBody(body_id=b.body_id, player_id=b.player_id, x=b.x, y=b.y)
            for b in self._state.bodies
        ]
        return WorldSnapshot(tick=self._state.tick, players=players, bodies=bodies)

    def _advance_physics(self, dt: float) -> None:
        inputs = self._inputs
        self._inputs = {}
        for pid, (dx, dy) in inputs.items():
            player = self._state.player(pid)
            if player is None or not player.alive:
                continue
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            step = self.config.player_speed * dt
            ux, uy = dx / length, dy / length
            nx, ny = resolve_movement_steps_flat(
                player.x,
                player.y,
                ux * step,
                uy * step,
                self._flat_walls,
                max_step=self.config.max_movement_step,
            )
            left, top, right, bottom = self._game_map.bounds()
            player.x = min(max(nx, left), right)
            player.y = min(max(ny, top), bottom)

    # ------------------------------------------------------------------ saída

    def _lobby_accepted(self, player_id: int) -> JoinAccepted:
        players = sorted(self._state.players.values(), key=lambda p: p.player_id)
        return JoinAccepted(
            game_id=self._state.game_id,
            player_id=player_id,
            host_player_id=self._host_id if self._host_id is not None else player_id,
            players=[LobbyPlayer(player_id=p.player_id, nickname=p.nickname) for p in players],
        )

    def _maybe_promote_host(self, outbox: list[_OutboxItem]) -> None:
        if self._host_id is not None and self._host_id in self._state.players:
            return
        remaining = sorted(p.player_id for p in self._state.players.values())
        self._host_id = remaining[0] if remaining else None
        if self._host_id is not None:
            for conn in self._conns:
                if conn.player_id is not None:
                    outbox.append((conn, self._lobby_accepted(conn.player_id)))

    def _broadcast(self, message: Message) -> None:
        with self._lock:
            conns = list(self._conns)
        for conn in conns:
            conn.send(message)

    def _flush(self, outbox: list[_OutboxItem]) -> None:
        for conn, message in outbox:
            if conn is None:
                self._broadcast(message)
            else:
                conn.send(message)


# ---------------------------------------------------------------------------
# CLI (servidor standalone)
# ---------------------------------------------------------------------------


def _server_config(args: argparse.Namespace) -> GameConfig:
    """Valida argumentos da CLI e monta a ``GameConfig`` (pura e testável).

    Levanta ``ValueError`` para configurações inválidas; a ``main`` converte
    em ``parser.error`` (mensagem clara e exit code 2).
    """
    if not 1 <= args.port <= 65535:
        raise ValueError(f"porta fora do intervalo [1, 65535]: {args.port}")
    if args.ws_port is not None:
        if not 1 <= args.ws_port <= 65535:
            raise ValueError(f"ws-port fora do intervalo [1, 65535]: {args.ws_port}")
        if args.ws_port == args.port:
            raise ValueError("ws-port deve ser diferente da porta TCP")
    if args.tick_rate is not None and args.tick_rate < 1:
        raise ValueError(f"tick-rate deve ser >= 1: {args.tick_rate}")
    if args.max_players is not None and not 1 <= args.max_players <= MAX_PLAYERS:
        raise ValueError(f"max-players deve estar em [1, {MAX_PLAYERS}]: {args.max_players}")
    if args.seed is not None and not 0 <= args.seed < 2**63:
        raise ValueError(f"seed fora do intervalo [0, 2**63): {args.seed}")
    config = GameConfig()
    if args.ws_port is not None:
        config = dataclasses.replace(config, ws_port=args.ws_port)
    if args.max_players is not None:
        config = dataclasses.replace(config, max_players=args.max_players)
    if args.tick_rate is not None:
        config = dataclasses.replace(config, tick_rate=args.tick_rate)
    if args.seed is not None:
        config = dataclasses.replace(config, map_seed=args.seed)
    return config


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="codecon-amoung-us-server")
    parser.add_argument("--host", default="127.0.0.1", help="endereço de escuta")
    parser.add_argument("--port", type=int, default=5555, help="porta de escuta TCP")
    parser.add_argument(
        "--ws-port",
        type=int,
        default=None,
        help="porta WebSocket (transporte preferencial; ex.: 80 atravessa firewalls)",
    )
    parser.add_argument("--map", default=None, help="caminho do mapa Tiled (default: lab)")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="seed fixa do gerador procedural (default: aleatória por partida)",
    )
    parser.add_argument("--max-players", type=int, default=None, help="limite de jogadores")
    parser.add_argument("--tick-rate", type=int, default=None, help="ticks por segundo")
    args = parser.parse_args(argv)

    try:
        config = _server_config(args)
    except ValueError as exc:
        parser.error(str(exc))
    server = GameServer(host=args.host, port=args.port, config=config, map_path=args.map)
    server.start()
    try:
        print(f"servidor ouvindo em {args.host}:{server.port} (mapa: {server._game_map.name})")
        if server._ws_listener is not None:
            print(f"websocket ouvindo em {args.host}:{server._ws_listener.port}")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nencerrando servidor...")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
