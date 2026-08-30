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
from ._native_pixels import apply_background_removal

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


def _border_background(data: bytearray, w: int, h: int) -> tuple[int, int, int]:
    """Cor de fundo = cor RGB dominante na borda do frame (varia por cor/variante)."""
    border: Counter[tuple[int, int, int]] = Counter()
    stride = w * 4
    for x in range(w):
        i = x * 4
        border[(data[i], data[i + 1], data[i + 2])] += 1
        j = (h - 1) * stride + x * 4
        border[(data[j], data[j + 1], data[j + 2])] += 1
    for y in range(h):
        i = y * stride
        border[(data[i], data[i + 1], data[i + 2])] += 1
        j = y * stride + (w - 1) * 4
        border[(data[j], data[j + 1], data[j + 2])] += 1
    return border.most_common(1)[0][0]


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
        """Carrega um frame: remove o fundo e corta o bbox do sprite.

        Os passes por pixel (flood fill do fundo, remoção de alpha e
        bounding box) rodam no kernel ``_native_pixels`` sobre um buffer
        RGBA contíguo — bytecode Python só na borda e na cola com pygame.
        """
        if not path.is_file():
            raise FileNotFoundError(f"sprite não encontrado: {path}")
        # Sem convert_alpha(): não exige video mode (funciona com SDL dummy).
        raw = pygame.image.load(str(path))
        # Os PNGs paleta 8-bit trazem colorkey preto; get_at (algoritmo
        # original) ignora colorkey, mas o blit o aplicaria como alpha 0.
        # Limpar a chave mantém o blit byte a byte equivalente ao get_at.
        raw.set_colorkey(None)
        w, h = raw.get_size()
        # Normaliza para RGBA 32-bit: layout de buffer conhecido (w*4 por
        # linha) para o kernel, independente do formato do PNG.
        work = pygame.Surface((w, h), pygame.SRCALPHA)
        work.blit(raw, (0, 0))
        data = bytearray(pygame.image.tostring(work, "RGBA"))
        background = _border_background(data, w, h)
        bbox = apply_background_removal(data, w, h, *background)
        out = pygame.image.fromstring(bytes(data), (w, h), "RGBA")
        if bbox is None:
            return out
        minx, miny, maxx, maxy = bbox
        cropped = out.subsurface((minx, miny, maxx - minx + 1, maxy - miny + 1)).copy()
        return pygame.transform.scale(
            cropped, (cropped.get_width() * _SCALE, cropped.get_height() * _SCALE)
        )

    def frame_count(self, color: str, anim: PlayerAnim) -> int:
        return self._counts[(color, anim)]

    def frame(self, color: str, anim: PlayerAnim, index: int) -> pygame.Surface:
        return self._frames[(color, anim, index)]
