"""Minigame "Passar cartão": timing de precisão.

O indicador varre a fenda em ping-pong; o jogador pressiona (clique ou
ESPAÇO) quando ele está sobre a zona-alvo. Erros dão feedback direcional
("cedo"/"tarde demais") — progressão estruturada por tentativa, sem
bloqueio: tentativas ilimitadas. ``SwipeLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_W, Minigame, register

__all__ = ["SwipeLogic", "SwipeCardMinigame"]

_TRACK_X0 = 60
_TRACK_X1 = CONTENT_W - 60
_TRACK_Y = 210
_ZONE_W = 90  # largura da zona-alvo (centrada na fenda)
_FEEDBACK_SECONDS = 1.6


class SwipeLogic:
    """Estado do timing da fenda (coordenadas locais)."""

    def __init__(self, speed: float) -> None:
        self.speed = speed
        self.x = float(_TRACK_X0)
        self.direction = 1.0
        self.attempts = 0
        self.feedback = ""
        self.feedback_t = 0.0
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def zone(self) -> tuple[float, float]:
        center = (_TRACK_X0 + _TRACK_X1) / 2
        return (center - _ZONE_W / 2, center + _ZONE_W / 2)

    def update(self, dt: float) -> None:
        if self._done:
            return
        self.x += self.direction * self.speed * dt
        if self.x >= _TRACK_X1:
            self.x = _TRACK_X1 - (self.x - _TRACK_X1)
            self.direction = -1.0
        elif self.x <= _TRACK_X0:
            self.x = _TRACK_X0 + (_TRACK_X0 - self.x)
            self.direction = 1.0
        self.feedback_t += dt

    def press(self) -> None:
        """Avalia a tentativa no instante do clique/tecla."""
        if self._done:
            return
        lo, hi = self.zone
        self.attempts += 1
        if lo <= self.x <= hi:
            self._done = True
            self.feedback = "aceito!"
        elif self.x < lo:
            self.feedback = "cedo demais"
        else:
            self.feedback = "tarde demais"
        self.feedback_t = 0.0


class SwipeCardMinigame(Minigame):
    """Wrapper pygame do timing de cartão."""

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

        self.logic = SwipeLogic(difficulty_for("swipe_card").speed)

    def handle_event(self, event: pygame.event.Event) -> None:
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            or event.type == pygame.KEYDOWN
            and event.key == pygame.K_SPACE
        ):
            self.logic.press()
        if self.logic.done:
            self._done = True

    def update(self, dt: float) -> None:
        self.logic.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        logic = self.logic
        track = pygame.Rect(ox + _TRACK_X0, oy + _TRACK_Y - 14, _TRACK_X1 - _TRACK_X0, 28)
        pygame.draw.rect(surface, TOKENS.surface_interactive_pressed, track, border_radius=8)
        lo, hi = logic.zone
        zone = pygame.Rect(ox + lo, oy + _TRACK_Y - 18, hi - lo, 36)
        pygame.draw.rect(surface, TOKENS.status_success, zone, border_radius=8)
        pygame.draw.rect(surface, TOKENS.text_primary, zone, 2, border_radius=8)
        # indicador: barra sempre visível (pulso só decorativo; omitido com
        # reduced_motion — a barra já carrega a informação)
        x = int(ox + logic.x)
        color = (
            TOKENS.status_danger
            if logic.feedback and logic.feedback != "aceito!"
            else TOKENS.status_info
        )
        if logic.feedback_t > _FEEDBACK_SECONDS:
            color = TOKENS.status_info
        pygame.draw.rect(surface, color, (x - 5, oy + _TRACK_Y - 26, 10, 52), border_radius=4)
        if logic.feedback and logic.feedback_t <= _FEEDBACK_SECONDS:
            text = self.fonts.body.render(logic.feedback, True, TOKENS.text_primary)
            surface.blit(text, text.get_rect(center=(ox + CONTENT_W // 2, oy + _TRACK_Y + 70)))
        attempts = self.fonts.caption.render(
            f"tentativas: {logic.attempts}", True, TOKENS.text_secondary
        )
        surface.blit(attempts, (ox + _TRACK_X0, oy + _TRACK_Y + 110))


register("swipe_card", SwipeCardMinigame)
