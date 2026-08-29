"""Física simples de movimento e colisão com paredes do mapa.

Não depende de pygame nem do parser Tiled: recebe rects do modelo do mapa.
"""

from __future__ import annotations

import math

from ..map.model import Rect

__all__ = ["resolve_movement", "resolve_movement_steps"]


def _collides(x: float, y: float, walls: list[Rect], margin: float) -> bool:
    return any(wall.contains(x, y, margin) for wall in walls)


def resolve_movement(
    x: float,
    y: float,
    dx: float,
    dy: float,
    walls: list[Rect],
    margin: float = 0.0,
) -> tuple[float, float]:
    """Move um ponto (x, y) por (dx, dy) resolvendo colisão por eixo.

    Se o deslocamento em um eixo colidir com uma parede, o movimento
    naquele eixo é cancelado (deslizamento pelas paredes).
    """
    new_x = x + dx
    if not _collides(new_x, y, walls, margin):
        x = new_x
    new_y = y + dy
    if not _collides(x, new_y, walls, margin):
        y = new_y
    return x, y


def resolve_movement_steps(
    x: float,
    y: float,
    dx: float,
    dy: float,
    walls: list[Rect],
    max_step: float,
    margin: float = 0.0,
) -> tuple[float, float]:
    """Move por (dx, dy) em subpassos de até ``max_step``.

    Colisão testada somente no ponto final de cada subpasso pode "pular"
    paredes finas quando o deslocamento total é grande (ex.: dt anômalo).
    Limitando o passo a menos que a menor espessura de parede do mapa,
    nenhuma parede é transposta.
    """
    total = math.hypot(dx, dy)
    if total == 0:
        return x, y
    steps = max(1, math.ceil(total / max_step))
    ux, uy = dx / total, dy / total
    step_len = total / steps
    for _ in range(steps):
        x, y = resolve_movement(x, y, ux * step_len, uy * step_len, walls, margin)
    return x, y
