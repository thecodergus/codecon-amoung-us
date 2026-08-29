"""Modelo de domínio do jogo (puro, sem pygame/msgspec/parser).

As estruturas aqui são a fonte de verdade do gameplay. Regras em
``rules.py``, votação em ``voting.py``, reunião em ``meeting.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .meeting import Meeting


class Role(StrEnum):
    """Papel atribuído a cada jogador no início da partida."""

    CREW = "crew"
    IMPOSTOR = "impostor"


class Team(StrEnum):
    """Time derivado do papel."""

    CREW = "crew"
    IMPOSTOR = "impostor"


def team_of(role: Role) -> Team:
    """Time ao qual um papel pertence."""
    return Team.IMPOSTOR if role is Role.IMPOSTOR else Team.CREW


class Phase(StrEnum):
    """Fase atual da partida no servidor."""

    LOBBY = "lobby"
    PLAYING = "playing"
    MEETING = "meeting"
    ENDED = "ended"


@dataclass
class PlayerState:
    """Estado mutável de um jogador durante a partida."""

    player_id: int
    nickname: str
    x: float = 0.0
    y: float = 0.0
    role: Role | None = None
    alive: bool = True

    @property
    def team(self) -> Team | None:
        return team_of(self.role) if self.role is not None else None


@dataclass
class Body:
    """Corpo deixado por uma vítima de kill, reportável."""

    body_id: int
    player_id: int
    x: float
    y: float
    created_at: float
    reported: bool = False


@dataclass
class Task:
    """Tarefa do mapa com posição e raio de interação."""

    task_id: int
    task_type: str
    x: float
    y: float
    interaction_radius: float


@dataclass
class GameState:
    """Estado completo da partida (autoritativo, mantido no servidor)."""

    game_id: str
    phase: Phase = Phase.LOBBY
    players: dict[int, PlayerState] = field(default_factory=dict)
    bodies: list[Body] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    # player_id -> lista de task_ids atribuídos
    task_assignments: dict[int, list[int]] = field(default_factory=dict)
    # player_id -> set de task_ids concluídos
    done_tasks: dict[int, set[int]] = field(default_factory=dict)
    # impostor_id -> timestamp do último kill
    last_kill_at: dict[int, float] = field(default_factory=dict)
    tick: int = 0
    next_body_id: int = 1
    meeting: Meeting | None = None

    def player(self, player_id: int) -> PlayerState | None:
        return self.players.get(player_id)

    def task_by_id(self, task_id: int) -> Task | None:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def body_by_id(self, body_id: int) -> Body | None:
        for body in self.bodies:
            if body.body_id == body_id:
                return body
        return None

    def alive_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.alive]
