"""Testes dos view models puros de interação (sem pygame).

Cobre ``derive_interaction_context`` (E), ``derive_report_target`` (R) e
``derive_kill_action`` (Espaço): prioridades, raios, cooldown e estados
morto/indisponível.
"""

from __future__ import annotations

from codecon_amoung_us.game.model import Role
from codecon_amoung_us.map.model import GameMap, SpawnPoint, TaskPoint
from codecon_amoung_us.protocol import (
    ActionKind,
    SnapshotBody,
    SnapshotPlayer,
    TaskInfo,
    TaskState,
    WorldSnapshot,
)
from codecon_amoung_us.ui.viewmodel import (
    GameHudView,
    InteractionContext,
    TaskMarkerState,
    derive_game_hud,
    derive_interaction_context,
    derive_kill_action,
    derive_report_target,
    derive_task_markers,
    gameover_layout,
    voting_layout,
    voting_page_count,
)

# mapa de teste: 10x8 tiles de 64px, duas tarefas e botão de emergência
_MAP = GameMap(
    name="test",
    width=10,
    height=8,
    tile_width=64,
    tile_height=64,
    walls=[],
    floor_rects=[],
    decorative_rects=[],
    spawn_points=[SpawnPoint(spawn_id=0, x=100.0, y=100.0)],
    task_points=[
        TaskPoint(task_id=1, task_type="wires", x=300.0, y=300.0, interaction_radius=20.0),
        TaskPoint(task_id=2, task_type="swipe", x=500.0, y=300.0, interaction_radius=20.0),
    ],
    emergency_meeting=(600.0, 400.0),
    emergency_meeting_radius=30.0,
)


def _player(x: float, y: float, *, player_id: int = 0, alive: bool = True) -> SnapshotPlayer:
    return SnapshotPlayer(player_id=player_id, x=x, y=y, alive=alive)


def _tasks(*tasks: tuple[int, bool]) -> TaskState:
    return TaskState(
        tasks=[TaskInfo(task_id=tid, task_type="wires", done=done) for tid, done in tasks]
    )


def _snapshot(*players: SnapshotPlayer, bodies: list[SnapshotBody] | None = None) -> WorldSnapshot:
    return WorldSnapshot(tick=1, players=list(players), bodies=bodies or [])


def test_crew_far_from_everything_has_no_context() -> None:
    me = _player(100.0, 100.0)
    ctx = _derive(me)
    assert ctx is None


def test_crew_near_assigned_task_gets_task_context() -> None:
    me = _player(310.0, 300.0)  # dentro do raio da tarefa 1
    ctx = _derive(me, task_ids=[1])
    assert ctx is not None
    assert ctx.kind is ActionKind.TASK
    assert ctx.target_id == 1


def test_task_not_assigned_is_not_interactive() -> None:
    me = _player(310.0, 300.0)
    ctx = _derive(me, task_ids=[])
    assert ctx is None  # tarefa 1 existe, mas não foi atribuída


def test_task_already_done_is_not_interactive() -> None:
    me = _player(310.0, 300.0)
    ctx = _derive(me, task_ids=[1], done={1})
    assert ctx is None


def test_crew_near_emergency_button_gets_emergency() -> None:
    me = _player(610.0, 400.0)
    ctx = _derive(me, task_ids=[])
    assert ctx is not None
    assert ctx.kind is ActionKind.EMERGENCY


def test_overlap_resolves_to_nearest() -> None:
    # tarefa 1 (300,300, raio 20) e botão (600,400): perto da tarefa
    me = _player(310.0, 300.0)
    ctx = _derive(me, task_ids=[1])
    assert ctx is not None and ctx.kind is ActionKind.TASK
    # perto do botão
    me2 = _player(605.0, 400.0)
    ctx2 = _derive(me2, task_ids=[1])
    assert ctx2 is not None and ctx2.kind is ActionKind.EMERGENCY


def test_dead_player_has_no_context() -> None:
    me = _player(310.0, 300.0, alive=False)
    ctx = _derive(me, task_ids=[1])
    assert ctx is None


def test_crew_near_body_gets_report_target() -> None:
    me = _player(100.0, 100.0)
    body = SnapshotBody(body_id=3, player_id=2, x=110.0, y=100.0)
    snapshot = _snapshot(me, bodies=[body])
    assert derive_report_target(me=me, snapshot=snapshot) == 3


def test_report_requires_proximity() -> None:
    me = _player(100.0, 100.0)
    body = SnapshotBody(body_id=3, player_id=2, x=400.0, y=400.0)
    snapshot = _snapshot(me, bodies=[body])
    assert derive_report_target(me=me, snapshot=snapshot) is None


def test_dead_crew_cannot_report() -> None:
    me = _player(100.0, 100.0, alive=False)
    body = SnapshotBody(body_id=3, player_id=2, x=110.0, y=100.0)
    snapshot = _snapshot(me, bodies=[body])
    assert derive_report_target(me=me, snapshot=snapshot) is None


def test_impostor_near_target_gets_kill_ready() -> None:
    me = _player(100.0, 100.0)
    target = _player(115.0, 100.0, player_id=1)
    snapshot = _snapshot(me, target)
    ctx = derive_kill_action(
        me=me, role=Role.IMPOSTOR, snapshot=snapshot, kill_cooldown_until=None, now=100.0
    )
    assert ctx is not None
    assert ctx.kind is ActionKind.KILL
    assert ctx.target_id == 1
    assert ctx.cooldown_remaining == 0.0


def test_impostor_kill_with_cooldown_reports_remaining() -> None:
    me = _player(100.0, 100.0)
    target = _player(115.0, 100.0, player_id=1)
    snapshot = _snapshot(me, target)
    ctx = derive_kill_action(
        me=me, role=Role.IMPOSTOR, snapshot=snapshot, kill_cooldown_until=107.0, now=100.0
    )
    assert ctx is not None
    assert ctx.cooldown_remaining == 7.0


def test_impostor_out_of_range_gets_no_kill() -> None:
    me = _player(100.0, 100.0)
    target = _player(500.0, 500.0, player_id=1)
    snapshot = _snapshot(me, target)
    ctx = derive_kill_action(
        me=me, role=Role.IMPOSTOR, snapshot=snapshot, kill_cooldown_until=None, now=100.0
    )
    assert ctx is None


def test_crew_has_no_kill_action() -> None:
    me = _player(100.0, 100.0)
    target = _player(115.0, 100.0, player_id=1)
    snapshot = _snapshot(me, target)
    ctx = derive_kill_action(
        me=me, role=Role.CREW, snapshot=snapshot, kill_cooldown_until=None, now=100.0
    )
    assert ctx is None


def test_dead_impostor_has_no_kill_action() -> None:
    me = _player(100.0, 100.0, alive=False)
    target = _player(115.0, 100.0, player_id=1)
    snapshot = _snapshot(me, target)
    ctx = derive_kill_action(
        me=me, role=Role.IMPOSTOR, snapshot=snapshot, kill_cooldown_until=None, now=100.0
    )
    assert ctx is None


def _derive(
    me: SnapshotPlayer,
    *,
    task_ids: list[int] | None = None,
    done: set[int] | None = None,
) -> InteractionContext | None:
    state = _tasks(*[(tid, tid in (done or set())) for tid in (task_ids or [])])
    return derive_interaction_context(
        me=me,
        game_map=_MAP,
        my_task_ids=task_ids or [],
        tasks_state=state,
    )


# ---------------------------------------------------------------------------
# Marcadores de tarefa e HUD
# ---------------------------------------------------------------------------


def _hud(
    *,
    role: Role | None = Role.CREW,
    me: SnapshotPlayer | None = None,
    task_ids: list[int] | None = None,
    done: set[int] | None = None,
    snapshot: WorldSnapshot | None = None,
    kill_cooldown_until: float | None = None,
    now: float = 0.0,
) -> GameHudView:
    return derive_game_hud(
        role=role,
        me=me,
        game_map=_MAP,
        my_task_ids=task_ids or [],
        tasks_state=_tasks(*[(tid, tid in (done or set())) for tid in (task_ids or [])]),
        snapshot=snapshot,
        kill_cooldown_until=kill_cooldown_until,
        now=now,
    )


def test_task_markers_states() -> None:
    me = _player(310.0, 300.0)
    markers = derive_task_markers(
        game_map=_MAP, my_task_ids=[1], tasks_state=_tasks((1, False)), me=me
    )
    by_id = {m.task_id: m for m in markers}
    assert by_id[1].state is TaskMarkerState.INTERACTABLE  # dentro do raio
    assert by_id[2].state is TaskMarkerState.UNASSIGNED  # não atribuída
    # concluída
    markers_done = derive_task_markers(
        game_map=_MAP, my_task_ids=[1], tasks_state=_tasks((1, True)), me=me
    )
    assert next(m for m in markers_done if m.task_id == 1).state is TaskMarkerState.DONE
    # distante
    far = _player(100.0, 100.0)
    markers_far = derive_task_markers(
        game_map=_MAP, my_task_ids=[1], tasks_state=_tasks((1, False)), me=far
    )
    assert next(m for m in markers_far if m.task_id == 1).state is TaskMarkerState.ASSIGNED


def test_hud_crew_far_from_everything_no_primary_action() -> None:
    me = _player(100.0, 100.0)
    hud = _hud(me=me, snapshot=_snapshot(me))
    assert hud.primary_action is None
    assert hud.role_label == "TRIPULANTE"


def test_hud_crew_near_task_shows_interact() -> None:
    me = _player(310.0, 300.0)
    hud = _hud(me=me, task_ids=[1], snapshot=_snapshot(me))
    assert hud.primary_action is not None
    assert hud.primary_action.keycap == "E"
    assert hud.primary_action.label == "INTERAGIR"


def test_hud_crew_near_body_shows_report() -> None:
    me = _player(100.0, 100.0)
    body = SnapshotBody(body_id=3, player_id=2, x=110.0, y=100.0)
    hud = _hud(me=me, snapshot=_snapshot(me, bodies=[body]))
    assert hud.primary_action is not None
    assert hud.primary_action.keycap == "R"
    assert hud.primary_action.label == "REPORTAR"


def test_hud_impostor_kill_ready() -> None:
    me = _player(100.0, 100.0)
    target = _player(115.0, 100.0, player_id=1)
    hud = _hud(
        role=Role.IMPOSTOR,
        me=me,
        snapshot=_snapshot(me, target),
        kill_cooldown_until=None,
        now=100.0,
    )
    assert hud.primary_action is not None
    assert hud.primary_action.keycap == "SPACE"
    assert hud.primary_action.label == "PRONTO"
    assert hud.primary_action.countdown == 0.0


def test_hud_impostor_kill_in_cooldown() -> None:
    me = _player(100.0, 100.0)
    target = _player(115.0, 100.0, player_id=1)
    hud = _hud(
        role=Role.IMPOSTOR,
        me=me,
        snapshot=_snapshot(me, target),
        kill_cooldown_until=107.0,
        now=100.0,
    )
    assert hud.primary_action is not None
    assert hud.primary_action.countdown == 7.0
    assert hud.kill_cooldown_remaining == 7.0


def test_hud_spectator_has_no_actions() -> None:
    me = _player(100.0, 100.0, alive=False)
    target = _player(115.0, 100.0, player_id=1)
    hud = _hud(role=Role.CREW, me=me, snapshot=_snapshot(me, target))
    assert hud.spectator
    assert hud.primary_action is None
    assert hud.role_label == "ESPECTADOR"


# ------------------------------------------------------- layouts de telas

WINDOW = (1280, 768)


def _rects_within(
    rects: tuple[tuple[int, int, int, int], ...], bounds: tuple[int, int, int, int]
) -> bool:
    bx, by, bw, bh = bounds
    return all(
        bx <= x and by <= y and x + w <= bx + bw and y + h <= by + bh for x, y, w, h in rects
    )


def test_voting_layout_footer_fixo_para_qualquer_n() -> None:
    """Rodapé (PULAR/VOTAR) permanece dentro do painel para 4, 7, 8 e 10 votantes."""
    for n_voters in (4, 7, 8, 10):
        for page in range(voting_page_count(n_voters)):
            layout = voting_layout(n_voters, page, WINDOW)
            assert _rects_within((layout.skip_button, layout.vote_button), layout.panel)
            assert _rects_within((layout.skip_button, layout.vote_button), (0, 0, *WINDOW))
            assert _rects_within(layout.cards, layout.panel)


def test_voting_layout_paginacao() -> None:
    assert voting_page_count(4) == 1
    assert voting_page_count(5) == 1
    assert voting_page_count(6) == 2
    assert voting_page_count(10) == 2
    assert len(voting_layout(10, 0, WINDOW).cards) == 5
    assert len(voting_layout(10, 1, WINDOW).cards) == 5
    assert len(voting_layout(7, 1, WINDOW).cards) == 2
    # página fora da faixa é clampada, nunca gera geometria inválida
    clamped = voting_layout(6, 99, WINDOW)
    assert clamped.page == 1
    assert len(clamped.cards) == 1


def test_voting_layout_sem_sobreposicao_cards_rodape() -> None:
    for n_voters in (5, 10):
        for page in range(voting_page_count(n_voters)):
            layout = voting_layout(n_voters, page, WINDOW)
            for card in layout.cards:
                assert card[1] + card[3] <= layout.skip_button[1]


def test_gameover_layout_ate_5_jogadores_coluna_unica() -> None:
    layout = gameover_layout(5, WINDOW)
    assert len(layout.cards) == 5
    assert len({card[0] for card in layout.cards}) == 1
    assert _rects_within(layout.cards, layout.panel)
    assert _rects_within((layout.back_button,), (0, 0, *WINDOW))


def test_gameover_layout_8_e_10_jogadores_duas_colunas_dentro_da_janela() -> None:
    for n_players in (8, 10):
        layout = gameover_layout(n_players, WINDOW)
        assert len(layout.cards) == n_players
        assert len({card[0] for card in layout.cards}) == 2
        assert _rects_within(layout.cards, layout.panel)
        assert _rects_within(layout.cards, (0, 0, *WINDOW))
        assert _rects_within((layout.back_button,), (0, 0, *WINDOW))
        assert layout.hint_center[1] < WINDOW[1]
