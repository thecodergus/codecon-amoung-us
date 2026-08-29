"""Livro de fontes com cache (Open Sans via pygame-menu).

Nenhuma tela funcional deve usar a fonte default do Pygame; todos os textos
passam por aqui (caption/body/control/heading/display).
"""

from __future__ import annotations

import pygame
import pygame_menu

__all__ = ["FontBook"]

_FONT_PATH = pygame_menu.font.FONT_OPEN_SANS


class FontBook:
    """Cache de fontes Open Sans por (tamanho, negrito)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[int, bool], pygame.font.Font] = {}

    def _font(self, size: int, bold: bool = False) -> pygame.font.Font:
        key = (size, bold)
        font = self._cache.get(key)
        if font is None:
            font = pygame.font.Font(_FONT_PATH, size)
            if bold:
                font.set_bold(True)
            self._cache[key] = font
        return font

    @property
    def caption(self) -> pygame.font.Font:
        """Rótulos pequenos / dicas."""
        return self._font(14)

    @property
    def body(self) -> pygame.font.Font:
        """Corpo de texto / valores de HUD."""
        return self._font(18)

    @property
    def control(self) -> pygame.font.Font:
        """Botões e controles."""
        return self._font(26)

    @property
    def heading(self) -> pygame.font.Font:
        """Títulos de tela."""
        return self._font(32)

    @property
    def display(self) -> pygame.font.Font:
        """Grandes estados / títulos principais."""
        return self._font(44, bold=True)
