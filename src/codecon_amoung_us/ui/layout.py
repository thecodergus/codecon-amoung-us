"""Transformação de viewport (letterbox) e conversão de coordenadas.

Todas as funções são puras e testáveis; o App usa ``fit_viewport`` para
mapear a superfície lógica na janela física e os eventos de mouse pelo
caminho único ``screen_to_logical``.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ViewportTransform", "fit_viewport"]


@dataclass(frozen=True)
class ViewportTransform:
    """Mapeamento logical -> physical preservando aspect ratio."""

    logical_size: tuple[int, int]
    physical_size: tuple[int, int]
    scale: float
    offset_x: float
    offset_y: float

    def logical_to_screen(self, x: float, y: float) -> tuple[float, float]:
        return self.offset_x + x * self.scale, self.offset_y + y * self.scale

    def screen_to_logical(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.offset_x) / self.scale, (y - self.offset_y) / self.scale

    def contains_physical(self, x: float, y: float) -> bool:
        """True se o ponto físico cai dentro do viewport lógico (letterbox)."""
        lx, ly = self.screen_to_logical(x, y)
        lw, lh = self.logical_size
        return 0.0 <= lx <= lw and 0.0 <= ly <= lh


def fit_viewport(logical: tuple[int, int], physical: tuple[int, int]) -> ViewportTransform:
    """Ajusta o viewport lógico na janela física com letterbox centralizado.

    Nunca estica: ``scale`` = min(fator x, fator y); sobras viram barras
    laterais (offset_x/offset_y).
    """
    lw, lh = logical
    pw, ph = physical
    if lw <= 0 or lh <= 0 or pw <= 0 or ph <= 0:
        raise ValueError("dimensões do viewport e da janela devem ser positivas")
    scale = min(pw / lw, ph / lh)
    offset_x = (pw - lw * scale) / 2.0
    offset_y = (ph - lh * scale) / 2.0
    return ViewportTransform(logical, physical, scale, offset_x, offset_y)
