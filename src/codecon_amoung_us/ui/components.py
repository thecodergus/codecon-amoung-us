"""Componentes reutilizáveis da UI (pygame): Button, PlayerCard, FocusManager.

Os componentes não armazenam regras do jogo: recebem ``state`` pronto (a
tela o deriva do estado/viewmodel) e apenas desenham e respondem a eventos.
Foco de teclado (Tab/Shift+Tab, Enter/Space) é tratado pelo ``FocusManager``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

import pygame

from .fonts import FontBook
from .theme import BORDER, RADIUS, SPACING, TOKENS

__all__ = [
    "ButtonState",
    "Button",
    "FocusManager",
    "Keycap",
    "PlayerCardState",
    "PlayerCard",
    "ProgressBar",
    "ActionPrompt",
]

# Alvo mínimo de área de toque (px lógicos) para ações principais.
MIN_TARGET_SIZE = 40


class ButtonState(StrEnum):
    """Estados visuais de um botão."""

    DEFAULT = "default"
    HOVER = "hover"
    FOCUSED = "focused"
    PRESSED = "pressed"
    SELECTED = "selected"
    DISABLED = "disabled"
    COOLDOWN = "cooldown"


def _surface_color(state: ButtonState) -> tuple[int, int, int]:
    if state is ButtonState.DISABLED:
        return (30, 34, 50)
    if state is ButtonState.PRESSED:
        return TOKENS.surface_interactive_pressed
    if state in (ButtonState.HOVER, ButtonState.FOCUSED, ButtonState.SELECTED):
        return TOKENS.surface_interactive_hover
    return TOKENS.surface_interactive


def _text_color(state: ButtonState) -> tuple[int, int, int]:
    if state is ButtonState.DISABLED:
        return TOKENS.text_disabled
    return TOKENS.text_primary


class Button:
    """Botão de estado explícito (sem regras de jogo; hover por estado)."""

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        label: str,
        on_click: Callable[[], None] | None = None,
        *,
        state: ButtonState = ButtonState.DEFAULT,
        icon: str | None = None,
        font: pygame.font.Font | None = None,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.state = state
        self.icon = icon
        self.font = font if font is not None else FontBook().control

    @property
    def enabled(self) -> bool:
        return self.state is not ButtonState.DISABLED

    def activate(self) -> None:
        """Executa a ação se o botão não estiver desabilitado."""
        if self.enabled and self.on_click is not None:
            self.on_click()

    def draw(self, surface: pygame.Surface) -> None:
        color = _surface_color(self.state)
        pygame.draw.rect(surface, color, self.rect, border_radius=RADIUS)
        pygame.draw.rect(
            surface, TOKENS.surface_panel_border, self.rect, width=BORDER, border_radius=RADIUS
        )
        if self.state is ButtonState.FOCUSED:
            # anel de foco distinto do hover
            ring = self.rect.inflate(6, 6)
            pygame.draw.rect(surface, TOKENS.focus_ring, ring, width=2, border_radius=RADIUS + 2)
        label = self.icon + " " + self.label if self.icon else self.label
        text = self.font.render(label, True, _text_color(self.state))
        surface.blit(text, text.get_rect(center=self.rect.center))

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Processa clique; True se o evento foi consumido."""
        if (
            event.type == pygame.MOUSEBUTTONDOWN
            and event.button == 1
            and self.rect.collidepoint(event.pos)
        ):
            self.activate()
            return True
        return False


class FocusManager:
    """Navegação por teclado entre controles (Tab/Shift+Tab, Enter/Space).

    O foco é visualmente distinto do hover (anel ``focus_ring``).
    """

    def __init__(self, buttons: Sequence[Button]) -> None:
        self._buttons = list(buttons)
        self.index = 0 if self._buttons else -1

    @property
    def focused(self) -> Button | None:
        if self.index < 0 or self.index >= len(self._buttons):
            return None
        button = self._buttons[self.index]
        if not button.enabled:
            self.next()
            return self.focused
        return button

    def next(self) -> None:
        if not self._buttons:
            self.index = -1
            return
        start = self.index
        while True:
            self.index = (self.index + 1) % len(self._buttons)
            if self._buttons[self.index].enabled or self.index == start:
                return

    def previous(self) -> None:
        if not self._buttons:
            self.index = -1
            return
        start = self.index
        while True:
            self.index = (self.index - 1) % len(self._buttons)
            if self._buttons[self.index].enabled or self.index == start:
                return

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_TAB:
            if pygame.key.get_mods() & pygame.KMOD_SHIFT:
                self.previous()
            else:
                self.next()
        elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
            focused = self.focused
            if focused is not None:
                focused.activate()


@dataclass
class Keycap:
    """Chip visual de uma tecla (ex.: [E])."""

    label: str
    rect: pygame.Rect
    font: pygame.font.Font | None = None

    def draw(self, surface: pygame.Surface) -> None:
        font = self.font if self.font is not None else FontBook().body
        pygame.draw.rect(surface, TOKENS.surface_interactive, self.rect, border_radius=6)
        pygame.draw.rect(surface, TOKENS.surface_panel_border, self.rect, width=1, border_radius=6)
        text = font.render(self.label, True, TOKENS.text_primary)
        surface.blit(text, text.get_rect(center=self.rect.center))


class PlayerCardState(StrEnum):
    """Estados do card de jogador (lobby/votação/game over)."""

    NORMAL = "normal"
    HOST = "host"
    SELECTED = "selected"
    DEAD = "dead"
    LOCAL_PLAYER = "local_player"
    WINNER = "winner"
    LOSER = "loser"
    DISABLED = "disabled"


@dataclass
class PlayerCard:
    """Card único de jogador com Duckee, nickname, badge e estado."""

    rect: pygame.Rect
    nickname: str
    avatar: pygame.Surface | None = None
    state: PlayerCardState = PlayerCardState.NORMAL
    secondary: str | None = None
    font: pygame.font.Font | None = None

    def draw(self, surface: pygame.Surface) -> None:
        font = self.font if self.font is not None else FontBook().body
        if self.state is PlayerCardState.SELECTED:
            fill, border = (38, 52, 70), TOKENS.status_info
        elif self.state is PlayerCardState.HOST:
            fill, border = (42, 38, 30), TOKENS.status_task
        elif self.state is PlayerCardState.DEAD or self.state is PlayerCardState.DISABLED:
            fill, border = (24, 26, 34), TOKENS.text_disabled
        elif self.state is PlayerCardState.WINNER:
            fill, border = (28, 46, 34), TOKENS.status_success
        elif self.state is PlayerCardState.LOSER:
            fill, border = (44, 28, 30), TOKENS.status_danger
        else:
            fill, border = TOKENS.surface_panel, TOKENS.surface_panel_border
        pygame.draw.rect(surface, fill, self.rect, border_radius=RADIUS)
        pygame.draw.rect(surface, border, self.rect, width=2, border_radius=RADIUS)
        if self.avatar is not None:
            surface.blit(
                self.avatar, self.avatar.get_rect(center=(self.rect.x + 34, self.rect.centery))
            )
        text_color = (
            TOKENS.text_disabled
            if self.state in (PlayerCardState.DEAD, PlayerCardState.DISABLED)
            else TOKENS.text_primary
        )
        name = font.render(self.nickname, True, text_color)
        surface.blit(name, name.get_rect(midleft=(self.rect.x + 66, self.rect.centery - 12)))
        if self.secondary:
            sec = font.render(self.secondary, True, border)
            surface.blit(sec, sec.get_rect(midleft=(self.rect.x + 66, self.rect.centery + 14)))

    def contains(self, pos: tuple[int, int]) -> bool:
        return self.rect.collidepoint(pos)


@dataclass
class ProgressBar:
    """Barra de progresso simples (preenchimento 0..1)."""

    rect: pygame.Rect
    value: float
    color: tuple[int, int, int] = TOKENS.status_task

    def draw(self, surface: pygame.Surface) -> None:
        pygame.draw.rect(surface, (30, 34, 52), self.rect, border_radius=5)
        fill = pygame.Rect(
            self.rect.x,
            self.rect.y,
            int(self.rect.width * max(0.0, min(1.0, self.value))),
            self.rect.height,
        )
        if fill.width > 0:
            pygame.draw.rect(surface, self.color, fill, border_radius=5)


@dataclass
class ActionPrompt:
    """Prompt de ação contextual: keycap + rótulo + contagem opcional."""

    keycap_label: str
    label: str
    rect: pygame.Rect
    countdown: float | None = None
    font: pygame.font.Font | None = None

    def draw(self, surface: pygame.Surface) -> None:
        font = self.font if self.font is not None else FontBook().body
        pygame.draw.rect(surface, (24, 28, 44), self.rect, border_radius=RADIUS)
        pygame.draw.rect(
            surface, TOKENS.surface_panel_border, self.rect, width=1, border_radius=RADIUS
        )
        key = Keycap(
            self.keycap_label,
            pygame.Rect(self.rect.x + SPACING, self.rect.y + 4, 34, self.rect.height - 8),
            font,
        )
        key.draw(surface)
        text = font.render(self.label, True, TOKENS.text_primary)
        surface.blit(text, text.get_rect(midleft=(key.rect.right + SPACING, self.rect.centery)))
        if self.countdown is not None:
            seconds = max(0.0, self.countdown)
            counter = font.render(f"{seconds:.0f}s", True, TOKENS.status_task)
            surface.blit(
                counter, counter.get_rect(midright=(self.rect.right - SPACING, self.rect.centery))
            )
