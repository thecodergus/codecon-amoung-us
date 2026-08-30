"""Distinguibilidade dos marcadores de tarefa sob deficiência cromática (CVD).

Simula protanopia, deuteranopia e tritanopia sobre os crops dos marcadores
nos estados ASSIGNED/NEAR/INTERACTABLE/DONE e garante que cada par de
estados permanece separável por luminância/geometria mesmo quando a
informação de matiz colapsa — o critério da Game Accessibility Guidelines
("Ensure no essential information is conveyed by a fixed colour alone",
Vision/Basic): cor como reforço, nunca canal único.

Simulação no espaço LMS (Viénot-Brettel-Mollon): matrizes conforme a
implementação de referência daltonize (J. Dietrich, GPL-2 — aqui apenas as
constantes numéricas publicadas), conferida com Chilukala 2026
(DOI 10.1051/itmconf/20268601002: RGB→LMS→déficit→RGB segue o padrão
corrente). Comparação em luminância (não em RGB): se dois estados só se
distinguissem por matiz de mesma luminância, o teste falharia.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from itertools import combinations

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.ui.app import App
from codecon_amoung_us.ui.camera import Camera2D
from codecon_amoung_us.ui.viewmodel import TaskMarkerState, TaskMarkerView

_CROP = 64  # lado do crop quadrado centrado no marcador (px)
_MIN_DIFF_PIXELS = 20  # mínimo de pixels divergentes por par de estados
_LUM_TOLERANCE = 8 / 255  # divergência mínima de luminância por pixel

# RGB -> LMS e inversa (Viénot-Brettel-Mollon, constantes da ref. daltonize).
_RGB2LMS = (
    (0.3904725, 0.54990437, 0.00890159),
    (0.07092586, 0.96310739, 0.00135809),
    (0.02314268, 0.12801221, 0.93605194),
)
_LMS2RGB = (
    (2.85831110, -1.62870796, -0.02481870),
    (-0.210434776, 1.15841493, 0.00032046),
    (-0.0418895045, -0.118154333, 1.06888657),
)
# Déficit no espaço LMS: p=protanopia, d=deuteranopia, t=tritanopia.
_CB_MATRICES = {
    "p": ((0.0, 0.90822864, 0.008192), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "d": ((1.0, 0.0, 0.0), (1.10104433, 0.0, -0.00901975), (0.0, 0.0, 1.0)),
    "t": ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (-0.15773032, 1.19465634, 0.0)),
}

_SEPARABLE_STATES = (
    TaskMarkerState.ASSIGNED,
    TaskMarkerState.NEAR,
    TaskMarkerState.INTERACTABLE,
    TaskMarkerState.DONE,
)


@pytest.fixture(scope="module")
def app() -> Iterator[App]:
    instance = App()
    instance.renderer.reduced_motion = True  # marcadores estáticos (determinismo)
    yield instance
    instance._shutdown_connection()


def _render_marker_pixels(app: App, state: TaskMarkerState) -> list[tuple[int, int, int]]:
    """Crop quadrado do marcador renderizado isolado (pulso fixo em 0)."""
    surface = pygame.Surface((_CROP, _CROP))
    camera = Camera2D(viewport_size=(float(_CROP), float(_CROP)), bounds=app.game_map.bounds())
    half = _CROP / 2.0
    camera.snap_to(half, half)
    marker = TaskMarkerView(task_id=1, x=half, y=half, state=state)
    app.renderer._draw_task_marker(surface, camera, marker, 0.0)
    return [surface.get_at((x, y))[:3] for y in range(_CROP) for x in range(_CROP)]


def _mat_vec(matrix: tuple[tuple[float, float, float], ...], vec: list[float]) -> list[float]:
    return [sum(row[k] * vec[k] for k in range(3)) for row in matrix]


def _simulate_luminance(pixels: list[tuple[int, int, int]], deficit: str) -> list[float]:
    """Luminância por pixel após simular o déficit (canal de matiz removido)."""
    out: list[float] = []
    for r, g, b in pixels:
        lms = _mat_vec(_RGB2LMS, [r / 255.0, g / 255.0, b / 255.0])
        sim = _mat_vec(_CB_MATRICES[deficit], lms)
        sr, sg, sb = (min(1.0, max(0.0, c)) for c in _mat_vec(_LMS2RGB, sim))
        out.append(0.2126 * sr + 0.7152 * sg + 0.0722 * sb)
    return out


def test_cvd_simulation_changes_hue(app: App) -> None:
    """Sanidade: o filtro altera pixels coloridos (não é identidade)."""
    pixels = _render_marker_pixels(app, TaskMarkerState.INTERACTABLE)
    filtered = [
        _mat_vec(
            _LMS2RGB, _mat_vec(_CB_MATRICES["p"], _mat_vec(_RGB2LMS, [r / 255, g / 255, b / 255]))
        )
        for r, g, b in pixels
    ]
    changed = sum(
        1
        for (r, g, b), (fr, fg, fb) in zip(pixels, filtered, strict=True)
        if abs(fr * 255 - r) + abs(fg * 255 - g) + abs(fb * 255 - b) > 24
    )
    assert changed > 0, "simulação de protanopia não alterou nenhum pixel"


@pytest.mark.parametrize("deficit", ["p", "d", "t"])
def test_marker_states_stay_separable_under_cvd(app: App, deficit: str) -> None:
    luminance = {
        state: _simulate_luminance(_render_marker_pixels(app, state), deficit)
        for state in _SEPARABLE_STATES
    }
    for first, second in combinations(_SEPARABLE_STATES, 2):
        diff = sum(
            1
            for la, lb in zip(luminance[first], luminance[second], strict=True)
            if abs(la - lb) > _LUM_TOLERANCE
        )
        assert diff >= _MIN_DIFF_PIXELS, (
            f"estados {first.value}/{second.value} colapsam sob déficit "
            f"'{deficit}': apenas {diff} px divergentes em luminância"
        )
