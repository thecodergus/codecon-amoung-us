"""Invariantes estruturais dos 7 minigames (checklist A-07 parametrizado).

Complementa ``test_puzzles.py`` (lógica por tipo) com invariantes que valem
para todos os tipos: estado inicial limpo, propagação de ``reduced_motion``,
isolamento entre instâncias (sem estado compartilhado) e — para os puzzles
posicionais — cliques fora da ``play_area`` são no-op. Puzzles de timing
(``calibrate``, ``swipe_card``) tratam clique/ESPAÇO como "press" em qualquer
posição por design, então ficam fora do caso posicional.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from codecon_amoung_us.game.task_catalog import TASK_TYPES  # noqa: E402
from codecon_amoung_us.ui.fonts import FontBook  # noqa: E402
from codecon_amoung_us.ui.puzzles import create_minigame  # noqa: E402
from codecon_amoung_us.ui.puzzles.base import CONTENT_H, CONTENT_W  # noqa: E402

_POSITIONAL_TYPES = ("wires", "fix_wiring", "clean_filter", "start_reactor", "asteroids")


@pytest.fixture(scope="module")
def fonts() -> FontBook:
    pygame.init()
    return FontBook()


@pytest.mark.parametrize("task_type", TASK_TYPES)
def test_estado_inicial_limpo(fonts: FontBook, task_type: str) -> None:
    game = create_minigame(task_type, task_id=3, fonts=fonts, seed=1)
    assert game.task_type == task_type
    assert game.task_id == 3
    assert not game.done
    assert (game.play_area.width, game.play_area.height) == (CONTENT_W, CONTENT_H)


@pytest.mark.parametrize("task_type", TASK_TYPES)
def test_reduced_motion_propagado(fonts: FontBook, task_type: str) -> None:
    game = create_minigame(task_type, task_id=1, fonts=fonts, seed=1, reduced_motion=True)
    assert game.reduced_motion is True


@pytest.mark.parametrize("task_type", TASK_TYPES)
def test_instancias_nao_compartilham_estado(fonts: FontBook, task_type: str) -> None:
    a = create_minigame(task_type, task_id=1, fonts=fonts, seed=1)
    b = create_minigame(task_type, task_id=1, fonts=fonts, seed=1)
    assert a.logic is not b.logic
    assert a.rng is not b.rng


@pytest.mark.parametrize("task_type", _POSITIONAL_TYPES)
def test_clique_fora_da_play_area_e_noop(fonts: FontBook, task_type: str) -> None:
    game = create_minigame(task_type, task_id=1, fonts=fonts, seed=1)
    game.play_area = pygame.Rect(400, 300, CONTENT_W, CONTENT_H)
    far_away = (10, 10)  # tela, fora da play_area deslocada
    game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=far_away, button=1))
    game.handle_event(pygame.event.Event(pygame.MOUSEMOTION, pos=far_away, buttons=(1, 0, 0)))
    game.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=far_away, button=1))
    assert not game.done
