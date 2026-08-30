"""Minigame "Ligar fios": arrastar cada fio ao terminal da mesma cor.

``WiresLogic`` é pura (sem pygame): nós à esquerda em ordem fixa,
terminais à direita embaralhados pelo RNG semeado; arraste conecta apenas
o par da mesma cor. ``WiresMinigame`` traduz eventos e desenha.
"""

from __future__ import annotations

import math
import random

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_H, CONTENT_W, Minigame, register

__all__ = ["WIRE_COLORS", "WiresLogic", "WiresMinigame"]

# Paleta Okabe-Ito (segura para daltonismo), 4 fios.
WIRE_COLORS: tuple[tuple[int, int, int], ...] = (
    (0, 114, 178),  # azul
    (230, 159, 0),  # laranja
    (0, 158, 115),  # verde-azulado
    (213, 94, 0),  # vermelhão
)

_LEFT_X = 60
_RIGHT_X = CONTENT_W - 60
_NODE_R = 18
_GRAB_R = 30
_TOP = 90
_STEP = (CONTENT_H - 2 * _TOP) // 3


def _node_y(index: int) -> int:
    return _TOP + index * _STEP


class WiresLogic:
    """Estado e regras do puzzle de fios (coordenadas locais)."""

    def __init__(self, rng: random.Random) -> None:
        self.right_order: list[int] = list(range(len(WIRE_COLORS)))
        rng.shuffle(self.right_order)
        # right_order[i] = índice da cor do terminal na linha i da direita
        self.connections: dict[int, int] = {}  # fio (cor) -> linha do terminal
        self.dragging: int | None = None
        self.cursor: tuple[float, float] = (0.0, 0.0)

    @property
    def done(self) -> bool:
        return len(self.connections) == len(WIRE_COLORS)

    def right_color_at(self, row: int) -> int:
        return self.right_order[row]

    def press(self, pos: tuple[float, float]) -> None:
        for wire in range(len(WIRE_COLORS)):
            if wire in self.connections:
                continue
            if math.hypot(pos[0] - _LEFT_X, pos[1] - _node_y(wire)) <= _GRAB_R:
                self.dragging = wire
                self.cursor = pos
                return

    def move(self, pos: tuple[float, float]) -> None:
        if self.dragging is not None:
            self.cursor = pos

    def release(self, pos: tuple[float, float]) -> None:
        wire = self.dragging
        self.dragging = None
        if wire is None:
            return
        for row in range(len(WIRE_COLORS)):
            if row in self.connections.values():
                continue
            if math.hypot(pos[0] - _RIGHT_X, pos[1] - _node_y(row)) <= _GRAB_R:
                if self.right_color_at(row) == wire:
                    self.connections[wire] = row
                return


class WiresMinigame(Minigame):
    """Wrapper pygame: eventos de mouse + desenho do estado."""

    def __init__(
        self,
        task_id: int,
        *,
        fonts: FontBook,
        seed: int | None = None,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__(task_id, fonts=fonts, seed=seed, reduced_motion=reduced_motion)
        self.logic = WiresLogic(self.rng)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press(self._to_local(event.pos))
        elif event.type == pygame.MOUSEMOTION:
            self.logic.move(self._to_local(event.pos))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.logic.release(self._to_local(event.pos))
        if self.logic.done:
            self._done = True

    def update(self, dt: float) -> None:
        """Puzzle estático: nada a simular entre eventos."""

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        logic = self.logic
        for wire, color in enumerate(WIRE_COLORS):
            start = (ox + _LEFT_X, oy + _node_y(wire))
            end: tuple[float, float]
            if wire in logic.connections:
                end = (ox + _RIGHT_X, oy + _node_y(logic.connections[wire]))
                pygame.draw.line(surface, color, start, end, 6)
            elif wire == logic.dragging:
                end = (ox + logic.cursor[0], oy + logic.cursor[1])
                pygame.draw.line(surface, color, start, end, 6)
            else:
                stub = (start[0] + 26, start[1])
                pygame.draw.line(surface, color, start, stub, 6)
            pygame.draw.circle(surface, color, start, _NODE_R)
            pygame.draw.circle(surface, TOKENS.text_primary, start, _NODE_R, 2)
        for row in range(len(WIRE_COLORS)):
            color = WIRE_COLORS[logic.right_color_at(row)]
            center = (ox + _RIGHT_X, oy + _node_y(row))
            pygame.draw.circle(surface, color, center, _NODE_R)
            pygame.draw.circle(surface, TOKENS.text_primary, center, _NODE_R, 2)


register("wires", WiresMinigame)
