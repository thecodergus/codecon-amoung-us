"""Sprites das estações de tarefa (objetos do mundo), carregados dos assets.

Os PNGs (``assets/tasks/<task_type>.png`` + ``emergency.png``) são gerados por
``scripts/build_task_props.py`` (determinístico, com gate de frescor no CI) a
partir do pack "Top Down Lab". Cada sprite é 64x64 px de mundo com fundo
transparente e representa o objeto físico da estação (console com fios, totem
de cartão, monitor etc.) — a renderização desenha por cima apenas os
signifiers de estado (tag, halo, "!", check).

O loader pré-computa a variante ``dim`` de cada sprite (estações não
atribuídas ao jogador ou já concluídas), evitando custo por frame.
"""

from __future__ import annotations

from pathlib import Path

import pygame

from ..config import default_assets_dir
from ..game.task_catalog import TASK_TYPES

__all__ = ["PROP_NAMES", "PROP_SIZE", "TaskProps"]

# Nomes de sprite válidos: os 7 tipos de tarefa + o botão de emergência.
PROP_NAMES: tuple[str, ...] = (*TASK_TYPES, "emergency")
# Lado do sprite quadrado em px de mundo (16 px de grade x4, ver builder).
PROP_SIZE: int = 64

# Multiplicador RGB da variante dim (mantém alfa): apaga sem sumir — o objeto
# continua sendo mobília do mundo, só deixa de ser "para você".
_DIM_MULT = (110, 110, 130, 255)


def _dim_variant(sprite: pygame.Surface) -> pygame.Surface:
    """Cópia escurecida do sprite (canal alfa preservado)."""
    dim = sprite.copy()
    dim.fill(_DIM_MULT, special_flags=pygame.BLEND_RGBA_MULT)
    return dim


class TaskProps:
    """Sprites das estações por nome, normais e dim, prontos para blit."""

    def __init__(self, assets_dir: Path | None = None) -> None:
        base = (assets_dir or default_assets_dir()) / "tasks"
        self._normal: dict[str, pygame.Surface] = {}
        self._dim: dict[str, pygame.Surface] = {}
        for name in PROP_NAMES:
            path = base / f"{name}.png"
            if not path.is_file():
                raise FileNotFoundError(f"sprite de estação não encontrado: {path}")
            # Sem convert_alpha(): não exige video mode (funciona com SDL dummy).
            sprite = pygame.image.load(str(path))
            self._normal[name] = sprite
            self._dim[name] = _dim_variant(sprite)

    def sprite(self, name: str, *, dimmed: bool = False) -> pygame.Surface:
        """Sprite da estação ``name`` (``dimmed`` = não atribuída/concluída)."""
        return (self._dim if dimmed else self._normal)[name]
