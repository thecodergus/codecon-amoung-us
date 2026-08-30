"""Modelo interno do mapa (sem pygame, sem parser Tiled).

Estruturas convertidas pelo loader a partir do asset Tiled; usadas por
física, servidor e renderização.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Rect", "Room", "SpawnPoint", "TaskPoint", "GameMap"]


@dataclass(frozen=True)
class Rect:
    """Retângulo axis-aligned em pixels."""

    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x

    @property
    def top(self) -> float:
        return self.y

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, px: float, py: float, margin: float = 0.0) -> bool:
        """True se o ponto está dentro do retângulo (com margem opcional)."""
        return (
            self.left + margin <= px <= self.right - margin
            and self.top + margin <= py <= self.bottom - margin
        )


@dataclass(frozen=True)
class SpawnPoint:
    """Ponto de spawn de um jogador."""

    spawn_id: int
    x: float
    y: float


@dataclass(frozen=True)
class TaskPoint:
    """Ponto de tarefa com tipo e raio de interação (propriedades do Tiled)."""

    task_id: int
    task_type: str
    x: float
    y: float
    interaction_radius: float


@dataclass(frozen=True)
class Room:
    """Sala/área nomeada do mapa (região espacial aproximada, validação/UI)."""

    name: str
    rect: Rect


@dataclass(frozen=True)
class GameMap:
    """Mapa convertido em estruturas internas do jogo."""

    name: str
    width: int
    height: int
    tile_width: int
    tile_height: int
    walls: list[Rect]
    floor_rects: list[Rect]
    decorative_rects: list[tuple[Rect, tuple[int, int, int]]]
    spawn_points: list[SpawnPoint]
    task_points: list[TaskPoint]
    emergency_meeting: tuple[float, float] | None
    emergency_meeting_radius: float
    rooms: list[Room] = field(default_factory=list)

    def bounds(self) -> tuple[float, float, float, float]:
        """Limites do mapa em pixels: (esquerda, topo, direita, base)."""
        return 0.0, 0.0, float(self.width * self.tile_width), float(self.height * self.tile_height)
