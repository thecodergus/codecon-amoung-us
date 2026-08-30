"""Minigame "Reparar circuito": Lights-Out 3x3.

Clicar num painel alterna ele e os vizinhos ortogonais; o objetivo é
acender os 9. O estado inicial é gerado a partir da solução (todos
acesos) aplicando cliques aleatórios do RNG semeado — solubilidade
garantida por construção. ``LightsOutLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import random

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_H, CONTENT_W, Minigame, register

__all__ = ["GRID", "LightsOutLogic", "FixWiringMinigame"]

GRID = 3
_SCRAMBLE_CLICKS = 5
_CELL = 96
_GAP = 16
_BOARD = GRID * _CELL + (GRID - 1) * _GAP
_ORIGIN_X = (CONTENT_W - _BOARD) // 2
_ORIGIN_Y = (CONTENT_H - _BOARD) // 2 + 10


class LightsOutLogic:
    """Tabuleiro Lights-Out 3x3 (coordenadas locais)."""

    def __init__(self, rng: random.Random) -> None:
        self.lit: list[list[bool]] = [[True] * GRID for _ in range(GRID)]
        self.moves = 0
        # embaralha a partir da solução; refaz se voltar ao resolvido
        while self._solved():
            for _ in range(_SCRAMBLE_CLICKS):
                self._toggle(rng.randrange(GRID), rng.randrange(GRID))
        self.moves = 0

    def _toggle(self, row: int, col: int) -> None:
        for dr, dc in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            r, c = row + dr, col + dc
            if 0 <= r < GRID and 0 <= c < GRID:
                self.lit[r][c] = not self.lit[r][c]

    def _solved(self) -> bool:
        return all(all(row) for row in self.lit)

    @property
    def done(self) -> bool:
        return self._solved()

    def cell_rect(self, row: int, col: int) -> tuple[int, int, int, int]:
        return (
            _ORIGIN_X + col * (_CELL + _GAP),
            _ORIGIN_Y + row * (_CELL + _GAP),
            _CELL,
            _CELL,
        )

    def press(self, pos: tuple[float, float]) -> None:
        for row in range(GRID):
            for col in range(GRID):
                x, y, w, h = self.cell_rect(row, col)
                if x <= pos[0] < x + w and y <= pos[1] < y + h:
                    self._toggle(row, col)
                    self.moves += 1
                    return


class FixWiringMinigame(Minigame):
    """Wrapper pygame do Lights-Out."""

    def __init__(
        self,
        task_id: int,
        *,
        fonts: FontBook,
        seed: int | None = None,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__(task_id, fonts=fonts, seed=seed, reduced_motion=reduced_motion)
        self.logic = LightsOutLogic(self.rng)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press(self._to_local(event.pos))
        if self.logic.done:
            self._done = True

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        for row in range(GRID):
            for col in range(GRID):
                x, y, w, h = self.logic.cell_rect(row, col)
                rect = pygame.Rect(ox + x, oy + y, w, h)
                lit = self.logic.lit[row][col]
                fill = TOKENS.status_task if lit else TOKENS.surface_interactive_pressed
                pygame.draw.rect(surface, fill, rect, border_radius=10)
                pygame.draw.rect(surface, TOKENS.surface_panel_border, rect, 2, border_radius=10)
                if lit:
                    pygame.draw.circle(
                        surface, TOKENS.surface_panel, (rect.centerx, rect.centery), 10
                    )
        moves = self.fonts.caption.render(
            f"jogadas: {self.logic.moves}", True, TOKENS.text_secondary
        )
        surface.blit(moves, (ox + _ORIGIN_X, oy + _ORIGIN_Y + _BOARD + 12))


register("fix_wiring", FixWiringMinigame)
