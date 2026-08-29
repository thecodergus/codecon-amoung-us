"""Testes da física de movimento: deslizamento e anti-tunelamento por subpassos."""

from __future__ import annotations

from codecon_amoung_us.game.physics import resolve_movement, resolve_movement_steps
from codecon_amoung_us.map.model import Rect

# Parede vertical de 16 px (espessura mínima das paredes do skeld).
WALL = Rect(x=100.0, y=0.0, width=16.0, height=200.0)


def test_resolve_movement_slides_along_wall() -> None:
    # (95, 50) -> passo de 9 px para a direita entraria na parede [100..116];
    # o eixo x é cancelado e o eixo y desliza
    x, y = resolve_movement(95.0, 50.0, 9.0, 9.0, [WALL])
    assert x == 95.0
    assert y == 59.0


def test_resolve_movement_steps_preserves_free_movement() -> None:
    x, y = resolve_movement_steps(50.0, 50.0, 9.0, 0.0, [], max_step=8.0)
    assert x == 59.0
    assert y == 50.0


def test_resolve_movement_steps_no_tunnel_through_16px_wall() -> None:
    # Deslocamento de 90 px em um único tick (dt anômalo): sem subpassos,
    # o ponto-final (140, 50) estaria dentro/além da parede [100..116].
    x, y = resolve_movement_steps(50.0, 50.0, 90.0, 0.0, [WALL], max_step=8.0)
    assert x < WALL.left  # não transpôs a parede
    assert x >= 90.0  # avançou o máximo possível


def test_resolve_movement_steps_zero_displacement() -> None:
    assert resolve_movement_steps(50.0, 50.0, 0.0, 0.0, [WALL], max_step=8.0) == (50.0, 50.0)
