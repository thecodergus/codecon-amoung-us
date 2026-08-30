"""Máquina de estado da animação de jogadores (walk fluida, transição sem salto).

Cobre os defeitos corrigidos em ``Renderer.draw_players``:

- histerese: posições só mudam quando chega snapshot (~20 Hz) e o render roda
  a 60 fps — a animação não pode piscar idle/walk nos frames sem movimento;
- transição idle→walk zera o clock do jogador (o ciclo começa no frame 0);
- suavização exponencial da posição renderizada (sem degrau de 20 Hz), com
  snap em teleporte e sem suavização sob ``reduced_motion``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.config import default_map_path
from codecon_amoung_us.map.loader import load_map
from codecon_amoung_us.protocol import SnapshotPlayer
from codecon_amoung_us.ui.camera import Camera2D
from codecon_amoung_us.ui.render import Renderer
from codecon_amoung_us.ui.sprites import PlayerAnim

_DT = 1.0 / 60.0
_BASE = (2208.0, 1120.0)  # centro do hub (dentro da câmera)


@pytest.fixture()
def renderer() -> Iterator[Renderer]:
    pygame.init()
    yield Renderer(load_map(default_map_path()))


def _camera(renderer: Renderer) -> Camera2D:
    camera = Camera2D(viewport_size=(1280.0, 704.0), bounds=renderer.game_map.bounds())
    camera.snap_to(*_BASE)
    return camera


def _draw(
    renderer: Renderer,
    surface: pygame.Surface,
    camera: Camera2D,
    x: float,
    y: float,
    *,
    alive: bool = True,
) -> None:
    players = [SnapshotPlayer(player_id=0, x=x, y=y, alive=alive)]
    renderer.draw_players(surface, camera, players, 0, dt=_DT)


def _anim_of(renderer: Renderer, player_id: int = 0) -> PlayerAnim:
    return renderer._player_anims[player_id].anim


def test_static_player_stays_idle(renderer: Renderer) -> None:
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    for _ in range(30):
        _draw(renderer, surface, camera, *_BASE)
    assert _anim_of(renderer) is PlayerAnim.IDLE


def test_walk_does_not_flicker_between_snapshots(renderer: Renderer) -> None:
    """Cadência de snapshot (movimento a cada 3 frames): WALK contínuo."""
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    x, y = _BASE
    for frame in range(31):
        if frame % 3 == 1:
            x += 9.0  # 180 px/s a 20 Hz = 9 px por snapshot
        _draw(renderer, surface, camera, x, y)
        if frame >= 1:
            assert _anim_of(renderer) is PlayerAnim.WALK, f"flicker no frame {frame}"


def test_idle_to_walk_transition_resets_clock(renderer: Renderer) -> None:
    """A transição zera o clock: o ciclo de walk começa no frame 0."""
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    x, y = _BASE
    for _ in range(10):
        _draw(renderer, surface, camera, x, y)
    assert renderer._player_anims[0].clock > 0.1  # idle acumulando
    _draw(renderer, surface, camera, x + 9.0, y)  # primeiro movimento
    state = renderer._player_anims[0]
    assert state.anim is PlayerAnim.WALK
    assert state.clock <= 2 * _DT  # zerado na transição + 1 frame


def test_position_smoothing_converges(renderer: Renderer) -> None:
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    x, y = _BASE
    _draw(renderer, surface, camera, x, y)
    target_x = x + 9.0
    _draw(renderer, surface, camera, target_x, y)
    render_x = renderer._player_anims[0].render_x
    assert x < render_x < target_x  # interpola, não salta
    for _ in range(60):
        _draw(renderer, surface, camera, target_x, y)
    assert abs(renderer._player_anims[0].render_x - target_x) < 0.5


def test_teleport_snaps_position(renderer: Renderer) -> None:
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    x, y = _BASE
    _draw(renderer, surface, camera, x, y)
    far_x = x + 200.0
    _draw(renderer, surface, camera, far_x, y)
    assert renderer._player_anims[0].render_x == far_x


def test_reduced_motion_disables_smoothing() -> None:
    pygame.init()
    renderer = Renderer(load_map(default_map_path()), reduced_motion=True)
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    x, y = _BASE
    _draw(renderer, surface, camera, x, y)
    target_x = x + 9.0
    _draw(renderer, surface, camera, target_x, y)
    assert renderer._player_anims[0].render_x == target_x  # snap, sem interpolação


def test_dead_player_shows_death_frame(renderer: Renderer) -> None:
    surface = pygame.Surface((1280, 768))
    camera = _camera(renderer)
    _draw(renderer, surface, camera, *_BASE, alive=False)
    assert _anim_of(renderer) is PlayerAnim.DEATH
