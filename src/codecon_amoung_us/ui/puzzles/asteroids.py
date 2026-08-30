"""Minigame "Destruir asteroides": clique nos alvos antes que escapem.

Asteroides cruzam o painel a partir das bordas (direção e velocidade do
RNG semeado); clicar num asteroide o destrói e conta para a cota. Os que
saem da área simplesmente desaparecem (sem penalidade) e novos nascem
até a cota ser cumprida. ``AsteroidsLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import math
import random

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_H, CONTENT_W, Minigame, register

__all__ = ["Asteroid", "AsteroidsLogic", "AsteroidsMinigame"]

_MAX_ACTIVE = 4
_SPAWN_INTERVAL = 0.7
_MARGIN = 40  # nasce/morre fora da área visível


class Asteroid:
    """Um asteroide em movimento (coordenadas locais)."""

    def __init__(self, x: float, y: float, vx: float, vy: float, radius: float) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.radius = radius
        self.alive = True


class AsteroidsLogic:
    """Campo de asteroides (coordenadas locais)."""

    def __init__(self, rng: random.Random, quota: int, speed: float) -> None:
        self.rng = rng
        self.quota = quota
        self.speed = speed
        self.asteroids: list[Asteroid] = []
        self.destroyed = 0
        self.spawn_timer = 0.0

    @property
    def done(self) -> bool:
        return self.destroyed >= self.quota

    def _spawn(self) -> None:
        side = self.rng.randrange(4)
        if side == 0:  # esquerda -> direita
            x, y = -_MARGIN, self.rng.uniform(0, CONTENT_H)
        elif side == 1:  # direita -> esquerda
            x, y = CONTENT_W + _MARGIN, self.rng.uniform(0, CONTENT_H)
        elif side == 2:  # topo -> base
            x, y = self.rng.uniform(0, CONTENT_W), -_MARGIN
        else:  # base -> topo
            x, y = self.rng.uniform(0, CONTENT_W), CONTENT_H + _MARGIN
        # mira um ponto interno aleatório (trajetória atravessa a área)
        tx = self.rng.uniform(CONTENT_W * 0.2, CONTENT_W * 0.8)
        ty = self.rng.uniform(CONTENT_H * 0.2, CONTENT_H * 0.8)
        dist = math.hypot(tx - x, ty - y) or 1.0
        speed = self.speed * self.rng.uniform(0.8, 1.3)
        vx, vy = (tx - x) / dist * speed, (ty - y) / dist * speed
        radius = self.rng.uniform(16, 26)
        self.asteroids.append(Asteroid(x, y, vx, vy, radius))

    def update(self, dt: float) -> None:
        if self.done:
            return
        self.spawn_timer += dt
        active = [a for a in self.asteroids if a.alive]
        if self.spawn_timer >= _SPAWN_INTERVAL and len(active) < _MAX_ACTIVE:
            self.spawn_timer = 0.0
            self._spawn()
        for asteroid in self.asteroids:
            if not asteroid.alive:
                continue
            asteroid.x += asteroid.vx * dt
            asteroid.y += asteroid.vy * dt
            if (
                asteroid.x < -_MARGIN
                or asteroid.x > CONTENT_W + _MARGIN
                or asteroid.y < -_MARGIN
                or asteroid.y > CONTENT_H + _MARGIN
            ):
                asteroid.alive = False

    def press(self, pos: tuple[float, float]) -> None:
        for asteroid in self.asteroids:
            if not asteroid.alive:
                continue
            if math.hypot(pos[0] - asteroid.x, pos[1] - asteroid.y) <= asteroid.radius + 6:
                asteroid.alive = False
                self.destroyed += 1
                return


class AsteroidsMinigame(Minigame):
    """Wrapper pygame do campo de asteroides."""

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

        params = difficulty_for("asteroids")
        self.logic = AsteroidsLogic(self.rng, params.targets, params.speed)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press(self._to_local(event.pos))
        if self.logic.done:
            self._done = True

    def update(self, dt: float) -> None:
        self.logic.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        for asteroid in self.logic.asteroids:
            if not asteroid.alive:
                continue
            center = (ox + int(asteroid.x), oy + int(asteroid.y))
            radius = int(asteroid.radius)
            pygame.draw.circle(surface, (140, 110, 90), center, radius)
            pygame.draw.circle(surface, TOKENS.text_primary, center, radius, 2)
            pygame.draw.circle(surface, (100, 78, 62), center, radius // 3)
        label = self.fonts.body.render(
            f"{self.logic.destroyed}/{self.logic.quota}", True, TOKENS.text_primary
        )
        surface.blit(label, label.get_rect(center=(ox + CONTENT_W // 2, oy + 40)))


register("asteroids", AsteroidsMinigame)
