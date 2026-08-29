"""Testes das regras de gameplay (kill, tarefas, vitória, física)."""

from __future__ import annotations

from codecon_amoung_us.game.model import (
    Body,
    GameState,
    Phase,
    PlayerState,
    Role,
    Task,
    Team,
)
from codecon_amoung_us.game.physics import resolve_movement
from codecon_amoung_us.game.rules import (
    all_tasks_done,
    apply_kill,
    can_complete_task,
    can_kill,
    can_report,
    check_win,
    complete_task,
)
from codecon_amoung_us.map.model import Rect


def test_impostor_can_kill_in_range(four_player_state: GameState) -> None:
    # impostor (0) em (100,100); tripulante (1) em (110,100): distância 10 < 40
    assert can_kill(
        four_player_state, 0, 1, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_crew_cannot_kill(four_player_state: GameState) -> None:
    assert not can_kill(
        four_player_state, 1, 0, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_cannot_kill_dead_target(four_player_state: GameState) -> None:
    four_player_state.players[1].alive = False
    assert not can_kill(
        four_player_state, 0, 1, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_cannot_kill_out_of_range(four_player_state: GameState) -> None:
    # tripulante (2) em (200,100): distância 100 > 40
    assert not can_kill(
        four_player_state, 0, 2, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_cannot_kill_self(four_player_state: GameState) -> None:
    assert not can_kill(
        four_player_state, 0, 0, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_kill_cooldown_blocks_then_allows(four_player_state: GameState) -> None:
    # Aproxima o tripulante 2 do impostor para isolar o cooldown (alcance ok)
    four_player_state.players[2].x = 115.0
    # primeiro kill em t=100
    assert can_kill(
        four_player_state, 0, 1, now=100.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )
    apply_kill(four_player_state, 0, 1, now=100.0)
    # cooldown de 15s: ainda bloqueado em t=114.9, liberado em t=115.0
    assert not can_kill(
        four_player_state, 0, 2, now=114.9, kill_radius=40.0, kill_cooldown_seconds=15.0
    )
    assert can_kill(
        four_player_state, 0, 2, now=115.0, kill_radius=40.0, kill_cooldown_seconds=15.0
    )


def test_apply_kill_marks_dead_and_creates_body(four_player_state: GameState) -> None:
    body = apply_kill(four_player_state, 0, 1, now=200.0)
    assert four_player_state.players[1].alive is False
    assert body.player_id == 1
    assert body.x == 110.0 and body.y == 100.0
    assert body.reported is False
    assert four_player_state.last_kill_at[0] == 200.0
    assert len(four_player_state.bodies) == 1


def test_can_report_in_range(four_player_state: GameState) -> None:
    body = Body(body_id=1, player_id=1, x=110.0, y=100.0, created_at=0.0)
    four_player_state.bodies.append(body)
    # impostor (0) em (100,100): distância 10 <= 50
    assert can_report(four_player_state, 0, 1, report_radius=50.0)


def test_can_report_out_of_range(four_player_state: GameState) -> None:
    body = Body(body_id=1, player_id=1, x=200.0, y=200.0, created_at=0.0)
    four_player_state.bodies.append(body)
    # impostor (0) em (100,100): distância ~141 > 50
    assert not can_report(four_player_state, 0, 1, report_radius=50.0)


def test_can_report_dead_reporter(four_player_state: GameState) -> None:
    body = Body(body_id=1, player_id=1, x=110.0, y=100.0, created_at=0.0)
    four_player_state.bodies.append(body)
    four_player_state.players[0].alive = False
    assert not can_report(four_player_state, 0, 1, report_radius=50.0)


def test_can_report_missing_body(four_player_state: GameState) -> None:
    assert not can_report(four_player_state, 0, 99, report_radius=50.0)


def test_complete_task_valid(four_player_state: GameState) -> None:
    # tripulante 1 tem a tarefa 1 em (300,300), raio 20
    assert complete_task(four_player_state, 1, 1, x=310.0, y=300.0)
    assert 1 in four_player_state.done_tasks[1]


def test_complete_task_not_assigned(four_player_state: GameState) -> None:
    # tarefa 2 não está atribuída ao tripulante 1
    assert not can_complete_task(four_player_state, 1, 2, x=320.0, y=300.0)


def test_complete_task_out_of_range(four_player_state: GameState) -> None:
    assert not can_complete_task(four_player_state, 1, 1, x=500.0, y=500.0)


def test_complete_task_dead_player(four_player_state: GameState) -> None:
    four_player_state.players[1].alive = False
    assert not can_complete_task(four_player_state, 1, 1, x=310.0, y=300.0)


def test_complete_task_already_done(four_player_state: GameState) -> None:
    four_player_state.done_tasks[1] = {1}
    assert not complete_task(four_player_state, 1, 1, x=310.0, y=300.0)


def test_impostor_has_no_tasks(four_player_state: GameState) -> None:
    assert can_complete_task(four_player_state, 0, 1, x=300.0, y=300.0) is False


def test_win_crew_when_no_impostors(four_player_state: GameState) -> None:
    four_player_state.players[0].alive = False
    assert check_win(four_player_state) is Team.CREW


def test_win_impostors_when_they_are_majority(four_player_state: GameState) -> None:
    # 1 impostor vivo, 1 tripulante vivo -> 1 >= 1
    four_player_state.players[2].alive = False
    four_player_state.players[3].alive = False
    assert check_win(four_player_state) is Team.IMPOSTOR


def test_win_crew_when_all_tasks_done(four_player_state: GameState) -> None:
    # não há imposor morto; completar todas as tarefas dos tripulantes vence
    for pid in (1, 2, 3):
        four_player_state.done_tasks[pid] = {1}
    assert all_tasks_done(four_player_state)
    assert check_win(four_player_state) is Team.CREW


def test_no_win_while_playing(four_player_state: GameState) -> None:
    assert check_win(four_player_state) is None


def test_no_win_in_crew_only_game_with_pending_tasks() -> None:
    # Partida sem papel IMPOSTOR (ex.: jogador único, impostor_count = 0):
    # sem tarefas concluídas, o jogo continua — não há vitória instantânea.
    state = GameState(game_id="game-solo", phase=Phase.PLAYING)
    state.players[0] = PlayerState(player_id=0, nickname="solo", role=Role.CREW)
    state.tasks = [Task(task_id=1, task_type="wires", x=0.0, y=0.0, interaction_radius=20.0)]
    state.task_assignments[0] = [1]
    state.done_tasks[0] = set()
    assert check_win(state) is None


def test_win_crew_in_crew_only_game_when_all_tasks_done() -> None:
    state = GameState(game_id="game-solo", phase=Phase.PLAYING)
    state.players[0] = PlayerState(player_id=0, nickname="solo", role=Role.CREW)
    state.tasks = [Task(task_id=1, task_type="wires", x=0.0, y=0.0, interaction_radius=20.0)]
    state.task_assignments[0] = [1]
    state.done_tasks[0] = {1}
    assert check_win(state) is Team.CREW


def test_no_win_outside_playing_phase(four_player_state: GameState) -> None:
    four_player_state.phase = Phase.MEETING
    assert check_win(four_player_state) is None


def test_resolve_movement_axis_separation() -> None:
    walls = [Rect(x=100.0, y=0.0, width=10.0, height=50.0)]
    # deslocamento diagonal em direção à parede: eixo X bloqueado, Y avança
    nx, ny = resolve_movement(95.0, 40.0, 10.0, 10.0, walls)
    assert nx == 95.0  # X bloqueado
    assert ny == 50.0  # Y livre


def test_resolve_movement_free() -> None:
    walls = [Rect(x=100.0, y=0.0, width=10.0, height=50.0)]
    nx, ny = resolve_movement(0.0, 0.0, 10.0, 10.0, walls)
    assert nx == 10.0 and ny == 10.0
