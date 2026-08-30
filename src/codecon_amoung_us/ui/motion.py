"""Sistema de movimento e easing (funções puras).

Durações em categorias (FAST/NORMAL/EMPHASIS) para não repetir valores
arbitrários por tela. Animações devem consultar ``UiSettings.reduced_motion``
antes de aplicar deslocamento/pulse (ver ``theme.py``).
"""

from __future__ import annotations

import cython

__all__ = ["FAST", "NORMAL", "EMPHASIS", "ease_out_cubic", "lerp", "normalized_progress"]

# Durações baseline de design (ms), a validar visualmente.
FAST: float = 100.0
NORMAL: float = 170.0
EMPHASIS: float = 260.0


@cython.ccall
def ease_out_cubic(t: cython.double) -> cython.double:
    """Easing cúbico de saída (desacelera ao final), t em [0, 1]."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


@cython.ccall
def lerp(a: cython.double, b: cython.double, t: cython.double) -> cython.double:
    """Interpolação linear entre ``a`` e ``b`` (t em [0, 1])."""
    return a + (b - a) * t


@cython.ccall
def normalized_progress(
    start: cython.double, duration: cython.double, now: cython.double
) -> cython.double:
    """Progresso normalizado (0..1) de um intervalo de tempo."""
    if duration <= 0:
        return 1.0
    return max(0.0, min(1.0, (now - start) / duration))
