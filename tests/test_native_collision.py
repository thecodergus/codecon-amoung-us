"""Equivalência do kernel de colisão (``game/_native_collision``) com a física.

``game/physics.py`` é o oráculo: o kernel sobre paredes achatadas deve
produzir posições **bit a bit idênticas** às de ``resolve_movement_steps``
para qualquer entrada — inclusive ``dx``/``dy`` anômalos (dt de 0,5 s, que
força dezenas de subpassos) e margens positivas. Roda igual nos modos puro
e compilado (paridade do kernel).
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from codecon_amoung_us.game._native_collision import (
    flatten_walls,
    resolve_movement_steps_flat,
)
from codecon_amoung_us.game.physics import resolve_movement_steps
from codecon_amoung_us.map.model import Rect

# Coordenadas/deltas limitados ao envelope real do jogo (mapa ~2-3k px,
# FloatRange do protocolo em ±1e6), longe de overflow de double.
_coord = st.floats(-2048.0, 4096.0, allow_nan=False, allow_infinity=False)
_delta = st.floats(-1024.0, 1024.0, allow_nan=False, allow_infinity=False)
_size = st.floats(1.0, 512.0, allow_nan=False, allow_infinity=False)
_max_step = st.floats(0.5, 64.0, allow_nan=False, allow_infinity=False)
_margin = st.floats(0.0, 8.0, allow_nan=False, allow_infinity=False)

_walls = st.lists(
    st.builds(lambda x, y, w, h: Rect(x=x, y=y, width=w, height=h), _coord, _coord, _size, _size),
    max_size=48,
)


@given(
    x=_coord,
    y=_coord,
    dx=_delta,
    dy=_delta,
    walls=_walls,
    max_step=_max_step,
    margin=_margin,
)
@settings(max_examples=2000)
def test_kernel_matches_physics_bitwise(
    x: float,
    y: float,
    dx: float,
    dy: float,
    walls: list[Rect],
    max_step: float,
    margin: float,
) -> None:
    expected = resolve_movement_steps(x, y, dx, dy, walls, max_step=max_step, margin=margin)
    actual = resolve_movement_steps_flat(
        x, y, dx, dy, flatten_walls(walls), max_step=max_step, margin=margin
    )
    assert actual == expected


def test_flatten_walls_matches_rect_geometry() -> None:
    walls = [
        Rect(x=1.5, y=-2.0, width=16.0, height=32.0),
        Rect(x=0.0, y=0.0, width=1.0, height=1.0),
    ]
    x0, y0, x1, y1 = flatten_walls(walls)
    assert list(x0) == [1.5, 0.0]
    assert list(y0) == [-2.0, 0.0]
    assert list(x1) == [17.5, 1.0]
    assert list(y1) == [30.0, 1.0]


def test_empty_walls_never_collides() -> None:
    # Sem paredes o movimento nunca é bloqueado; o valor exato tem a mesma
    # acumulação de subpassos da referência (comparação contra o oráculo).
    expected = resolve_movement_steps(0.0, 0.0, 30.0, 40.0, [], max_step=8.0)
    assert (
        resolve_movement_steps_flat(0.0, 0.0, 30.0, 40.0, flatten_walls([]), max_step=8.0)
        == expected
    )
