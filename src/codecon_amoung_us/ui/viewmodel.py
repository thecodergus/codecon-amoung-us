"""View models puros (sem pygame) para a UI.

Transformam estado do jogo + estado local em modelos de apresentação e em
contextos de interação. Nenhuma regra de domínio mora no renderer: o App
executa apenas a ação devolvida pelas funções daqui.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ..config import KILL_RADIUS, REPORT_RADIUS
from ..game.model import Role
from ..map.model import GameMap
from ..protocol import ActionKind, SnapshotPlayer, TaskState, WorldSnapshot
from .theme import TOKENS

__all__ = [
    "InteractionContext",
    "derive_interaction_context",
    "derive_report_target",
    "derive_kill_action",
    "TaskMarkerState",
    "TaskMarkerView",
    "derive_task_markers",
    "HudAction",
    "GameHudView",
    "derive_game_hud",
    "VoteUiState",
    "VotingLayout",
    "voting_page_count",
    "voting_layout",
    "GameOverLayout",
    "gameover_layout",
]


@dataclass(frozen=True)
class InteractionContext:
    """Ação contextual disponível para o jogador agora.

    ``cooldown_remaining`` (segundos) só é preenchido para KILL; 0 = pronto.
    """

    kind: ActionKind
    target_id: int | None = None
    cooldown_remaining: float | None = None


def derive_interaction_context(
    *,
    me: SnapshotPlayer,
    game_map: GameMap,
    my_task_ids: Sequence[int],
    tasks_state: TaskState | None,
    kill_cooldown_until: float | None,
    snapshot: WorldSnapshot | None,
    now: float,
) -> InteractionContext | None:
    """Ação da tecla de interação (E): tarefa ou reunião de emergência.

    - tarefa atribuída e incompleta dentro do raio de interação → TASK;
    - botão de emergência dentro do raio do mapa → EMERGENCY;
    - sobreposição → elemento mais próximo; desempate determinístico
      (TASK antes de EMERGENCY em distâncias iguais);
    - jogador morto ou nenhum contexto → None.
    """
    if me is None or not me.alive:
        return None
    done_ids = (
        {t.task_id for t in tasks_state.tasks if t.done} if tasks_state is not None else set()
    )
    candidates: list[tuple[float, ActionKind, int | None]] = []
    for point in game_map.task_points:
        if point.task_id not in my_task_ids or point.task_id in done_ids:
            continue
        distance = math.hypot(point.x - me.x, point.y - me.y)
        if distance <= point.interaction_radius:
            candidates.append((distance, ActionKind.TASK, point.task_id))
    if game_map.emergency_meeting is not None:
        ex, ey = game_map.emergency_meeting
        distance = math.hypot(ex - me.x, ey - me.y)
        if distance <= game_map.emergency_meeting_radius:
            candidates.append((distance, ActionKind.EMERGENCY, None))
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], 0 if c[1] is ActionKind.TASK else 1))
    _distance, kind, target_id = candidates[0]
    return InteractionContext(kind=kind, target_id=target_id)


def derive_report_target(*, me: SnapshotPlayer, snapshot: WorldSnapshot | None) -> int | None:
    """Corpo mais próximo dentro do raio de report (R). None se inacessível."""
    if me is None or not me.alive or snapshot is None:
        return None
    bodies = [b for b in snapshot.bodies if math.hypot(b.x - me.x, b.y - me.y) <= REPORT_RADIUS]
    if not bodies:
        return None
    return min(bodies, key=lambda b: math.hypot(b.x - me.x, b.y - me.y)).body_id


def derive_kill_action(
    *,
    me: SnapshotPlayer,
    role: Role | None,
    snapshot: WorldSnapshot | None,
    kill_cooldown_until: float | None,
    now: float,
    kill_radius: float = KILL_RADIUS,
) -> InteractionContext | None:
    """Ação de eliminação (Espaço) para o impostor, com cooldown restante.

    Retorna None quando não há alvo vivo dentro do raio; caso contrário,
    o contexto carrega o alvo e os segundos restantes de cooldown
    (0 = pronto).
    """
    if me is None or not me.alive or role is not Role.IMPOSTOR or snapshot is None:
        return None
    alive = [p for p in snapshot.players if p.alive and p.player_id != me.player_id]
    if not alive:
        return None
    nearest = min(alive, key=lambda p: math.hypot(p.x - me.x, p.y - me.y))
    if math.hypot(nearest.x - me.x, nearest.y - me.y) > kill_radius:
        return None
    remaining = 0.0
    if kill_cooldown_until is not None:
        remaining = max(0.0, kill_cooldown_until - now)
    return InteractionContext(
        kind=ActionKind.KILL,
        target_id=nearest.player_id,
        cooldown_remaining=remaining,
    )


class TaskMarkerState(StrEnum):
    """Estado visual de uma tarefa no mundo."""

    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    NEAR = "near"
    INTERACTABLE = "interactable"
    DONE = "done"


class VoteUiState(StrEnum):
    """Estado da votação local (fluxo seleção -> envio -> registrado)."""

    SELECTING = "selecting"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"


@dataclass(frozen=True)
class TaskMarkerView:
    """Marcador de tarefa já transformado para apresentação."""

    task_id: int
    x: float
    y: float
    state: TaskMarkerState
    pulse: bool = False


def derive_task_markers(
    *,
    game_map: GameMap,
    my_task_ids: Sequence[int],
    tasks_state: TaskState | None,
    me: SnapshotPlayer | None,
) -> list[TaskMarkerView]:
    """Estados contextuais das tarefas no mundo.

    Não atribuída → discreta; atribuída distante → estática; próxima →
    highlight; interagível → pulse curto; concluída → check/desaturada.
    """
    done_ids = (
        {t.task_id for t in tasks_state.tasks if t.done} if tasks_state is not None else set()
    )
    markers: list[TaskMarkerView] = []
    for point in game_map.task_points:
        if point.task_id not in my_task_ids:
            markers.append(
                TaskMarkerView(point.task_id, point.x, point.y, TaskMarkerState.UNASSIGNED)
            )
            continue
        if point.task_id in done_ids:
            markers.append(TaskMarkerView(point.task_id, point.x, point.y, TaskMarkerState.DONE))
            continue
        if me is not None and me.alive:
            distance = math.hypot(point.x - me.x, point.y - me.y)
            if distance <= point.interaction_radius:
                markers.append(
                    TaskMarkerView(
                        point.task_id, point.x, point.y, TaskMarkerState.INTERACTABLE, pulse=True
                    )
                )
                continue
            if distance <= point.interaction_radius * 2.5:
                markers.append(
                    TaskMarkerView(point.task_id, point.x, point.y, TaskMarkerState.NEAR)
                )
                continue
        markers.append(TaskMarkerView(point.task_id, point.x, point.y, TaskMarkerState.ASSIGNED))
    return markers


@dataclass(frozen=True)
class HudAction:
    """Ação contextual exibida no ActionPrompt."""

    keycap: str
    label: str
    countdown: float | None = None


@dataclass(frozen=True)
class GameHudView:
    """Modelo de apresentação do HUD de gameplay (imutável)."""

    role_label: str
    role_color: tuple[int, int, int]
    tasks_done: int
    tasks_total: int
    alive: int
    total: int
    spectator: bool
    primary_action: HudAction | None
    kill_cooldown_remaining: float | None


def _nearby_report_action(me: SnapshotPlayer, snapshot: WorldSnapshot | None) -> HudAction | None:
    body_id = derive_report_target(me=me, snapshot=snapshot)
    return HudAction("R", "REPORTAR") if body_id is not None else None


def derive_game_hud(
    *,
    role: Role | None,
    me: SnapshotPlayer | None,
    game_map: GameMap,
    my_task_ids: Sequence[int],
    tasks_state: TaskState | None,
    snapshot: WorldSnapshot | None,
    kill_cooldown_until: float | None,
    now: float,
) -> GameHudView:
    """HUD completo derivado do estado (crew/impostor/espectador)."""
    tasks_done = sum(1 for t in tasks_state.tasks if t.done) if tasks_state is not None else 0
    tasks_total = len(my_task_ids)
    alive = sum(1 for p in snapshot.players if p.alive) if snapshot is not None else 0
    total = len(snapshot.players) if snapshot is not None else 0
    spectator = me is None or not me.alive or role is None

    if spectator:
        role_label, role_color = "ESPECTADOR", TOKENS.text_secondary
    elif role is Role.IMPOSTOR:
        role_label, role_color = "IMPOSTOR", TOKENS.status_danger
    else:
        role_label, role_color = "TRIPULANTE", TOKENS.status_info

    primary_action: HudAction | None = None
    if not spectator and me is not None and snapshot is not None:
        if role is Role.IMPOSTOR:
            kill = derive_kill_action(
                me=me,
                role=role,
                snapshot=snapshot,
                kill_cooldown_until=kill_cooldown_until,
                now=now,
            )
            if kill is not None:
                label = "PRONTO" if kill.cooldown_remaining == 0.0 else "ELIMINAR"
                primary_action = HudAction("SPACE", label, countdown=kill.cooldown_remaining)
            else:
                primary_action = _nearby_report_action(me, snapshot) or _derive_interact(
                    me, game_map, my_task_ids, tasks_state, kill_cooldown_until, snapshot, now
                )
        else:
            primary_action = _nearby_report_action(me, snapshot) or _derive_interact(
                me, game_map, my_task_ids, tasks_state, kill_cooldown_until, snapshot, now
            )

    kill_cooldown_remaining = None
    if kill_cooldown_until is not None:
        kill_cooldown_remaining = max(0.0, kill_cooldown_until - now)

    return GameHudView(
        role_label=role_label,
        role_color=role_color,
        tasks_done=tasks_done,
        tasks_total=tasks_total,
        alive=alive,
        total=total,
        spectator=spectator,
        primary_action=primary_action,
        kill_cooldown_remaining=kill_cooldown_remaining,
    )


def _derive_interact(
    me: SnapshotPlayer,
    game_map: GameMap,
    my_task_ids: Sequence[int],
    tasks_state: TaskState | None,
    kill_cooldown_until: float | None,
    snapshot: WorldSnapshot | None,
    now: float,
) -> HudAction | None:
    """Ação da tecla E como prompt (tarefa ou reunião)."""
    context = derive_interaction_context(
        me=me,
        game_map=game_map,
        my_task_ids=my_task_ids,
        tasks_state=tasks_state,
        kill_cooldown_until=kill_cooldown_until,
        snapshot=snapshot,
        now=now,
    )
    if context is None:
        return None
    if context.kind is ActionKind.TASK:
        return HudAction("E", "INTERAGIR")
    if context.kind is ActionKind.EMERGENCY:
        return HudAction("E", "REUNIÃO")
    return None


# ------------------------------------------------------------------ telas

# Geometria das telas de votação e de fim de jogo, em coordenadas lógicas e
# sem dependência de pygame: funções puras, testáveis headless. O painel e o
# rodapé são fixos; a lista de jogadores é paginada/colunada para nunca
# exceder a janela lógica (o servidor aceita até 10 jogadores).

VOTING_CARDS_PER_PAGE = 5
VOTING_CARD_HEIGHT = 74
VOTING_CARD_GAP = 10

GAMEOVER_ROWS_PER_COLUMN = 5
GAMEOVER_CARD_HEIGHT = 64
GAMEOVER_CARD_GAP = 12
GAMEOVER_COLUMN_GAP = 24

RectTuple = tuple[int, int, int, int]


@dataclass(frozen=True)
class VotingLayout:
    """Geometria resolvida da tela de votação para uma página."""

    panel: RectTuple
    cards: tuple[RectTuple, ...]
    skip_button: RectTuple
    vote_button: RectTuple
    status_center: tuple[int, int]
    page_info_center: tuple[int, int]
    page: int
    page_count: int


def voting_page_count(n_voters: int) -> int:
    """Número de páginas de cards (mínimo 1)."""
    return max(1, math.ceil(max(0, n_voters) / VOTING_CARDS_PER_PAGE))


def voting_layout(n_voters: int, page: int, window: tuple[int, int] = (1280, 768)) -> VotingLayout:
    """Layout paginado da votação: cards da página + rodapé fixo no painel.

    O rodapé (PULAR/VOTAR) tem posição fixa no painel, portanto permanece
    dentro da janela lógica para qualquer ``n_voters`` suportado.
    """
    win_w, win_h = window
    panel_w, panel_h = 620, 640
    panel_x, panel_y = (win_w - panel_w) // 2, (win_h - panel_h) // 2
    page_count = voting_page_count(n_voters)
    page = min(max(0, page), page_count - 1)
    visible = min(VOTING_CARDS_PER_PAGE, max(0, n_voters - page * VOTING_CARDS_PER_PAGE))
    cards = tuple(
        (
            panel_x + 36,
            panel_y + 104 + row * (VOTING_CARD_HEIGHT + VOTING_CARD_GAP),
            panel_w - 72,
            VOTING_CARD_HEIGHT,
        )
        for row in range(visible)
    )
    footer_y = panel_y + panel_h - 64
    center_x = panel_x + panel_w // 2
    return VotingLayout(
        panel=(panel_x, panel_y, panel_w, panel_h),
        cards=cards,
        skip_button=(center_x - 210, footer_y, 200, 46),
        vote_button=(center_x + 10, footer_y, 200, 46),
        status_center=(center_x, footer_y - 28),
        page_info_center=(center_x, panel_y + 530),
        page=page,
        page_count=page_count,
    )


@dataclass(frozen=True)
class GameOverLayout:
    """Geometria resolvida da tela de fim de jogo."""

    panel: RectTuple
    cards: tuple[RectTuple, ...]
    back_button: RectTuple
    hint_center: tuple[int, int]


def gameover_layout(n_players: int, window: tuple[int, int] = (1280, 768)) -> GameOverLayout:
    """Layout da tela de fim de jogo: 1 coluna até 5 jogadores, 2 colunas acima.

    Com 2 colunas de 5 linhas cabem os 10 jogadores suportados pelo servidor
    dentro do painel (e da janela lógica).
    """
    win_w, _ = window
    panel_w, panel_h = 820, 440
    panel_x, panel_y = (win_w - panel_w) // 2, 400 - panel_h // 2
    n = max(0, n_players)
    step = GAMEOVER_CARD_HEIGHT + GAMEOVER_CARD_GAP
    if n <= GAMEOVER_ROWS_PER_COLUMN:
        col_w = panel_w - 80
        cards = tuple(
            (panel_x + 40, panel_y + 32 + row * step, col_w, GAMEOVER_CARD_HEIGHT)
            for row in range(n)
        )
    else:
        col_w = (panel_w - 80 - GAMEOVER_COLUMN_GAP) // 2
        cards = tuple(
            (
                panel_x + 40 + col * (col_w + GAMEOVER_COLUMN_GAP),
                panel_y + 32 + row * step,
                col_w,
                GAMEOVER_CARD_HEIGHT,
            )
            for idx in range(n)
            for col, row in [(idx // GAMEOVER_ROWS_PER_COLUMN, idx % GAMEOVER_ROWS_PER_COLUMN)]
        )
    return GameOverLayout(
        panel=(panel_x, panel_y, panel_w, panel_h),
        cards=cards,
        back_button=(win_w // 2 - 120, panel_y + panel_h + 24, 240, 48),
        hint_center=(win_w // 2, panel_y + panel_h + 84),
    )
