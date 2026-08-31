"""Gates do gerador procedural de mapas (seed -> GameMap validado).

Espelha os invariantes do antigo builder autorado contra uma amostra de
seeds (mundo maior que o viewport, área caminhável mínima, salas mínimas,
componente caminhável único, alcançabilidade BFS de todos os pontos de
gameplay, distribuição de tarefas) e adiciona os invariantes novos do
gerador: determinismo (mesma seed -> mesma geometria, inclusive entre
processos) e variedade (seeds distintas -> layouts distintos).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import deque
from collections.abc import Iterable

import pytest

from codecon_amoung_us.config import MAX_PLAYERS
from codecon_amoung_us.game.task_catalog import TASK_TYPES
from codecon_amoung_us.map.generator import generate_map, to_tiled_json, walkable_cells_of
from codecon_amoung_us.map.model import GameMap

# Viewport lógico de gameplay (canvas 1280x768 menos a faixa do HUD).
VIEWPORT_W, VIEWPORT_H = 1280, 704
OLD_AREA = 1280 * 704

SEEDS = [1, 2, 3, 7, 42, 99, 123, 2026, 31337, 2**62]


def _cell_of(game_map: GameMap, px: float, py: float) -> tuple[int, int]:
    return int(px // game_map.tile_width), int(py // game_map.tile_height)


def _flood(walk: set[tuple[int, int]], start: tuple[int, int]) -> set[tuple[int, int]]:
    seen = {start}
    queue: deque[tuple[int, int]] = deque([start])
    while queue:
        cx, cy = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cx + dx, cy + dy)
            if nxt in walk and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def _gameplay_cells(game_map: GameMap) -> Iterable[tuple[int, int]]:
    for spawn in game_map.spawn_points:
        yield _cell_of(game_map, spawn.x, spawn.y)
    for task in game_map.task_points:
        yield _cell_of(game_map, task.x, task.y)
    assert game_map.emergency_meeting is not None
    yield _cell_of(game_map, *game_map.emergency_meeting)


@pytest.mark.parametrize("seed", SEEDS)
def test_generated_map_passes_structural_gates(seed: int) -> None:
    game_map = generate_map(seed)
    _left, _top, right, bottom = game_map.bounds()
    assert right > VIEWPORT_W and bottom > VIEWPORT_H
    assert right * bottom >= 6 * OLD_AREA
    assert len(game_map.rooms) >= 10
    assert len(game_map.spawn_points) >= MAX_PLAYERS
    assert game_map.emergency_meeting is not None

    walk = walkable_cells_of(game_map)
    assert len(walk) >= 1000

    points = list(_gameplay_cells(game_map))
    for cell in points:
        assert cell in walk, f"ponto fora do caminhável: {cell}"
    reachable = _flood(walk, points[0])
    assert reachable == walk, "caminhável fragmentado"
    for cell in points:
        assert cell in reachable, f"ponto inalcançável: {cell}"

    task_rooms = {
        room.name
        for task in game_map.task_points
        for room in game_map.rooms
        if room.rect.contains(task.x, task.y)
    }
    assert len(task_rooms) >= 6
    assert {task.task_type for task in game_map.task_points} == set(TASK_TYPES)

    ex, ey = game_map.emergency_meeting
    assert any(room.rect.contains(ex, ey) for room in game_map.rooms)


def test_same_seed_same_geometry() -> None:
    assert generate_map(42) == generate_map(42)


def test_distinct_seeds_distinct_layouts() -> None:
    signatures = {
        tuple((wall.x, wall.y, wall.width, wall.height) for wall in generate_map(seed).walls)
        for seed in range(20)
    }
    assert len(signatures) == 20


def test_to_tiled_json_roundtrip_is_deterministic() -> None:
    doc_a = json.dumps(to_tiled_json(generate_map(42)), sort_keys=True)
    doc_b = json.dumps(to_tiled_json(generate_map(42)), sort_keys=True)
    assert doc_a == doc_b


def test_cross_process_determinism() -> None:
    """A geometria da seed é idêntica em outro processo (contrato servidor<->cliente)."""

    def digest(game_map: GameMap) -> str:
        payload = json.dumps(to_tiled_json(game_map), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    code = (
        "import hashlib, json;"
        "from codecon_amoung_us.map.generator import generate_map, to_tiled_json;"
        "doc = json.dumps(to_tiled_json(generate_map(42)), sort_keys=True);"
        "print(hashlib.sha256(doc.encode()).hexdigest())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    # O banner do pygame (import indireto) vai para stdout: o hash é a
    # última linha não vazia.
    printed = [line for line in result.stdout.splitlines() if line.strip()]
    assert printed[-1].strip() == digest(generate_map(42))
