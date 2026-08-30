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
from .task_props import PROP_SIZE, TaskProps
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
        self.task_props = TaskProps()
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
        *,
        emergency_active: bool = False,
    ) -> None:
        """Recorte da câmera da cena + estações de tarefa (objetos do mundo)."""
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
                sx, sy = camera.world_to_screen(ex, ey)
                x, y = int(sx), int(sy)
                sprite = self.task_props.sprite("emergency")
                surface.blit(sprite, (x - PROP_SIZE // 2, y - PROP_SIZE // 2))
                if emergency_active:
                    self._draw_interaction_halo(surface, x, y, pulse)

    @staticmethod
    def _draw_bang(surface: pygame.Surface, x: int, y: int) -> None:
        """Glifo "!" (signifier de ação disponível, desenhado sem fonte)."""
        pygame.draw.rect(surface, (30, 26, 8), (x - 2, y - 8, 5, 10))
        pygame.draw.circle(surface, (30, 26, 8), (x, y + 6), 3)
        pygame.draw.rect(surface, (255, 224, 132), (x - 1, y - 7, 3, 8))
        pygame.draw.circle(surface, (255, 224, 132), (x, y + 5), 2)

    def _draw_interaction_halo(self, surface: pygame.Surface, x: int, y: int, pulse: float) -> None:
        """Halo de interatividade: anel duplo pulsante + glifo "!" no canto."""
        grow = int(3 * pulse)
        rect = pygame.Rect(0, 0, PROP_SIZE - 4 + grow * 2, PROP_SIZE - 4 + grow * 2)
        rect.center = (x, y)
        pygame.draw.rect(surface, (255, 224, 132), rect, width=3, border_radius=8)
        inner = rect.inflate(-8, -8)
        pygame.draw.rect(surface, (255, 244, 190), inner, width=1, border_radius=6)
        self._draw_bang(surface, x + PROP_SIZE // 2 - 6, y - PROP_SIZE // 2 + 6)

    def _draw_task_marker(
        self, surface: pygame.Surface, camera: Camera2D, marker: TaskMarkerView, pulse: float
    ) -> None:
        if not _in_view(camera, marker.x, marker.y):
            return  # fora do retângulo da câmera
        sx, sy = camera.world_to_screen(marker.x, marker.y)
        x, y = int(sx), int(sy)
        # A estação é mobília do mundo: sempre visível; dim quando a tarefa
        # não é sua (UNASSIGNED) ou já foi concluída (DONE).
        dimmed = marker.state in (TaskMarkerState.UNASSIGNED, TaskMarkerState.DONE)
        sprite = self.task_props.sprite(marker.task_type, dimmed=dimmed)
        surface.blit(sprite, (x - PROP_SIZE // 2, y - PROP_SIZE // 2))
        if marker.state is TaskMarkerState.DONE:
            # badge de check verde (luminância alta + geometria própria)
            cx, cy = x + PROP_SIZE // 2 - 10, y + PROP_SIZE // 2 - 10
            pygame.draw.circle(surface, (16, 60, 28), (cx, cy), 8)
            pygame.draw.circle(surface, (120, 230, 130), (cx, cy), 8, 2)
            pygame.draw.lines(
                surface,
                (120, 230, 130),
                False,
                [(cx - 4, cy), (cx - 1, cy + 3), (cx + 4, cy - 3)],
                2,
            )
            return
        if marker.state is TaskMarkerState.INTERACTABLE:
            self._draw_interaction_halo(surface, x, y, pulse)
            return
        if marker.state is TaskMarkerState.NEAR:
            # aproximação: contorno fino (sem pulsação)
            rect = pygame.Rect(0, 0, PROP_SIZE - 4, PROP_SIZE - 4)
            rect.center = (x, y)
            pygame.draw.rect(surface, (255, 224, 132), rect, width=1, border_radius=8)
            return
        if marker.state is TaskMarkerState.ASSIGNED:
            # tag amarela estática no topo da estação ("tem tarefa sua aqui")
            tx, ty = x, y - PROP_SIZE // 2 + 6
            points = [(tx, ty - 5), (tx + 5, ty), (tx, ty + 5), (tx - 5, ty)]
            pygame.draw.polygon(surface, (30, 26, 8), points)
            points = [(tx, ty - 4), (tx + 4, ty), (tx, ty + 4), (tx - 4, ty)]
            pygame.draw.polygon(surface, (255, 224, 132), points)

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
