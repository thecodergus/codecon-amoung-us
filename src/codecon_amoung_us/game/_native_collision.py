"""Kernel de colisão ponto-retângulo (Cython Pure Python Mode).

As paredes do mapa (``list[Rect]``) são achatadas UMA VEZ em quatro arrays
contíguos de ``double`` (``flatten_walls``) por quem detém o mapa — o
servidor, no ``__init__``. Os hot loops (teste de colisão por eixo e laço
de subpassos) operam sobre typed memoryviews com escalares ``double`` e
índices ``Py_ssize_t``: nenhum objeto Python é tocado por parede/subpasso
quando compilado.

``game/physics.py`` permanece a referência semântica (API pública pura);
a equivalência bit a bit entre os dois caminhos é property-tested em
``tests/test_native_collision.py`` (incluindo dx/dy anômalos que forçam
muitos subpassos). ``math.hypot``/``math.ceil`` ficam na fronteira para
garantir resultados idênticos ao CPython (número de subpassos incluso).
"""

from __future__ import annotations

import math
from array import array
from collections.abc import Iterable

import cython

from ..map.model import Rect

__all__ = ["FlatWalls", "flatten_walls", "resolve_movement_steps_flat"]

# (x0, y0, x1, y1) contíguos; x1/y1 já somam width/height (o que as
# properties right/bottom do Rect recomputariam a cada chamada).
FlatWalls = tuple[array[float], array[float], array[float], array[float]]


def flatten_walls(walls: Iterable[Rect]) -> FlatWalls:
    """Achata retângulos em quatro arrays de double (uma vez, nunca por tick)."""
    x0, y0, x1, y1 = array("d"), array("d"), array("d"), array("d")
    for wall in walls:
        x0.append(wall.x)
        y0.append(wall.y)
        x1.append(wall.x + wall.width)
        y1.append(wall.y + wall.height)
    return x0, y0, x1, y1


@cython.cfunc
def _collides(
    px: cython.double,
    py: cython.double,
    vx0: cython.double[::1],
    vy0: cython.double[::1],
    vx1: cython.double[::1],
    vy1: cython.double[::1],
    margin: cython.double,
) -> cython.bint:
    i: cython.Py_ssize_t
    # len() (e não .shape): compilado vira shape[0]; interpretado, o declare
    # devolve o próprio array — paridade dos dois modos.
    n: cython.Py_ssize_t = len(vx0)
    for i in range(n):
        # Mesma expressão de Rect.contains (left/top + margin, right/bottom
        # - margin) com early-exit na primeira colisão, como o any().
        if vx0[i] + margin <= px <= vx1[i] - margin and vy0[i] + margin <= py <= vy1[i] - margin:
            return True
    return False


@cython.cfunc
def _walk(
    x: cython.double,
    y: cython.double,
    sx: cython.double,
    sy: cython.double,
    steps: cython.Py_ssize_t,
    vx0: cython.double[::1],
    vy0: cython.double[::1],
    vx1: cython.double[::1],
    vy1: cython.double[::1],
    margin: cython.double,
) -> tuple[cython.double, cython.double]:
    _k: cython.Py_ssize_t
    nx: cython.double
    ny: cython.double
    for _k in range(steps):
        # resolve_movement por subpasso: testa cada eixo e cancela o
        # deslocamento do eixo que colide (deslizamento pelas paredes).
        nx = x + sx
        if not _collides(nx, y, vx0, vy0, vx1, vy1, margin):
            x = nx
        ny = y + sy
        if not _collides(x, ny, vx0, vy0, vx1, vy1, margin):
            y = ny
    return x, y


@cython.ccall
def resolve_movement_steps_flat(
    x: cython.double,
    y: cython.double,
    dx: cython.double,
    dy: cython.double,
    walls: FlatWalls,
    max_step: cython.double,
    margin: cython.double = 0.0,
) -> tuple[cython.double, cython.double]:
    """Equivalente a ``physics.resolve_movement_steps`` sobre paredes planas.

    ``total``/``steps`` são computados aqui (fronteira) com as mesmas
    funções do CPython usadas pela referência, garantindo bit-identidade —
    inclusive a contagem de subpassos em deslocamentos anômalos.
    """
    total = math.hypot(dx, dy)
    if total == 0:
        return x, y
    steps = max(1, math.ceil(total / max_step))
    ux, uy = dx / total, dy / total
    step_len = total / steps
    x0, y0, x1, y1 = walls
    # Aquisição dos buffers UMA vez por chamada (não por subpasso/eixo).
    vx0 = cython.declare(cython.double[::1], x0)
    vy0 = cython.declare(cython.double[::1], y0)
    vx1 = cython.declare(cython.double[::1], x1)
    vy1 = cython.declare(cython.double[::1], y1)
    return _walk(x, y, ux * step_len, uy * step_len, steps, vx0, vy0, vx1, vy1, margin)
