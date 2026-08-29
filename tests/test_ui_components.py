"""Testes dos componentes de UI (SDL dummy).

Cobre estados de ``Button`` (draw sem exceção, disabled não clica, foco via
Tab/Enter/Space, targets >= 40 px), ``PlayerCard`` (estados e clique) e o
contrato de não armazenar regras do jogo.
"""

from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from codecon_amoung_us.ui.components import (
    MIN_TARGET_SIZE,
    ActionPrompt,
    Button,
    ButtonState,
    FocusManager,
    PlayerCard,
    PlayerCardState,
    ProgressBar,
)

pytestmark = pytest.mark.ui


def test_button_draws_in_every_state() -> None:
    pygame.init()
    surface = pygame.Surface((400, 300))
    for state in ButtonState:
        button = Button((10, 10, 120, 44), "ok", state=state)
        button.draw(surface)


def test_button_click_fires_callback() -> None:
    pygame.init()
    calls: list[int] = []
    button = Button((10, 10, 100, 40), "ok", lambda: calls.append(1))
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(50, 30))
    button.handle_event(event)
    assert calls == [1]
    # clique fora do retângulo não dispara
    outside = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(500, 500))
    button.handle_event(outside)
    assert calls == [1]


def test_disabled_button_does_not_activate() -> None:
    pygame.init()
    calls: list[int] = []
    button = Button((10, 10, 100, 40), "ok", lambda: calls.append(1), state=ButtonState.DISABLED)
    event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(50, 30))
    button.handle_event(event)
    assert calls == []
    button.activate()
    assert calls == []


def test_main_action_targets_are_at_least_40px() -> None:
    assert MIN_TARGET_SIZE >= 40
    pygame.init()
    buttons = [
        Button((10, 10, 40, 40), "a"),
        Button((10, 10, 120, 44), "b"),
        Button((10, 10, 200, 40), "c"),
    ]
    for button in buttons:
        assert button.rect.width >= MIN_TARGET_SIZE
        assert button.rect.height >= MIN_TARGET_SIZE


def test_focus_manager_tab_cycles_and_activates(monkeypatch: pytest.MonkeyPatch) -> None:
    pygame.init()
    calls: list[int] = []
    buttons = [
        Button((10, 10, 100, 40), "a", lambda: calls.append(0)),
        Button((10, 60, 100, 40), "b", lambda: calls.append(1)),
        Button((10, 110, 100, 40), "c", lambda: calls.append(2)),
    ]
    focus = FocusManager(buttons)
    monkeypatch.setattr(pygame.key, "get_mods", lambda: 0)
    tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
    focus.handle_event(tab)
    assert focus.index == 1
    focus.handle_event(tab)
    assert focus.index == 2
    focus.handle_event(tab)
    assert focus.index == 0  # cíclico
    # Shift+Tab volta
    monkeypatch.setattr(pygame.key, "get_mods", lambda: pygame.KMOD_SHIFT)
    shift_tab = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
    focus.handle_event(shift_tab)
    assert focus.index == len(buttons) - 1
    # Enter ativa o foco atual
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN)
    focus.handle_event(enter)
    assert calls == [len(buttons) - 1]


def test_focus_skips_disabled_buttons() -> None:
    pygame.init()
    buttons = [
        Button((10, 10, 100, 40), "a", state=ButtonState.DISABLED),
        Button((10, 60, 100, 40), "b"),
        Button((10, 110, 100, 40), "c"),
    ]
    focus = FocusManager(buttons)
    assert focus.focused is buttons[1]  # nunca cai no disabled


def test_player_card_draws_every_state() -> None:
    pygame.init()
    surface = pygame.Surface((400, 300))
    for state in PlayerCardState:
        card = PlayerCard(
            pygame.Rect(10, 10, 200, 64), "gustavo", state=state, secondary="IMPOSTOR"
        )
        card.draw(surface)


def test_player_card_hit_testing() -> None:
    pygame.init()
    card = PlayerCard(pygame.Rect(10, 10, 200, 64), "gustavo")
    assert card.contains((100, 40))
    assert not card.contains((400, 200))


def test_progress_bar_and_action_prompt_draw() -> None:
    pygame.init()
    surface = pygame.Surface((400, 300))
    ProgressBar(pygame.Rect(10, 10, 200, 10), value=0.4).draw(surface)
    ActionPrompt("E", "INTERAGIR", pygame.Rect(10, 30, 240, 44)).draw(surface)
    ActionPrompt("SPACE", "ELIMINAR", pygame.Rect(10, 80, 280, 44), countdown=7.0).draw(surface)


def test_renderer_reduced_motion_disables_pulse() -> None:
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map
    from codecon_amoung_us.ui.render import Renderer
    from codecon_amoung_us.ui.viewmodel import TaskMarkerState, TaskMarkerView

    pygame.init()
    renderer = Renderer(load_map(default_map_path()), reduced_motion=True)
    assert renderer.reduced_motion is True
    surface = pygame.Surface((1280, 768))
    markers = [TaskMarkerView(1, 300.0, 300.0, TaskMarkerState.INTERACTABLE, pulse=True)]
    renderer.draw_map(surface, markers)  # desenha sem pulsação contínua


def test_ui_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from codecon_amoung_us.ui.theme import settings_from_env

    monkeypatch.delenv("CODECON_AMONG_US_REDUCED_MOTION", raising=False)
    assert settings_from_env().reduced_motion is False
    monkeypatch.setenv("CODECON_AMONG_US_REDUCED_MOTION", "1")
    assert settings_from_env().reduced_motion is True
