"""Testes do carregamento do mapa a partir do asset Tiled (sem pygame)."""

from __future__ import annotations

import json

import pytest

from codecon_amoung_us.config import default_map_path
from codecon_amoung_us.map.loader import MapError, load_map
from codecon_amoung_us.map.model import GameMap


@pytest.fixture
def game_map() -> GameMap:
    return load_map(default_map_path())


def test_loads_real_asset(game_map: GameMap) -> None:
    assert game_map.name == "lab"
    assert game_map.width == 40
    assert game_map.height == 22
    assert game_map.tile_width == 64
    assert game_map.tile_height == 64


def test_walls_loaded(game_map: GameMap) -> None:
    assert len(game_map.walls) >= 3
    # todas as paredes são rects válidos
    for wall in game_map.walls:
        assert wall.width > 0 and wall.height > 0


def test_spawn_points_with_ids(game_map: GameMap) -> None:
    assert [s.spawn_id for s in game_map.spawn_points] == list(range(10))
    assert len({(s.x, s.y) for s in game_map.spawn_points}) == 10


def test_task_points_with_properties(game_map: GameMap) -> None:
    assert len(game_map.task_points) == 10
    by_type = {t.task_type for t in game_map.task_points}
    assert {"wires", "swipe_card", "fix_wiring", "calibrate", "clean_filter"} <= by_type
    # interaction_radius veio da propriedade customizada do Tiled
    assert all(t.interaction_radius == 20.0 for t in game_map.task_points)


def test_emergency_meeting_point(game_map: GameMap) -> None:
    assert game_map.emergency_meeting is not None
    assert game_map.emergency_meeting_radius == 25.0


def test_rooms_loaded(game_map: GameMap) -> None:
    # mapa multi-sala: pelo menos 6 áreas nomeadas e distintas
    assert len(game_map.rooms) >= 6
    names = [room.name for room in game_map.rooms]
    assert len(set(names)) == len(names)
    for room in game_map.rooms:
        assert room.rect.width > 0 and room.rect.height > 0


def test_floor_and_decorative(game_map: GameMap) -> None:
    # o chão do lab é um retângulo único (o fundo é a própria cena)
    assert len(game_map.floor_rects) == 1
    assert len(game_map.decorative_rects) == 0


def test_missing_file_raises() -> None:
    with pytest.raises(MapError):
        load_map("nao_existe.json")


def test_missing_required_layer_raises(tmp_path: object) -> None:
    import pathlib

    tmp = pathlib.Path(str(tmp_path))
    minimal = {
        "type": "map",
        "version": "1.10",
        "orientation": "orthogonal",
        "width": 10,
        "height": 10,
        "tilewidth": 32,
        "tileheight": 32,
        "infinite": False,
        "layers": [
            {
                "id": 1,
                "name": "floor",
                "type": "objectgroup",
                "visible": True,
                "opacity": 1,
                "draworder": "topdown",
                "objects": [],
            }
        ],
        "tilesets": [],
    }
    bad = tmp / "sem_walls.json"
    bad.write_text(json.dumps(minimal), encoding="utf-8")
    with pytest.raises(MapError, match="walls"):
        load_map(bad)


def test_bounds(game_map: GameMap) -> None:
    left, top, right, bottom = game_map.bounds()
    assert (left, top, right, bottom) == (0.0, 0.0, 2560.0, 1408.0)
