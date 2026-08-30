"""Minigame "Reativar reator": Simon-says 3x3.

O painel exibe uma sequência de pads acendendo um a um; o jogador repete
na mesma ordem. Erro reexibe a sequência (sem perda de progresso além da
tentativa). A sequência vem do RNG semeado — determinística em testes.
``ReactorLogic`` é pura; o wrapper desenha.
"""

from __future__ import annotations

import random

import pygame

from ..fonts import FontBook
from ..theme import TOKENS
from .base import CONTENT_H, CONTENT_W, Minigame, register

__all__ = ["PADS", "ReactorLogic", "ReactorMinigame", "ReactorPhase"]

PADS = 9  # grade 3x3
_PAD = 84
_GAP = 14
_BOARD = 3 * _PAD + 2 * _GAP
_ORIGIN_X = (CONTENT_W - _BOARD) // 2
_ORIGIN_Y = (CONTENT_H - _BOARD) // 2 + 6

ReactorPhase = str  # "showing" | "input" | "done"


class ReactorLogic:
    """Estado do Simon-says (coordenadas locais)."""

    def __init__(self, rng: random.Random, length: int, pads_per_second: float) -> None:
        self.sequence: list[int] = [rng.randrange(PADS) for _ in range(length)]
        self.interval = 1.0 / pads_per_second
        self.phase: ReactorPhase = "showing"
        self.show_index = 0  # próximo pad a exibir
        self.show_timer = 0.0
        self.input_index = 0  # acertos consecutivos na fase de entrada
        self.flash: int | None = None  # pad aceso neste instante
        self.wrong_flash = 0.0  # tempo restante de flash de erro

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def update(self, dt: float) -> None:
        if self.phase != "showing":
            self.wrong_flash = max(0.0, self.wrong_flash - dt)
            return
        self.show_timer += dt
        if self.show_timer < self.interval:
            return
        self.show_timer = 0.0
        if self.show_index < len(self.sequence):
            self.flash = self.sequence[self.show_index]
            self.show_index += 1
        else:
            self.flash = None
            self.phase = "input"
            self.input_index = 0

    def pad_rect(self, pad: int) -> tuple[int, int, int, int]:
        row, col = divmod(pad, 3)
        return (
            _ORIGIN_X + col * (_PAD + _GAP),
            _ORIGIN_Y + row * (_PAD + _GAP),
            _PAD,
            _PAD,
        )

    def press(self, pos: tuple[float, float]) -> None:
        if self.phase != "input":
            return
        for pad in range(PADS):
            x, y, w, h = self.pad_rect(pad)
            if not (x <= pos[0] < x + w and y <= pos[1] < y + h):
                continue
            if pad == self.sequence[self.input_index]:
                self.flash = pad
                self.input_index += 1
                if self.input_index == len(self.sequence):
                    self.phase = "done"
            else:
                # erro: reexibe a sequência desde o início
                self.phase = "showing"
                self.show_index = 0
                self.show_timer = -0.4  # pausa antes de reexibir
                self.flash = None
                self.wrong_flash = 0.5
            return


class ReactorMinigame(Minigame):
    """Wrapper pygame do Simon-says."""

    def __init__(
        self,
        task_id: int,
        *,
        fonts: FontBook,
        seed: int | None = None,
        reduced_motion: bool = False,
    ) -> None:
        super().__init__(task_id, fonts=fonts, seed=seed, reduced_motion=reduced_motion)
        from ...game.task_catalog import difficulty_for

        params = difficulty_for("start_reactor")
        self.logic = ReactorLogic(self.rng, params.targets, params.speed)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.logic.press(self._to_local(event.pos))
        if self.logic.done:
            self._done = True

    def update(self, dt: float) -> None:
        self.logic.update(dt)

    def draw(self, surface: pygame.Surface) -> None:
        ox, oy = self.play_area.x, self.play_area.y
        logic = self.logic
        for pad in range(PADS):
            x, y, w, h = logic.pad_rect(pad)
            rect = pygame.Rect(ox + x, oy + y, w, h)
            lit = pad == logic.flash
            if lit and logic.phase == "showing":
                fill = TOKENS.status_task
            elif lit:
                fill = TOKENS.status_success
            else:
                fill = TOKENS.surface_interactive_pressed
            pygame.draw.rect(surface, fill, rect, border_radius=10)
            border = TOKENS.status_danger if logic.wrong_flash > 0 else TOKENS.surface_panel_border
            pygame.draw.rect(surface, border, rect, 2, border_radius=10)
        if logic.phase == "showing":
            hint = "observe a sequência..."
        elif logic.phase == "input":
            hint = f"repita: {logic.input_index}/{len(logic.sequence)}"
        else:
            hint = "reator ativo!"
        label = self.fonts.body.render(hint, True, TOKENS.text_primary)
        surface.blit(label, label.get_rect(center=(ox + CONTENT_W // 2, oy + 40)))


register("start_reactor", ReactorMinigame)
