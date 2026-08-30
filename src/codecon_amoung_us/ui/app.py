"""Aplicação Pygame: menus (pygame-menu), lobby, jogo e votação.

Ponto de entrada ``main()``. Hosting embute o servidor em uma thread no
mesmo processo (``GameServer``); o cliente de rede é o ``GameClient``.
"""

from __future__ import annotations

import math
import os
import queue
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, cast

import pygame
import pygame_menu

from ..config import default_assets_dir, default_map_path
from ..game.model import Role
from ..map.loader import load_map
from ..map.model import GameMap
from ..net.client import GameClient
from ..net.server import GameServer
from ..protocol import (
    ActionAccepted,
    ActionDenied,
    ActionKind,
    DenialCode,
    Ejected,
    GameOver,
    JoinAccepted,
    LobbyPlayer,
    MeetingEnded,
    MeetingStarted,
    Message,
    PlayerDisconnected,
    PlayerJoined,
    ProtocolError,
    RoleAssigned,
    SnapshotPlayer,
    StartGame,
    TaskState,
    WorldSnapshot,
)
from .camera import Camera2D
from .components import Button, ButtonState, FocusManager, PlayerCard, PlayerCardState
from .fonts import FontBook
from .layout import fit_viewport
from .puzzles import TASK_DISPLAY, Minigame, create_minigame
from .puzzles.base import CONTENT_H, CONTENT_W
from .render import (
    COLOR_ACCENT,
    COLOR_BG,
    COLOR_CREW,
    COLOR_IMPOSTOR,
    COLOR_PANEL,
    COLOR_PANEL_BORDER,
    COLOR_TASK,
    COLOR_TEXT,
    COLOR_TEXT_DIM,
    WORLD_HEIGHT,
    Renderer,
)
from .sprites import PlayerAnim, color_for
from .theme import TOKENS, settings_from_env
from .viewmodel import (
    VOTING_CARDS_PER_PAGE,
    VoteUiState,
    VotingLayout,
    derive_game_hud,
    derive_interaction_context,
    derive_report_target,
    derive_task_markers,
    gameover_layout,
    voting_layout,
)

__all__ = ["App", "Screen", "main"]


class Screen(StrEnum):
    """Telas da aplicação (máquina de estados da UI).

    ``StrEnum`` mantém compatibilidade com comparações contra strings em
    testes e no script de captura; atribuições usam sempre os membros.
    """

    MAIN = "main"
    HOST = "host"
    JOIN = "join"
    LOBBY = "lobby"
    CONNECTING = "connecting"
    GAME = "game"
    VOTING = "voting"
    EJECTED = "ejected"
    MEETING_ENDED = "meeting_ended"
    GAME_OVER = "gameover"
    ERROR = "error"
    SETTINGS = "settings"


# Nome público do produto (fonte única para a UI e a janela).
DISPLAY_NAME = "Codecon Lab • Among Ducks"

# Resolução lógica (mundo 1280x704 + HUD ~64 px). A janela física pode ter
# qualquer tamanho; o viewport preserva o aspect com letterbox.
WINDOW_W, WINDOW_H = 1280, 768

# Texto de feedback por código de recusa (fallback: reason do servidor).
_DENIAL_TEXT: dict[DenialCode, str] = {
    DenialCode.OUT_OF_RANGE: "Fora de alcance",
    DenialCode.COOLDOWN: "Eliminação ainda em recarga",
    DenialCode.INVALID_TARGET: "Alvo inválido",
    DenialCode.ALREADY_DONE: "Esta tarefa já foi concluída",
    DenialCode.NOT_ASSIGNED: "Tarefa não atribuída",
    DenialCode.ALREADY_VOTED: "Voto já registrado",
    DenialCode.INVALID_PHASE: "Você não pode usar essa ação agora",
    DenialCode.NOT_HOST: "Somente o host pode iniciar",
    DenialCode.INSUFFICIENT_PLAYERS: "Jogadores insuficientes",
    DenialCode.NOT_ALIVE: "Ação indisponível",
}


def _denial_text(code: DenialCode, reason: str) -> str:
    """Texto de apresentação para um ``ActionDenied`` (por código)."""
    return _DENIAL_TEXT.get(code, reason)


@dataclass
class _Toast:
    """Notificação não modal com expiração por relógio."""

    text: str
    created_at: float


class ConnectionState(StrEnum):
    """Estado da conexão (host/join) — nunca bloqueia a renderização."""

    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass(frozen=True)
class ConnectionSuccess:
    """Resultado do worker de conexão: cliente + servidor embutido (se host)."""

    client: GameClient
    server: GameServer | None


@dataclass(frozen=True)
class ConnectionFailure:
    """Falha de conexão do worker (mensagem para a tela de erro)."""

    message: str


def _movement_direction(keys: Sequence[bool]) -> tuple[float, float] | None:
    """Direção normalizada de movimento a partir do estado do teclado (WASD).

    Retorna ``None`` quando nenhuma tecla de movimento está pressionada.
    """
    dx = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
    dy = (1 if keys[pygame.K_s] else 0) - (1 if keys[pygame.K_w] else 0)
    if dx == 0 and dy == 0:
        return None
    length = math.hypot(dx, dy)
    return dx / length, dy / length


def _menu_theme() -> pygame_menu.Theme:
    """Tema dos menus: cena do lab escurecida + acento laranja.

    O pygame-menu 4.5.2 só aceita BaseImage a partir de arquivo: a cena é
    escurecida em uma superfície, salva em um arquivo temporário e carregada
    como fundo (a superfície permanece em memória). Substitui o starfield
    procedural para manter a identidade do laboratório/Duckee.
    """
    scene_path = default_assets_dir() / "maps" / "lab_menu.png"
    if not scene_path.is_file():
        scene_path = default_assets_dir() / "maps" / "lab_scene.png"
    if scene_path.is_file():
        background = pygame.image.load(str(scene_path)).convert()
    else:
        background = pygame.Surface((WINDOW_W, WINDOW_H))
        background.fill((12, 14, 24))
    background = (
        pygame.transform.smoothscale(background, (WINDOW_W, WINDOW_H))
        if background.get_size() != (WINDOW_W, WINDOW_H)
        else background
    )
    shade = pygame.Surface(background.get_size(), pygame.SRCALPHA)
    shade.fill((8, 10, 18, 170))
    background.blit(shade, (0, 0))
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pygame.image.save(background, path)
        mode = getattr(pygame_menu.baseimage.BaseImage, "IMAGE_MODE_REPEAT_XY", 103)
        image = pygame_menu.baseimage.BaseImage(path, drawing_mode=mode)
    finally:
        os.remove(path)
    return pygame_menu.themes.Theme(
        background_color=image,
        title_background_color=(30, 34, 54),
        title_font_color=COLOR_ACCENT,
        title_font_size=42,
        widget_font=pygame_menu.font.FONT_OPEN_SANS,
        widget_font_color=COLOR_TEXT,
        widget_font_size=28,
        selection_color=COLOR_ACCENT,
    )


class App:
    """Aplicação principal (cliente com ou sem host embutido)."""

    def __init__(self) -> None:
        pygame.init()
        pygame.display.set_caption(DISPLAY_NAME)
        # canvas lógico + janela física redimensionável (letterbox no present)
        self.display = pygame.display.set_mode((WINDOW_W, WINDOW_H), pygame.RESIZABLE)
        self.screen = pygame.Surface((WINDOW_W, WINDOW_H))
        self.viewport = fit_viewport((WINDOW_W, WINDOW_H), self.display.get_size())
        self.clock = pygame.time.Clock()
        self.fonts = FontBook()
        self.font = self.fonts.control
        self.font_big = self.fonts.heading

        self.client: GameClient | None = None
        self.server: GameServer | None = None
        self.game_map: GameMap = load_map(default_map_path())
        self.ui_settings = settings_from_env()
        self.renderer = Renderer(self.game_map, reduced_motion=self.ui_settings.reduced_motion)
        # câmera do gameplay (cliente-only): segue o jogador local com
        # suavização por dt; snap na primeira aparição (sem travelling)
        self.camera = Camera2D(
            viewport_size=(WINDOW_W, WORLD_HEIGHT), bounds=self.game_map.bounds()
        )
        self._camera_needs_snap = True
        self._dt = 1.0 / 60.0

        # estado de UI
        self.screen_name: Screen = Screen.MAIN
        self.error_message = ""
        self.is_host = False
        self.my_id: int | None = None
        self.host_id: int | None = None
        self.role: Role | None = None
        self.my_task_ids: list[int] = []
        self.tasks_state: TaskState | None = None
        self.lobby_players: list[LobbyPlayer] = []
        self.meeting: MeetingStarted | None = None
        self._meeting_started_at = 0.0
        self.vote_ui_state = VoteUiState.SELECTING
        self.selected_vote_target: int | None = None
        self._voting_page = 0
        self._voting_cursor = 0
        self.game_over: GameOver | None = None
        # minigame modal da tarefa em andamento (None = mundo livre)
        self._puzzle: Minigame | None = None
        self.last_snapshot: WorldSnapshot | None = None
        self._nicknames: dict[int, str] = {}
        self._snapshot_lock = threading.Lock()
        self._messages: list[Message] = []
        self._messages_lock = threading.Lock()
        self.running = True
        # feedback não modal + cooldown local do impostor
        self.toasts: list[_Toast] = []
        self._toast_lifetime = 2.5
        self.kill_cooldown_until: float | None = None
        # apresentação da ejeção privada e transições dirigidas por relógio
        self.private_ejection: Ejected | None = None
        self.pending_game_over: GameOver | None = None
        self._ejection_started_at = 0.0
        self._meeting_ended_at = 0.0
        self._ejected_min_duration = 2.5
        self._meeting_ended_min_duration = 1.2
        # conexão assíncrona (worker thread + fila para a thread gráfica)
        self.connection_state = ConnectionState.IDLE
        self._connection_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
        self._connection_thread: threading.Thread | None = None
        self._connection_cancel: threading.Event | None = None

        self._theme = _menu_theme()
        self.menu_main = self._build_main_menu()
        self.menu_host = self._build_host_menu()
        self.menu_join = self._build_join_menu()
        self.menu_settings = self._build_settings_menu()
        self.lobby_menu = self._build_lobby_menu()
        self._current_menu: pygame_menu.Menu | None = None
        # controles persistentes por tela: hover/pressed e foco sobrevivem
        # entre frames (botões não são reconstruídos a cada render)
        self._lobby_ui_state: tuple[list[Button], FocusManager] | None = None
        self._voting_buttons: list[Button] | None = None
        self._single_ui_states: dict[str, tuple[list[Button], FocusManager]] = {}

    def _push_toast(self, text: str) -> None:
        """Adiciona um toast não modal (máximo 3 visíveis)."""
        self.toasts.append(_Toast(text=text, created_at=time.monotonic()))
        if len(self.toasts) > 3:
            self.toasts.pop(0)

    def _prune_toasts(self, now: float) -> None:
        self.toasts = [t for t in self.toasts if now - t.created_at < self._toast_lifetime]

    def _draw_toasts(self, surface: pygame.Surface) -> None:
        """Desenha os toasts no canto superior direito (sobre a cena)."""
        self._prune_toasts(time.monotonic())
        y = 24
        for toast in self.toasts:
            text = self.font.render(toast.text, True, COLOR_TEXT)
            panel = pygame.Rect(0, 0, text.get_width() + 36, 38)
            panel.topright = (surface.get_width() - 20, y)
            pygame.draw.rect(surface, (24, 28, 44), panel, border_radius=10)
            pygame.draw.rect(surface, COLOR_PANEL_BORDER, panel, width=2, border_radius=10)
            surface.blit(text, text.get_rect(center=panel.center))
            y += 46

    # ------------------------------------------------------------------ menus

    def _build_main_menu(self) -> pygame_menu.Menu:
        menu = pygame_menu.Menu(DISPLAY_NAME, WINDOW_W, WINDOW_H, theme=self._theme)
        menu.add.label("LAB • AMONG DUCKS", font_size=18, font_color=COLOR_TEXT_DIM)
        menu.add.button("Criar partida", self._open_host)
        menu.add.button("Entrar em partida", self._open_join)
        menu.add.button("Configurações", self._open_settings)
        menu.add.button("Sair", pygame_menu.events.EXIT)
        return menu

    def _build_host_menu(self) -> pygame_menu.Menu:
        menu = pygame_menu.Menu("Criar partida", WINDOW_W, WINDOW_H, theme=self._theme)
        self.nickname_input = menu.add.text_input("Apelido: ", default="host", maxchar=12)
        self.port_input = menu.add.text_input("Porta: ", default="5555", maxchar=5)
        menu.add.button("Iniciar servidor", self._create_game)
        menu.add.button("Voltar", self._back_to_main)
        return menu

    def _build_join_menu(self) -> pygame_menu.Menu:
        menu = pygame_menu.Menu("Entrar em partida", WINDOW_W, WINDOW_H, theme=self._theme)
        self.join_nickname = menu.add.text_input("Apelido: ", default="player", maxchar=12)
        self.join_ip = menu.add.text_input("Servidor: ", default="127.0.0.1", maxchar=64)
        self.join_port = menu.add.text_input("Porta: ", default="5555", maxchar=5)
        menu.add.button("Entrar", self._join_game)
        menu.add.button("Voltar", self._back_to_main)
        return menu

    def _build_settings_menu(self) -> pygame_menu.Menu:
        menu = pygame_menu.Menu("Configurações", WINDOW_W, WINDOW_H, theme=self._theme)
        menu.add.selector(
            "Reduzir movimento: ",
            [("NÃO", False), ("SIM", True)],
            default=1 if self.ui_settings.reduced_motion else 0,
            onchange=self._on_reduced_motion_change,
        )
        menu.add.button("Voltar", self._back_to_main)
        return menu

    def _on_reduced_motion_change(self, _value: tuple[str, bool], enabled: bool) -> None:
        """Aplica a preferência imediatamente (sem reiniciar a aplicação)."""
        self.ui_settings = replace(self.ui_settings, reduced_motion=enabled)
        self.renderer.reduced_motion = enabled

    def _build_lobby_menu(self) -> pygame_menu.Menu:
        menu = pygame_menu.Menu("Lobby", WINDOW_W, WINDOW_H, theme=self._theme)
        # cast localizado e documentado: os stubs do pygame-menu não tipam o
        # retorno de add.label (sem stubs/declaração); mantido enquanto o
        # pacote não fornece tipos (diretriz: sem Any generalizado).
        self.lobby_list_label = cast(Any, menu.add.label(""))
        self.lobby_warning_label = cast(Any, menu.add.label(""))
        menu.add.button("Iniciar (host)", self._start_game)
        menu.add.button("Sair", self._leave_lobby)
        return menu

    # ------------------------------------------------------------------ navegação

    def _open_host(self) -> None:
        self.screen_name = Screen.HOST
        self._current_menu = self.menu_host

    def _open_join(self) -> None:
        self.screen_name = Screen.JOIN
        self._current_menu = self.menu_join

    def _open_settings(self) -> None:
        self.screen_name = Screen.SETTINGS
        self._current_menu = self.menu_settings

    def _back_to_main(self) -> None:
        self.screen_name = Screen.MAIN
        self._current_menu = self.menu_main

    def _show_error(self, message: str) -> None:
        self.error_message = message
        self._single_ui_states.pop("error", None)
        self.screen_name = Screen.ERROR

    # ------------------------------------------------------------------ conexão

    def _create_game(self) -> None:
        nickname = str(self.nickname_input.get_value()).strip() or "host"
        try:
            port = int(str(self.port_input.get_value()) or "5555")
        except ValueError:
            self._show_error("Porta inválida")
            return
        self._start_connect_worker(nickname=nickname, port=port, host=True)

    def _join_game(self) -> None:
        nickname = str(self.join_nickname.get_value()).strip() or "player"
        ip = str(self.join_ip.get_value()).strip() or "127.0.0.1"
        try:
            port = int(str(self.join_port.get_value()) or "5555")
        except ValueError:
            self._show_error("Porta inválida")
            return
        self._start_connect_worker(nickname=nickname, port=port, host=False, ip=ip)

    def _start_connect_worker(
        self, *, nickname: str, port: int, host: bool, ip: str = "127.0.0.1"
    ) -> None:
        """Inicia a conexão em thread; a UI continua renderizando."""
        self.connection_state = ConnectionState.CONNECTING
        self.screen_name = Screen.CONNECTING
        self._current_menu = None
        self._single_ui_states.pop("connecting", None)
        # Fila e evento por tentativa: resultados de tentativas canceladas caem
        # numa fila órfã (nunca lidos) e o worker faz o próprio teardown.
        self._connection_queue = queue.SimpleQueue()
        self._connection_cancel = threading.Event()
        self._connection_thread = threading.Thread(
            target=self._connect_worker,
            args=(nickname, ip, port, host, self._connection_queue, self._connection_cancel),
            name="connect-worker",
            daemon=True,
        )
        self._connection_thread.start()

    def _connect_worker(
        self,
        nickname: str,
        ip: str,
        port: int,
        host: bool,
        attempt_queue: queue.SimpleQueue[object],
        cancel: threading.Event,
    ) -> None:
        """Worker: sobe servidor (se host), conecta e publica o resultado.

        Cancelamento cooperativo (``threading.Event``, docs.python.org): o
        evento não interrompe o ``connect`` bloqueante, mas é verificado após
        cada etapa; em sucesso tardio o próprio worker desfaz cliente e
        servidor, sem vazar porta nem registrar cliente fantasma.
        """
        server: GameServer | None = None
        client = GameClient()
        try:
            if host:
                server = GameServer(host="127.0.0.1", port=port)
                server.start()
                port = server.port
                ip = "127.0.0.1"
                if cancel.is_set():
                    server.stop()
                    return
            client.connect(ip, port, nickname, timeout=5.0)
            if cancel.is_set():
                client.close()
                if server is not None:
                    server.stop()
                return
            attempt_queue.put(ConnectionSuccess(client=client, server=server))
        except (OSError, TimeoutError) as exc:
            if server is not None:
                server.stop()
            attempt_queue.put(ConnectionFailure(message=str(exc)))

    def _poll_connection(self) -> None:
        """Consome o resultado do worker na thread gráfica (main loop)."""
        if self.connection_state is not ConnectionState.CONNECTING:
            return
        try:
            result = self._connection_queue.get_nowait()
        except queue.Empty:
            return
        if isinstance(result, ConnectionSuccess):
            self.client = result.client
            self.server = result.server
            self.connection_state = ConnectionState.CONNECTED
            self.is_host = result.server is not None
            self._enter_lobby()
        elif isinstance(result, ConnectionFailure):
            self.connection_state = ConnectionState.FAILED
            self._show_error(f"Não foi possível conectar: {result.message}")

    def _cancel_connecting(self) -> None:
        """Cancela a conexão em andamento e volta ao menu principal.

        Sinaliza o evento cooperativo: o worker descarta sucesso tardio e faz
        teardown de cliente/servidor; o resultado (se houver) cai na fila órfã
        da tentativa, que ``_poll_connection`` não lê mais.
        """
        if self._connection_cancel is not None:
            self._connection_cancel.set()
        if self._connection_thread is not None:
            self._connection_thread = None
        self.connection_state = ConnectionState.IDLE
        self.screen_name = Screen.MAIN
        self._current_menu = self.menu_main

    def _enter_lobby(self) -> None:
        self.screen_name = Screen.LOBBY
        self._current_menu = self.lobby_menu
        self._lobby_ui_state = None
        self._clear_lobby_warning()
        # O JoinAccepted do próprio jogador é consumido dentro de connect();
        # popula o róster a partir do estado guardado no cliente antes do
        # drain, para que PlayerJoined subsequentes sejam anexados corretamente.
        if self.client is not None and self.client.join_accepted is not None:
            joined = self.client.join_accepted
            self.my_id = joined.player_id
            self.host_id = joined.host_player_id
            self.lobby_players = list(joined.players)
        self._drain_network()
        self._refresh_lobby()

    def _start_game(self) -> None:
        self._clear_lobby_warning()
        if self.client is not None:
            self.client.start_game()

    def _clear_lobby_warning(self) -> None:
        self.lobby_warning_label.set_title("")

    def _leave_lobby(self) -> None:
        self._shutdown_connection()
        self.screen_name = Screen.MAIN
        self._current_menu = self.menu_main

    def _shutdown_connection(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.is_host = False
        self.my_id = None
        self.host_id = None
        self.role = None
        self.my_task_ids = []
        self.tasks_state = None
        self.lobby_players = []
        self.meeting = None
        self.vote_ui_state = VoteUiState.SELECTING
        self.selected_vote_target = None
        self.game_over = None
        self._puzzle = None
        self.last_snapshot = None
        self.toasts = []
        self.kill_cooldown_until = None
        self.private_ejection = None
        self.pending_game_over = None
        self._lobby_ui_state = None
        self._voting_buttons = None
        self._single_ui_states.clear()

    def _exit_to_main(self) -> None:
        """Encerra a conexão e retorna ao menu principal (padrão de saída)."""
        self._shutdown_connection()
        self._camera_needs_snap = True
        self.screen_name = Screen.MAIN
        self._current_menu = self.menu_main

    # ------------------------------------------------------------------ rede

    def _drain_network(self) -> None:
        if self.client is None:
            return
        for message in self.client.drain():
            self._handle_message(message)

    def _handle_message(self, message: Message) -> None:
        if isinstance(message, JoinAccepted):
            self.my_id = message.player_id
            self.host_id = message.host_player_id
            self.lobby_players = list(message.players)
            self._nicknames.update({p.player_id: p.nickname for p in message.players})
        elif isinstance(message, PlayerJoined):
            self.lobby_players.append(message.player)
            self._nicknames[message.player.player_id] = message.player.nickname
        elif isinstance(message, PlayerDisconnected):
            self.lobby_players = [p for p in self.lobby_players if p.player_id != message.player_id]
        elif isinstance(message, StartGame):
            self.screen_name = Screen.GAME
            self.lobby_players = []
            self._camera_needs_snap = True
            self._nicknames.update({p.player_id: p.nickname for p in message.players})
        elif isinstance(message, RoleAssigned):
            self.role = message.role
            self.my_task_ids = list(message.task_ids)
            self.tasks_state = None
        elif isinstance(message, MeetingStarted):
            self.meeting = message
            self._puzzle = None  # reunião interrompe o puzzle sem completar
            self.vote_ui_state = VoteUiState.SELECTING
            self.selected_vote_target = None
            self._voting_page = 0
            self._voting_cursor = 0
            self._voting_buttons = None
            self._meeting_started_at = time.monotonic()
            self.screen_name = Screen.VOTING
        elif isinstance(message, MeetingEnded):
            self.meeting = None
            # O ejetado permanece na tela de ejeção privada; os demais veem a
            # transição genérica (idêntica para ejeção, empate e skip).
            if (
                self.screen_name is not Screen.EJECTED
                and self.screen_name is not Screen.MEETING_ENDED
            ):
                self.screen_name = Screen.MEETING_ENDED
                self._meeting_ended_at = time.monotonic()
        elif isinstance(message, Ejected):
            self.private_ejection = message
            if self.screen_name is not Screen.EJECTED:
                self.screen_name = Screen.EJECTED
                self._ejection_started_at = time.monotonic()
        elif isinstance(message, GameOver):
            self.game_over = message
            self._single_ui_states.pop("gameover", None)
            # GameOver pode chegar no mesmo ciclo que Ejected/MeetingEnded;
            # a apresentação da ejeção tem prioridade (duração mínima).
            if self.screen_name in (Screen.EJECTED, Screen.MEETING_ENDED):
                self.pending_game_over = message
            else:
                self.screen_name = Screen.GAME_OVER
        elif isinstance(message, ProtocolError):
            # Erro de protocolo encerra a sessão: derruba client e server
            # embutido (host) antes de mostrar o erro — evita conexão órfã.
            self._shutdown_connection()
            self._show_error(f"Erro de protocolo: {message.message}")
        elif isinstance(message, ActionAccepted):
            # Confirmação privada: inicia o cooldown local do impostor ou
            # registra o voto local (somente após a aceitação do servidor).
            if message.action is ActionKind.KILL and message.cooldown_seconds is not None:
                self.kill_cooldown_until = time.monotonic() + message.cooldown_seconds
            elif message.action is ActionKind.VOTE:
                self.vote_ui_state = VoteUiState.SUBMITTED
        elif isinstance(message, ActionDenied):
            # Feedback: aviso inline no lobby; toast nas telas de jogo/votação.
            if (
                message.action is ActionKind.KILL
                and message.code is DenialCode.COOLDOWN
                and message.retry_after_seconds is not None
            ):
                retry_until = time.monotonic() + message.retry_after_seconds
                if self.kill_cooldown_until is None or retry_until > self.kill_cooldown_until:
                    self.kill_cooldown_until = retry_until
            if message.action is ActionKind.VOTE:
                # voto recusado: volta para a seleção (nunca parece registrado)
                self.vote_ui_state = VoteUiState.SELECTING
            if self.screen_name is Screen.LOBBY:
                self.lobby_warning_label.set_title(message.reason)
            elif self.screen_name in (Screen.GAME, Screen.VOTING):
                self._push_toast(_denial_text(message.code, message.reason))
        elif isinstance(message, WorldSnapshot):
            with self._snapshot_lock:
                self.last_snapshot = message
        elif isinstance(message, TaskState):
            self.tasks_state = message
        else:
            pass

    # ------------------------------------------------------------------ loop

    def run(self) -> None:
        self._current_menu = self.menu_main
        while self.running:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    self.running = False
            self._drain_network()
            self._poll_connection()
            self._update_transitions()
            self._render(self._translate_events(events))
            self._present()
            self._dt = self.clock.tick(60) / 1000.0
        self._shutdown_connection()
        pygame.quit()

    def _translate_events(self, events: list[pygame.event.Event]) -> list[pygame.event.Event]:
        """Traduz coordenadas físicas do mouse para o canvas lógico.

        Caminho único de conversão: nenhum componente converte coordenadas.
        Eventos fora do viewport (letterbox) apontam para fora da tela lógica.
        """
        translated: list[pygame.event.Event] = []
        for event in events:
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                pos = event.pos
                if not self.viewport.contains_physical(*pos):
                    translated.append(
                        pygame.event.Event(event.type, **{**event.dict, "pos": (-1, -1)})
                    )
                else:
                    lx, ly = self.viewport.screen_to_logical(*pos)
                    translated.append(
                        pygame.event.Event(
                            event.type, **{**event.dict, "pos": (round(lx), round(ly))}
                        )
                    )
            else:
                translated.append(event)
        return translated

    def _present(self) -> None:
        """Escala o canvas lógico para a janela física preservando o aspect."""
        physical = self.display.get_size()
        self.viewport = fit_viewport((WINDOW_W, WINDOW_H), physical)
        scale = self.viewport.scale
        scaled = pygame.transform.smoothscale(
            self.screen,
            (max(1, round(WINDOW_W * scale)), max(1, round(WINDOW_H * scale))),
        )
        self.display.fill((0, 0, 0))
        self.display.blit(scaled, (round(self.viewport.offset_x), round(self.viewport.offset_y)))
        pygame.display.flip()

    def _update_transitions(self, now: float | None = None) -> None:
        """Avança as transições de apresentação por relógio (sem sleep).

        ``now`` é injetável para testes determinísticos; o loop chama sem
        argumento (relógio real).
        """
        now = time.monotonic() if now is None else now
        if self.screen_name is Screen.EJECTED and (
            now - self._ejection_started_at >= self._ejected_min_duration
        ):
            if self.pending_game_over is not None:
                self.screen_name = Screen.GAME_OVER
            else:
                self.screen_name = Screen.MEETING_ENDED
                self._meeting_ended_at = now
        elif self.screen_name is Screen.MEETING_ENDED and (
            now - self._meeting_ended_at >= self._meeting_ended_min_duration
        ):
            if self.pending_game_over is not None:
                self.screen_name = Screen.GAME_OVER
            else:
                self.screen_name = Screen.GAME

    def _render(self, events: list[pygame.event.Event]) -> None:
        if self.screen_name in (Screen.MAIN, Screen.HOST, Screen.JOIN, Screen.SETTINGS):
            menu = self._current_menu
            if menu is not None:
                menu.update(events)
                menu.draw(self.screen)
        elif self.screen_name is Screen.LOBBY:
            self._render_lobby(events)
        elif self.screen_name is Screen.GAME:
            self._render_game(events)
        elif self.screen_name is Screen.VOTING:
            self._render_voting(events)
        elif self.screen_name is Screen.CONNECTING:
            self._render_connecting(events)
        elif self.screen_name is Screen.EJECTED:
            self._render_ejected(events)
        elif self.screen_name is Screen.MEETING_ENDED:
            self._render_meeting_ended(events)
        elif self.screen_name is Screen.GAME_OVER:
            self._render_gameover(events)
        elif self.screen_name is Screen.ERROR:
            self._render_error(events)

    def _refresh_lobby(self) -> None:
        if self.lobby_menu is None:
            return
        players = ", ".join(p.nickname for p in self.lobby_players) or "(vazio)"
        host_flag = " (host)" if self.is_host else ""
        self.lobby_list_label.set_title(f"Jogadores: {players}{host_flag}")

    @staticmethod
    def _apply_focus(buttons: list[Button], focus: FocusManager) -> None:
        """Reflete o botão focado do FocusManager no flag visual de cada botão."""
        focused = focus.focused
        for button in buttons:
            button.focused = button is focused

    def _render_lobby(self, events: list[pygame.event.Event]) -> None:
        """Lobby custom: grid de PlayerCard com badge HOST e botões.

        ``lobby_list_label``/``lobby_warning_label`` continuam atualizados
        (compatibilidade com avisos e testes), mas a apresentação é a grid.
        """
        self.screen.fill(COLOR_BG)
        panel = pygame.Rect(0, 0, 920, 640)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=2, border_radius=16)
        title = self.font_big.render("LOBBY", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 40)))
        count_text = self.font.render(
            f"{len(self.lobby_players)} jogador(es)  ·  código da partida: {self._lobby_game_id()}",
            True,
            COLOR_TEXT_DIM,
        )
        self.screen.blit(count_text, count_text.get_rect(center=(panel.centerx, panel.y + 74)))

        # grid de PlayerCards (2 colunas; suporta até MAX_PLAYERS=10)
        card_w, card_h, gap = 400, 64, 12
        for i, player in enumerate(self.lobby_players):
            col, row = i % 2, i // 2
            rect = pygame.Rect(
                panel.x + 40 + col * (card_w + gap),
                panel.y + 96 + row * (card_h + gap),
                card_w,
                card_h,
            )
            if player.player_id == self.host_id:
                state, secondary = PlayerCardState.HOST, "HOST"
            elif player.player_id == self.my_id:
                state, secondary = PlayerCardState.LOCAL_PLAYER, "VOCÊ"
            else:
                state, secondary = PlayerCardState.NORMAL, None
            card = PlayerCard(
                rect,
                player.nickname,
                avatar=self._avatar(player.player_id, 52),
                state=state,
                secondary=secondary,
                font=self.font,
            )
            card.draw(self.screen)

        # aviso (ex.: "jogadores insuficientes") — não modal
        warning = self.lobby_warning_label.get_title()
        if warning:
            warn = self.font.render(warning, True, COLOR_IMPOSTOR)
            self.screen.blit(warn, warn.get_rect(center=(panel.centerx, panel.bottom - 150)))

        start_state = (
            ButtonState.DEFAULT
            if self.is_host and len(self.lobby_players) >= 1
            else ButtonState.DISABLED
        )
        buttons, focus = self._lobby_controls(panel)
        buttons[0].state = start_state
        self._apply_focus(buttons, focus)
        for button in buttons:
            button.draw(self.screen)
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._leave_lobby()
                return
            focus.handle_event(event)
            for button in buttons:
                button.handle_event(event)

    def _lobby_controls(self, panel: pygame.Rect) -> tuple[list[Button], FocusManager]:
        """Botões + FocusManager do lobby (persistentes entre frames)."""
        if self._lobby_ui_state is None:
            buttons = [
                Button(
                    (panel.centerx - 250, panel.bottom - 92, 220, 48),
                    "Iniciar (host)",
                    self._start_game,
                ),
                Button(
                    (panel.centerx + 30, panel.bottom - 92, 220, 48),
                    "Sair",
                    self._leave_lobby,
                ),
            ]
            self._lobby_ui_state = (buttons, FocusManager(buttons))
        return self._lobby_ui_state

    def _single_button_controls(
        self,
        screen: str,
        rect: tuple[int, int, int, int],
        label: str,
        on_click: Callable[[], None],
    ) -> tuple[list[Button], FocusManager]:
        """Botão único + FocusManager persistentes (connecting/gameover/error)."""
        controls = self._single_ui_states.get(screen)
        if controls is None:
            button = Button(rect, label, on_click)
            controls = ([button], FocusManager([button]))
            self._single_ui_states[screen] = controls
        return controls

    def _lobby_game_id(self) -> str:
        if self.client is not None and self.client.join_accepted is not None:
            return self.client.join_accepted.game_id
        return "-"

    # ------------------------------------------------------------------ game

    def _render_game(self, events: list[pygame.event.Event]) -> None:
        with self._snapshot_lock:
            snapshot = self.last_snapshot
        me: SnapshotPlayer | None = None
        if snapshot is not None and self.my_id is not None:
            me = next((p for p in snapshot.players if p.player_id == self.my_id), None)
        # câmera: snap na primeira aparição do jogador local; depois segue
        # com suavização por dt (também quando morto — posição no snapshot)
        if me is not None:
            if self._camera_needs_snap:
                self.camera.snap_to(me.x, me.y)
                self._camera_needs_snap = False
            else:
                self.camera.update((me.x, me.y), self._dt)
        markers = derive_task_markers(
            game_map=self.game_map,
            my_task_ids=self.my_task_ids,
            tasks_state=self.tasks_state,
            me=me,
        )
        # halo de interatividade do botão de emergência (jogador vivo no raio)
        emergency_active = False
        if me is not None and me.alive and self.game_map.emergency_meeting is not None:
            ex, ey = self.game_map.emergency_meeting
            emergency_active = (
                math.hypot(ex - me.x, ey - me.y) <= self.game_map.emergency_meeting_radius
            )
        self.renderer.draw_map(self.screen, self.camera, markers, emergency_active=emergency_active)
        if snapshot is not None and self.my_id is not None:
            self.renderer.draw_bodies(self.screen, self.camera, snapshot.bodies)
            self.renderer.draw_players(
                self.screen,
                self.camera,
                snapshot.players,
                self.my_id,
                nicknames=self._nicknames,
                dt=self._dt,
            )
        hud = derive_game_hud(
            role=self.role,
            me=me,
            game_map=self.game_map,
            my_task_ids=self.my_task_ids,
            tasks_state=self.tasks_state,
            snapshot=snapshot,
            kill_cooldown_until=self.kill_cooldown_until,
            now=time.monotonic(),
        )
        self.renderer.draw_hud(self.screen, hud)
        # morte com o puzzle aberto: fecha sem completar (mundo não pausa)
        if self._puzzle is not None and (me is None or not me.alive):
            self._puzzle = None
        if self._puzzle is not None:
            self._render_puzzle(events)
        else:
            for event in events:
                if event.type == pygame.KEYDOWN:
                    self._handle_game_key(event.key)
            self._handle_game_movement()
        self._draw_toasts(self.screen)

    # ------------------------------------------------------------------ puzzle

    def _open_puzzle(self, task_id: int) -> None:
        """Abre o minigame modal da tarefa (tipo vem do mapa carregado)."""
        task_type = next(
            (t.task_type for t in self.game_map.task_points if t.task_id == task_id), None
        )
        if task_type is None:
            return
        self._puzzle = create_minigame(
            task_type,
            task_id,
            fonts=self.fonts,
            reduced_motion=self.renderer.reduced_motion,
        )

    def _render_puzzle(self, events: list[pygame.event.Event]) -> None:
        """Desenha o puzzle modal sobre o mundo (que continua ativo)."""
        puzzle = self._puzzle
        if puzzle is None:
            return
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 205))
        self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(0, 0, CONTENT_W + 80, CONTENT_H + 150)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=2, border_radius=16)
        title_text, hint_text = TASK_DISPLAY.get(
            puzzle.task_type, (puzzle.task_type.replace("_", " "), "")
        )
        title = self.font_big.render(title_text, True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 34)))
        hint = self.font.render(hint_text, True, COLOR_TEXT_DIM)
        self.screen.blit(hint, hint.get_rect(center=(panel.centerx, panel.y + 66)))
        play = pygame.Rect(0, 0, CONTENT_W, CONTENT_H)
        play.centerx = panel.centerx
        play.y = panel.y + 92
        puzzle.play_area = play
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                # abandonar: fecha sem completar (progresso do puzzle perdido)
                self._puzzle = None
                return
            puzzle.handle_event(event)
        puzzle.update(self._dt)
        puzzle.draw(self.screen)
        if puzzle.done:
            task_id = puzzle.task_id
            self._puzzle = None
            if self.client is not None:
                self.client.complete_task(task_id)
            return
        footer = self.fonts.caption.render("ESC para sair", True, COLOR_TEXT_DIM)
        self.screen.blit(footer, footer.get_rect(center=(panel.centerx, panel.bottom - 18)))

    def _handle_game_movement(self) -> None:
        """Envia MovementInput ao servidor enquanto WASD estiver pressionado."""
        if self.client is None:
            return
        direction = _movement_direction(pygame.key.get_pressed())
        if direction is not None:
            self.client.move(*direction)

    def _handle_game_key(self, key: int) -> None:
        if key == pygame.K_ESCAPE:
            self._exit_to_main()
            return
        if self.client is None:
            return
        with self._snapshot_lock:
            snapshot = self.last_snapshot
        if snapshot is None or self.my_id is None:
            return
        me = next((p for p in snapshot.players if p.player_id == self.my_id), None)
        if me is None or not me.alive:
            return
        if key == pygame.K_r:
            # reportar corpo mais próximo (mesmo raio do servidor)
            body_id = derive_report_target(me=me, snapshot=snapshot)
            if body_id is not None:
                self.client.report(body_id)
            else:
                self._push_toast("Nenhum corpo por perto")
            return
        if key == pygame.K_e:
            # interação contextual: tarefa atribuída/incompleta ou reunião
            context = derive_interaction_context(
                me=me,
                game_map=self.game_map,
                my_task_ids=self.my_task_ids,
                tasks_state=self.tasks_state,
            )
            if context is None:
                return
            if context.kind is ActionKind.TASK and context.target_id is not None:
                # tarefa exige resolver o minigame; a conclusão vai ao
                # servidor só quando o puzzle termina (ver _render_puzzle)
                self._open_puzzle(context.target_id)
            elif context.kind is ActionKind.EMERGENCY:
                self.client.emergency()
            return
        if key == pygame.K_SPACE and self.role is Role.IMPOSTOR:
            # envia kill ao alvo vivo mais próximo; recusas (alcance/cooldown)
            # chegam tipadas do servidor e viram toast
            alive = [p for p in snapshot.players if p.alive and p.player_id != self.my_id]
            if alive:
                nearest = min(alive, key=lambda p: math.hypot(p.x - me.x, p.y - me.y))
                self.client.kill(nearest.player_id)
            return

    # ------------------------------------------------------------------ votação

    def _avatar(self, player_id: int, height: int) -> pygame.Surface:
        """Sprite duckee do jogador redimensionado para a altura dada."""
        sprite = self.renderer.sprites.frame(color_for(player_id), PlayerAnim.IDLE, 0)
        width, _height = sprite.get_size()
        scale = height / _height
        return pygame.transform.scale(sprite, (max(1, int(width * scale)), height))

    def _nickname_of(self, player_id: int) -> str:
        return self._nicknames.get(player_id, f"P{player_id}")

    def _render_voting(self, events: list[pygame.event.Event]) -> None:
        with self._snapshot_lock:
            snapshot = self.last_snapshot
        me: SnapshotPlayer | None = None
        if snapshot is not None and self.my_id is not None:
            me = next((p for p in snapshot.players if p.player_id == self.my_id), None)
        markers = derive_task_markers(
            game_map=self.game_map,
            my_task_ids=self.my_task_ids,
            tasks_state=self.tasks_state,
            me=me,
        )
        self.renderer.draw_map(self.screen, self.camera, markers)
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 205))
        self.screen.blit(overlay, (0, 0))
        if self.meeting is None:
            return
        panel = pygame.Rect(0, 0, 620, 640)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=2, border_radius=16)
        title = self.font_big.render(f"Reunião #{self.meeting.meeting_id}", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 38)))
        reason = self.meeting.reason.value.replace("_", " ")
        remaining = max(
            0,
            int(self.meeting.vote_timeout_seconds - (time.monotonic() - self._meeting_started_at)),
        )
        subtitle = self.font.render(
            f"Motivo: {reason}   |   Votação encerra em {remaining}s", True, COLOR_TEXT_DIM
        )
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 76)))
        layout = voting_layout(len(self.meeting.voters), self._voting_page)
        self._voting_page = layout.page
        first = layout.page * VOTING_CARDS_PER_PAGE
        visible_ids = self.meeting.voters[first : first + len(layout.cards)]
        max_cursor = len(visible_ids) + 1  # cards + PULAR + VOTAR
        self._voting_cursor = min(self._voting_cursor, max_cursor)
        selecting = self.vote_ui_state is VoteUiState.SELECTING
        card_hit: list[tuple[pygame.Rect, int]] = []
        for row, player_id in enumerate(visible_ids):
            card_rect = pygame.Rect(layout.cards[row])
            if selecting and player_id == self.selected_vote_target:
                state = PlayerCardState.SELECTED
            elif self.vote_ui_state is VoteUiState.SUBMITTED:
                state = PlayerCardState.DISABLED
            else:
                state = PlayerCardState.NORMAL
            card = PlayerCard(
                card_rect,
                self._nickname_of(player_id),
                avatar=self._avatar(player_id, 52),
                state=state,
                secondary="Clique para votar" if state is PlayerCardState.NORMAL else None,
                font=self.font,
            )
            card.draw(self.screen)
            if row == self._voting_cursor:
                ring = card_rect.inflate(6, 6)
                pygame.draw.rect(self.screen, TOKENS.focus_ring, ring, width=2, border_radius=14)
            card_hit.append((card_rect, player_id))
        if layout.page_count > 1:
            info = self.font.render(
                f"Página {layout.page + 1}/{layout.page_count} — </> ou roda do mouse",
                True,
                COLOR_TEXT_DIM,
            )
            self.screen.blit(info, info.get_rect(center=layout.page_info_center))
        button_state = self._vote_button_state()
        skip_button, vote_button = self._voting_controls(layout)
        skip_button.rect = pygame.Rect(layout.skip_button)
        vote_button.rect = pygame.Rect(layout.vote_button)
        skip_button.state = button_state
        vote_button.state = button_state
        skip_button.focused = self._voting_cursor == len(visible_ids) and (
            button_state is ButtonState.DEFAULT
        )
        vote_button.focused = self._voting_cursor == max_cursor and (
            button_state is ButtonState.DEFAULT
        )
        buttons = [skip_button, vote_button]
        for button in buttons:
            button.draw(self.screen)
        # estados de envio/confirmação (sem duplo envio)
        if self.vote_ui_state is VoteUiState.SUBMITTING:
            status = self.font.render("ENVIANDO VOTO…", True, COLOR_TEXT)
            self.screen.blit(status, status.get_rect(center=layout.status_center))
        elif self.vote_ui_state is VoteUiState.SUBMITTED:
            status = self.font.render("VOTO REGISTRADO", True, COLOR_TASK)
            self.screen.blit(status, status.get_rect(center=layout.status_center))
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_main()
                return
            if event.type == pygame.KEYDOWN and selecting:
                if event.key in (pygame.K_DOWN, pygame.K_TAB) and not (
                    event.key == pygame.K_TAB and pygame.key.get_mods() & pygame.KMOD_SHIFT
                ):
                    self._voting_cursor = (self._voting_cursor + 1) % (max_cursor + 1)
                elif event.key == pygame.K_UP or (
                    event.key == pygame.K_TAB and pygame.key.get_mods() & pygame.KMOD_SHIFT
                ):
                    self._voting_cursor = (self._voting_cursor - 1) % (max_cursor + 1)
                elif event.key in (pygame.K_LEFT, pygame.K_PAGEUP):
                    self._voting_page = max(0, self._voting_page - 1)
                    self._voting_cursor = 0
                elif event.key in (pygame.K_RIGHT, pygame.K_PAGEDOWN):
                    self._voting_page = min(layout.page_count - 1, self._voting_page + 1)
                    self._voting_cursor = 0
                elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    if self._voting_cursor < len(visible_ids):
                        self.selected_vote_target = visible_ids[self._voting_cursor]
                    elif self._voting_cursor == len(visible_ids):
                        self._cast_vote(None)
                    else:
                        self._cast_vote(self.selected_vote_target)
            if event.type == pygame.MOUSEBUTTONDOWN and event.button in (4, 5):
                delta = -1 if event.button == 4 else 1
                self._voting_page = min(layout.page_count - 1, max(0, self._voting_page + delta))
                self._voting_cursor = 0
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and selecting:
                for row, (card_rect, player_id) in enumerate(card_hit):
                    if card_rect.collidepoint(event.pos):
                        self.selected_vote_target = player_id
                        self._voting_cursor = row
                        break
            for button in buttons:
                button.handle_event(event)
        self._draw_toasts(self.screen)

    def _vote_button_state(self) -> ButtonState:
        """Estado dos botões de votação conforme o fluxo local."""
        if self.vote_ui_state is VoteUiState.SUBMITTED:
            return ButtonState.DISABLED
        if self.vote_ui_state is VoteUiState.SUBMITTING:
            return ButtonState.COOLDOWN
        return ButtonState.DEFAULT

    def _voting_controls(self, layout: VotingLayout) -> tuple[Button, Button]:
        """Botões PULAR/VOTAR persistentes durante a reunião."""
        if self._voting_buttons is None:
            self._voting_buttons = [
                Button(layout.skip_button, "PULAR", lambda: self._cast_vote(None)),
                Button(
                    layout.vote_button,
                    "VOTAR",
                    lambda: self._cast_vote(self.selected_vote_target),
                ),
            ]
        return self._voting_buttons[0], self._voting_buttons[1]

    def _cast_vote(self, target: int | None) -> None:
        """Envia o voto apenas em SELECTING; nunca reenvia após SUBMITTING."""
        if self.client is None or self.meeting is None:
            return
        if self.vote_ui_state is not VoteUiState.SELECTING:
            return
        if target is None or target == self.selected_vote_target:
            self.vote_ui_state = VoteUiState.SUBMITTING
            self.client.vote(self.meeting.meeting_id, target)

    def _render_connecting(self, events: list[pygame.event.Event]) -> None:
        """Tela de conexão sem congelamento: worker em thread, cancelável."""
        self.screen.fill(COLOR_BG)
        panel = pygame.Rect(0, 0, 640, 260)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=2, border_radius=16)
        title = self.font_big.render("Conectando ao servidor…", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 56)))
        hint = self.font.render(
            "A interface continua responsiva durante a conexão", True, COLOR_TEXT_DIM
        )
        self.screen.blit(hint, hint.get_rect(center=(panel.centerx, panel.y + 110)))
        buttons, focus = self._single_button_controls(
            "connecting",
            (panel.centerx - 100, panel.bottom - 74, 200, 44),
            "Cancelar",
            self._cancel_connecting,
        )
        self._apply_focus(buttons, focus)
        buttons[0].draw(self.screen)
        for event in events:
            focus.handle_event(event)
            buttons[0].handle_event(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._cancel_connecting()
                return

    # ------------------------------------------------------------------ finais

    def _render_ejected(self, events: list[pygame.event.Event]) -> None:
        """Experiência privada do ejetado: VOCÊ FOI EJETADO + espectador.

        Não mostra contagem, votos, papéis de terceiros nem o resultado da
        reunião — só a identidade do próprio jogador.
        """
        self.screen.fill(COLOR_BG)
        panel = pygame.Rect(0, 0, 640, 420)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_IMPOSTOR, panel, width=2, border_radius=16)
        title = self.font_big.render("VOCÊ FOI EJETADO", True, COLOR_IMPOSTOR)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 48)))
        if self.private_ejection is not None:
            avatar = self._avatar(self.private_ejection.player_id, 110)
            self.screen.blit(avatar, avatar.get_rect(center=(panel.centerx, panel.y + 180)))
        subtitle = self.font.render("MODO ESPECTADOR", True, COLOR_TEXT)
        self.screen.blit(subtitle, subtitle.get_rect(center=(panel.centerx, panel.y + 290)))
        hint = self.font.render("Pressione ESC para voltar ao menu", True, COLOR_TEXT_DIM)
        self.screen.blit(hint, hint.get_rect(center=(panel.centerx, panel.bottom - 44)))
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_main()
                return

    def _render_meeting_ended(self, events: list[pygame.event.Event]) -> None:
        """Transição genérica de fim de reunião — idêntica para todos os
        desfechos (ejeção, empate, skip) para preservar o sigilo."""
        overlay = pygame.Surface((WINDOW_W, WINDOW_H), pygame.SRCALPHA)
        overlay.fill((8, 10, 16, 215))
        self.screen.blit(overlay, (0, 0))
        title = self.font_big.render("REUNIÃO ENCERRADA", True, COLOR_TEXT)
        self.screen.blit(title, title.get_rect(center=(WINDOW_W // 2, WINDOW_H // 2)))
        for event in events:
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_main()
                return

    def _render_gameover(self, events: list[pygame.event.Event]) -> None:
        self.screen.fill(COLOR_BG)
        if self.game_over is None:
            return
        winner = "IMPOSTORES" if self.game_over.winner.value == "impostor" else "TRIPULANTES"
        winner_color = COLOR_IMPOSTOR if winner == "IMPOSTORES" else COLOR_CREW
        title = self.font_big.render(f"Fim de jogo — {winner} venceram!", True, winner_color)
        self.screen.blit(title, title.get_rect(center=(WINDOW_W // 2, 90)))
        panel = pygame.Rect(0, 0, 820, 440)
        panel.center = (WINDOW_W // 2, 400)
        pygame.draw.rect(self.screen, COLOR_PANEL, panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_PANEL_BORDER, panel, width=2, border_radius=16)
        layout = gameover_layout(len(self.game_over.roles))
        for card_rect_tuple, (player_id, role) in zip(
            layout.cards, sorted(self.game_over.roles.items()), strict=True
        ):
            card_rect = pygame.Rect(card_rect_tuple)
            if role is Role.IMPOSTOR:
                state = (
                    PlayerCardState.WINNER
                    if self.game_over.winner.value == "impostor"
                    else PlayerCardState.LOSER
                )
            else:
                state = (
                    PlayerCardState.WINNER
                    if self.game_over.winner.value == "crew"
                    else PlayerCardState.LOSER
                )
            if player_id == self.my_id:
                secondary = "VOCÊ"
            else:
                secondary = "IMPOSTOR" if role is Role.IMPOSTOR else "TRIPULANTE"
            card = PlayerCard(
                card_rect,
                self._nickname_of(player_id),
                avatar=self._avatar(player_id, 52),
                state=state,
                secondary=secondary,
                font=self.font,
            )
            card.draw(self.screen)
        buttons, focus = self._single_button_controls(
            "gameover", layout.back_button, "VOLTAR AO MENU", self._exit_to_main
        )
        buttons[0].rect = pygame.Rect(layout.back_button)
        self._apply_focus(buttons, focus)
        buttons[0].draw(self.screen)
        hint = self.font.render("ESC também volta ao menu", True, COLOR_TEXT_DIM)
        self.screen.blit(hint, hint.get_rect(center=layout.hint_center))
        for event in events:
            focus.handle_event(event)
            buttons[0].handle_event(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._exit_to_main()
                return

    def _render_error(self, events: list[pygame.event.Event]) -> None:
        self.screen.fill(COLOR_BG)
        panel = pygame.Rect(0, 0, 720, 300)
        panel.center = (WINDOW_W // 2, WINDOW_H // 2)
        pygame.draw.rect(self.screen, (36, 22, 26), panel, border_radius=16)
        pygame.draw.rect(self.screen, COLOR_IMPOSTOR, panel, width=2, border_radius=16)
        title = self.font_big.render("Erro", True, COLOR_IMPOSTOR)
        self.screen.blit(title, title.get_rect(center=(panel.centerx, panel.y + 44)))
        y = panel.y + 100
        for line in _wrap_text(self.error_message, self.font, panel.width - 80):
            surf = self.font.render(line, True, COLOR_TEXT)
            self.screen.blit(surf, surf.get_rect(center=(panel.centerx, y)))
            y += 34
        buttons, focus = self._single_button_controls(
            "error",
            (panel.centerx - 100, panel.bottom - 74, 200, 44),
            "Voltar",
            self._back_to_main,
        )
        self._apply_focus(buttons, focus)
        buttons[0].draw(self.screen)
        for event in events:
            focus.handle_event(event)
            buttons[0].handle_event(event)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._back_to_main()
                return


def _wrap_text(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Quebra o texto em linhas que cabem em ``max_width`` px."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def main() -> None:
    # Evita falha por falta de áudio em ambientes sem dispositivo
    try:
        App().run()
    except Exception as exc:  # noqa: BLE001 - reporta erro de startup sem crash silencioso
        print(f"Erro fatal: {exc}")
        raise
