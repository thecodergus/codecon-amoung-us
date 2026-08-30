"""Carregamento e processamento dos sprites de personagem (duckee).

Os PNGs de origem (``models/duckee/<cor>/individual_animations/<anim>/png_sequence``)
são paleta 8-bit sem canal alpha, com o fundo preto sólido. O carregamento:

1. remove o preto alcançável a partir da borda do frame (flood fill),
   preservando o contorno preto do próprio sprite;
2. corta o bounding box não-transparente;
3. escala 3x (pixel art, sem suavização).

As cores seguem ``DUCKEE_COLORS``; a cor de um jogador é derivada do
``player_id`` (sem cor no protocolo).
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path

import pygame

from ..config import DUCKEE_DIRNAME, default_models_dir

__all__ = ["DUCKEE_COLORS", "PlayerAnim", "color_for", "DuckeeSprites"]

DUCKEE_COLORS: tuple[str, ...] = (
    "aqua",
    "blue",
    "green",
    "orange",
    "purple",
    "red",
    "tan",
    "yellow",
)


class PlayerAnim(StrEnum):
    """Animações de personagem disponíveis (conjunto finito e fechado)."""

    IDLE = "idle"
    WALK = "walk"
    DEATH = "death"


# animação -> (pasta no asset, número de frames)
_ANIMATIONS: dict[PlayerAnim, tuple[str, int]] = {
    PlayerAnim.IDLE: ("idle", 4),
    PlayerAnim.WALK: ("walk_run", 4),
    PlayerAnim.DEATH: ("death", 1),
}

_SCALE = 3


def color_for(player_id: int) -> str:
    """Cor do duckee para o jogador (estável por ``player_id``)."""
    return DUCKEE_COLORS[player_id % len(DUCKEE_COLORS)]


def _frame_filename(anim: PlayerAnim, index: int) -> str:
    if anim is PlayerAnim.DEATH:
        return "duckee_death.png"
    base = "walk_run" if anim is PlayerAnim.WALK else anim.value
    return f"duckee_{base}{index + 1}.png"


def _rgb(pixel: pygame.Color) -> tuple[int, int, int]:
    """Cor RGB de um pixel (get_at retorna Color; evita slices de tupla)."""
    return (pixel.r, pixel.g, pixel.b)


class DuckeeSprites:
    """Sprites dos duckee por cor/anim, prontos para blit (fundo removido)."""

    def __init__(self, models_dir: Path | None = None) -> None:
        base = (models_dir or default_models_dir()) / DUCKEE_DIRNAME
        self._frames: dict[tuple[str, PlayerAnim, int], pygame.Surface] = {}
        self._counts: dict[tuple[str, PlayerAnim], int] = {}
        for color in DUCKEE_COLORS:
            for anim, (folder, count) in _ANIMATIONS.items():
                self._counts[(color, anim)] = count
                for index in range(count):
                    path = (
                        base
                        / color
                        / "individual_animations"
                        / folder
                        / "png_sequence"
                        / _frame_filename(anim, index)
                    )
                    self._frames[(color, anim, index)] = self._load_frame(path)

    @staticmethod
    def _load_frame(path: Path) -> pygame.Surface:
        """Carrega um frame: remove o fundo preto e corta o bbox do sprite."""
        if not path.is_file():
            raise FileNotFoundError(f"sprite não encontrado: {path}")
        # Sem convert_alpha(): não exige video mode (funciona com SDL dummy).
        raw = pygame.image.load(str(path))
        w, h = raw.get_size()
        # cor de fundo = cor dominante na borda do frame (varia por cor/variante)
        border: Counter[tuple[int, int, int]] = Counter()
        for x in range(w):
            border[_rgb(raw.get_at((x, 0)))] += 1
            border[_rgb(raw.get_at((x, h - 1)))] += 1
        for y in range(h):
            border[_rgb(raw.get_at((0, y)))] += 1
            border[_rgb(raw.get_at((w - 1, y)))] += 1
        background = border.most_common(1)[0][0]
        # marca o fundo alcançável a partir da borda (flood fill por cor exata)
        reachable = [[False] * w for _ in range(h)]
        stack: list[tuple[int, int]] = []
        for x in range(w):
            stack.extend([(x, 0), (x, h - 1)])
        for y in range(h):
            stack.extend([(0, y), (w - 1, y)])
        while stack:
            x, y = stack.pop()
            if not (0 <= x < w and 0 <= y < h) or reachable[y][x]:
                continue
            reachable[y][x] = True
            if _rgb(raw.get_at((x, y))) != background:
                continue
            stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
        out = pygame.Surface((w, h), pygame.SRCALPHA)
        for y in range(h):
            for x in range(w):
                if not reachable[y][x]:
                    out.set_at((x, y), raw.get_at((x, y)))
        # bounding box não-transparente
        minx, miny, maxx, maxy = w, h, -1, -1
        for y in range(h):
            for x in range(w):
                if out.get_at((x, y))[3] > 0:
                    minx = min(minx, x)
                    miny = min(miny, y)
                    maxx = max(maxx, x)
                    maxy = max(maxy, y)
        if maxx < 0:
            return out
        cropped = out.subsurface((minx, miny, maxx - minx + 1, maxy - miny + 1)).copy()
        return pygame.transform.scale(
            cropped, (cropped.get_width() * _SCALE, cropped.get_height() * _SCALE)
        )

    def frame_count(self, color: str, anim: PlayerAnim) -> int:
        return self._counts[(color, anim)]

    def frame(self, color: str, anim: PlayerAnim, index: int) -> pygame.Surface:
        return self._frames[(color, anim, index)]
