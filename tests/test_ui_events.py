"""Testes de UI dirigidos por eventos sintéticos (SDL dummy).

Exercita os handlers de teclado/mouse do ``App`` conectado a um servidor
real: ESC volta ao menu na tela de jogo; a direção de movimento derivada
do estado do teclado (WASD) está correta; cliques em ``Button`` disparam a
ação. Não abre janela real (SDL_VIDEODRIVER=dummy).
"""

from __future__ import annotations

import os
import queue
import socket
import threading
import time
from collections.abc import Iterator

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.game.meeting import MeetingReason
from codecon_amoung_us.game.model import Role, Team
from codecon_amoung_us.net.client import GameClient
from codecon_amoung_us.net.server import GameServer
from codecon_amoung_us.protocol import (
    ActionAccepted,
    ActionDenied,
    ActionKind,
    DenialCode,
    GameOver,
    LobbyPlayer,
    MeetingStarted,
    PlayerInfo,
    ProtocolError,
)
from codecon_amoung_us.ui.app import (
    App,
    ConnectionFailure,
    ConnectionState,
    Screen,
    _movement_direction,
)
from codecon_amoung_us.ui.components import Button, ButtonState
from codecon_amoung_us.ui.viewmodel import VoteUiState

pytestmark = pytest.mark.ui


@pytest.fixture
def app() -> Iterator[App]:
    app = App()
    yield app
    app._shutdown_connection()
    # Sem pygame.quit() aqui: ciclos quit->init corrompem o cache global de
    # fontes do pygame-menu (objetos SDL liberados) e o render seguinte
    # segfaulta (observado em execução 2026-08-29). SDL dummy encerra no
    # processo.


def _fake_keys(*pressed: int) -> list[bool]:
    keys = [False] * 512
    for key in pressed:
        keys[key] = True
    return keys


def test_movement_direction_single_axis() -> None:
    assert _movement_direction(_fake_keys(pygame.K_w)) == (0.0, -1.0)
    assert _movement_direction(_fake_keys(pygame.K_a)) == (-1.0, 0.0)
    assert _movement_direction(_fake_keys(pygame.K_s)) == (0.0, 1.0)
    assert _movement_direction(_fake_keys(pygame.K_d)) == (1.0, 0.0)


def test_movement_direction_diagonal_is_normalized() -> None:
    direction = _movement_direction(_fake_keys(pygame.K_w, pygame.K_d))
    assert direction is not None
    dx, dy = direction
    assert abs(dx) == abs(dy) == pytest.approx(2**-0.5)


def test_movement_direction_none_when_idle() -> None:
    assert _movement_direction(_fake_keys()) is None


def test_button_click_fires_callback() -> None:
    # pygame.init() é idempotente; não chamamos pygame.quit() aqui pelo mesmo
    # motivo da fixture: o cache global de fontes do pygame-menu não sobrevive
    # a ciclos quit->init (segfault observado).
    pygame.init()
    calls: list[int] = []
    button = Button((10, 10, 100, 40), "ok", lambda: calls.append(1))
    # clique completo: MOUSEBUTTONDOWN arma; MOUSEBUTTONUP dentro ativa
    button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(50, 30)))
    assert calls == []
    button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(50, 30)))
    assert calls == [1]
    # clique fora do retângulo não dispara
    button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(500, 500)))
    button.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(500, 500)))
    assert calls == [1]


def test_escape_in_game_returns_to_main(app: App) -> None:
    # App conectado a um servidor real (como o host faz): ESC derruba tudo.
    server = GameServer(host="127.0.0.1", port=0)
    server.start()
    client = GameClient()
    try:
        client.connect("127.0.0.1", server.port, "tester", timeout=5.0)
        app.client = client
        app.server = server
        app.screen_name = Screen.GAME
        app._handle_game_key(pygame.K_ESCAPE)
        assert app.screen_name == "main"
        assert app.client is None
        assert app.server is None
        assert app._current_menu is app.menu_main
    finally:
        client.close()
        server.stop()


def test_escape_in_voting_returns_to_main(app: App) -> None:
    app.meeting = MeetingStarted(
        meeting_id=1,
        reason=MeetingReason.KILL_REPORTED,
        voters=[0, 1],
        vote_timeout_seconds=30.0,
    )
    app.screen_name = Screen.VOTING
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    app._render_voting([event])
    assert app.screen_name == "main"
    assert app._current_menu is app.menu_main


def test_protocol_error_tears_down_connection(app: App) -> None:
    # ProtocolError no meio da sessão encerra client e server embutido.
    server = GameServer(host="127.0.0.1", port=0)
    server.start()
    client = GameClient()
    try:
        client.connect("127.0.0.1", server.port, "tester", timeout=5.0)
        app.client = client
        app.server = server
        app._handle_message(ProtocolError(code="bad_frame", message="x"))
        assert app.client is None
        assert app.server is None
        assert app.screen_name == "error"
    finally:
        client.close()
        server.stop()


def test_action_denied_shows_warning_in_lobby(app: App) -> None:
    app.screen_name = Screen.LOBBY
    app._handle_message(
        ActionDenied(
            action=ActionKind.START_GAME,
            code=DenialCode.INSUFFICIENT_PLAYERS,
            reason="jogadores insuficientes",
        )
    )
    assert app.lobby_warning_label.get_title() == "jogadores insuficientes"
    # iniciar limpa o aviso
    app._start_game()
    assert app.lobby_warning_label.get_title() == ""


def _create_game_with_free_port(app: App, *, attempts: int = 5) -> int:
    """Cria partida embutida em porta sondada; refaz a sonda em EADDRINUSE.

    Probe-then-bind é TOCTOU: outro processo pode tomar a porta efêmera entre
    a sonda e o bind do servidor embutido (causa-raiz do flake G-01, capturada
    em V-01 em 2026-08-30: conexões de processos alheios em TIME_WAIT/LAST_ACK
    na porta recém-sondada). O produto reporta o erro corretamente; o teste
    refaz a sonda com uma porta nova, como um usuário faria. Erros que não
    sejam a corrida de porta propagam como falha — o retry não mascara nada.
    """
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])
        app.port_input.set_value(str(port))
        app._create_game()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and app.connection_state.value not in (
            "connected",
            "failed",
        ):
            app._poll_connection()
            time.sleep(0.01)
        if app.connection_state.value == "connected":
            return port
        if "Address already in use" not in app.error_message:
            break
        app._shutdown_connection()
        app._back_to_main()
        app.connection_state = ConnectionState.IDLE
    raise AssertionError(f"criação de partida falhou: {app.error_message}")


def test_create_game_populates_lobby_and_start_transitions(app: App) -> None:
    import time as _time

    _create_game_with_free_port(app)
    try:
        assert app.is_host
        assert app.screen_name == "lobby"
        assert app.client is not None
        assert app.server is not None
        # o róster do lobby inclui o próprio host
        assert [p.nickname for p in app.lobby_players] == ["host"]
        app._refresh_lobby()
        title = app.lobby_list_label.get_title()
        assert "host" in title
        assert "(vazio)" not in title
        # iniciar sozinho transiciona para a tela de jogo (papel: tripulante)
        app._start_game()
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and not (
            app.screen_name == "game" and app.role is Role.CREW
        ):
            app._drain_network()
            _time.sleep(0.02)
        assert app.screen_name == "game"
        assert app.role is Role.CREW
    finally:
        app._shutdown_connection()


def test_join_failure_shows_error(app: App) -> None:
    import time as _time

    # servidor efêmero que é fechado imediatamente: a porta recusa conexão
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    app.join_ip.set_value("127.0.0.1")
    app.join_port.set_value(str(port))
    app._join_game()
    deadline = _time.monotonic() + 8.0
    while _time.monotonic() < deadline and app.connection_state.value != "failed":
        app._poll_connection()
        _time.sleep(0.01)
    assert app.connection_state.value == "failed"
    assert app.screen_name == "error"
    assert "conectar" in app.error_message


def test_cancel_connecting_returns_to_main(app: App) -> None:
    # porta sem servidor: a conexão ficaria pendente até timeout; cancelar
    # deve voltar imediatamente ao menu sem esperar o worker
    app.connection_state = ConnectionState.CONNECTING
    app.screen_name = Screen.CONNECTING
    app._cancel_connecting()
    assert app.connection_state.value == "idle"
    assert app.screen_name == "main"
    assert app._current_menu is app.menu_main


# ---------------------------------------------------------------------------
# Input com viewport: coordenadas físicas -> lógicas (letterbox)
# ---------------------------------------------------------------------------


def test_mouse_click_translated_to_logical_center(app: App) -> None:
    from codecon_amoung_us.ui.layout import fit_viewport

    app.viewport = fit_viewport((1280, 768), (1920, 1080))
    events = [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(960, 540))]
    translated = app._translate_events(events)
    # centro físico = centro lógico (640, 384)
    assert translated[0].pos == (640, 384)


def test_letterbox_click_translated_outside(app: App) -> None:
    from codecon_amoung_us.ui.layout import fit_viewport

    # janela muito larga: sobras laterais (letterbox)
    app.viewport = fit_viewport((1280, 768), (2560, 768))
    events = [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 384))]
    translated = app._translate_events(events)
    assert translated[0].pos == (-1, -1)  # fora do viewport: sem interação


def test_motion_events_also_translated(app: App) -> None:
    from codecon_amoung_us.ui.layout import fit_viewport

    app.viewport = fit_viewport((1280, 768), (1920, 1080))
    events = [pygame.event.Event(pygame.MOUSEMOTION, pos=(960, 540))]
    translated = app._translate_events(events)
    assert translated[0].pos == (640, 384)


def test_game_movement_sends_normalized_move(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    moves: list[tuple[float, float]] = []
    client = GameClient()
    monkeypatch.setattr(client, "move", lambda dx, dy: moves.append((dx, dy)))
    monkeypatch.setattr(pygame.key, "get_pressed", lambda: _fake_keys(pygame.K_w))
    app.client = client
    app._handle_game_movement()
    assert moves == [(0.0, -1.0)]


def test_action_denied_in_game_pushes_toast(app: App) -> None:
    app.screen_name = Screen.GAME
    app._handle_message(
        ActionDenied(
            action=ActionKind.KILL,
            code=DenialCode.COOLDOWN,
            reason="kill em recarga",
            retry_after_seconds=12.0,
        )
    )
    assert len(app.toasts) == 1
    assert app.toasts[0].text == "Eliminação ainda em recarga"
    # cooldown local atualizado a partir do retry_after
    assert app.kill_cooldown_until is not None
    assert app.kill_cooldown_until > time.monotonic()


def test_action_denied_in_voting_pushes_toast(app: App) -> None:
    app.screen_name = Screen.VOTING
    app._handle_message(
        ActionDenied(
            action=ActionKind.VOTE,
            code=DenialCode.ALREADY_VOTED,
            reason="voto não aceito",
        )
    )
    assert [t.text for t in app.toasts] == ["Voto já registrado"]


def test_action_accepted_kill_starts_cooldown(app: App) -> None:
    app._handle_message(ActionAccepted(action=ActionKind.KILL, cooldown_seconds=15.0))
    assert app.kill_cooldown_until is not None
    remaining = app.kill_cooldown_until - time.monotonic()
    assert 14.0 <= remaining <= 15.0


def test_toasts_expire_by_clock(app: App) -> None:
    app._push_toast("primeiro")
    app._push_toast("segundo")
    # envelhece o primeiro toast além da vida útil
    app.toasts[0].created_at -= app._toast_lifetime + 1.0
    app._prune_toasts(time.monotonic())
    assert [t.text for t in app.toasts] == ["segundo"]


def test_hud_stays_fixed_when_camera_moves(app: App) -> None:
    from codecon_amoung_us.protocol import SnapshotPlayer, WorldSnapshot

    app.my_id = 0
    app.role = Role.CREW
    app.screen_name = Screen.GAME
    app.last_snapshot = WorldSnapshot(
        tick=1, players=[SnapshotPlayer(player_id=0, x=400.0, y=352.0, alive=True)], bodies=[]
    )
    hud_rect = pygame.Rect(0, 704, 1280, 64)
    world_rect = pygame.Rect(0, 0, 1280, 704)

    app.camera.snap_to(640.0, 352.0)
    app._render_game([])
    hud_a = pygame.image.tobytes(app.screen.subsurface(hud_rect), "RGBA")
    world_a = pygame.image.tobytes(app.screen.subsurface(world_rect), "RGBA")

    app.camera.snap_to(1920.0, 1056.0)
    app._render_game([])
    hud_b = pygame.image.tobytes(app.screen.subsurface(hud_rect), "RGBA")
    world_b = pygame.image.tobytes(app.screen.subsurface(world_rect), "RGBA")

    # HUD pixel-idêntico entre posições de câmera; região do mundo muda
    assert hud_a == hud_b
    assert world_a != world_b


def test_toast_stack_limited_to_three(app: App) -> None:
    for text in ("a", "b", "c", "d"):
        app._push_toast(text)
    assert [t.text for t in app.toasts] == ["b", "c", "d"]


def _setup_game_state(app: App, *, x: float, y: float, alive: bool = True) -> None:
    """Estado mínimo de jogo para testar handlers de teclado (sem servidor)."""
    from codecon_amoung_us.protocol import SnapshotPlayer, WorldSnapshot

    app.my_id = 0
    app.role = Role.CREW
    app.last_snapshot = WorldSnapshot(
        tick=1, players=[SnapshotPlayer(player_id=0, x=x, y=y, alive=alive)], bodies=[]
    )


def _setup_puzzle(app: App) -> int:
    """Estado de jogo com o jogador sobre uma tarefa atribuída; retorna o id."""
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map
    from codecon_amoung_us.protocol import TaskInfo, TaskState

    game_map = load_map(default_map_path())
    point = game_map.task_points[0]
    _setup_game_state(app, x=point.x, y=point.y)
    app.my_task_ids = [point.task_id]
    app.tasks_state = TaskState(
        tasks=[TaskInfo(task_id=point.task_id, task_type=point.task_type, done=False)]
    )
    return point.task_id


def test_e_key_opens_task_puzzle_without_completing(
    monkeypatch: pytest.MonkeyPatch, app: App
) -> None:
    task_id = _setup_puzzle(app)
    completed: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda tid: completed.append(tid))
    app.client = client
    app._handle_game_key(pygame.K_e)
    # E abre o minigame; nada vai ao servidor antes de resolver o puzzle
    assert app._puzzle is not None
    assert app._puzzle.task_id == task_id
    assert completed == []


def test_puzzle_done_sends_complete_task(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    task_id = _setup_puzzle(app)
    completed: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda tid: completed.append(tid))
    app.client = client
    app._handle_game_key(pygame.K_e)
    assert app._puzzle is not None
    app._puzzle._done = True  # puzzle resolvido (lógica coberta em test_puzzles)
    app._render_puzzle([])
    assert completed == [task_id]
    assert app._puzzle is None


def test_puzzle_escape_abandons_without_completing(
    monkeypatch: pytest.MonkeyPatch, app: App
) -> None:
    _setup_puzzle(app)
    completed: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda tid: completed.append(tid))
    app.client = client
    app._handle_game_key(pygame.K_e)
    assert app._puzzle is not None
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)
    app._render_puzzle([event])
    assert app._puzzle is None
    assert completed == []


def test_meeting_started_closes_puzzle(app: App) -> None:
    _setup_puzzle(app)
    app.client = GameClient()  # _handle_game_key exige sessão ativa
    app._handle_game_key(pygame.K_e)
    assert app._puzzle is not None
    app._handle_message(_meeting())
    assert app._puzzle is None


def test_death_closes_puzzle_without_completing(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    _setup_puzzle(app)
    completed: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda tid: completed.append(tid))
    app.client = client
    app._handle_game_key(pygame.K_e)
    assert app._puzzle is not None
    # morreu com o puzzle aberto: o próximo frame do jogo fecha sem completar
    _setup_game_state(app, x=0.0, y=0.0, alive=False)
    app._render_game([])
    assert app._puzzle is None
    assert completed == []


def test_e_key_sends_nothing_outside_radius(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map
    from codecon_amoung_us.protocol import TaskInfo, TaskState

    game_map = load_map(default_map_path())
    point = game_map.task_points[0]
    spawn = game_map.spawn_points[0]
    _setup_game_state(app, x=spawn.x, y=spawn.y)
    app.my_task_ids = [point.task_id]
    app.tasks_state = TaskState(
        tasks=[TaskInfo(task_id=point.task_id, task_type=point.task_type, done=False)]
    )
    completed: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda task_id: completed.append(task_id))
    monkeypatch.setattr(client, "emergency", lambda: completed.append(-1))
    app.client = client
    app._handle_game_key(pygame.K_e)
    assert completed == []


def test_e_key_ignored_when_dead(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map
    from codecon_amoung_us.protocol import TaskInfo, TaskState

    game_map = load_map(default_map_path())
    point = game_map.task_points[0]
    _setup_game_state(app, x=point.x, y=point.y, alive=False)
    app.my_task_ids = [point.task_id]
    app.tasks_state = TaskState(
        tasks=[TaskInfo(task_id=point.task_id, task_type=point.task_type, done=False)]
    )
    calls: list[object] = []
    client = GameClient()
    monkeypatch.setattr(client, "complete_task", lambda task_id: calls.append(task_id))
    monkeypatch.setattr(client, "emergency", lambda: calls.append("e"))
    monkeypatch.setattr(client, "report", lambda body_id: calls.append(body_id))
    monkeypatch.setattr(client, "kill", lambda target_id: calls.append(target_id))
    app.client = client
    app._handle_game_key(pygame.K_e)
    app._handle_game_key(pygame.K_r)
    app._handle_game_key(pygame.K_SPACE)
    assert calls == []


def test_space_key_sends_kill_to_nearest_alive(monkeypatch: pytest.MonkeyPatch, app: App) -> None:
    from codecon_amoung_us.protocol import SnapshotPlayer, WorldSnapshot

    app.my_id = 0
    app.role = Role.IMPOSTOR
    app.last_snapshot = WorldSnapshot(
        tick=1,
        players=[
            SnapshotPlayer(player_id=0, x=100.0, y=100.0, alive=True),
            SnapshotPlayer(player_id=1, x=500.0, y=500.0, alive=True),
            SnapshotPlayer(player_id=2, x=120.0, y=100.0, alive=True),
        ],
        bodies=[],
    )
    kills: list[int] = []
    client = GameClient()
    monkeypatch.setattr(client, "kill", lambda target_id: kills.append(target_id))
    app.client = client
    app._handle_game_key(pygame.K_SPACE)
    # envia para o mais próximo; recusas (alcance/cooldown) chegam do servidor
    assert kills == [2]


# ---------------------------------------------------------------------------
# Ejeção privada e transições dirigidas por relógio
# ---------------------------------------------------------------------------


def _handle_drain(app: App, *messages: object) -> None:
    """Simula um drain de rede contendo as mensagens dadas, em ordem."""
    for message in messages:
        app._handle_message(message)  # type: ignore[arg-type]


def test_ejected_meeting_ended_same_drain_shows_ejection(app: App) -> None:
    from codecon_amoung_us.game.model import Role
    from codecon_amoung_us.protocol import Ejected, MeetingEnded

    app.screen_name = Screen.VOTING
    _handle_drain(
        app,
        Ejected(player_id=1, role=Role.CREW),
        MeetingEnded(meeting_id=1),
    )
    assert app.screen_name == "ejected"
    assert app.private_ejection is not None
    assert app.private_ejection.player_id == 1


def test_ejected_then_game_over_after_minimum_duration(app: App) -> None:
    from codecon_amoung_us.game.model import Role, Team
    from codecon_amoung_us.protocol import Ejected, GameOver, MeetingEnded

    app._ejected_min_duration = 2.5
    app.screen_name = Screen.VOTING
    _handle_drain(
        app,
        Ejected(player_id=1, role=Role.CREW),
        MeetingEnded(meeting_id=1),
        GameOver(winner=Team.CREW, players=[], roles={}),
    )
    # a tela de ejeção tem prioridade mesmo com GameOver no mesmo drain
    assert app.screen_name == "ejected"
    assert app.pending_game_over is not None
    # antes da duração mínima, nada muda
    app._update_transitions(now=app._ejection_started_at + 1.0)
    assert app.screen_name == "ejected"
    # após a duração mínima, GameOver
    app._update_transitions(now=app._ejection_started_at + 3.0)
    assert app.screen_name == "gameover"


def test_ejected_without_game_over_returns_to_game(app: App) -> None:
    from codecon_amoung_us.game.model import Role
    from codecon_amoung_us.protocol import Ejected, MeetingEnded

    app.screen_name = Screen.VOTING
    _handle_drain(app, Ejected(player_id=1, role=Role.CREW), MeetingEnded(meeting_id=1))
    assert app.screen_name == "ejected"
    app._update_transitions(now=app._ejection_started_at + 3.0)
    assert app.screen_name == "meeting_ended"
    app._update_transitions(now=app._meeting_ended_at + 2.0)
    assert app.screen_name == "game"


def test_non_ejected_sees_generic_transition_then_game(app: App) -> None:
    from codecon_amoung_us.protocol import MeetingEnded

    app.screen_name = Screen.VOTING
    _handle_drain(app, MeetingEnded(meeting_id=1))
    assert app.screen_name == "meeting_ended"
    app._update_transitions(now=app._meeting_ended_at + 2.0)
    assert app.screen_name == "game"


def test_non_ejected_meeting_ended_game_over_same_drain(app: App) -> None:
    from codecon_amoung_us.game.model import Team
    from codecon_amoung_us.protocol import GameOver, MeetingEnded

    app.screen_name = Screen.VOTING
    _handle_drain(app, MeetingEnded(meeting_id=1), GameOver(winner=Team.CREW, players=[], roles={}))
    assert app.screen_name == "meeting_ended"
    assert app.pending_game_over is not None
    app._update_transitions(now=app._meeting_ended_at + 2.0)
    assert app.screen_name == "gameover"


# ---------------------------------------------------------------------------
# Votação: seleção, confirmação e estados (sem voto otimista)
# ---------------------------------------------------------------------------


def _meeting() -> MeetingStarted:
    return MeetingStarted(
        meeting_id=1,
        reason=MeetingReason.KILL_REPORTED,
        voters=[0, 1, 2],
        vote_timeout_seconds=30.0,
    )


def test_vote_selects_card_and_casts(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    app.meeting = _meeting()
    app.my_id = 0
    sent: list[tuple[int, int | None]] = []
    client = GameClient()
    monkeypatch.setattr(client, "vote", lambda mid, target: sent.append((mid, target)))
    app.client = client
    # seleção via clique no card (posição do primeiro card do painel)
    app.screen_name = Screen.VOTING
    events = [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(400, 300))]
    app._render_voting(events)
    assert app.vote_ui_state.value == "selecting"
    assert app.selected_vote_target is not None
    # votar
    app._cast_vote(app.selected_vote_target)
    assert app.vote_ui_state.value == "submitting"
    assert sent == [(1, app.selected_vote_target)]


def test_vote_confirmed_only_after_action_accepted(app: App) -> None:
    app.meeting = _meeting()
    app.vote_ui_state = VoteUiState.SUBMITTING
    # antes da confirmação do servidor, não aparece SUBMITTED
    assert app.vote_ui_state.value == "submitting"
    app._handle_message(ActionAccepted(action=ActionKind.VOTE))
    assert app.vote_ui_state.value == "submitted"


def test_vote_denied_returns_to_selecting_with_toast(app: App) -> None:
    app.meeting = _meeting()
    app.vote_ui_state = VoteUiState.SUBMITTING
    app.screen_name = Screen.VOTING
    app._handle_message(
        ActionDenied(
            action=ActionKind.VOTE,
            code=DenialCode.ALREADY_VOTED,
            reason="voto não aceito",
        )
    )
    assert app.vote_ui_state == VoteUiState.SELECTING
    assert [t.text for t in app.toasts] == ["Voto já registrado"]


def test_no_double_vote_after_submitted(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    app.meeting = _meeting()
    app.my_id = 0
    app.vote_ui_state = VoteUiState.SUBMITTED
    app.selected_vote_target = 1
    sent: list[tuple[int, int | None]] = []
    client = GameClient()
    monkeypatch.setattr(client, "vote", lambda mid, target: sent.append((mid, target)))
    app.client = client
    app._cast_vote(1)
    app._cast_vote(2)
    assert sent == []  # nenhum reenvio após SUBMITTED
    assert app.vote_ui_state == VoteUiState.SUBMITTED


def test_vote_requires_selecting_state(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    app.meeting = _meeting()
    app.my_id = 0
    app.vote_ui_state = VoteUiState.SUBMITTING
    sent: list[tuple[int, int | None]] = []
    client = GameClient()
    monkeypatch.setattr(client, "vote", lambda mid, target: sent.append((mid, target)))
    app.client = client
    app._cast_vote(1)
    assert sent == []  # em SUBMITTING não envia de novo


# ------------------------------------------------- cancelamento de conexão


def test_cancel_connect_host_releases_port(app: App) -> None:
    """Cancel ativo antes do connect: worker para o servidor e não publica."""
    attempt_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
    cancel = threading.Event()
    cancel.set()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app._connect_worker("host", "127.0.0.1", port, None, True, attempt_queue, cancel)
    assert attempt_queue.empty()
    # porta liberada: um novo servidor sobe na mesma porta sem EADDRINUSE
    server = GameServer(host="127.0.0.1", port=port)
    server.start()
    server.stop()


def test_cancel_after_connect_closes_client_and_publishes_nothing(
    app: App, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sucesso tardio com cancel ativo: fecha o cliente e não publica."""
    closed: list[bool] = []
    cancel = threading.Event()

    class StubClient:
        def connect_auto(
            self,
            host: str,
            *,
            tcp_port: int | None,
            ws_port: int | None,
            nickname: str,
            timeout: float = 5.0,
        ) -> None:
            cancel.set()

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr("codecon_amoung_us.ui.app.GameClient", StubClient)
    attempt_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
    app._connect_worker("nick", "127.0.0.1", 1, None, False, attempt_queue, cancel)
    assert closed == [True]
    assert attempt_queue.empty()


def test_poll_ignores_result_after_cancel(app: App) -> None:
    """Resultado que chega após o cancel não altera o estado (fila órfã)."""
    app.connection_state = ConnectionState.CONNECTING
    app._connection_queue = queue.SimpleQueue()
    app._connection_cancel = threading.Event()
    app._cancel_connecting()
    app._connection_queue.put(ConnectionFailure(message="tarde"))
    app._poll_connection()
    assert app.connection_state is ConnectionState.IDLE


# ---------------------------------------------------------------------------
# Foco de teclado persistente nas telas customizadas
# ---------------------------------------------------------------------------


def _enter_lobby_screen(app: App, *, is_host: bool = True) -> None:
    app.is_host = is_host
    app.lobby_players = [LobbyPlayer(player_id=0, nickname="host")]
    app.my_id = 0
    app.host_id = 0
    app.screen_name = Screen.LOBBY


def test_lobby_focus_persists_between_frames(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """O índice de foco do lobby sobrevive à renderização (não é recriado)."""
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    _enter_lobby_screen(app)
    app._render_lobby([])
    controls = app._lobby_ui_state
    assert controls is not None
    buttons, focus = controls
    assert focus.index == 0
    tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
    app._render_lobby([tab])
    assert focus.index == 1  # o evento move o índice já neste frame
    # frame seguinte sem eventos: o anel é aplicado ao segundo controle
    app._render_lobby([])
    assert focus.index == 1
    assert buttons[1].focused is True
    assert buttons[0].focused is False
    # e persiste nos frames subsequentes
    app._render_lobby([])
    assert focus.index == 1
    assert buttons[1].focused is True


def test_lobby_focus_skips_disabled_start_for_non_host(app: App) -> None:
    """Sem host, Iniciar fica disabled e o foco inicial cai em Sair."""
    _enter_lobby_screen(app, is_host=False)
    app._render_lobby([])
    controls = app._lobby_ui_state
    assert controls is not None
    buttons, _focus = controls
    assert buttons[0].state is ButtonState.DISABLED
    assert buttons[0].focused is False
    assert buttons[1].focused is True


def test_enter_activates_persisted_focus(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enter ativa o controle focado em um frame anterior (Sair -> menu)."""
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    _enter_lobby_screen(app)
    app._render_lobby([])
    tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
    app._render_lobby([tab])
    app._render_lobby([enter])
    assert app.screen_name == "main"


def test_custom_screens_have_keyboard_navigation(app: App, monkeypatch: pytest.MonkeyPatch) -> None:
    """Tab/Enter/ESC têm comportamento definido nas telas customizadas."""
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
    escape = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)

    # connecting: Cancelar focado; Enter cancela a tentativa
    app.screen_name = Screen.CONNECTING
    app._render_connecting([])
    buttons, _focus = app._single_ui_states["connecting"]
    assert buttons[0].focused is True
    app._render_connecting([enter])
    assert app.screen_name == "main"

    # game over: VOLTAR AO MENU focado; ESC volta ao menu (por evento)
    app.game_over = GameOver(
        winner=Team.CREW,
        players=[PlayerInfo(player_id=0, nickname="a")],
        roles={0: Role.CREW},
    )
    app.screen_name = Screen.GAME_OVER
    app._render_gameover([])
    buttons, _focus = app._single_ui_states["gameover"]
    assert buttons[0].focused is True
    app._render_gameover([escape])
    assert app.screen_name == "main"

    # error: Voltar focado; Enter e ESC voltam ao menu
    app._show_error("falha de teste")
    app._render_error([])
    buttons, _focus = app._single_ui_states["error"]
    assert buttons[0].focused is True
    app._render_error([enter])
    assert app.screen_name == "main"
    app._show_error("outra falha")
    app._render_error([escape])
    assert app.screen_name == "main"


# ---------------------------------------------------------------------------
# Configurações (reduced motion)
# ---------------------------------------------------------------------------


def test_reduced_motion_toggle_updates_renderer(app: App) -> None:
    """O toggle de Configurações aplica no renderer imediatamente (runtime)."""
    app._on_reduced_motion_change(("SIM", True), True)
    assert app.ui_settings.reduced_motion is True
    assert app.renderer.reduced_motion is True
    app._on_reduced_motion_change(("NÃO", False), False)
    assert app.ui_settings.reduced_motion is False
    assert app.renderer.reduced_motion is False


def test_reduced_motion_env_var_is_initial_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A env var define o valor inicial (a tela passa a ser o controle)."""
    monkeypatch.setenv("CODECON_AMONG_US_REDUCED_MOTION", "1")
    env_app = App()
    try:
        assert env_app.ui_settings.reduced_motion is True
        assert env_app.renderer.reduced_motion is True
    finally:
        env_app._shutdown_connection()


def test_settings_screen_opens_from_main_menu(app: App) -> None:
    app._open_settings()
    assert app.screen_name == "settings"
    assert app._current_menu is app.menu_settings
    app._render([])  # branch de menu renderiza sem exceção
    app._back_to_main()
    assert app.screen_name == "main"
    assert app._current_menu is app.menu_main


# ------------------------------------------------- descoberta LAN (UI)


def test_join_discovered_connects_via_websocket(app: App) -> None:
    """Selecionar uma partida descoberta conecta sem digitar IP, via WS."""
    import time as _time

    from codecon_amoung_us.config import GameConfig
    from codecon_amoung_us.net.discovery import DiscoveredGame

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        ws_port = probe.getsockname()[1]
    server = GameServer(host="127.0.0.1", port=0, config=GameConfig(ws_port=ws_port))
    server.start()
    try:
        game = DiscoveredGame(
            ip="127.0.0.1",
            host_name="dono",
            players=1,
            max_players=10,
            tcp_port=server.port,
            ws_port=ws_port,
        )
        app._join_discovered("player", game)
        deadline = _time.monotonic() + 8.0
        while _time.monotonic() < deadline and app.connection_state is ConnectionState.CONNECTING:
            app._poll_connection()
            _time.sleep(0.01)
        assert app.connection_state is ConnectionState.CONNECTED
        assert app.client is not None
        assert app.client.transport == "ws"
        assert app.screen_name == "lobby"
    finally:
        app._shutdown_connection()
        server.stop()


def test_create_game_starts_ws_and_shows_network_info(app: App) -> None:
    """Host embutido sobe TCP+WS (porta adjacente) e o lobby mostra a rede."""
    app.nickname_input.set_value("dono")
    port = _create_game_with_free_port(app)
    try:
        assert app.connection_state is ConnectionState.CONNECTED
        assert app.is_host
        assert app.server is not None
        assert app.server.ws_port == port + 1
        app._refresh_lobby()
        assert f":{app.server.port}" in app.lobby_net_label.get_title()
    finally:
        app._shutdown_connection()
