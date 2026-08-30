"""Testes da Camera2D (sem display: floats puros, sem pygame).

Cobre centralização longe das bordas, clamp nos quatro cantos, snap inicial
sem travelling, suavização monótona sem overshoot, independência
aproximada de FPS e o roundtrip mundo<->tela.
"""

from __future__ import annotations

import math

import pytest

from codecon_amoung_us.ui.camera import DT_MAX, Camera2D

# Mundo do lab triplicado: 4480x2432; viewport de gameplay 1280x704.
VIEWPORT = (1280.0, 704.0)
BOUNDS = (0.0, 0.0, 4480.0, 2432.0)


@pytest.fixture
def camera() -> Camera2D:
    return Camera2D(viewport_size=VIEWPORT, bounds=BOUNDS)


def _simulate(camera: Camera2D, target: tuple[float, float], dt: float, steps: int) -> None:
    for _ in range(steps):
        camera.update(target, dt)


def test_centering_away_from_borders(camera: Camera2D) -> None:
    target = (1280.0, 704.0)  # centro do mapa, longe de qualquer borda
    camera.snap_to(*target)
    assert camera.center == pytest.approx(target)
    _simulate(camera, target, 1 / 60, 120)
    assert camera.center == pytest.approx(target)
    # jogador aparece no centro do viewport: tela = mundo - offset
    sx, sy = camera.world_to_screen(*target)
    assert (sx, sy) == pytest.approx((VIEWPORT[0] / 2, VIEWPORT[1] / 2))


@pytest.mark.parametrize(
    ("player", "expected_offset"),
    [
        ((32.0, 32.0), (0, 0)),  # canto superior esquerdo
        ((4448.0, 32.0), (4480 - 1280, 0)),  # canto superior direito
        ((32.0, 2400.0), (0, 2432 - 704)),  # canto inferior esquerdo
        ((4448.0, 2400.0), (4480 - 1280, 2432 - 704)),  # canto inferior direito
    ],
)
def test_clamp_corners(
    camera: Camera2D, player: tuple[float, float], expected_offset: tuple[int, int]
) -> None:
    camera.snap_to(*player)
    assert camera.offset() == expected_offset
    _simulate(camera, player, 1 / 60, 120)
    assert camera.offset() == expected_offset
    # nenhuma área fora do mapa é exibida
    assert camera.screen_to_world(0.0, 0.0) == expected_offset


def test_snap_initializes_on_player(camera: Camera2D) -> None:
    # primeiro snapshot válido: câmera começa no jogador, sem travelling
    camera.snap_to(1900.0, 900.0)
    cx, cy = camera.center
    assert (cx, cy) == pytest.approx((1900.0, 900.0))
    assert camera.offset() == (round(1900 - 640), round(900 - 352))


def test_smoothing_converges_without_overshoot(camera: Camera2D) -> None:
    camera.snap_to(1280.0, 704.0)
    target = (1700.0, 900.0)  # salto abrupto do alvo
    previous = camera.center
    for _ in range(240):  # 4 s a 60 Hz
        camera.update(target, 1 / 60)
        current = camera.center
        # aproximação monótona (distância nunca aumenta) e sem overshoot
        assert math.dist(current, target) <= math.dist(previous, target) + 1e-9
        assert current[0] <= target[0] + 1e-9
        assert current[1] <= target[1] + 1e-9
        previous = current
    assert math.dist(camera.center, target) < 1.0


def test_dt_clamped_after_long_frame(camera: Camera2D) -> None:
    camera.snap_to(1280.0, 704.0)
    camera.update((1700.0, 704.0), 10.0)  # Alt+Tab: dt gigante é limitado
    # com dt limitado a DT_MAX, alpha = 1 - exp(-8 * 0.1) < 1: sem salto total
    cx, _ = camera.center
    assert cx < 1280.0 + (1700.0 - 1280.0) * (1.0 - math.exp(-8.0 * DT_MAX)) + 1e-9
    assert DT_MAX < 1.0


def test_fps_independence(camera: Camera2D) -> None:
    target = (1800.0, 1000.0)
    finals: list[tuple[float, float]] = []
    for fps in (30, 60, 120):
        cam = Camera2D(viewport_size=VIEWPORT, bounds=BOUNDS)
        cam.snap_to(1280.0, 704.0)
        _simulate(cam, target, 1 / fps, 2 * fps)  # mesmo total: 2 s
        finals.append(cam.center)
    baseline = finals[0]
    for other in finals[1:]:
        # tolerância ~0,5% da distância percorrida (~640 px)
        assert math.dist(other, baseline) < 4.0


def test_world_screen_roundtrip(camera: Camera2D) -> None:
    camera.snap_to(1500.0, 800.0)
    for point in [(1500.0, 800.0), (1000.0, 600.0), (2100.0, 1100.0)]:
        sx, sy = camera.world_to_screen(*point)
        assert camera.screen_to_world(sx, sy) == point


def test_offset_is_single_int_per_state(camera: Camera2D) -> None:
    camera.snap_to(1500.7, 800.3)
    first = camera.offset()
    second = camera.offset()
    assert first == second
    assert all(isinstance(component, int) for component in first)
