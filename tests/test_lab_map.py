"""Validação estrutural do mapa lab expandido (asset commitado).

Espelha os gates do ``scripts/build_lab_map.py`` contra o asset vigente:
mundo maior que o viewport nos dois eixos, área >= 2x a anterior, salas
mínimas, componente caminhável único e alcançabilidade por caminho (BFS —
nunca linha reta) de todos os pontos de gameplay.
"""

from __future__ import annotations

from collections import deque

import pytest

from codecon_amoung_us.config import MAX_PLAYERS, default_map_path
from codecon_amoung_us.map.loader import load_map
from codecon_amoung_us.map.model import GameMap

# Viewport lógico de gameplay (canvas 1280x768 menos a faixa do HUD).
VIEWPORT_W, VIEWPORT_H = 1280, 704
# Área do mapa anterior (20x11 tiles de 64 px).
OLD_AREA = 1280 * 704


@pytest.fixture(scope="module")
def game_map() -> GameMap:
    return load_map(default_map_path())


def _cell_of(game_map: GameMap, px: float, py: float) -> tuple[int, int]:
    return int(px // game_map.tile_width), int(py // game_map.tile_height)


def _walkable_grid(game_map: GameMap) -> list[list[bool]]:
    """Grade de células (64 px): célula livre = centro fora de paredes."""
    grid: list[list[bool]] = []
    for cy in range(game_map.height):
        row: list[bool] = []
        for cx in range(game_map.width):
            px = cx * game_map.tile_width + game_map.tile_width / 2
            py = cy * game_map.tile_height + game_map.tile_height / 2
            row.append(not any(wall.contains(px, py) for wall in game_map.walls))
        grid.append(row)
    return grid


def _flood(
    game_map: GameMap, grid: list[list[bool]], start: tuple[int, int]
) -> set[tuple[int, int]]:
    """Componente caminhável alcançável a partir de ``start`` (BFS 4-viz.)."""
    seen = {start}
    dq: deque[tuple[int, int]] = deque([start])
    while dq:
        cx, cy = dq.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if (
                0 <= nx < game_map.width
                and 0 <= ny < game_map.height
                and grid[ny][nx]
                and (nx, ny) not in seen
            ):
                seen.add((nx, ny))
                dq.append((nx, ny))
    return seen


def test_map_exceeds_viewport_in_both_axes(game_map: GameMap) -> None:
    _left, _top, right, bottom = game_map.bounds()
    assert right > VIEWPORT_W
    assert bottom > VIEWPORT_H


def test_map_area_at_least_double_previous(game_map: GameMap) -> None:
    _left, _top, right, bottom = game_map.bounds()
    assert right * bottom >= 2 * OLD_AREA


def test_minimum_room_count(game_map: GameMap) -> None:
    assert len(game_map.rooms) >= 6


def test_enough_spawns_for_max_players(game_map: GameMap) -> None:
    assert len(game_map.spawn_points) >= MAX_PLAYERS


def test_walkable_is_single_component(game_map: GameMap) -> None:
    grid = _walkable_grid(game_map)
    start = next(
        (cx, cy) for cy in range(game_map.height) for cx in range(game_map.width) if grid[cy][cx]
    )
    reachable = _flood(game_map, grid, start)
    total = sum(row.count(True) for row in grid)
    assert len(reachable) == total


def test_gameplay_points_not_inside_walls(game_map: GameMap) -> None:
    points = [(s.x, s.y) for s in game_map.spawn_points]
    points += [(t.x, t.y) for t in game_map.task_points]
    assert game_map.emergency_meeting is not None
    points.append(game_map.emergency_meeting)
    for px, py in points:
        assert not any(wall.contains(px, py) for wall in game_map.walls), (px, py)


def test_every_spawn_reaches_tasks_and_emergency(game_map: GameMap) -> None:
    grid = _walkable_grid(game_map)
    assert game_map.emergency_meeting is not None
    targets = [_cell_of(game_map, *game_map.emergency_meeting)]
    targets += [_cell_of(game_map, t.x, t.y) for t in game_map.task_points]
    for spawn in game_map.spawn_points:
        start = _cell_of(game_map, spawn.x, spawn.y)
        assert grid[start[1]][start[0]], f"spawn em célula bloqueada: {start}"
        reachable = _flood(game_map, grid, start)
        for target in targets:
            assert target in reachable, f"spawn {start} não alcança {target}"


def test_tasks_spread_across_rooms(game_map: GameMap) -> None:
    rooms_of_tasks = {
        room.name
        for task in game_map.task_points
        for room in game_map.rooms
        if room.rect.contains(task.x, task.y)
    }
    assert len(rooms_of_tasks) >= 4


def test_emergency_button_in_room(game_map: GameMap) -> None:
    assert game_map.emergency_meeting is not None
    ex, ey = game_map.emergency_meeting
    assert any(room.rect.contains(ex, ey) for room in game_map.rooms)
