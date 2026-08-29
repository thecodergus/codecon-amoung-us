"""Testes de layout (viewport/letterbox), motion e tokens — puros, sem pygame.

Cobre ``fit_viewport`` em 4 resoluções (aspect preservado, roundtrip de
coordenadas, letterbox sem interação), easing/motion e contraste heurístico
dos tokens de texto.
"""

from __future__ import annotations

import pytest

from codecon_amoung_us.ui.layout import fit_viewport
from codecon_amoung_us.ui.motion import ease_out_cubic, lerp, normalized_progress
from codecon_amoung_us.ui.theme import TOKENS

LOGICAL = (1280, 768)

RESOLUTIONS = [
    (1280, 768),
    (1366, 768),
    (1920, 1080),
    (2560, 1440),
]


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Razão de contraste WCAG (heurística) entre duas cores."""

    def luminance(c: tuple[int, int, int]) -> float:
        def channel(v: int) -> float:
            x = v / 255.0
            return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(v) for v in c)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    l1, l2 = luminance(a), luminance(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("physical", RESOLUTIONS)
def test_fit_viewport_preserves_aspect(physical: tuple[int, int]) -> None:
    transform = fit_viewport(LOGICAL, physical)
    pw, ph = physical
    lw, lh = LOGICAL
    assert transform.scale > 0
    # viewport dentro da janela
    assert transform.offset_x >= 0 and transform.offset_y >= 0
    assert transform.offset_x + lw * transform.scale <= pw + 1e-6
    assert transform.offset_y + lh * transform.scale <= ph + 1e-6
    # aspect ratio preservado
    assert abs(transform.scale - min(pw / lw, ph / lh)) < 1e-9


@pytest.mark.parametrize("physical", RESOLUTIONS)
def test_screen_logical_roundtrip(physical: tuple[int, int]) -> None:
    transform = fit_viewport(LOGICAL, physical)
    for x, y in [(0.0, 0.0), (640.0, 384.0), (1279.0, 767.0)]:
        sx, sy = transform.logical_to_screen(x, y)
        rx, ry = transform.screen_to_logical(sx, sy)
        assert abs(rx - x) < 1e-6 and abs(ry - y) < 1e-6


@pytest.mark.parametrize("physical", RESOLUTIONS)
def test_points_outside_viewport_are_not_interactive(physical: tuple[int, int]) -> None:
    transform = fit_viewport(LOGICAL, physical)
    pw, ph = physical
    # quando há letterbox, os cantos da janela ficam fora do viewport lógico
    if transform.offset_x > 0 or transform.offset_y > 0:
        for corner in [(0, 0), (pw - 1, 0), (0, ph - 1), (pw - 1, ph - 1)]:
            assert transform.contains_physical(*corner) is False
    # centro lógico mapeado dentro do viewport (sempre)
    cx, cy = transform.logical_to_screen(640.0, 384.0)
    assert transform.contains_physical(cx, cy) is True
    # todo ponto dentro do retângulo do viewport é interativo
    inside = transform.logical_to_screen(100.0, 100.0)
    assert transform.contains_physical(*inside) is True


def test_fit_viewport_requires_positive_dimensions() -> None:
    with pytest.raises(ValueError):
        fit_viewport((0, 768), (1920, 1080))
    with pytest.raises(ValueError):
        fit_viewport(LOGICAL, (0, 0))


def test_fit_viewport_letterbox_for_wide_window() -> None:
    # janela muito larga: barras laterais, offset_x > 0
    transform = fit_viewport(LOGICAL, (2560, 768))
    assert transform.offset_x > 0
    assert transform.offset_y == 0


def test_ease_out_cubic_bounds() -> None:
    assert ease_out_cubic(0.0) == 0.0
    assert ease_out_cubic(1.0) == 1.0
    assert 0.0 < ease_out_cubic(0.5) < 1.0
    assert ease_out_cubic(0.5) > 0.5  # desacelera no fim


def test_lerp_basic() -> None:
    assert lerp(0.0, 10.0, 0.0) == 0.0
    assert lerp(0.0, 10.0, 1.0) == 10.0
    assert lerp(0.0, 10.0, 0.5) == 5.0


def test_normalized_progress() -> None:
    assert normalized_progress(start=10.0, duration=2.0, now=10.0) == 0.0
    assert normalized_progress(start=10.0, duration=2.0, now=12.0) == 1.0
    assert normalized_progress(start=10.0, duration=2.0, now=11.0) == 0.5
    assert normalized_progress(start=0.0, duration=0.0, now=5.0) == 1.0


def test_tokens_contrast_heuristic() -> None:
    """Contraste mínimo heurístico: texto primário e secundário sobre fundo."""
    assert _contrast(TOKENS.text_primary, TOKENS.surface_background) >= 4.5
    assert _contrast(TOKENS.text_secondary, TOKENS.surface_background) >= 3.0
    # foco distingue-se da superfície (visível)
    assert _contrast(TOKENS.focus_ring, TOKENS.surface_panel) >= 2.0


def test_tokens_preserve_palette() -> None:
    # a paleta original é preservada: navy, ciano, amarelo, vermelho, laranja
    assert TOKENS.surface_background == (14, 16, 26)
    assert TOKENS.status_info == (96, 196, 255)
    assert TOKENS.status_task == (255, 212, 92)
    assert TOKENS.status_danger == (242, 74, 74)
    assert TOKENS.action_primary == (255, 122, 26)
