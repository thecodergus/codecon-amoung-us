"""Atribuição de tarefas aos jogadores (tripulantes recebem tarefas,
impostores não — recebem lista vazia)."""

from __future__ import annotations

import random

from .model import GameState, Role, Task

__all__ = ["assign_tasks"]


def assign_tasks(state: GameState, rng: random.Random | None = None) -> dict[int, list[int]]:
    """Atribui ``tasks_per_crew`` tarefas distintas a cada tripulante.

    Impostores recebem lista vazia (tarefas "falsas" não são necessárias
    no MVP). Usa o RNG fornecido (determinístico em testes) ou um novo.
    """
    rng = rng if rng is not None else random.Random()
    crew = [p for p in state.players.values() if p.role is Role.CREW]
    task_pool = [t.task_id for t in state.tasks]
    assignments: dict[int, list[int]] = {p.player_id: [] for p in state.players.values()}
    if not task_pool:
        return assignments
    tasks_per_crew = min(2, len(task_pool))
    for player in crew:
        chosen = rng.sample(task_pool, tasks_per_crew)
        assignments[player.player_id] = sorted(chosen)
    return assignments


def all_assigned_tasks(state: GameState) -> list[tuple[int, Task]]:
    """(player_id, task) para cada tarefa atribuída a algum jogador."""
    result: list[tuple[int, Task]] = []
    for player_id, task_ids in state.task_assignments.items():
        for task_id in task_ids:
            task = state.task_by_id(task_id)
            if task is not None:
                result.append((player_id, task))
    return result
