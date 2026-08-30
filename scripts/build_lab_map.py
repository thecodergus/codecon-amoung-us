"""Constrói o mapa do lab a partir de um layout declarado de salas e corredores.

O layout é autorado neste script como retângulos de células (grade 70x38 de
64 px -> mundo 4480x2432): 12 salas nomeadas ligadas por corredores em anel e
raios até o hub central, formando ciclos (não é um mapa linear). A cena
``assets/maps/lab_scene.png`` é composta deterministicamente com tiles do
pack "Top Down Lab" (ansimuz) — ``models/mapa/Top Down Lab files/Tileset.png``
— e a geometria lógica é emitida em ``assets/maps/lab.json`` no mesmo schema
Tiled dos demais mapas (object layers: floor, walls, spawn_points,
task_points, emergency_meeting, rooms). Também gera
``assets/maps/lab_menu.png`` (crop 1280x704 do hub, fundo dos menus) e
``models/mapa/overlay-lab.png`` (cena + paredes + marcadores, QA humana).

O script é determinístico e reexecutável (idempotente) e falha (exit != 0)
se qualquer gate de validação não passar: mundo maior que o viewport nos
dois eixos e com pelo menos 6x a área do mapa original, quantidade mínima
de salas e de células caminháveis, componente caminhável único (BFS),
alcançabilidade de todos os pontos
de gameplay (spawns, tarefas, emergência) por caminho, distâncias mínimas
entre pontos, distribuição de tarefas por múltiplas salas, ciclo no grafo
sala/corredor e paredes válidas. A colisão deriva apenas do JSON — a imagem
é puramente visual.

Modo ``--check`` (gate de frescor para CI): regenera os artefatos em memória
e compara com os commitados (``lab.json`` byte-a-byte; PNGs por pixels
decodificados, imune a variação de encoder), sem escrever nada — exit != 0
com a lista de assets dessincronizados.

Sem dependências novas: usa apenas pygame para ler/escrever pixels.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import deque
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from codecon_amoung_us.config import MAX_PLAYERS  # noqa: E402
from codecon_amoung_us.game.task_catalog import TASK_TYPES as _TASK_TYPES  # noqa: E402

# ---------------------------------------------------------------------------
# Configuração do mundo.
# ---------------------------------------------------------------------------
_TILE = 64
_MAP_W = 70
_MAP_H = 38
# Viewport de gameplay (canvas lógico 1280x768 menos a faixa do HUD).
_VIEWPORT_W = 1280
_VIEWPORT_H = 704
# Baseline do mapa original (20x11 tiles de 64 px) para o gate de área.
_OLD_AREA = 1280 * 704

# ---------------------------------------------------------------------------
# Layout declarado (retângulos de células: nome, x, y, w, h).
# ---------------------------------------------------------------------------
_ROOMS: list[tuple[str, int, int, int, int]] = [
    ("medbay", 3, 3, 10, 6),
    ("laboratorio", 18, 2, 10, 5),
    ("eletrica", 33, 3, 10, 6),
    ("navegacao", 50, 2, 12, 6),
    ("seguranca", 4, 14, 8, 6),
    ("hub", 28, 14, 14, 8),
    ("oxigenio", 54, 14, 10, 6),
    ("reator", 3, 28, 10, 6),
    ("analise", 18, 29, 10, 5),
    ("armazem", 33, 28, 10, 6),
    ("motores", 48, 29, 10, 5),
    ("comunicacao", 61, 28, 7, 6),
]
_CORRIDORS: list[tuple[str, int, int, int, int]] = [
    ("corr_n", 13, 5, 37, 3),  # medbay <-> laboratorio <-> eletrica <-> navegacao
    ("corr_s", 13, 29, 48, 3),  # reator <-> analise <-> armazem <-> motores <-> comunicacao
    ("corr_w", 7, 9, 3, 19),  # medbay <-> seguranca <-> reator
    ("corr_e", 56, 8, 2, 21),  # navegacao <-> oxigenio <-> motores
    ("spoke_n", 32, 7, 3, 7),  # corr_n/eletrica -> hub
    ("spoke_s", 32, 22, 3, 6),  # hub -> armazem
    ("spoke_w", 8, 16, 20, 3),  # corr_w/seguranca -> hub
    ("spoke_e", 40, 16, 16, 3),  # hub -> oxigenio/corr_e
]

# Pontos de gameplay autorados (células), distribuídos pelas salas.
_SPAWNS: list[tuple[int, int]] = [
    (30, 16),  # hub
    (37, 16),  # hub
    (30, 20),  # hub
    (37, 20),  # hub
    (6, 6),  # medbay
    (22, 5),  # laboratorio
    (38, 6),  # eletrica
    (7, 31),  # reator
    (36, 31),  # armazem
    (56, 5),  # navegacao
]
_EMERGENCY: tuple[int, int] = (34, 17)  # centro do hub
_TASKS: list[tuple[int, int]] = [
    (4, 4),  # medbay
    (10, 4),  # medbay
    (19, 3),  # laboratorio
    (25, 3),  # laboratorio
    (34, 7),  # eletrica
    (41, 4),  # eletrica
    (4, 29),  # reator
    (11, 32),  # reator
    (19, 30),  # analise
    (41, 32),  # armazem
    (49, 30),  # motores
    (51, 3),  # navegacao
    (62, 29),  # comunicacao
    (55, 15),  # oxigenio
    # Etapa 1 (28 estações, 4 por tipo): 14 pontos novos, todos validados
    # contra os gates (caminhável, ≥1,5 célula de qualquer ponto, em sala).
    (6, 16),  # seguranca
    (10, 18),  # seguranca
    (61, 16),  # oxigenio
    (26, 32),  # analise
    (60, 4),  # navegacao
    (53, 7),  # navegacao
    (56, 31),  # motores
    (34, 29),  # armazem
    (9, 28),  # reator
    (12, 29),  # reator
    (64, 32),  # comunicacao
    (61, 33),  # comunicacao
    (38, 8),  # eletrica
    (33, 5),  # eletrica
]

# ---------------------------------------------------------------------------
# Tiles do pack (coords de tiles de 16 px no Tileset.png), identificados por
# inspeção visual da grade: linha 1 = banda de maquinário (topo de parede),
# linha 2 = face frontal, linha 9 = piso teal liso, (3,8) = faixa de
# segurança na borda superior (limiar de porta), (3,7)/(4,7) = piso de grade
# (identidade visual do reator).
# ---------------------------------------------------------------------------
_FLOOR_TILES: list[tuple[int, int]] = [(2, 9), (3, 9), (6, 9), (7, 9)]
_ROOM_FLOOR_TILES: dict[str, list[tuple[int, int]]] = {
    "reator": [(3, 7), (4, 7)],
}
_DOOR_TILE: tuple[int, int] = (3, 8)
_WALL_TOP_ROW = 1  # cols 1-8: variantes de maquinário
_WALL_FACE_ROW = 2  # cols 1-8: faces frontais

_REPO = Path(__file__).resolve().parent.parent
_TILESET = _REPO / "models" / "mapa" / "Top Down Lab files" / "Tileset.png"
_OUT_MAP = _REPO / "assets" / "maps" / "lab.json"
_OUT_SCENE = _REPO / "assets" / "maps" / "lab_scene.png"
_OUT_MENU = _REPO / "assets" / "maps" / "lab_menu.png"
_OUT_OVERLAY = _REPO / "models" / "mapa" / "overlay-lab.png"


class BuildError(Exception):
    """Falha de um gate de validação (o script sai com código != 0)."""


# ---------------------------------------------------------------------------
# Geometria do layout.
# ---------------------------------------------------------------------------
def _rect_cells(x: int, y: int, w: int, h: int) -> set[tuple[int, int]]:
    return {(cx, cy) for cy in range(y, y + h) for cx in range(x, x + w)}


def region_cells() -> dict[str, set[tuple[int, int]]]:
    """Células de cada região nomeada (salas e corredores)."""
    regions: dict[str, set[tuple[int, int]]] = {}
    for name, x, y, w, h in [*_ROOMS, *_CORRIDORS]:
        regions[name] = _rect_cells(x, y, w, h)
    return regions


def walkable_cells(regions: dict[str, set[tuple[int, int]]]) -> set[tuple[int, int]]:
    """União das células de salas e corredores."""
    cells: set[tuple[int, int]] = set()
    for region in regions.values():
        cells |= region
    return cells


def walkable_grid(walk: set[tuple[int, int]]) -> list[list[bool]]:
    return [[(x, y) in walk for x in range(_MAP_W)] for y in range(_MAP_H)]


def largest_component(walk: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Maior componente conexo de células caminháveis (4-vizinhança)."""
    seen: set[tuple[int, int]] = set()
    best: set[tuple[int, int]] = set()
    for start in sorted(walk):
        if start in seen:
            continue
        comp: set[tuple[int, int]] = set()
        queue = deque([start])
        seen.add(start)
        while queue:
            cx, cy = queue.popleft()
            comp.add((cx, cy))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nxt = (cx + dx, cy + dy)
                if nxt in walk and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        if len(comp) > len(best):
            best = comp
    return best


def blocked_rects(walk: set[tuple[int, int]]) -> list[tuple[int, int, int, int]]:
    """Agrupa TODAS as células não-caminháveis em rects de parede.

    O mundo fica hermético: qualquer célula fora da união caminhável é
    parede, inclusive o vazio externo — nenhuma região "livre" inalcançável
    resta no mapa. O agrupamento é por linhas (run-length merge vertical),
    o que colapsa o vazio em poucos rects grandes.
    """
    blocked = {(x, y) for y in range(_MAP_H) for x in range(_MAP_W) if (x, y) not in walk}
    runs: list[tuple[int, int, int, int]] = []  # (x, y, w, h)
    for y in range(_MAP_H):
        x = 0
        while x < _MAP_W:
            if (x, y) in blocked:
                x0 = x
                while x < _MAP_W and (x, y) in blocked:
                    x += 1
                runs.append((x0, y, x - x0, 1))
            else:
                x += 1
    merged: list[tuple[int, int, int, int]] = []
    for run in sorted(runs, key=lambda r: (r[0], r[1])):
        placed = False
        for i, rect in enumerate(merged):
            rx, ry, rw, rh = rect
            if rx == run[0] and rw == run[2] and ry + rh == run[1]:
                merged[i] = (rx, ry, rw, rh + 1)
                placed = True
                break
        if not placed:
            merged.append(run)
    return merged


def cell_center(cell: tuple[int, int]) -> tuple[float, float]:
    """Centro da célula em coordenadas de mundo (px)."""
    return (cell[0] * _TILE + _TILE / 2, cell[1] * _TILE + _TILE / 2)


# ---------------------------------------------------------------------------
# Gates de validação (BFS/alcançabilidade — nunca linha reta).
# ---------------------------------------------------------------------------
def validate(regions: dict[str, set[tuple[int, int]]], walk: set[tuple[int, int]]) -> None:
    """Falha com ``BuildError`` se qualquer invariante do mapa não valer."""
    # Mundo excede o viewport nos dois eixos e área >= 6x a do mapa original.
    world_w, world_h = _MAP_W * _TILE, _MAP_H * _TILE
    if world_w <= _VIEWPORT_W or world_h <= _VIEWPORT_H:
        raise BuildError(f"mundo {world_w}x{world_h} não excede o viewport nos dois eixos")
    if world_w * world_h < 6 * _OLD_AREA:
        raise BuildError(f"área {world_w * world_h} menor que 6x a original ({6 * _OLD_AREA})")

    # Área caminhável efetiva: pelo menos ~3x o baseline do mapa 40x22 (370 células).
    if len(walk) < 1000:
        raise BuildError(f"área caminhável pequena demais: {len(walk)} células (mínimo 1000)")

    # Salas: quantidade mínima, nomes únicos, retângulos disjuntos.
    if len(_ROOMS) < 10:
        raise BuildError(f"poucas salas: {len(_ROOMS)} (mínimo 10)")
    names = [name for name, *_ in _ROOMS]
    if len(set(names)) != len(names):
        raise BuildError("nomes de sala duplicados")
    for i, (name_a, xa, ya, wa, ha) in enumerate(_ROOMS):
        cells_a = _rect_cells(xa, ya, wa, ha)
        for name_b, xb, yb, wb, hb in _ROOMS[i + 1 :]:
            if cells_a & _rect_cells(xb, yb, wb, hb):
                raise BuildError(f"salas sobrepostas: {name_a} / {name_b}")

    # Caminhável forma um único componente (nenhuma região inacessível).
    component = largest_component(walk)
    if component != walk:
        raise BuildError(
            f"caminhável fragmentado: {len(walk) - len(component)} células fora do componente"
        )

    # Pontos de gameplay: dentro do caminhável e alcançáveis (mesmo componente).
    all_points = [*_SPAWNS, *_TASKS, _EMERGENCY]
    if len(set(all_points)) != len(all_points):
        raise BuildError("pontos de gameplay duplicados")
    for cell in all_points:
        if cell not in walk:
            raise BuildError(f"ponto fora da área caminhável: {cell}")
        if cell not in component:
            raise BuildError(f"ponto inalcançável a partir do hub: {cell}")

    # Distâncias mínimas: 1,5 célula entre pontos; spawns longe do botão.
    for i, a in enumerate(all_points):
        for b in all_points[i + 1 :]:
            if math.hypot(a[0] - b[0], a[1] - b[1]) < 1.5:
                raise BuildError(f"pontos próximos demais: {a} {b}")
    for spawn in _SPAWNS:
        if abs(spawn[0] - _EMERGENCY[0]) + abs(spawn[1] - _EMERGENCY[1]) < 2:
            raise BuildError(f"spawn colado no botão de emergência: {spawn}")

    # Spawns para o máximo de jogadores; tarefas distribuídas por salas.
    if len(_SPAWNS) < MAX_PLAYERS:
        raise BuildError(f"spawns insuficientes: {len(_SPAWNS)} < MAX_PLAYERS={MAX_PLAYERS}")
    task_rooms = {room_of(cell) for cell in _TASKS} - {None}
    if len(task_rooms) < 6:
        raise BuildError(f"tarefas concentradas: apenas {len(task_rooms)} salas (mínimo 6)")
    if len(_TASKS) < len(_TASK_TYPES):
        raise BuildError(f"tarefas insuficientes: {len(_TASKS)} < {len(_TASK_TYPES)} tipos")

    # Topologia não linear: grafo sala/corredor com pelo menos um ciclo.
    if not _region_graph_has_cycle(regions):
        raise BuildError("grafo sala/corredor sem ciclos (mapa linear)")


def room_of(cell: tuple[int, int]) -> str | None:
    """Nome da sala que contém a célula (None se corredor/fora)."""
    for name, x, y, w, h in _ROOMS:
        if x <= cell[0] < x + w and y <= cell[1] < y + h:
            return name
    return None


def _region_graph_has_cycle(regions: dict[str, set[tuple[int, int]]]) -> bool:
    """True se o grafo de adjacência entre regiões contém um ciclo.

    Aresta = regiões com células sobrepostas ou 4-adjacentes; ciclo detectado
    por union-find (aresta ligando nós já no mesmo componente).
    """
    parent = {name: name for name in regions}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    names = sorted(regions)
    expanded = {
        name: cells | {(cx + dx, cy + dy) for cx, cy in cells for dx, dy in ((1, 0), (0, 1))}
        for name, cells in regions.items()
    }
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if not (expanded[a] & regions[b]):
                continue
            root_a, root_b = find(a), find(b)
            if root_a == root_b:
                return True
            parent[root_a] = root_b
    return False


# ---------------------------------------------------------------------------
# Emissão do lab.json (schema Tiled, object layers).
# ---------------------------------------------------------------------------
def build_lab_json(
    walls: list[tuple[int, int, int, int]],
) -> dict[str, object]:
    """Monta o documento Tiled equivalente ao skeld.json (object layers)."""
    next_id = 1

    def obj_id() -> int:
        nonlocal next_id
        value = next_id
        next_id += 1
        return value

    layers: list[dict[str, object]] = []
    # floor: retângulo único cobrindo o mapa (o fundo é a própria cena).
    layers.append(
        {
            "id": 1,
            "name": "floor",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": [
                {
                    "id": obj_id(),
                    "name": "lab_floor",
                    "x": 0,
                    "y": 0,
                    "width": _MAP_W * _TILE,
                    "height": _MAP_H * _TILE,
                    "visible": True,
                    "rotation": 0,
                }
            ],
        }
    )
    # walls
    wall_objects: list[dict[str, object]] = []
    for x, y, w, h in walls:
        wall_objects.append(
            {
                "id": obj_id(),
                "name": f"wall_{x}_{y}",
                "x": x * _TILE,
                "y": y * _TILE,
                "width": w * _TILE,
                "height": h * _TILE,
                "properties": [{"name": "collidable", "type": "bool", "value": True}],
                "visible": True,
                "rotation": 0,
            }
        )
    layers.append(
        {
            "id": 2,
            "name": "walls",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": wall_objects,
        }
    )
    # spawn_points
    spawn_objects: list[dict[str, object]] = []
    for index, (sx, sy) in enumerate(_SPAWNS):
        px, py = cell_center((sx, sy))
        spawn_objects.append(
            {
                "id": obj_id(),
                "name": f"spawn{index}",
                "point": True,
                "x": px,
                "y": py,
                "properties": [{"name": "spawn_id", "type": "int", "value": index}],
                "visible": True,
                "rotation": 0,
                "width": 0,
                "height": 0,
            }
        )
    layers.append(
        {
            "id": 3,
            "name": "spawn_points",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": spawn_objects,
        }
    )
    # task_points
    task_objects: list[dict[str, object]] = []
    for index, (tx, ty) in enumerate(_TASKS):
        px, py = cell_center((tx, ty))
        task_objects.append(
            {
                "id": obj_id(),
                "name": f"task{index + 1}",
                "point": True,
                "x": px,
                "y": py,
                "properties": [
                    {
                        "name": "task_type",
                        "type": "string",
                        "value": _TASK_TYPES[index % len(_TASK_TYPES)],
                    },
                    {"name": "interaction_radius", "type": "float", "value": 56.0},
                ],
                "visible": True,
                "rotation": 0,
                "width": 0,
                "height": 0,
            }
        )
    layers.append(
        {
            "id": 4,
            "name": "task_points",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": task_objects,
        }
    )
    # emergency_meeting
    ex, ey = cell_center(_EMERGENCY)
    layers.append(
        {
            "id": 5,
            "name": "emergency_meeting",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": [
                {
                    "id": obj_id(),
                    "name": "meeting_button",
                    "point": True,
                    "x": ex,
                    "y": ey,
                    "properties": [{"name": "interaction_radius", "type": "float", "value": 44.0}],
                    "visible": True,
                    "rotation": 0,
                    "width": 0,
                    "height": 0,
                }
            ],
        }
    )
    # rooms (metadados de validação/QA; opcionais no loader)
    room_objects: list[dict[str, object]] = []
    for name, x, y, w, h in _ROOMS:
        room_objects.append(
            {
                "id": obj_id(),
                "name": name,
                "x": x * _TILE,
                "y": y * _TILE,
                "width": w * _TILE,
                "height": h * _TILE,
                "visible": True,
                "rotation": 0,
            }
        )
    layers.append(
        {
            "id": 6,
            "name": "rooms",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": room_objects,
        }
    )
    return {
        "type": "map",
        "version": "1.10",
        "tiledversion": "1.10.2",
        "orientation": "orthogonal",
        "renderorder": "right-down",
        "width": _MAP_W,
        "height": _MAP_H,
        "tilewidth": _TILE,
        "tileheight": _TILE,
        "infinite": False,
        "nextlayerid": 7,
        "nextobjectid": next_id,
        "layers": layers,
        "tilesets": [],
    }


# ---------------------------------------------------------------------------
# Composição da cena (visual; colisão deriva apenas do JSON).
# ---------------------------------------------------------------------------
def compose_scene(
    regions: dict[str, set[tuple[int, int]]], walk: set[tuple[int, int]]
) -> pygame.Surface:
    """Renderiza o mundo com tiles do pack (1 célula = 1 tile x4).

    Regras: caminhável -> piso teal (portas com faixa de segurança); parede
    com vizinho caminhável ao sul -> banda de maquinário; parede logo abaixo
    de maquinário -> face frontal; demais células -> vazio (preto).
    """
    if not _TILESET.is_file():
        raise BuildError(f"tileset não encontrado: {_TILESET}")
    tileset = pygame.image.load(str(_TILESET))
    cache: dict[tuple[int, int], pygame.Surface] = {}

    def tile(tx: int, ty: int) -> pygame.Surface:
        key = (tx, ty)
        if key not in cache:
            sub = tileset.subsurface((tx * 16, ty * 16, 16, 16)).copy()
            cache[key] = pygame.transform.scale(sub, (_TILE, _TILE))
        return cache[key]

    room_cells: set[tuple[int, int]] = set()
    for name, *_ in _ROOMS:
        room_cells |= regions[name]
    room_of_cell = {cell: name for name, *_ in _ROOMS for cell in regions[name]}
    doors = {
        cell
        for cell in walk - room_cells
        if any(
            (cell[0] + dx, cell[1] + dy) in room_cells
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
        )
    }
    machinery = {
        (cx, cy)
        for cx in range(_MAP_W)
        for cy in range(_MAP_H)
        if (cx, cy) not in walk and (cx, cy + 1) in walk
    }

    scene = pygame.Surface((_MAP_W * _TILE, _MAP_H * _TILE))
    scene.fill((0, 0, 0))
    for cy in range(_MAP_H):
        for cx in range(_MAP_W):
            cell = (cx, cy)
            if cell in walk:
                variants = _ROOM_FLOOR_TILES.get(room_of_cell.get(cell, ""), _FLOOR_TILES)
                index = (cx * 3 + cy * 7) % len(variants)
                sprite = tile(*_DOOR_TILE) if cell in doors else tile(*variants[index])
            elif cell in machinery:
                sprite = tile(1 + cx % 8, _WALL_TOP_ROW)
            elif (cx, cy - 1) in machinery:
                sprite = tile(1 + cx % 8, _WALL_FACE_ROW)
            else:
                continue
            scene.blit(sprite, (cx * _TILE, cy * _TILE))
    return scene


def overlay_surface(
    scene: pygame.Surface,
    walls: list[tuple[int, int, int, int]],
) -> pygame.Surface:
    """Cena + paredes magenta + marcadores (QA humana)."""
    canvas = scene.copy()
    overlay = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    for x, y, w, h in walls:
        pygame.draw.rect(overlay, (255, 0, 255, 90), (x * _TILE, y * _TILE, w * _TILE, h * _TILE))
        pygame.draw.rect(
            overlay, (255, 0, 255, 255), (x * _TILE, y * _TILE, w * _TILE, h * _TILE), 2
        )
    canvas.blit(overlay, (0, 0))
    for sx, sy in _SPAWNS:
        px, py = cell_center((sx, sy))
        pygame.draw.circle(canvas, (80, 160, 255), (int(px), int(py)), 10, 3)
    for tx, ty in _TASKS:
        px, py = cell_center((tx, ty))
        pygame.draw.circle(canvas, (255, 220, 80), (int(px), int(py)), 8, 3)
    ex, ey = cell_center(_EMERGENCY)
    pygame.draw.circle(canvas, (255, 60, 60), (int(ex), int(ey)), 12, 3)
    return canvas


def menu_crop(scene: pygame.Surface) -> pygame.Surface:
    """Crop 1280x704 centrado no hub (fundo dos menus, sem distorção)."""
    hx, hy = cell_center(_EMERGENCY)
    left = min(max(int(hx) - _VIEWPORT_W // 2, 0), _MAP_W * _TILE - _VIEWPORT_W)
    top = min(max(int(hy) - _VIEWPORT_H // 2, 0), _MAP_H * _TILE - _VIEWPORT_H)
    return scene.subsurface((left, top, _VIEWPORT_W, _VIEWPORT_H)).copy()


def _generate() -> tuple[
    dict[str, object], pygame.Surface, set[tuple[int, int]], list[tuple[int, int, int, int]]
]:
    """Gera os artefatos em memória: documento do mapa, cena, caminhável e paredes."""
    regions = region_cells()
    walk = walkable_cells(regions)
    validate(regions, walk)
    walls = blocked_rects(walk)
    if len(walls) < 3:
        raise BuildError(f"poucas paredes extraídas: {len(walls)}")
    for x, y, w, h in walls:
        if w < 1 or h < 1:
            raise BuildError(f"parede degenerada: {(x, y, w, h)}")
    return build_lab_json(walls), compose_scene(regions, walk), walk, walls


def _png_pixels_equal(path: Path, surface: pygame.Surface) -> bool:
    """True se o PNG em ``path`` decodifica para os mesmos pixels de ``surface``.

    Comparação por RGB decodificado (PNG é lossless): imune a diferenças de
    encoder entre versões de SDL/libpng e plataformas. O canal alfa é
    ignorado de propósito: as superfícies geradas são 32 bits sem SRCALPHA e
    o PNG commitado é 24 bits — o alfa é descartado na escrita e não carrega
    conteúdo.
    """
    if not path.is_file():
        return False
    loaded = pygame.image.load(str(path))
    return loaded.get_size() == surface.get_size() and (
        pygame.image.tobytes(loaded, "RGB") == pygame.image.tobytes(surface, "RGB")
    )


def check_freshness() -> int:
    """Gate de frescor: regenera os artefatos e compara com os commitados.

    Não escreve nada. Exit != 0 com a lista de assets dessincronizados
    (regenerar com ``uv run python scripts/build_lab_map.py``).
    """
    pygame.init()
    try:
        map_doc, scene, _walk, walls = _generate()
        stale: list[str] = []
        map_text = json.dumps(map_doc, indent=2)
        if not _OUT_MAP.is_file() or _OUT_MAP.read_text(encoding="utf-8") != map_text:
            stale.append(_OUT_MAP.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_SCENE, scene):
            stale.append(_OUT_SCENE.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_MENU, menu_crop(scene)):
            stale.append(_OUT_MENU.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_OVERLAY, overlay_surface(scene, walls)):
            stale.append(_OUT_OVERLAY.relative_to(_REPO).as_posix())
        if stale:
            print(f"ERRO: assets dessincronizados com o builder: {', '.join(stale)}")
            print("regenere com: uv run python scripts/build_lab_map.py")
            return 1
        print("assets sincronizados com o builder (lab.json + 3 PNGs)")
        return 0
    except BuildError as exc:
        print(f"ERRO: {exc}")
        return 1
    finally:
        pygame.quit()


def main() -> int:
    pygame.init()
    try:
        map_doc, scene, walk, walls = _generate()
        _OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
        _OUT_MAP.write_text(json.dumps(map_doc, indent=2), encoding="utf-8")
        pygame.image.save(scene, str(_OUT_SCENE))
        pygame.image.save(menu_crop(scene), str(_OUT_MENU))
        pygame.image.save(overlay_surface(scene, walls), str(_OUT_OVERLAY))

        print(f"lab.json -> {_OUT_MAP.relative_to(_REPO)}")
        print(f"scene    -> {_OUT_SCENE.relative_to(_REPO)}")
        print(f"menu     -> {_OUT_MENU.relative_to(_REPO)}")
        print(f"overlay  -> {_OUT_OVERLAY.relative_to(_REPO)}")
        print(
            f"mundo {_MAP_W * _TILE}x{_MAP_H * _TILE}; salas: {len(_ROOMS)}; "
            f"caminhável: {len(walk)} células; paredes: {len(walls)}; "
            f"spawns: {len(_SPAWNS)}; tasks: {len(_TASKS)}; emergency: {_EMERGENCY}"
        )
        return 0
    except BuildError as exc:
        print(f"ERRO: {exc}")
        return 1
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(check_freshness() if "--check" in sys.argv else main())
