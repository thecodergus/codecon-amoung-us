"""Renderização do mundo do jogo e helpers de UI (pygame).

Desenha a cena do lab (pré-renderizada, maior que o viewport), jogadores
como sprites duckee animados (idle/walk/death), corpos com o frame de morte
do dono, marcadores de tarefa e botão de emergência pulsantes, e um painel
HUD inferior com papel, progresso de tarefas, vivos e dica de controles.

Todos os elementos do mundo passam pela mesma transformação da ``Camera2D``
(mundo -> tela) recebida como parâmetro; o HUD não faz parte do mundo e não
recebe offset de câmera.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import pygame

from ..config import default_assets_dir
from ..map.model import GameMap
from ..protocol import SnapshotBody, SnapshotPlayer
from .camera import Camera2D
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

# Viewport lógico de gameplay (1280x704); o restante da janela é o painel
# HUD. O mundo do mapa é maior — a câmera recorta a região visível.
WORLD_WIDTH = 1280
WORLD_HEIGHT = 704

# Margem de culling (px) além do retângulo da câmera: cobre sprites e
# marcadores parcialmente visíveis na borda.
_CULL_MARGIN = 64


def _in_view(camera: Camera2D, x: float, y: float) -> bool:
    """True se o ponto do mundo está dentro do retângulo da câmera (+ margem)."""
    sx, sy = camera.world_to_screen(x, y)
    return -_CULL_MARGIN <= sx <= WORLD_WIDTH + _CULL_MARGIN and (
        -_CULL_MARGIN <= sy <= WORLD_HEIGHT + _CULL_MARGIN
    )


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
        """Cena do lab em resolução de mundo (maior que o viewport).

        Garante o tamanho exato do mundo para que o blit com ``area``
        (recorte da câmera) seja sempre válido; o ajuste acontece uma única
        vez no carregamento, nunca por frame.
        """
        world_w = self.game_map.width * self.game_map.tile_width
        world_h = self.game_map.height * self.game_map.tile_height
        path = default_assets_dir() / "maps" / "lab_scene.png"
        if path.is_file():
            background = pygame.image.load(str(path))
            if background.get_size() != (world_w, world_h):
                background = pygame.transform.smoothscale(background, (world_w, world_h))
            return background
        background = pygame.Surface((world_w, world_h))
        background.fill((30, 34, 44))
        return background

    # ------------------------------------------------------------------ mapa

    def draw_map(
        self,
        surface: pygame.Surface,
        camera: Camera2D,
        markers: list[TaskMarkerView] | None = None,
    ) -> None:
        """Recorte da câmera da cena + marcadores de tarefa contextuais."""
        ox, oy = camera.offset()
        surface.blit(self._background, (0, 0), area=pygame.Rect(ox, oy, WORLD_WIDTH, WORLD_HEIGHT))
        ticks = pygame.time.get_ticks()
        # reduced motion: sem pulsação contínua (marcador estático)
        pulse = 0.0 if self.reduced_motion else (math.sin(ticks / 180.0) + 1.0) / 2.0
        for marker in markers or []:
            self._draw_task_marker(surface, camera, marker, pulse)
        if self.game_map.emergency_meeting is not None:
            ex, ey = self.game_map.emergency_meeting
            if _in_view(camera, ex, ey):
                # botão de reunião: anel estático (sem pulsação contínua)
                sx, sy = camera.world_to_screen(ex, ey)
                pygame.draw.circle(surface, COLOR_EMERGENCY, (int(sx), int(sy)), 14)
                pygame.draw.circle(surface, (255, 255, 255), (int(sx), int(sy)), 18, 2)

    def _draw_task_marker(
        self, surface: pygame.Surface, camera: Camera2D, marker: TaskMarkerView, pulse: float
    ) -> None:
        if marker.state is TaskMarkerState.UNASSIGNED:
            return  # discreta/invisível
        if not _in_view(camera, marker.x, marker.y):
            return  # fora do retângulo da câmera
        sx, sy = camera.world_to_screen(marker.x, marker.y)
        x, y = int(sx), int(sy)
        if marker.state is TaskMarkerState.DONE:
            pygame.draw.circle(surface, (62, 68, 84), (x, y), 8)
            pygame.draw.circle(surface, (90, 96, 116), (x, y), 8, 2)
            # check desaturado
            pygame.draw.lines(
                surface, (90, 96, 116), False, [(x - 4, y), (x - 1, y + 4), (x + 5, y - 4)], 2
            )
            return
        # Estados ativos: losango (forma própria — nunca só cor). NEAR ganha
        # um anel externo; INTERACTABLE é preenchido, pulsa e mostra "!".
        if marker.state is TaskMarkerState.INTERACTABLE:
            radius = 10 + int(4 * pulse if marker.pulse else 0)
            points = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
            pygame.draw.polygon(surface, (255, 224, 132), points)
            pygame.draw.polygon(surface, (30, 26, 8), points, 2)
            # glifo "!" (signifier de ação disponível, desenhado sem fonte)
            pygame.draw.rect(surface, (30, 26, 8), (x - 1, y - radius // 2, 3, radius // 2 + 1))
            pygame.draw.circle(surface, (30, 26, 8), (x, y + radius // 2 - 1), 2)
            return
        if marker.state is TaskMarkerState.NEAR:
            radius = 8
            points = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
            pygame.draw.polygon(surface, (24, 28, 40), points)
            pygame.draw.polygon(surface, (255, 224, 132), points, 2)
            pygame.draw.circle(surface, (255, 224, 132), (x, y), radius + 5, 2)
            return
        radius = 7
        points = [(x, y - radius), (x + radius, y), (x, y + radius), (x - radius, y)]
        pygame.draw.polygon(surface, (24, 28, 40), points)
        pygame.draw.polygon(surface, COLOR_TASK, points, 2)

    # ------------------------------------------------------------- jogadores

    def draw_players(
        self,
        surface: pygame.Surface,
        camera: Camera2D,
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
            if not _in_view(camera, player.x, player.y):
                self._last_pos[player.player_id] = (player.x, player.y)
                continue  # fora do retângulo da câmera
            sx, sy = camera.world_to_screen(player.x, player.y)
            sprite = self.sprites.frame(color, anim, index)
            if flip:
                sprite = pygame.transform.flip(sprite, True, False)
            width, height = sprite.get_size()
            surface.blit(sprite, (round(sx - width / 2), round(sy - height)))
            nickname = (
                nicknames.get(player.player_id, f"P{player.player_id}")
                if nicknames is not None
                else f"P{player.player_id}"
            )
            _draw_text_with_outline(
                surface,
                self.font_small,
                nickname,
                (round(sx), round(sy - height - 14)),
                COLOR_TEXT,
            )
            if player.player_id == me_id and player.alive:
                pygame.draw.circle(surface, COLOR_ME, (round(sx), round(sy)), 22, 2)
            self._last_pos[player.player_id] = (player.x, player.y)

    def draw_bodies(
        self, surface: pygame.Surface, camera: Camera2D, bodies: list[SnapshotBody]
    ) -> None:
        for body in bodies:
            if not _in_view(camera, body.x, body.y):
                continue  # fora do retângulo da câmera
            sx, sy = camera.world_to_screen(body.x, body.y)
            color = color_for(body.player_id)
            sprite = self.sprites.frame(color, "death", 0)
            width, height = sprite.get_size()
            surface.blit(sprite, (round(sx - width / 2), round(sy - height)))
            x, y = round(sx), round(sy)
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
