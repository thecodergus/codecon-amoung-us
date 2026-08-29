"""Tokens semânticos do design system (cores, espaçamento, radius, motion).

A paleta base é preservada (navy, ciano, amarelo, vermelho, laranja); o que
muda é a semântica: superfícies hierárquicas, estados de interação e
contraste entre texto e fundo. Nenhum pygame aqui — módulo puro e testável.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "ColorTokens",
    "TOKENS",
    "SPACING",
    "RADIUS",
    "BORDER",
    "HUD_HEIGHT",
    "UiSettings",
    "settings_from_env",
]


@dataclass(frozen=True)
class ColorTokens:
    """Cores semânticas do tema (RGB)."""

    # superfícies
    surface_background: tuple[int, int, int] = (14, 16, 26)
    surface_panel: tuple[int, int, int] = (20, 24, 38)
    surface_panel_border: tuple[int, int, int] = (56, 66, 102)
    surface_interactive: tuple[int, int, int] = (52, 62, 100)
    surface_interactive_hover: tuple[int, int, int] = (86, 100, 150)
    surface_interactive_pressed: tuple[int, int, int] = (38, 46, 76)
    # texto
    text_primary: tuple[int, int, int] = (235, 235, 235)
    text_secondary: tuple[int, int, int] = (155, 162, 190)
    text_disabled: tuple[int, int, int] = (105, 112, 138)
    # ação e status
    action_primary: tuple[int, int, int] = (255, 122, 26)
    status_info: tuple[int, int, int] = (96, 196, 255)
    status_task: tuple[int, int, int] = (255, 212, 92)
    status_danger: tuple[int, int, int] = (242, 74, 74)
    status_success: tuple[int, int, int] = (96, 210, 96)
    focus_ring: tuple[int, int, int] = (255, 255, 255)


TOKENS = ColorTokens()

# Espaçamento / raio / borda / altura do HUD (px lógicos)
SPACING: int = 8
RADIUS: int = 10
BORDER: int = 2
HUD_HEIGHT: int = 64


@dataclass(frozen=True)
class UiSettings:
    """Preferências de acessibilidade da UI."""

    reduced_motion: bool = False


def settings_from_env() -> UiSettings:
    """Lê preferências do ambiente (ex.: CODECON_AMONG_US_REDUCED_MOTION=1)."""
    return UiSettings(
        reduced_motion=os.environ.get("CODECON_AMONG_US_REDUCED_MOTION", "").lower()
        in ("1", "true", "yes"),
    )
