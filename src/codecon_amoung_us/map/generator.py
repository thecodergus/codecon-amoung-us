"""Geração procedural de mapas dirigida por seed (sem pygame, sem parser Tiled).

Pipeline construtivo generate-and-test (cf. survey de PCG da AIIDE 2024,
DOI 10.1609/aiide.v20i1.31877): salas em grade de zonas com jitter, corredores
em L sobre MST + arestas extras (ciclos), pontos de gameplay por amostragem
com rejeição e gates estruturais idênticos aos do antigo builder autorado
(componente único BFS, alcançabilidade, distâncias mínimas, ciclo no grafo
sala/corredor). Abordagens PCGML/GAN foram descartadas: exigem dataset e
quebram o determinismo leve servidor↔cliente.

Determinismo cross-processo: toda aleatoriedade vem de ``random.Random``
com seeds inteiras; sub-RNGs por tentativa derivam de ``getrandbits``
(nunca ``hash()``, que é randomizado por processo) e coleções são sempre
ordenadas antes de qualquer sorteio. O mesmo ``seed`` produz exatamente o
mesmo ``GameMap`` no servidor e em cada cliente.
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass

from ..config import MAX_PLAYERS
from ..game.task_catalog import TASK_TYPES
from .model import GameMap, Rect, Room, SpawnPoint, TaskPoint

__all__ = [
    "BuildError",
    "GenConfig",
    "DEFAULT_CONFIG",
    "generate_map",
    "to_tiled_json",
    "walkable_cells_of",
]


class BuildError(Exception):
    """Falha de um gate de validação (tentativa descartada; nova sub-seed)."""


@dataclass(frozen=True)
class GenConfig:
    """Parâmetros do gerador (dimensões de mundo, salas e tentativas)."""

    map_w: int = 70
    map_h: int = 38
    tile: int = 64
    room_count: int = 12
    zone_cols: int = 4
    zone_rows: int = 3
    room_min_w: int = 7
    room_max_w: int = 13
    room_min_h: int = 6
    room_max_h: int = 8
    # Margem mínima entre o retângulo da sala e as bordas da sua zona
    # (garante gap entre salas vizinhas sem teste de sobreposição global).
    zone_margin: int = 2
    # Arestas extras além da MST: garantem ciclos (mapa não linear).
    extra_edges: int = 4
    corridor_min_width: int = 2
    corridor_max_width: int = 3
    tasks_per_room: int = 2
    task_interaction_radius: float = 56.0
    emergency_interaction_radius: float = 44.0
    max_attempts: int = 200


DEFAULT_CONFIG = GenConfig()

# Viewport de gameplay (canvas lógico 1280x768 menos a faixa do HUD) e
# baseline do mapa original (20x11 tiles de 64 px) para os gates de área.
_VIEWPORT_W = 1280
_VIEWPORT_H = 704
_OLD_AREA = 1280 * 704

# Pool de nomes de sala (embaralhado por tentativa; tamanho >= room_count).
_ROOM_NAMES: tuple[str, ...] = (
    "medbay",
    "laboratorio",
    "eletrica",
    "navegacao",
    "seguranca",
    "hub",
    "oxigenio",
    "reator",
    "analise",
    "armazem",
    "motores",
    "comunicacao",
)

_Cell = tuple[int, int]
_RoomRect = tuple[str, int, int, int, int]  # (nome, x, y, w, h) em células


def _rect_cells(x: int, y: int, w: int, h: int) -> set[_Cell]:
    return {(cx, cy) for cy in range(y, y + h) for cx in range(x, x + w)}


def _cell_center(cell: _Cell, tile: int) -> tuple[float, float]:
    return (cell[0] * tile + tile / 2, cell[1] * tile + tile / 2)


# ---------------------------------------------------------------------------
# Estágio 1 — salas em grade de zonas com jitter.
# ---------------------------------------------------------------------------
def _place_rooms(rng: random.Random, cfg: GenConfig) -> list[_RoomRect]:
    """Uma sala por zona (grade zone_cols x zone_rows), posição/tamanho seedados.

    A grade garante espalhamento e disjunção; o jitter de posição e o tamanho
    variável quebram a rigidez visual da grade. Falha se alguma zona não
    comporta o tamanho mínimo de sala (config inválida).
    """
    if len(_ROOM_NAMES) < cfg.room_count:
        raise BuildError(f"pool de nomes insuficiente: {len(_ROOM_NAMES)} < {cfg.room_count}")
    if cfg.zone_cols * cfg.zone_rows < cfg.room_count:
        raise BuildError("grade de zonas menor que room_count")
    names = list(_ROOM_NAMES)
    rng.shuffle(names)  # lista ordenada canônica embaralhada pela seed
    zone_w = cfg.map_w // cfg.zone_cols
    zone_h = cfg.map_h // cfg.zone_rows
    margin = cfg.zone_margin
    rooms: list[_RoomRect] = []
    # Zonas em ordem fixa; a seed age no nome, tamanho e posição dentro da zona.
    for index in range(cfg.room_count):
        zc, zr = index % cfg.zone_cols, index // cfg.zone_cols
        inner_w = zone_w - 2 * margin
        inner_h = zone_h - 2 * margin
        if inner_w < cfg.room_min_w or inner_h < cfg.room_min_h:
            raise BuildError(
                f"zona {inner_w}x{inner_h} não comporta sala mínima "
                f"{cfg.room_min_w}x{cfg.room_min_h}"
            )
        w = rng.randint(cfg.room_min_w, min(cfg.room_max_w, inner_w))
        h = rng.randint(cfg.room_min_h, min(cfg.room_max_h, inner_h))
        x = zc * zone_w + margin + rng.randint(0, inner_w - w)
        y = zr * zone_h + margin + rng.randint(0, inner_h - h)
        rooms.append((names[index], x, y, w, h))
    return rooms


# ---------------------------------------------------------------------------
# Estágio 2 — conectividade: MST (Prim) + arestas extras mais curtas.
# ---------------------------------------------------------------------------
def _room_center(room: _RoomRect) -> _Cell:
    _name, x, y, w, h = room
    return (x + w // 2, y + h // 2)


def _connectivity_edges(
    rng: random.Random, rooms: list[_RoomRect], extra_edges: int
) -> list[tuple[int, int]]:
    """Arestas sala-sala: MST sobre centroides (jitter seedado) + extras curtas."""
    centers = [_room_center(room) for room in rooms]
    n = len(centers)
    weights: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            dist = math.dist(centers[i], centers[j])
            weights[(i, j)] = dist + rng.uniform(0.0, 0.5)  # desempate seedado

    mst: list[tuple[int, int]] = []
    in_tree = {0}
    while len(in_tree) < n:
        best: tuple[float, int, int] | None = None
        for i in sorted(in_tree):
            for j in range(n):
                if j in in_tree:
                    continue
                key = (min(i, j), max(i, j))
                candidate = (weights[key], i, j)  # endpoints reais, não a chave
                if best is None or candidate < best:
                    best = candidate
        assert best is not None  # grafo completo: sempre há candidato
        _w, i, j = best
        mst.append((i, j))
        in_tree.add(j)

    tree_pairs = {(min(i, j), max(i, j)) for i, j in mst}
    extras_pool = sorted(
        (pair for pair in weights if pair not in tree_pairs),
        key=lambda pair: (weights[pair], pair),
    )
    return mst + extras_pool[:extra_edges]


# ---------------------------------------------------------------------------
# Estágio 3 — corredores em L entre centros das salas ligadas.
# ---------------------------------------------------------------------------
def _carve_corridor(
    rng: random.Random, start: _Cell, end: _Cell, width: int, cfg: GenConfig
) -> set[_Cell]:
    """Células de um corredor em L (ordem do cotovelo e largura seedadas)."""
    x1, y1 = start
    x2, y2 = end
    half = width // 2
    cells: set[_Cell] = set()

    def h_run(row: int, xa: int, xb: int) -> None:
        for dy in range(-half, -half + width):
            yy = row + dy
            if not 0 <= yy < cfg.map_h:
                continue
            for xx in range(min(xa, xb), max(xa, xb) + 1):
                if 0 <= xx < cfg.map_w:
                    cells.add((xx, yy))

    def v_run(col: int, ya: int, yb: int) -> None:
        for dx in range(-half, -half + width):
            xx = col + dx
            if not 0 <= xx < cfg.map_w:
                continue
            for yy in range(min(ya, yb), max(ya, yb) + 1):
                if 0 <= yy < cfg.map_h:
                    cells.add((xx, yy))

    if rng.random() < 0.5:  # horizontal primeiro, cotovelo em (x2, y1)
        h_run(y1, x1, x2)
        v_run(x2, y1, y2)
    else:  # vertical primeiro, cotovelo em (x1, y2)
        v_run(x1, y1, y2)
        h_run(y2, x1, x2)
    return cells


# ---------------------------------------------------------------------------
# Estágio 4 — pontos de gameplay (emergência, spawns, tarefas).
# ---------------------------------------------------------------------------
def _place_spawns(rng: random.Random, candidates: list[_Cell], emergency: _Cell) -> list[_Cell]:
    """Spawns por farthest-point greedy a partir de um primeiro ponto seedado.

    A margem de 4 células para o botão supera o gate formal (Manhattan >= 2).
    """
    pool = [
        cell
        for cell in sorted(candidates)
        if abs(cell[0] - emergency[0]) + abs(cell[1] - emergency[1]) >= 4
    ]
    if len(pool) < MAX_PLAYERS:
        raise BuildError(f"pool de spawns pequeno demais: {len(pool)}")
    chosen = [pool[rng.randrange(len(pool))]]
    while len(chosen) < MAX_PLAYERS:
        best_cell: _Cell | None = None
        best_dist = -1.0
        for cell in pool:
            if cell in chosen:
                continue
            dist = min(math.dist(cell, other) for other in chosen)
            if dist > best_dist:
                best_cell, best_dist = cell, dist
        if best_cell is None or best_dist < 1.5:
            raise BuildError("spawns sem separação mínima no pool")
        chosen.append(best_cell)
    return chosen


def _place_tasks(
    rng: random.Random,
    rooms: list[_RoomRect],
    hub_index: int,
    taken: set[_Cell],
    cfg: GenConfig,
) -> list[tuple[_Cell, str]]:
    """``tasks_per_room`` tarefas por sala não-hub; tipos do catálogo em ciclo."""
    tasks: list[tuple[_Cell, str]] = []
    index = 0
    for room_index, room in enumerate(rooms):
        if room_index == hub_index:
            continue
        _name, x, y, w, h = room
        cells = sorted(_rect_cells(x + 1, y + 1, w - 2, h - 2))
        rng.shuffle(cells)  # ordem canônica (sorted) embaralhada pela seed
        picked = 0
        for cell in cells:
            if picked >= cfg.tasks_per_room:
                break
            if cell in taken:
                continue
            if any(math.dist(cell, other) < 1.5 for other in taken):
                continue
            tasks.append((cell, TASK_TYPES[index % len(TASK_TYPES)]))
            taken.add(cell)
            index += 1
            picked += 1
        if picked < cfg.tasks_per_room:
            raise BuildError(f"sala sem células para tarefas: {room[0]}")
    return tasks


# ---------------------------------------------------------------------------
# Gates de validação (portados do builder autorado; BFS, nunca linha reta).
# ---------------------------------------------------------------------------
def _largest_component(walk: set[_Cell]) -> set[_Cell]:
    seen: set[_Cell] = set()
    best: set[_Cell] = set()
    for start in sorted(walk):
        if start in seen:
            continue
        comp: set[_Cell] = set()
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


def _region_graph_has_cycle(regions: dict[str, set[_Cell]]) -> bool:
    """True se o grafo de adjacência entre regiões contém um ciclo (union-find)."""
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


def _blocked_rects(walk: set[_Cell], cfg: GenConfig) -> list[tuple[int, int, int, int]]:
    """Agrupa TODAS as células não-caminháveis em rects (run-length vertical)."""
    blocked = {(x, y) for y in range(cfg.map_h) for x in range(cfg.map_w) if (x, y) not in walk}
    runs: list[tuple[int, int, int, int]] = []
    for y in range(cfg.map_h):
        x = 0
        while x < cfg.map_w:
            if (x, y) in blocked:
                x0 = x
                while x < cfg.map_w and (x, y) in blocked:
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


def _validate(
    cfg: GenConfig,
    rooms: list[_RoomRect],
    regions: dict[str, set[_Cell]],
    walk: set[_Cell],
    spawns: list[_Cell],
    tasks: list[tuple[_Cell, str]],
    emergency: _Cell,
) -> None:
    """Falha com ``BuildError`` se qualquer invariante do mapa não valer."""
    world_w, world_h = cfg.map_w * cfg.tile, cfg.map_h * cfg.tile
    if world_w <= _VIEWPORT_W or world_h <= _VIEWPORT_H:
        raise BuildError(f"mundo {world_w}x{world_h} não excede o viewport nos dois eixos")
    if world_w * world_h < 6 * _OLD_AREA:
        raise BuildError(f"área {world_w * world_h} menor que 6x a original ({6 * _OLD_AREA})")
    if len(walk) < 1000:
        raise BuildError(f"área caminhável pequena demais: {len(walk)} células (mínimo 1000)")
    if len(rooms) < 10:
        raise BuildError(f"poucas salas: {len(rooms)} (mínimo 10)")
    names = [name for name, *_ in rooms]
    if len(set(names)) != len(names):
        raise BuildError("nomes de sala duplicados")
    for i, (name_a, xa, ya, wa, ha) in enumerate(rooms):
        cells_a = _rect_cells(xa, ya, wa, ha)
        for name_b, xb, yb, wb, hb in rooms[i + 1 :]:
            if cells_a & _rect_cells(xb, yb, wb, hb):
                raise BuildError(f"salas sobrepostas: {name_a} / {name_b}")

    component = _largest_component(walk)
    if component != walk:
        raise BuildError(
            f"caminhável fragmentado: {len(walk) - len(component)} células fora do componente"
        )

    task_cells = [cell for cell, _type in tasks]
    all_points = [*spawns, *task_cells, emergency]
    if len(set(all_points)) != len(all_points):
        raise BuildError("pontos de gameplay duplicados")
    for cell in all_points:
        if cell not in walk:
            raise BuildError(f"ponto fora da área caminhável: {cell}")
        if cell not in component:
            raise BuildError(f"ponto inalcançável a partir do hub: {cell}")
    for i, a in enumerate(all_points):
        for b in all_points[i + 1 :]:
            if math.dist(a, b) < 1.5:
                raise BuildError(f"pontos próximos demais: {a} {b}")
    for spawn in spawns:
        if abs(spawn[0] - emergency[0]) + abs(spawn[1] - emergency[1]) < 2:
            raise BuildError(f"spawn colado no botão de emergência: {spawn}")

    if len(spawns) < MAX_PLAYERS:
        raise BuildError(f"spawns insuficientes: {len(spawns)} < MAX_PLAYERS={MAX_PLAYERS}")
    room_of_cell = {cell: name for name, *_r in rooms for cell in _rect_cells(*_r)}
    task_rooms = {room_of_cell.get(cell) for cell in task_cells} - {None}
    if len(task_rooms) < 6:
        raise BuildError(f"tarefas concentradas: apenas {len(task_rooms)} salas (mínimo 6)")
    if len(tasks) < len(TASK_TYPES):
        raise BuildError(f"tarefas insuficientes: {len(tasks)} < {len(TASK_TYPES)} tipos")
    if {task_type for _cell, task_type in tasks} != set(TASK_TYPES):
        raise BuildError("catálogo de tipos de tarefa não coberto pelo mapa")
    if not _region_graph_has_cycle(regions):
        raise BuildError("grafo sala/corredor sem ciclos (mapa linear)")


# ---------------------------------------------------------------------------
# Tentativa única de geração (pode falhar; o chamador tenta nova sub-seed).
# ---------------------------------------------------------------------------
def _attempt(rng: random.Random, cfg: GenConfig, seed: int) -> GameMap:
    rooms = _place_rooms(rng, cfg)
    edges = _connectivity_edges(rng, rooms, cfg.extra_edges)

    regions: dict[str, set[_Cell]] = {}
    for name, x, y, w, h in rooms:
        regions[name] = _rect_cells(x, y, w, h)
    centers = [_room_center(room) for room in rooms]
    for edge_index, (i, j) in enumerate(edges):
        width = rng.randint(cfg.corridor_min_width, cfg.corridor_max_width)
        regions[f"corr_{edge_index}"] = _carve_corridor(rng, centers[i], centers[j], width, cfg)

    walk: set[_Cell] = set()
    for cells in regions.values():
        walk |= cells

    # Hub: sala cujo centro está mais perto do centroide do mapa (botão nela).
    centroid = (cfg.map_w / 2, cfg.map_h / 2)
    hub_index = min(
        range(len(rooms)),
        key=lambda idx: (math.dist(centers[idx], centroid), idx),
    )
    emergency = centers[hub_index]

    room_cells: set[_Cell] = set()
    for _name, x, y, w, h in rooms:
        room_cells |= _rect_cells(x, y, w, h)
    spawns = _place_spawns(rng, sorted(room_cells), emergency)
    taken: set[_Cell] = {emergency, *spawns}
    tasks = _place_tasks(rng, rooms, hub_index, taken, cfg)

    _validate(cfg, rooms, regions, walk, spawns, tasks, emergency)

    walls_cells = _blocked_rects(walk, cfg)
    if len(walls_cells) < 3:
        raise BuildError(f"poucas paredes extraídas: {len(walls_cells)}")
    for x, y, w, h in walls_cells:
        if w < 1 or h < 1:
            raise BuildError(f"parede degenerada: {(x, y, w, h)}")

    tile = cfg.tile
    task_points: list[TaskPoint] = []
    for index, (cell, task_type) in enumerate(tasks):
        px, py = _cell_center(cell, tile)
        task_points.append(
            TaskPoint(
                task_id=index + 1,
                task_type=task_type,
                x=px,
                y=py,
                interaction_radius=cfg.task_interaction_radius,
            )
        )
    return GameMap(
        name=f"mapa-{seed}",
        width=cfg.map_w,
        height=cfg.map_h,
        tile_width=tile,
        tile_height=tile,
        walls=[
            Rect(
                x=float(x * tile), y=float(y * tile), width=float(w * tile), height=float(h * tile)
            )
            for x, y, w, h in walls_cells
        ],
        floor_rects=[
            Rect(x=0.0, y=0.0, width=float(cfg.map_w * tile), height=float(cfg.map_h * tile))
        ],
        decorative_rects=[],
        spawn_points=[
            SpawnPoint(spawn_id=index, x=px, y=py)
            for index, (px, py) in enumerate(_cell_center(cell, tile) for cell in spawns)
        ],
        task_points=task_points,
        emergency_meeting=_cell_center(emergency, tile),
        emergency_meeting_radius=cfg.emergency_interaction_radius,
        rooms=[
            Room(
                name=name,
                rect=Rect(
                    x=float(x * tile),
                    y=float(y * tile),
                    width=float(w * tile),
                    height=float(h * tile),
                ),
            )
            for name, x, y, w, h in rooms
        ],
    )


def generate_map(seed: int, *, config: GenConfig = DEFAULT_CONFIG) -> GameMap:
    """Gera o ``GameMap`` completo e validado para ``seed`` (determinístico).

    Generate-and-test: cada tentativa usa uma sub-seed derivada; a primeira
    que passa em todos os gates vence. Levanta ``BuildError`` se o orçamento
    de tentativas se esgotar (praticamente inalcançável com a config padrão).
    """
    rng = random.Random(seed)
    for _ in range(config.max_attempts):
        sub_seed = rng.getrandbits(63)
        try:
            return _attempt(random.Random(sub_seed), config, seed)
        except BuildError:
            continue
    raise BuildError(f"nenhum layout válido em {config.max_attempts} tentativas (seed={seed})")


# ---------------------------------------------------------------------------
# Derivados do GameMap (células caminháveis) — usados por cena e QA.
# ---------------------------------------------------------------------------
def walkable_cells_of(game_map: GameMap) -> set[_Cell]:
    """Células (64 px) cujo centro não está dentro de nenhuma parede.

    As paredes emitidas pelo gerador são alinhadas ao tile, então a
    complementação por célula é exata (mesma regra dos testes do asset).
    """
    cells: set[_Cell] = set()
    for cy in range(game_map.height):
        for cx in range(game_map.width):
            px = cx * game_map.tile_width + game_map.tile_width / 2
            py = cy * game_map.tile_height + game_map.tile_height / 2
            if not any(wall.contains(px, py) for wall in game_map.walls):
                cells.add((cx, cy))
    return cells


# ---------------------------------------------------------------------------
# Emissão do documento Tiled (mesmo schema dos assets commitados).
# ---------------------------------------------------------------------------
def to_tiled_json(game_map: GameMap) -> dict[str, object]:
    """Documento Tiled equivalente ao asset commitado (object layers)."""
    next_id = 1

    def obj_id() -> int:
        nonlocal next_id
        value = next_id
        next_id += 1
        return value

    layers: list[dict[str, object]] = []
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
                    "name": f"{game_map.name}_floor",
                    "x": 0,
                    "y": 0,
                    "width": game_map.width * game_map.tile_width,
                    "height": game_map.height * game_map.tile_height,
                    "visible": True,
                    "rotation": 0,
                }
            ],
        }
    )
    wall_objects: list[dict[str, object]] = []
    for index, wall in enumerate(game_map.walls):
        wall_objects.append(
            {
                "id": obj_id(),
                "name": f"wall_{index}",
                "x": int(wall.x),
                "y": int(wall.y),
                "width": int(wall.width),
                "height": int(wall.height),
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
    spawn_objects: list[dict[str, object]] = []
    for spawn in game_map.spawn_points:
        spawn_objects.append(
            {
                "id": obj_id(),
                "name": f"spawn{spawn.spawn_id}",
                "point": True,
                "x": spawn.x,
                "y": spawn.y,
                "properties": [{"name": "spawn_id", "type": "int", "value": spawn.spawn_id}],
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
    task_objects: list[dict[str, object]] = []
    for index, task in enumerate(game_map.task_points):
        task_objects.append(
            {
                "id": obj_id(),
                "name": f"task{index + 1}",
                "point": True,
                "x": task.x,
                "y": task.y,
                "properties": [
                    {"name": "task_type", "type": "string", "value": task.task_type},
                    {
                        "name": "interaction_radius",
                        "type": "float",
                        "value": task.interaction_radius,
                    },
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
    emergency_objects: list[dict[str, object]] = []
    if game_map.emergency_meeting is not None:
        ex, ey = game_map.emergency_meeting
        emergency_objects.append(
            {
                "id": obj_id(),
                "name": "meeting_button",
                "point": True,
                "x": ex,
                "y": ey,
                "properties": [
                    {
                        "name": "interaction_radius",
                        "type": "float",
                        "value": game_map.emergency_meeting_radius,
                    }
                ],
                "visible": True,
                "rotation": 0,
                "width": 0,
                "height": 0,
            }
        )
    layers.append(
        {
            "id": 5,
            "name": "emergency_meeting",
            "type": "objectgroup",
            "visible": True,
            "opacity": 1,
            "draworder": "topdown",
            "objects": emergency_objects,
        }
    )
    room_objects: list[dict[str, object]] = []
    for room in game_map.rooms:
        room_objects.append(
            {
                "id": obj_id(),
                "name": room.name,
                "x": int(room.rect.x),
                "y": int(room.rect.y),
                "width": int(room.rect.width),
                "height": int(room.rect.height),
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
        "width": game_map.width,
        "height": game_map.height,
        "tilewidth": game_map.tile_width,
        "tileheight": game_map.tile_height,
        "infinite": False,
        "nextlayerid": 7,
        "nextobjectid": next_id,
        "layers": layers,
        "tilesets": [],
    }
