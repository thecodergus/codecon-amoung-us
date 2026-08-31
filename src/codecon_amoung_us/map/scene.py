"""Cena pastel procedural ("fofa") do mapa gerado por seed.

Camada puramente visual: a colisão deriva do ``GameMap``; este módulo só
desenha. Estética cozy/kawaii (pesquisa 2026): paleta pastel de alta
luminosidade por sala (esquema análogo via HSL), contornos arredondados,
props decorativos (flores, estrelas, corações, arbustos) e céu estrelado no
vazio externo.

Determinismo: mesma seed -> mesmos pixels. Apenas ``pygame.draw`` é usado
(rasterização própria do pygame, estável entre plataformas); nada de
gfxdraw/antialiasing nem fontes, para o gate de frescor pixel-a-pixel do CI
não depender de versão de SDL/freetype. Texturas por célula usam hash
aritmético (não o ``hash()`` builtin, randomizado por processo).
"""

from __future__ import annotations

import colorsys
import math
import random

import pygame

from .generator import walkable_cells_of
from .model import GameMap

__all__ = ["render_scene", "menu_crop", "overlay_surface"]

# Viewport lógico de gameplay (canvas 1280x768 menos a faixa do HUD).
_VIEWPORT_W = 1280
_VIEWPORT_H = 704

_Color = tuple[int, int, int]
_Cell = tuple[int, int]


def _hls(h_deg: float, lightness: float, saturation: float) -> _Color:
    """HSL -> RGB 0-255 (``colorsys`` usa H, L, S em 0..1)."""
    r, g, b = colorsys.hls_to_rgb((h_deg % 360.0) / 360.0, lightness, saturation)
    return (round(r * 255), round(g * 255), round(b * 255))


def _mix(a: _Color, b: _Color, t: float) -> _Color:
    return (
        round(a[0] + (b[0] - a[0]) * t),
        round(a[1] + (b[1] - a[1]) * t),
        round(a[2] + (b[2] - a[2]) * t),
    )


def _cell_noise(cell: _Cell) -> float:
    """Pseudo-aleatoriedade estável por célula em [0, 1) (hash aritmético)."""
    value = (cell[0] * 73856093) ^ (cell[1] * 19349663)
    value = (value ^ (value >> 13)) * 83492791
    value = value ^ (value >> 17)
    return (value % 10007) / 10007.0


# ---------------------------------------------------------------------------
# Paleta
# ---------------------------------------------------------------------------
class _Palette:
    """Cores derivadas da seed: matiz base + variação análoga por sala."""

    def __init__(self, rng: random.Random, room_names: list[str]) -> None:
        base_hue = rng.uniform(0.0, 360.0)
        self.void = _hls(base_hue + 220.0, 0.13, 0.35)
        self.star = _hls(base_hue + 40.0, 0.85, 0.25)
        self.corridor = _hls(base_hue + 30.0, 0.78, 0.22)
        self.corridor_alt = _hls(base_hue + 30.0, 0.74, 0.22)
        self.door = _hls(45.0, 0.75, 0.55)
        self.wall_cap = _hls(base_hue + 200.0, 0.72, 0.30)
        self.wall_face = _hls(base_hue + 200.0, 0.55, 0.32)
        self.wall_edge = _hls(base_hue + 200.0, 0.40, 0.35)
        # Matizes análogos (<= 60° de afastamento) e luminosidade alta: pastel.
        self.room_floor: dict[str, _Color] = {}
        self.room_floor_alt: dict[str, _Color] = {}
        self.room_outline: dict[str, _Color] = {}
        for index, name in enumerate(room_names):
            hue = base_hue + ((index * 137.5) % 60.0) - 30.0
            self.room_floor[name] = _hls(hue, 0.84, 0.42)
            self.room_floor_alt[name] = _hls(hue, 0.80, 0.42)
            self.room_outline[name] = _hls(hue, 0.62, 0.45)
        # Props (fixos da estética, independentes do matiz base).
        self.flower_petal = _hls(330.0, 0.78, 0.55)
        self.flower_center = _hls(50.0, 0.70, 0.65)
        self.leaf = _hls(120.0, 0.55, 0.40)
        self.heart = _hls(350.0, 0.70, 0.60)
        self.star_prop = _hls(50.0, 0.72, 0.60)
        self.bush = _hls(140.0, 0.60, 0.38)


# ---------------------------------------------------------------------------
# Props decorativos (primitivas pygame.draw; escala em px).
# ---------------------------------------------------------------------------
def _draw_flower(surface: pygame.Surface, x: int, y: int, size: int, pal: _Palette) -> None:
    petal = size // 3
    for angle in range(0, 360, 72):
        rad = math.radians(angle)
        px = x + round(math.cos(rad) * petal)
        py = y + round(math.sin(rad) * petal)
        pygame.draw.circle(surface, pal.flower_petal, (px, py), petal)
    pygame.draw.circle(surface, pal.flower_center, (x, y), max(2, size // 4))


def _draw_heart(surface: pygame.Surface, x: int, y: int, size: int, pal: _Palette) -> None:
    r = max(2, size // 4)
    pygame.draw.circle(surface, pal.heart, (x - r, y - r // 2), r)
    pygame.draw.circle(surface, pal.heart, (x + r, y - r // 2), r)
    pygame.draw.polygon(
        surface,
        pal.heart,
        [(x - 2 * r + 1, y - r // 3), (x + 2 * r - 1, y - r // 3), (x, y + 2 * r)],
    )


def _draw_star(surface: pygame.Surface, x: int, y: int, size: int, pal: _Palette) -> None:
    outer = size // 2
    inner = max(2, outer // 2)
    points = []
    for i in range(10):
        radius = outer if i % 2 == 0 else inner
        angle = math.radians(i * 36 - 90)
        points.append((x + round(math.cos(angle) * radius), y + round(math.sin(angle) * radius)))
    pygame.draw.polygon(surface, pal.star_prop, points)


def _draw_bush(surface: pygame.Surface, x: int, y: int, size: int, pal: _Palette) -> None:
    r = max(3, size // 3)
    pygame.draw.circle(surface, pal.bush, (x - r, y + r // 3), r)
    pygame.draw.circle(surface, pal.bush, (x + r, y + r // 3), r)
    pygame.draw.circle(surface, _mix(pal.bush, (255, 255, 255), 0.25), (x, y - r // 2), r)


_PROP_DRAWERS = (_draw_flower, _draw_heart, _draw_star, _draw_bush)


# ---------------------------------------------------------------------------
# Cena
# ---------------------------------------------------------------------------
def render_scene(game_map: GameMap, seed: int) -> pygame.Surface:
    """Renderiza o mundo pastel completo (1 célula = 1 tile) a partir do mapa."""
    tile = game_map.tile_width
    world_w = game_map.width * tile
    world_h = game_map.height * tile
    rng = random.Random(seed ^ 0xC0FE)

    walk = walkable_cells_of(game_map)
    room_of_cell: dict[_Cell, str] = {}
    for room in game_map.rooms:
        x0 = int(room.rect.x) // tile
        y0 = int(room.rect.y) // tile
        for cy in range(y0, y0 + int(room.rect.height) // tile):
            for cx in range(x0, x0 + int(room.rect.width) // tile):
                room_of_cell[(cx, cy)] = room.name
    room_cells = set(room_of_cell)
    doors = {
        cell
        for cell in walk - room_cells
        if any(
            (cell[0] + dx, cell[1] + dy) in room_cells
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
    }
    caps = {
        (cx, cy)
        for cx in range(game_map.width)
        for cy in range(game_map.height)
        if (cx, cy) not in walk and (cx, cy + 1) in walk
    }

    pal = _Palette(rng, [room.name for room in game_map.rooms])
    scene = pygame.Surface((world_w, world_h))
    scene.fill(pal.void)

    # Céu estrelado no vazio (antes dos pisos; estrelas fora do caminhável).
    for _ in range(240):
        cell = (rng.randrange(game_map.width), rng.randrange(game_map.height))
        if cell in walk:
            continue
        size = 1 + rng.randrange(2)
        px = cell[0] * tile + rng.randrange(tile)
        py = cell[1] * tile + rng.randrange(tile)
        pygame.draw.circle(scene, pal.star, (px, py), size)

    # Pisos: cor por sala (xadrez pastel por paridade + ruído estável).
    for cell in sorted(walk):
        cx, cy = cell
        rect = pygame.Rect(cx * tile, cy * tile, tile, tile)
        room_name = room_of_cell.get(cell)
        if room_name is None:
            base = pal.corridor if (cx + cy) % 2 == 0 else pal.corridor_alt
        else:
            base = (
                pal.room_floor[room_name] if (cx + cy) % 2 == 0 else pal.room_floor_alt[room_name]
            )
        noise = _cell_noise(cell)
        color = _mix(base, (255, 255, 255), 0.06 * noise)
        pygame.draw.rect(scene, color, rect)
        # Sprinkles de baixo contraste em parte das células (textura fofa).
        if noise > 0.82:
            dot_color = _mix(base, pal.wall_edge, 0.18)
            dx = 8 + round((noise - 0.82) / 0.18 * (tile - 16))
            pygame.draw.circle(scene, dot_color, (cx * tile + dx, cy * tile + tile - dx), 3)

    # Contorno arredondado das salas (leitura "blob", cantos suaves).
    for room in game_map.rooms:
        rect = pygame.Rect(
            int(room.rect.x) + 2,
            int(room.rect.y) + 2,
            int(room.rect.width) - 4,
            int(room.rect.height) - 4,
        )
        pygame.draw.rect(scene, pal.room_outline[room.name], rect, width=3, border_radius=tile // 3)

    # Limiar de porta: faixa contrastante na borda corredor<->sala.
    for cx, cy in sorted(doors):
        pygame.draw.rect(
            scene,
            pal.door,
            (cx * tile + 6, cy * tile + 6, tile - 12, tile - 12),
            width=3,
            border_radius=6,
        )

    # Paredes: "tampa" clara arredondada sobre a face (leitura top-down fofa).
    for cx, cy in sorted(caps):
        pygame.draw.rect(
            scene,
            pal.wall_face,
            (cx * tile, cy * tile, tile, tile),
            border_radius=8,
        )
        pygame.draw.rect(
            scene,
            pal.wall_cap,
            (cx * tile + 3, cy * tile + 3, tile - 6, tile // 2),
            border_radius=8,
        )
        pygame.draw.rect(
            scene,
            pal.wall_edge,
            (cx * tile, cy * tile, tile, tile),
            width=2,
            border_radius=8,
        )

    # Props decorativos por sala, evitando os pontos de gameplay.
    gameplay_points = [(s.x, s.y) for s in game_map.spawn_points] + [
        (t.x, t.y) for t in game_map.task_points
    ]
    if game_map.emergency_meeting is not None:
        gameplay_points.append(game_map.emergency_meeting)
    blocked_cells: set[_Cell] = set()
    for point_x, point_y in gameplay_points:
        cell = (int(point_x) // tile, int(point_y) // tile)
        blocked_cells.add(cell)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            blocked_cells.add((cell[0] + dx, cell[1] + dy))
    for room in game_map.rooms:
        x0 = int(room.rect.x) // tile
        y0 = int(room.rect.y) // tile
        w = int(room.rect.width) // tile
        h = int(room.rect.height) // tile
        interior = [
            (cx, cy)
            for cy in range(y0 + 1, y0 + h - 1)
            for cx in range(x0 + 1, x0 + w - 1)
            if (cx, cy) not in blocked_cells
        ]
        rng.shuffle(interior)  # ordem canônica (range) embaralhada pela seed
        for cell in interior[: rng.randint(1, 3)]:
            drawer = _PROP_DRAWERS[rng.randrange(len(_PROP_DRAWERS))]
            jitter_x = rng.randint(-tile // 5, tile // 5)
            jitter_y = rng.randint(-tile // 5, tile // 5)
            drawer(
                scene,
                cell[0] * tile + tile // 2 + jitter_x,
                cell[1] * tile + tile // 2 + jitter_y,
                tile // 2,
                pal,
            )
    return scene


def menu_crop(scene: pygame.Surface, game_map: GameMap) -> pygame.Surface:
    """Crop 1280x704 centrado no botão de emergência (fundo dos menus)."""
    if game_map.emergency_meeting is not None:
        hx, hy = game_map.emergency_meeting
    else:
        hx = game_map.width * game_map.tile_width / 2
        hy = game_map.height * game_map.tile_height / 2
    world_w = game_map.width * game_map.tile_width
    world_h = game_map.height * game_map.tile_height
    left = min(max(int(hx) - _VIEWPORT_W // 2, 0), world_w - _VIEWPORT_W)
    top = min(max(int(hy) - _VIEWPORT_H // 2, 0), world_h - _VIEWPORT_H)
    return scene.subsurface((left, top, _VIEWPORT_W, _VIEWPORT_H)).copy()


def overlay_surface(scene: pygame.Surface, game_map: GameMap) -> pygame.Surface:
    """Cena + paredes magenta + marcadores de gameplay (QA humana)."""
    canvas = scene.copy()
    overlay = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    for wall in game_map.walls:
        rect = (wall.x, wall.y, wall.width, wall.height)
        pygame.draw.rect(overlay, (255, 0, 255, 90), rect)
        pygame.draw.rect(overlay, (255, 0, 255, 255), rect, 2)
    canvas.blit(overlay, (0, 0))
    for spawn in game_map.spawn_points:
        pygame.draw.circle(canvas, (80, 160, 255), (int(spawn.x), int(spawn.y)), 10, 3)
    for task in game_map.task_points:
        pygame.draw.circle(canvas, (255, 220, 80), (int(task.x), int(task.y)), 8, 3)
    if game_map.emergency_meeting is not None:
        ex, ey = game_map.emergency_meeting
        pygame.draw.circle(canvas, (255, 60, 60), (int(ex), int(ey)), 12, 3)
    return canvas
