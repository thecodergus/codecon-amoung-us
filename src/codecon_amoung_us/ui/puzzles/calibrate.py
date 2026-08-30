"""Minigame "Calibrar sensores": 3 anéis com agulha rotativa.

Cada anel tem uma faixa-alvo fixa no topo; clicar (ou ESPAÇO) quando a
agulha cruza a faixa trava o anel e ativa o próximo, com velocidade
crescente. Errar não penaliza além da tentativa perdida.
``CalibrateLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import math

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_W, Minigame, register

__all__ = ["RINGS", "CalibrateLogic", "CalibrateMinigame"]

RINGS = 3
_CENTER_Y = 200
_RADIUS = 62
_WINDOW = 0.40  # metade da abertura da faixa-alvo (rad em torno do topo)
_SPEEDUP = 0.35  # incremento relativo de velocidade por anel


def _ring_center(index: int) -> tuple[int, int]:
    return (CONTENT_W // 2 + (index - 1) * 170, _CENTER_Y)


class CalibrateLogic:
    """Estado dos anéis (ângulos em radianos, 0 = topo)."""

    def __init__(self, base_speed: float) -> None:
        self.speeds = [base_speed * (1 + _SPEEDUP * i) for i in range(RINGS)]
        self.angles = [math.pi * (0.7 + 0.4 * i) for i in range(RINGS)]
        self.locked = [False] * RINGS
        self.attempts = 0

    @property
    def active(self) -> int | None:
        """Índice do anel ativo (primeiro não travado) ou None."""
        return next((i for i in range(RINGS) if not self.locked[i]), None)

    @property
    def done(self) -> bool:
        return all(self.locked)

    def update(self, dt: float) -> None:
        active = self.active
        if active is None:
            return
        self.angles[active] = (self.angles[active] + self.speeds[active] * dt) % (2 * math.pi)

    def press(self) -> bool:
        """Avalia o clique no anel ativo; True se travou."""
        active = self.active
        if active is None:
            return False
        self.attempts += 1
        angle = self.angles[active]
        # distância angular ao topo (0), normalizada para [0, pi]
        offset = min(angle, 2 * math.pi - angle)
        if offset <= _WINDOW:
            self.locked[active] = True
            return True
        return False


class CalibrateMinigame(Minigame):
    """Wrapper pygame da calibração de anéis."""

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

        self.logic = CalibrateLogic(difficulty_for("calibrate").speed)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press()
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
            self.logic.press()
        if self.logic.done:
            self._done = True

    def update(self, dt: float) -> None:
        self.logic.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        logic = self.logic
        active = logic.active
        for i in range(RINGS):
            cx, cy = _ring_center(i)
            center = (ox + cx, oy + cy)
            pygame.draw.circle(surface, TOKENS.surface_interactive_pressed, center, _RADIUS)
            ring_color = TOKENS.status_success if logic.locked[i] else TOKENS.surface_panel_border
            pygame.draw.circle(surface, ring_color, center, _RADIUS, 3)
            # faixa-alvo (arco no topo)
            rect = pygame.Rect(0, 0, _RADIUS * 2, _RADIUS * 2)
            rect.center = center
            arc_color = TOKENS.status_task if i == active else TOKENS.text_disabled
            pygame.draw.arc(
                surface,
                arc_color,
                rect,
                math.pi / 2 - _WINDOW,
                math.pi / 2 + _WINDOW,
                8,
            )
            if logic.locked[i]:
                check = self.fonts.body.render("OK", True, TOKENS.status_success)
                surface.blit(check, check.get_rect(center=center))
            else:
                # agulha (ângulo 0 = topo, cresce no sentido horário)
                angle = logic.angles[i]
                tip = (
                    center[0] + int(math.sin(angle) * (_RADIUS - 10)),
                    center[1] - int(math.cos(angle) * (_RADIUS - 10)),
                )
                pygame.draw.line(surface, TOKENS.status_danger, center, tip, 4)
        label = self.fonts.caption.render(
            f"anel {1 + (active if active is not None else RINGS - 1)} de {RINGS}   |   "
            f"tentativas: {logic.attempts}",
            True,
            TOKENS.text_secondary,
        )
        surface.blit(label, label.get_rect(center=(ox + CONTENT_W // 2, oy + _CENTER_Y + 110)))


register("calibrate", CalibrateMinigame)
