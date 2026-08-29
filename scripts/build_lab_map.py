"""Constrói o mapa do lab a partir da cena do pack "Top Down Lab" (ansimuz).

Lê ``models/mapa/Top Down Lab files/previews/preview.png`` (cena 320x176,
tiles de 16px, com 1px extra à direita), classifica cada tile de 16px por
maioria de cor (paleta do pack) e emite ``assets/maps/lab.json`` no mesmo
schema Tiled dos demais mapas do projeto (object layers: floor, walls,
spawn_points, task_points, emergency_meeting) com mundo 20x11 tiles de 64px
(1280x704). Também gera ``assets/maps/lab_scene.png`` (a cena em 1280x704,
usada como fundo pelo renderer) e ``models/mapa/overlay-lab.png`` (cena +
paredes + marcadores, para QA humana).

O script é determinístico e reexecutável (idempotente) e falha (exit != 0)
se qualquer gate de validação não passar: conectividade entre todos os
pontos de gameplay, pontos fora de paredes, linha reta livre do hub até
cada tarefa (necessária para a navegação dos testes) e contagens mínimas.

Sem dependências novas: usa apenas pygame para ler/escrever pixels.
"""

from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter, deque
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

# ---------------------------------------------------------------------------
# Paleta do pack (cores observadas no preview.png; tolerância 12 por canal).
# ---------------------------------------------------------------------------
_COLOR_FLOOR = [(0, 64, 64), (32, 96, 96), (6, 44, 49)]
_COLOR_WALL = [
    (96, 96, 128),
    (58, 58, 90),
    (32, 32, 64),
    (40, 57, 98),
    (61, 87, 114),
    (64, 64, 96),
]
_COLOR_OBJECT = [
    (128, 96, 0),
    (0, 160, 128),
    (109, 156, 205),
    (255, 252, 255),
    (164, 174, 193),
    (61, 46, 0),
    (162, 134, 10),
]
_PALETTE: dict[str, list[tuple[int, int, int]]] = {
    "K": [(0, 0, 0)],
    "F": _COLOR_FLOOR,
    "W": _COLOR_WALL,
    "O": _COLOR_OBJECT,
}
_TOL2 = 12 * 12

# Escala da cena (px da grade de 16px) para o mundo do jogo (px de 64px).
_SCALE = 4
# Tipos de tarefa (mesmos do skeld.json).
_TASK_TYPES = ["wires", "swipe_card", "fix_wiring", "calibrate", "clean_filter"]
# Configuração do lab.json.
_TILE = 64
_MAP_W = 20
_MAP_H = 11
# Células de chão; objetos (mobília) não bloqueiam.
_WALKABLE_CLASSES = {"F", "O"}

_REPO = Path(__file__).resolve().parent.parent
_PREVIEW = _REPO / "models" / "mapa" / "Top Down Lab files" / "previews" / "preview.png"
_OUT_MAP = _REPO / "assets" / "maps" / "lab.json"
_OUT_SCENE = _REPO / "assets" / "maps" / "lab_scene.png"
_OUT_OVERLAY = _REPO / "models" / "mapa" / "overlay-lab.png"


class BuildError(Exception):
    """Falha de um gate de validação (o script sai com código != 0)."""


def classify(color: pygame.Color) -> str:
    """Classe de cor: F (chão), W (parede), O (objeto), K (fundo/preto)."""
    r, g, b, a = color.r, color.g, color.b, color.a
    if a < 128:
        return "T"
    best, best_dist = "?", 1 << 30
    for name, colors in _PALETTE.items():
        for pr, pg, pb in colors:
            dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if dist < best_dist:
                best, best_dist = name, dist
    return best if best_dist <= _TOL2 else "?"


def load_scene() -> tuple[pygame.Surface, list[list[str]]]:
    """Carrega o preview, corta a borda de 1px e classifica os tiles de 16px."""
    if not _PREVIEW.is_file():
        raise BuildError(f"preview não encontrado: {_PREVIEW}")
    img = pygame.image.load(str(_PREVIEW))
    w, h = img.get_size()
    if w != 321 or h != 176:
        raise BuildError(f"preview inesperado: {w}x{h} (esperado 321x176)")
    scene = img.subsurface((0, 0, 320, 176)).copy()
    tiles: list[list[str]] = []
    for ty in range(_MAP_H):
        row: list[str] = []
        for tx in range(_MAP_W):
            counts: Counter[str] = Counter()
            for y in range(ty * 16, ty * 16 + 16):
                for x in range(tx * 16, tx * 16 + 16):
                    counts[classify(img.get_at((x, y)))] += 1
            row.append(counts.most_common(1)[0][0])
        tiles.append(row)
    return scene, tiles


def walkable(tiles: list[list[str]]) -> list[list[bool]]:
    return [[tiles[y][x] in _WALKABLE_CLASSES for x in range(_MAP_W)] for y in range(_MAP_H)]


def largest_component(walk: list[list[bool]]) -> set[tuple[int, int]]:
    """Maior componente conexo de células caminháveis (4-vizinhança)."""
    seen: set[tuple[int, int]] = set()
    best: set[tuple[int, int]] = set()
    for y in range(_MAP_H):
        for x in range(_MAP_W):
            if not walk[y][x] or (x, y) in seen:
                continue
            comp: set[tuple[int, int]] = set()
            queue = deque([(x, y)])
            seen.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                comp.add((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = cx + dx, cy + dy
                    if (
                        0 <= nx < _MAP_W
                        and 0 <= ny < _MAP_H
                        and walk[ny][nx]
                        and (nx, ny) not in seen
                    ):
                        seen.add((nx, ny))
                        queue.append((nx, ny))
            if len(comp) > len(best):
                best = comp
    return best


def blocked_rects(
    walk: list[list[bool]], playable: set[tuple[int, int]]
) -> list[tuple[int, int, int, int]]:
    """Agrupa células bloqueadas adjacentes ao componente jogável em rects.

    Células bloqueadas fora da vizinhança do componente são ignoradas (são o
    fundo externo da cena). O agrupamento é por linhas (run-length merge).
    """
    neigh = set()
    for x, y in playable:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < _MAP_W and 0 <= ny < _MAP_H and not walk[ny][nx]:
                neigh.add((nx, ny))
    # run-length: para cada linha, runs horizontais de bloqueio
    runs: list[tuple[int, int, int, int]] = []  # (x, y, w, h)
    for y in range(_MAP_H):
        x = 0
        while x < _MAP_W:
            if (x, y) in neigh:
                x0 = x
                while x < _MAP_W and (x, y) in neigh:
                    x += 1
                runs.append((x0, y, x - x0, 1))
            else:
                x += 1
    # merge vertical de runs com mesma faixa x e adjacentes
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


def distance(a: tuple[int, int], b: tuple[int, int]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def pick_points(
    playable: set[tuple[int, int]],
    total: int,
    *,
    anchors: list[tuple[int, int]] | None = None,
) -> list[tuple[int, int]]:
    """Escolhe pontos greedy: maximiza a distância mínima aos já escolhidos.

    ``total`` é o número final de células (âncoras + novas); retorna apenas
    as novas células.
    """
    anchors = anchors or []
    chosen = list(anchors)
    pool = sorted(playable)
    while len(chosen) < total:
        best_cell, best_score = pool[0], -1.0
        for cell in pool:
            if cell in chosen:
                continue
            score = min(distance(cell, other) for other in chosen) if chosen else 1.0
            if score > best_score:
                best_cell, best_score = cell, score
        chosen.append(best_cell)
    return chosen[len(anchors) :]


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def pick_emergency(
    playable: set[tuple[int, int]], blocked: set[tuple[int, int]]
) -> tuple[int, int]:
    """Hub: célula central do componente (menor soma de distâncias Manhattan a
    todas as demais), desde que não esteja colada em um bloqueio."""
    candidates = [c for c in playable if min(manhattan(c, other) for other in blocked) >= 2]
    if not candidates:
        candidates = sorted(playable)
    return min(candidates, key=lambda c: sum(manhattan(c, other) for other in playable))


def cell_center(cell: tuple[int, int]) -> tuple[float, float]:
    """Centro da célula em coordenadas de mundo (px)."""
    return (cell[0] * _SCALE * 16 + 32.0, cell[1] * _SCALE * 16 + 32.0)


def build_lab_json(
    walls: list[tuple[int, int, int, int]],
    spawns: list[tuple[int, int]],
    tasks: list[tuple[int, int]],
    emergency: tuple[int, int],
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
    for index, (sx, sy) in enumerate(spawns):
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
    for index, (tx, ty) in enumerate(tasks):
        px, py = cell_center((tx, ty))
        task_objects.append(
            {
                "id": obj_id(),
                "name": f"task{index + 1}",
                "point": True,
                "x": px,
                "y": py,
                "properties": [
                    {"name": "task_type", "type": "string", "value": _TASK_TYPES[index]},
                    {"name": "interaction_radius", "type": "float", "value": 20.0},
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
    ex, ey = cell_center(emergency)
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
                    "properties": [{"name": "interaction_radius", "type": "float", "value": 25.0}],
                    "visible": True,
                    "rotation": 0,
                    "width": 0,
                    "height": 0,
                }
            ],
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
        "nextlayerid": 6,
        "nextobjectid": next_id,
        "layers": layers,
        "tilesets": [],
    }


def draw_overlay(
    scene: pygame.Surface,
    walls: list[tuple[int, int, int, int]],
    spawns: list[tuple[int, int]],
    tasks: list[tuple[int, int]],
    emergency: tuple[int, int],
) -> None:
    """Gera overlay-lab.png: cena + paredes magenta + marcadores (QA humana)."""
    canvas = pygame.transform.scale(scene, (_MAP_W * _TILE, _MAP_H * _TILE))
    overlay = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    for x, y, w, h in walls:
        pygame.draw.rect(overlay, (255, 0, 255, 90), (x * _TILE, y * _TILE, w * _TILE, h * _TILE))
        pygame.draw.rect(
            overlay, (255, 0, 255, 255), (x * _TILE, y * _TILE, w * _TILE, h * _TILE), 2
        )
    canvas.blit(overlay, (0, 0))
    for sx, sy in spawns:
        px, py = cell_center((sx, sy))
        pygame.draw.circle(canvas, (80, 160, 255), (int(px), int(py)), 10, 3)
    for tx, ty in tasks:
        px, py = cell_center((tx, ty))
        pygame.draw.circle(canvas, (255, 220, 80), (int(px), int(py)), 8, 3)
    ex, ey = cell_center(emergency)
    pygame.draw.circle(canvas, (255, 60, 60), (int(ex), int(ey)), 12, 3)
    pygame.image.save(canvas, str(_OUT_OVERLAY))


def main() -> int:
    pygame.init()
    try:
        scene, tiles = load_scene()
        walk = walkable(tiles)
        playable = largest_component(walk)
        if len(playable) < 60:
            raise BuildError(f"componente jogável pequeno demais: {len(playable)} células")
        walls = blocked_rects(walk, playable)

        # emergency: célula central do componente, longe de paredes.
        blocked = {(x, y) for y in range(_MAP_H) for x in range(_MAP_W) if not walk[y][x]}
        emergency = pick_emergency(playable, blocked)

        spawns = pick_points(playable, 5, anchors=[emergency])
        tasks = pick_points(playable, 10, anchors=[emergency, *spawns])

        # Gates
        all_points = [emergency, *spawns, *tasks]
        if len({p for p in all_points}) != len(all_points):
            raise BuildError("pontos de gameplay duplicados")
        for cell in all_points:
            if cell not in playable:
                raise BuildError(f"ponto fora do componente jogável: {cell}")
        for i, a in enumerate(all_points):
            for b in all_points[i + 1 :]:
                if distance(a, b) < 1.5:
                    raise BuildError(f"pontos próximos demais: {a} {b}")
        if len(walls) < 3:
            raise BuildError(f"poucas paredes extraídas: {len(walls)}")
        for x, y, w, h in walls:
            if w < 1 or h < 1:
                raise BuildError(f"parede degenerada: {(x, y, w, h)}")

        map_doc = build_lab_json(walls, spawns, tasks, emergency)
        _OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
        _OUT_MAP.write_text(json.dumps(map_doc, indent=2), encoding="utf-8")
        pygame.image.save(
            pygame.transform.scale(scene, (_MAP_W * _TILE, _MAP_H * _TILE)), str(_OUT_SCENE)
        )
        draw_overlay(scene, walls, spawns, tasks, emergency)

        print(f"lab.json -> {_OUT_MAP.relative_to(_REPO)}")
        print(f"scene    -> {_OUT_SCENE.relative_to(_REPO)}")
        print(f"overlay  -> {_OUT_OVERLAY.relative_to(_REPO)}")
        print(
            f"componente jogável: {len(playable)} células; paredes: {len(walls)}; "
            f"spawns: {spawns}; tasks: {tasks}; emergency: {emergency}"
        )
        return 0
    except BuildError as exc:
        print(f"ERRO: {exc}")
        return 1
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
