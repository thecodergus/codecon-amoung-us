"""Renderização do mundo do jogo e helpers de UI (pygame).

Desenha a cena do lab (pré-renderizada), jogadores como sprites duckee
animados (idle/walk/death), corpos com o frame de morte do dono, marcadores
de tarefa e botão de emergência pulsantes, e um painel HUD inferior com
papel, progresso de tarefas, vivos e dica de controles.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pygame

from ..config import default_assets_dir
from ..map.model import GameMap
from ..protocol import SnapshotBody, SnapshotPlayer
from .components import ActionPrompt
from .fonts import FontBook
from .sprites import DuckeeSprites, color_for
from .theme import HUD_HEIGHT, RADIUS, SPACING, TOKENS
from .viewmodel import GameHudView, TaskMarkerState, TaskMarkerView

__all__ = ["Renderer"]

# Paleta (tema lab / among us)
COLOR_BG = (14, 16, 26)
COLOR_PANEL = (20, 24, 38)
COLOR_PANEL_BORDER = (56, 66, 102)
COLOR_TEXT = (235, 235, 235)
COLOR_TEXT_DIM = (155, 162, 190)
COLOR_ACCENT = (255, 122, 26)
COLOR_CREW = (96, 196, 255)
COLOR_IMPOSTOR = (242, 74, 74)
COLOR_TASK = (255, 212, 92)
COLOR_EMERGENCY = (255, 74, 74)
COLOR_ME = (96, 210, 255)
COLOR_BODY_X = (255, 70, 70)

# Área do mundo (1280x704); o restante da janela é o painel HUD.
WORLD_HEIGHT = 704


def _draw_text_with_outline(
    surface: pygame.Surface,
    font: pygame.font.Font,
    text: str,
    center: tuple[int, int],
    color: tuple[int, int, int],
    *,
    outline: tuple[int, int, int] = (10, 12, 18),
) -> None:
    """Texto centralizado com contorno escuro (legível sobre a cena)."""
    base = font.render(text, True, color)
    shadow = font.render(text, True, outline)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                surface.blit(shadow, shadow.get_rect(center=(center[0] + dx, center[1] + dy)))
    surface.blit(base, base.get_rect(center=center))


class Renderer:
    """Desenha o estado do jogo em uma superfície."""

    def __init__(self, game_map: GameMap, *, reduced_motion: bool = False) -> None:
        self.game_map = game_map
        self.reduced_motion = reduced_motion
        self.fonts = FontBook()
        self.font_small = self.fonts.caption
        self.font_med = self.fonts.body
        self.font_big = self.fonts.heading
        self.sprites = DuckeeSprites()
        self._background = self._load_background()
        self._last_pos: dict[int, tuple[float, float]] = {}
        self._last_flip: dict[int, bool] = {}

    def _load_background(self) -> pygame.Surface:
        """Cena do lab em resolução de mundo (1280x704), com fallback plano."""
        path = default_assets_dir() / "maps" / "lab_scene.png"
        if path.is_file():
            return pygame.image.load(str(path))
        background = pygame.Surface((self.game_map.width * self.game_map.tile_width, WORLD_HEIGHT))
        background.fill((30, 34, 44))
        return background

    # ------------------------------------------------------------------ mapa

    def draw_map(
        self, surface: pygame.Surface, markers: list[TaskMarkerView] | None = None
    ) -> None:
        """Cena + marcadores de tarefa contextuais (estado por marcador)."""
        surface.blit(self._background, (0, 0))
        ticks = pygame.time.get_ticks()
        # reduced motion: sem pulsação contínua (marcador estático)
        pulse = 0.0 if self.reduced_motion else (math.sin(ticks / 180.0) + 1.0) / 2.0
        for marker in markers or []:
            self._draw_task_marker(surface, marker, pulse)
        if self.game_map.emergency_meeting is not None:
            # botão de reunião: anel estático (sem pulsação contínua)
            ex, ey = self.game_map.emergency_meeting
            pygame.draw.circle(surface, COLOR_EMERGENCY, (int(ex), int(ey)), 14)
            pygame.draw.circle(surface, (255, 255, 255), (int(ex), int(ey)), 18, 2)

    def _draw_task_marker(
        self, surface: pygame.Surface, marker: TaskMarkerView, pulse: float
    ) -> None:
        x, y = int(marker.x), int(marker.y)
        if marker.state is TaskMarkerState.UNASSIGNED:
            return  # discreta/invisível
        if marker.state is TaskMarkerState.DONE:
            pygame.draw.circle(surface, (62, 68, 84), (x, y), 8)
            pygame.draw.circle(surface, (90, 96, 116), (x, y), 8, 2)
            # check desaturado
            pygame.draw.lines(
                surface, (90, 96, 116), False, [(x - 4, y), (x - 1, y + 4), (x + 5, y - 4)], 2
            )
            return
        if marker.state is TaskMarkerState.INTERACTABLE:
            radius = 8 + int(4 * pulse if marker.pulse else 0)
            color = (255, 224, 132)
            pygame.draw.circle(surface, color, (x, y), radius)
            pygame.draw.circle(surface, (30, 26, 8), (x, y), radius, 2)
            return
        if marker.state is TaskMarkerState.NEAR:
            pygame.draw.circle(surface, (196, 168, 84), (x, y), 7)
            pygame.draw.circle(surface, (30, 26, 8), (x, y), 7, 2)
            return
        pygame.draw.circle(surface, COLOR_TASK, (x, y), 6)
        pygame.draw.circle(surface, (30, 26, 8), (x, y), 6, 2)

    # ------------------------------------------------------------- jogadores

    def draw_players(
        self,
        surface: pygame.Surface,
        players: list[SnapshotPlayer],
        me_id: int,
        *,
        nicknames: Mapping[int, str] | None = None,
    ) -> None:
        ticks = pygame.time.get_ticks()
        for player in players:
            color = color_for(player.player_id)
            last = self._last_pos.get(player.player_id)
            dx = player.x - last[0] if last is not None else 0.0
            dy = player.y - last[1] if last is not None else 0.0
            moving = math.hypot(dx, dy) > 2.0
            if dx < -0.5:
                self._last_flip[player.player_id] = True
            elif dx > 0.5:
                self._last_flip[player.player_id] = False
            flip = self._last_flip.get(player.player_id, False)
            if player.alive:
                anim = "walk" if moving else "idle"
                count = self.sprites.frame_count(color, anim)
                index = (ticks // (130 if moving else 420)) % count
            else:
                anim, index = "death", 0
            sprite = self.sprites.frame(color, anim, index)
            if flip:
                sprite = pygame.transform.flip(sprite, True, False)
            width, height = sprite.get_size()
            surface.blit(sprite, (round(player.x - width / 2), round(player.y - height)))
            nickname = (
                nicknames.get(player.player_id, f"P{player.player_id}")
                if nicknames is not None
                else f"P{player.player_id}"
            )
            _draw_text_with_outline(
                surface,
                self.font_small,
                nickname,
                (round(player.x), round(player.y - height - 14)),
                COLOR_TEXT,
            )
            if player.player_id == me_id and player.alive:
                pygame.draw.circle(surface, COLOR_ME, (round(player.x), round(player.y)), 22, 2)
            self._last_pos[player.player_id] = (player.x, player.y)

    def draw_bodies(self, surface: pygame.Surface, bodies: list[SnapshotBody]) -> None:
        for body in bodies:
            color = color_for(body.player_id)
            sprite = self.sprites.frame(color, "death", 0)
            width, height = sprite.get_size()
            surface.blit(sprite, (round(body.x - width / 2), round(body.y - height)))
            x, y = round(body.x), round(body.y)
            pygame.draw.line(surface, COLOR_BODY_X, (x - 16, y - 16), (x + 16, y + 16), 3)
            pygame.draw.line(surface, COLOR_BODY_X, (x + 16, y - 16), (x - 16, y + 16), 3)

    # ------------------------------------------------------------------- HUD

    def draw_hud(self, surface: pygame.Surface, view: GameHudView) -> None:
        """Faixa inferior compacta (~64 px) dirigida pelo GameHudView."""
        panel = pygame.Rect(
            0, WORLD_HEIGHT, surface.get_width(), surface.get_height() - WORLD_HEIGHT
        )
        pygame.draw.rect(surface, TOKENS.surface_panel, panel)
        pygame.draw.line(
            surface,
            TOKENS.surface_panel_border,
            (0, WORLD_HEIGHT),
            (surface.get_width(), WORLD_HEIGHT),
            2,
        )

        # chip do papel
        chip = pygame.Rect(SPACING, WORLD_HEIGHT + (HUD_HEIGHT - 40) // 2, 150, 40)
        pygame.draw.rect(surface, view.role_color, chip, border_radius=RADIUS)
        pygame.draw.rect(surface, TOKENS.surface_panel_border, chip, width=2, border_radius=RADIUS)
        chip_text = self.font_med.render(view.role_label, True, (12, 14, 20))
        surface.blit(chip_text, chip_text.get_rect(center=chip.center))

        # progresso de tarefas + vivos (texto secundário)
        info_x = chip.right + SPACING * 2
        info = f"Tarefas {view.tasks_done}/{view.tasks_total}   ·   Vivos {view.alive}/{view.total}"
        info_text = self.font_small.render(info, True, TOKENS.text_secondary)
        surface.blit(
            info_text, info_text.get_rect(midleft=(info_x, WORLD_HEIGHT + HUD_HEIGHT // 2))
        )

        # cooldown persistente do impostor (número + texto, nunca só cor)
        if view.kill_cooldown_remaining is not None and view.kill_cooldown_remaining > 0:
            cd_text = self.font_med.render(
                f"Kill: {view.kill_cooldown_remaining:.0f}s", True, TOKENS.status_task
            )
            surface.blit(
                cd_text, cd_text.get_rect(midleft=(info_x + 300, WORLD_HEIGHT + HUD_HEIGHT // 2))
            )

        # prompt de ação contextual (à direita)
        if view.primary_action is not None:
            prompt_rect = pygame.Rect(
                surface.get_width() - 300, WORLD_HEIGHT + (HUD_HEIGHT - 44) // 2, 280, 44
            )
            prompt = ActionPrompt(
                view.primary_action.keycap,
                view.primary_action.label,
                prompt_rect,
                countdown=view.primary_action.countdown,
                font=self.font_med,
            )
            prompt.draw(surface)
