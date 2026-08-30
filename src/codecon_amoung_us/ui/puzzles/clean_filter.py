"""Minigame "Limpar filtro": arrastar os detritos para fora do filtro.

Os detritos nascem em posições aleatórias não sobrepostas (RNG semeado)
dentro do filtro; arrastar um detrito para fora da borda do filtro o
remove. ``CleanFilterLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import math
import random

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_H, CONTENT_W, Minigame, register

__all__ = ["Debris", "CleanFilterLogic", "CleanFilterMinigame"]

_FILTER_MARGIN = 50
_DEBRIS_R = 20
_DEBRIS_COLORS: tuple[tuple[int, int, int], ...] = (
    (140, 98, 57),  # marrom
    (120, 120, 128),  # cinza
    (86, 130, 89),  # verde escuro
)


class Debris:
    """Um detrito arrastável (coordenadas locais)."""

    def __init__(self, x: float, y: float, color: tuple[int, int, int]) -> None:
        self.x = x
        self.y = y
        self.color = color
        self.removed = False


class CleanFilterLogic:
    """Estado dos detritos (coordenadas locais)."""

    def __init__(self, rng: random.Random, count: int) -> None:
        self.debris: list[Debris] = []
        placed: list[tuple[float, float]] = []
        attempts = 0
        while len(self.debris) < count and attempts < 400:
            attempts += 1
            x = rng.uniform(_FILTER_MARGIN + _DEBRIS_R, CONTENT_W - _FILTER_MARGIN - _DEBRIS_R)
            y = rng.uniform(_FILTER_MARGIN + _DEBRIS_R, CONTENT_H - _FILTER_MARGIN - _DEBRIS_R)
            if all(math.hypot(x - px, y - py) > 2.5 * _DEBRIS_R for px, py in placed):
                placed.append((x, y))
                color = _DEBRIS_COLORS[len(self.debris) % len(_DEBRIS_COLORS)]
                self.debris.append(Debris(x, y, color))
        self.dragging: int | None = None

    @property
    def remaining(self) -> int:
        return sum(1 for d in self.debris if not d.removed)

    @property
    def done(self) -> bool:
        return self.remaining == 0

    def _filter_rect(self) -> tuple[int, int, int, int]:
        return (
            _FILTER_MARGIN,
            _FILTER_MARGIN,
            CONTENT_W - 2 * _FILTER_MARGIN,
            CONTENT_H - 2 * _FILTER_MARGIN,
        )

    def press(self, pos: tuple[float, float]) -> None:
        for index, debris in enumerate(self.debris):
            if debris.removed:
                continue
            if math.hypot(pos[0] - debris.x, pos[1] - debris.y) <= _DEBRIS_R + 8:
                self.dragging = index
                return

    def move(self, pos: tuple[float, float]) -> None:
        if self.dragging is None:
            return
        debris = self.debris[self.dragging]
        debris.x, debris.y = pos
        fx, fy, fw, fh = self._filter_rect()
        if not (fx <= debris.x <= fx + fw and fy <= debris.y <= fy + fh):
            debris.removed = True
            self.dragging = None

    def release(self) -> None:
        self.dragging = None


class CleanFilterMinigame(Minigame):
    """Wrapper pygame da limpeza de filtro."""

    def __init__(
        self,
        task_id: int,
        *,
        fonts: FontBook,
        seed: int | None = None,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__(task_id, fonts=fonts, seed=seed, reduced_motion=reduced_motion)
        from ...game.task_catalog import difficulty_for

        self.logic = CleanFilterLogic(self.rng, difficulty_for("clean_filter").targets)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press(self._to_local(event.pos))
        elif event.type == pygame.MOUSEMOTION:
            self.logic.move(self._to_local(event.pos))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.logic.release()
        if self.logic.done:
            self._done = True

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        fx, fy, fw, fh = self.logic._filter_rect()
        frame = pygame.Rect(ox + fx, oy + fy, fw, fh)
        pygame.draw.rect(surface, TOKENS.surface_interactive_pressed, frame, border_radius=14)
        pygame.draw.rect(surface, TOKENS.surface_panel_border, frame, 3, border_radius=14)
        # grade do filtro
        for gx in range(fx + 40, fx + fw, 40):
            pygame.draw.line(
                surface,
                TOKENS.surface_panel_border,
                (ox + gx, oy + fy + 8),
                (ox + gx, oy + fy + fh - 8),
                1,
            )
        for debris in self.logic.debris:
            if debris.removed:
                continue
            center = (ox + int(debris.x), oy + int(debris.y))
            pygame.draw.circle(surface, debris.color, center, _DEBRIS_R)
            pygame.draw.circle(surface, TOKENS.text_primary, center, _DEBRIS_R, 2)
        label = self.fonts.caption.render(
            f"restantes: {self.logic.remaining}", True, TOKENS.text_secondary
        )
        surface.blit(label, (ox + fx, oy + fy + fh + 12))


register("clean_filter", CleanFilterMinigame)
