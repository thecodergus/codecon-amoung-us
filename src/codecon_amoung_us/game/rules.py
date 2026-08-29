"""Regras puras de gameplay: kill, tarefas, condições de vitória."""

from __future__ import annotations

import math

from .model import Body, GameState, Phase, Role, Team

__all__ = [
    "distance",
    "can_kill",
    "apply_kill",
    "can_report",
    "can_complete_task",
    "complete_task",
    "all_tasks_done",
    "check_win",
]


def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Distância euclidiana entre dois pontos."""
    return math.hypot(x2 - x1, y2 - y1)


def can_kill(
    state: GameState,
    attacker_id: int,
    target_id: int,
    now: float,
    *,
    kill_radius: float,
    kill_cooldown_seconds: float,
) -> bool:
    """Validação completa de um kill (regras de domínio).

    Exige: atacante existe/vivo/Impostor; alvo existe/vivo/diferente;
    distância <= kill_radius; cooldown vencido.
    """
    attacker = state.player(attacker_id)
    target = state.player(target_id)
    if attacker is None or target is None:
        return False
    if not attacker.alive or not target.alive:
        return False
    if attacker.role is not Role.IMPOSTOR:
        return False
    if attacker_id == target_id:
        return False
    if distance(attacker.x, attacker.y, target.x, target.y) > kill_radius:
        return False
    last_kill = state.last_kill_at.get(attacker_id, -math.inf)
    return now - last_kill >= kill_cooldown_seconds


def apply_kill(state: GameState, attacker_id: int, target_id: int, now: float) -> Body:
    """Aplica o kill: marca o alvo como morto e cria um corpo.

    Pré-condição: ``can_kill`` já validado. Mutação atômica do estado.
    """
    target = state.players[target_id]
    target.alive = False
    state.last_kill_at[attacker_id] = now
    body = Body(
        body_id=state.next_body_id,
        player_id=target_id,
        x=target.x,
        y=target.y,
        created_at=now,
    )
    state.next_body_id += 1
    state.bodies.append(body)
    return body


def can_report(
    state: GameState,
    reporter_id: int,
    body_id: int,
    report_radius: float,
) -> bool:
    """Valida reportar um corpo: reporter existe/vivo e dentro do raio.

    O corpo deve existir (a checagem de ``reported`` fica no servidor, que
    remove o corpo ao iniciar a reunião).
    """
    reporter = state.player(reporter_id)
    body = state.body_by_id(body_id)
    if reporter is None or body is None:
        return False
    if not reporter.alive:
        return False
    return distance(reporter.x, reporter.y, body.x, body.y) <= report_radius


def can_complete_task(state: GameState, player_id: int, task_id: int, x: float, y: float) -> bool:
    """Valida completar tarefa: jogador existe/vivo, tarefa atribuída,
    ainda não concluída e dentro do raio de interação."""
    player = state.player(player_id)
    task = state.task_by_id(task_id)
    if player is None or task is None:
        return False
    if not player.alive:
        return False
    if task_id not in state.task_assignments.get(player_id, []):
        return False
    if task_id in state.done_tasks.get(player_id, set()):
        return False
    return distance(x, y, task.x, task.y) <= task.interaction_radius


def complete_task(state: GameState, player_id: int, task_id: int, x: float, y: float) -> bool:
    """Conclui a tarefa se válida. Retorna False se não pôde concluir."""
    if not can_complete_task(state, player_id, task_id, x, y):
        return False
    state.done_tasks.setdefault(player_id, set()).add(task_id)
    return True


def all_tasks_done(state: GameState) -> bool:
    """True se todas as tarefas atribuídas a tripulantes estão concluídas."""
    for player in state.players.values():
        if player.role is not Role.CREW:
            continue
        assigned = set(state.task_assignments.get(player.player_id, []))
        done = state.done_tasks.get(player.player_id, set())
        if not assigned <= done:
            return False
    return True


def check_win(state: GameState) -> Team | None:
    """Time vencedor, ou None se a partida continua.

    Impostores vivos >= tripulantes vivos -> impostores vencem.
    Nenhum impostor vivo (houve papel impostor) -> tripulantes.
    Partida sem impostor (ex.: jogador único) -> tripulantes apenas quando
    todas as tarefas forem concluídas; senão a partida continua.
    """
    if state.phase is not Phase.PLAYING:
        return None
    alive_impostors = sum(1 for p in state.players.values() if p.alive and p.role is Role.IMPOSTOR)
    alive_crew = sum(1 for p in state.players.values() if p.alive and p.role is Role.CREW)
    if alive_impostors == 0:
        # Impostores eliminados, ou partida sem impostor (ex.: jogador único,
        # impostor_count = 0). No primeiro caso os tripulantes vencem; no
        # segundo, a vitória só vem pelas tarefas — senão a partida terminaria
        # no primeiro tick.
        if any(p.role is Role.IMPOSTOR for p in state.players.values()):
            return Team.CREW
        if all_tasks_done(state):
            return Team.CREW
        return None
    if alive_impostors >= alive_crew:
        return Team.IMPOSTOR
    if all_tasks_done(state):
        return Team.CREW
    return None
