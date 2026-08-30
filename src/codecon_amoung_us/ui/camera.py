"""Câmera 2D do gameplay (cliente/UI apenas — nunca rede nem servidor).

Separa as coordenadas do **mundo** (posições autoritativas) das coordenadas
de **tela** (viewport lógico de gameplay). O alvo é o centro do jogador
local; quem se move é a câmera, nunca o jogador. A suavização usa
amortecimento exponencial dependente de ``dt`` (segundos), equivalente a
``alpha = 1 - exp(-follow_rate * dt)``, o que torna o movimento
aproximadamente independente da taxa de frames.

Sem dependência de pygame (floats puros) para testabilidade direta.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = ["FOLLOW_RATE", "DT_MAX", "Camera2D"]

# Taxa de acompanhamento do amortecimento exponencial (1/s). Valores maiores
# aproximam a câmera do alvo mais rápido; ~8 dá resposta firme sem degrau.
FOLLOW_RATE: float = 8.0
# Teto de dt por frame (s): protege contra saltos após travamentos,
# breakpoints ou Alt+Tab.
DT_MAX: float = 0.1


@dataclass
class Camera2D:
    """Câmera com centro em float, clamp nos bounds e offset inteiro puro.

    ``viewport_size`` é o tamanho do viewport lógico de gameplay (px);
    ``bounds`` são os limites do mundo ``(esquerda, topo, direita, base)``,
    derivados de ``GameMap.bounds()``.
    """

    viewport_size: tuple[float, float]
    bounds: tuple[float, float, float, float]
    follow_rate: float = FOLLOW_RATE
    _cx: float = field(default=0.0, repr=False)
    _cy: float = field(default=0.0, repr=False)

    def __post_init__(self) -> None:
        self._cx, self._cy = self._clamp_center(self._cx, self._cy)

    # -------------------------------------------------------------- estado

    @property
    def center(self) -> tuple[float, float]:
        """Centro atual da câmera em coordenadas de mundo (float)."""
        return self._cx, self._cy

    def _clamp_center(self, cx: float, cy: float) -> tuple[float, float]:
        """Limita o centro para que a câmera nunca exiba área fora do mundo.

        Em cada eixo com mapa maior que o viewport, o centro fica em
        ``[viewport/2, bound_max - viewport/2]``; caso contrário o eixo fica
        fixo no centro do mapa. Perto das bordas o jogador deixa de ficar
        exatamente centralizado — comportamento esperado.
        """
        left, top, right, bottom = self.bounds
        vw, vh = self.viewport_size
        if right - left > vw:
            cx = min(max(cx, left + vw / 2), right - vw / 2)
        else:
            cx = (left + right) / 2
        if bottom - top > vh:
            cy = min(max(cy, top + vh / 2), bottom - vh / 2)
        else:
            cy = (top + bottom) / 2
        return cx, cy

    # ----------------------------------------------------------- movimento

    def snap_to(self, cx: float, cy: float) -> None:
        """Posiciona a câmera imediatamente no alvo (já clampado).

        Usado na primeira aparição do jogador local: o primeiro frame válido
        começa na posição do jogador, sem travelling desde a origem.
        """
        self._cx, self._cy = self._clamp_center(cx, cy)

    def update(self, target: tuple[float, float], dt: float) -> None:
        """Avança a câmera em direção ao alvo com amortecimento exponencial.

        ``dt`` em segundos, limitado a ``DT_MAX``. Por construção a posição
        aproxima-se monotonicamente do alvo clampado, sem ultrapassá-lo.
        """
        dt = min(max(dt, 0.0), DT_MAX)
        tx, ty = self._clamp_center(*target)
        alpha = 1.0 - math.exp(-self.follow_rate * dt)
        self._cx += (tx - self._cx) * alpha
        self._cy += (ty - self._cy) * alpha

    # ------------------------------------------------------- transformação

    def offset(self) -> tuple[int, int]:
        """Origem da câmera (canto superior esquerdo) em px, inteiro.

        Função pura do estado: um único valor por frame, compartilhado por
        todos os elementos do mundo — evita jitter relativo por
        arredondamentos divergentes.
        """
        vw, vh = self.viewport_size
        return round(self._cx - vw / 2), round(self._cy - vh / 2)

    def world_to_screen(self, x: float, y: float) -> tuple[float, float]:
        """Mundo -> tela (viewport lógico de gameplay, origem em (0, 0))."""
        ox, oy = self.offset()
        return x - ox, y - oy

    def screen_to_world(self, x: float, y: float) -> tuple[float, float]:
        """Tela -> mundo (inverso exato de ``world_to_screen``)."""
        ox, oy = self.offset()
        return x + ox, y + oy
