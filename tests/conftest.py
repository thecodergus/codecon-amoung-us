"""Fixtures compartilhadas: partida com quatro jogadores, config, servidor."""

from __future__ import annotations

import pytest

from codecon_amoung_us.config import GameConfig
from codecon_amoung_us.game.model import GameState, Phase, PlayerState, Role, Task


@pytest.fixture
def config() -> GameConfig:
    return GameConfig()


@pytest.fixture
def four_player_state() -> GameState:
    """Partida em PLAYING com 4 jogadores: 1 impostor, 3 tripulantes.

    Impostor em (100, 100); tripulantes em (110, 100), (200, 100), (200, 200).
    Duas tarefas em (300, 300)/(320, 300); cada tripulante tem a tarefa 1.
    """
    state = GameState(game_id="game-test")
    positions = {0: (100.0, 100.0), 1: (110.0, 100.0), 2: (200.0, 100.0), 3: (200.0, 200.0)}
    roles = {0: Role.IMPOSTOR, 1: Role.CREW, 2: Role.CREW, 3: Role.CREW}
    for pid in range(4):
        x, y = positions[pid]
        state.players[pid] = PlayerState(
            player_id=pid, nickname=f"p{pid}", x=x, y=y, role=roles[pid]
        )
    state.tasks = [
        Task(task_id=1, task_type="wires", x=300.0, y=300.0, interaction_radius=20.0),
        Task(task_id=2, task_type="swipe_card", x=320.0, y=300.0, interaction_radius=20.0),
    ]
    for pid in range(1, 4):
        state.task_assignments[pid] = [1]
        state.done_tasks[pid] = set()
    state.phase = Phase.PLAYING
    return state
