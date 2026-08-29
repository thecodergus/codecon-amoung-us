"""Carregador do mapa: asset Tiled -> ``GameMap`` (estruturas do jogo).

O domínio e o servidor nunca dependem do parser Tiled diretamente; toda
conversão acontece aqui. Propriedades customizadas do Tiled (``task_type``,
``spawn_id``, ``collidable``, ``interaction_radius``) alimentam o modelo.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytiled_parser
from pytiled_parser import common_types, layer, tiled_object

from .model import GameMap, Rect, SpawnPoint, TaskPoint

__all__ = ["MapError", "load_map"]


class MapError(Exception):
    """Erro ao carregar/converter o mapa (arquivo, layer ou propriedade)."""


# Tipos de valor aceitos nas propriedades customizadas.
_PropValue = float | str | bool | Path | common_types.Color


def _prop(props: Mapping[str, _PropValue], name: str, default: _PropValue) -> _PropValue:
    return props.get(name, default)


def _as_float(value: _PropValue, name: str) -> float:
    try:
        # cast estático: o conjunto coercível é float|str|bool; Path/Color
        # caem no TypeError/ValueError abaixo em runtime.
        return float(cast("float | str | bool", value))
    except (TypeError, ValueError) as exc:
        raise MapError(f"propriedade '{name}' deveria ser numérica, obtido: {value!r}") from exc


def _as_int(value: _PropValue, name: str) -> int:
    return int(_as_float(value, name))


def _as_str(value: _PropValue, name: str) -> str:
    if isinstance(value, str):
        return value
    raise MapError(f"propriedade '{name}' deveria ser string, obtido: {value!r}")


def _as_color(value: _PropValue, name: str) -> tuple[int, int, int]:
    if isinstance(value, common_types.Color):
        return (value.red, value.green, value.blue)
    raise MapError(f"propriedade '{name}' deveria ser color, obtido: {value!r}")


def _object_layer(tiled: pytiled_parser.TiledMap, name: str) -> layer.ObjectLayer | None:
    for lyr in tiled.layers:
        if isinstance(lyr, layer.ObjectLayer) and lyr.name == name:
            return lyr
    return None


def _require_object_layer(tiled: pytiled_parser.TiledMap, name: str) -> layer.ObjectLayer:
    found = _object_layer(tiled, name)
    if found is None:
        raise MapError(f"layer de objetos obrigatório ausente: '{name}'")
    return found


def _rect_of(obj: tiled_object.TiledObject) -> Rect:
    return Rect(
        x=float(obj.coordinates.x),
        y=float(obj.coordinates.y),
        width=float(obj.size.width),
        height=float(obj.size.height),
    )


def _load_walls(lyr: layer.ObjectLayer) -> list[Rect]:
    walls: list[Rect] = []
    for obj in lyr.tiled_objects:
        if not isinstance(obj, tiled_object.Rectangle):
            continue
        collidable = _prop(obj.properties, "collidable", True)
        if bool(collidable):
            walls.append(_rect_of(obj))
    return walls


def _load_spawns(lyr: layer.ObjectLayer) -> list[SpawnPoint]:
    spawns: list[SpawnPoint] = []
    for index, obj in enumerate(lyr.tiled_objects):
        if not isinstance(obj, tiled_object.Point):
            continue
        spawn_id = _as_int(_prop(obj.properties, "spawn_id", index), "spawn_id")
        spawns.append(
            SpawnPoint(spawn_id=spawn_id, x=float(obj.coordinates.x), y=float(obj.coordinates.y))
        )
    return spawns


def _load_tasks(lyr: layer.ObjectLayer) -> list[TaskPoint]:
    tasks: list[TaskPoint] = []
    for index, obj in enumerate(lyr.tiled_objects):
        if not isinstance(obj, tiled_object.Point):
            continue
        task_type = _as_str(_prop(obj.properties, "task_type", "task"), "task_type")
        radius = _as_float(_prop(obj.properties, "interaction_radius", 20.0), "interaction_radius")
        tasks.append(
            TaskPoint(
                task_id=index + 1,
                task_type=task_type,
                x=float(obj.coordinates.x),
                y=float(obj.coordinates.y),
                interaction_radius=radius,
            )
        )
    return tasks


def _load_emergency(lyr: layer.ObjectLayer) -> tuple[tuple[float, float] | None, float]:
    for obj in lyr.tiled_objects:
        if isinstance(obj, tiled_object.Point):
            radius = _as_float(
                _prop(obj.properties, "interaction_radius", 25.0), "interaction_radius"
            )
            return (float(obj.coordinates.x), float(obj.coordinates.y)), radius
    return None, 0.0


def _load_decorative(
    lyr: layer.ObjectLayer,
) -> list[tuple[Rect, tuple[int, int, int]]]:
    items: list[tuple[Rect, tuple[int, int, int]]] = []
    for obj in lyr.tiled_objects:
        if isinstance(obj, tiled_object.Rectangle):
            color = _as_color(
                _prop(obj.properties, "color", common_types.Color(128, 128, 128, 255)), "color"
            )
            items.append((_rect_of(obj), color))
    return items


def load_map(path: str | Path) -> GameMap:
    """Carrega o asset Tiled e converte para ``GameMap`` (estruturas internas)."""
    map_path = Path(path)
    if not map_path.is_file():
        raise MapError(f"arquivo de mapa não encontrado: {map_path}")
    try:
        tiled = pytiled_parser.parse_map(map_path)
    except Exception as exc:  # noqa: BLE001 - parser externo; erro fica claro
        raise MapError(f"falha ao parsear o mapa {map_path}: {exc}") from exc

    floor_lyr = _require_object_layer(tiled, "floor")
    walls_lyr = _require_object_layer(tiled, "walls")
    spawn_lyr = _require_object_layer(tiled, "spawn_points")
    task_lyr = _require_object_layer(tiled, "task_points")

    floor_rects = [
        _rect_of(o) for o in floor_lyr.tiled_objects if isinstance(o, tiled_object.Rectangle)
    ]
    walls = _load_walls(walls_lyr)
    spawns = _load_spawns(spawn_lyr)
    tasks = _load_tasks(task_lyr)

    emergency_lyr = _object_layer(tiled, "emergency_meeting")
    if emergency_lyr is None:
        emergency, emergency_radius = None, 0.0
    else:
        emergency, emergency_radius = _load_emergency(emergency_lyr)

    decorative_lyr = _object_layer(tiled, "decorative")
    decorative = _load_decorative(decorative_lyr) if decorative_lyr is not None else []

    return GameMap(
        name=map_path.stem,
        width=int(tiled.map_size.width),
        height=int(tiled.map_size.height),
        tile_width=int(tiled.tile_size.width),
        tile_height=int(tiled.tile_size.height),
        walls=walls,
        floor_rects=floor_rects,
        decorative_rects=decorative,
        spawn_points=spawns,
        task_points=tasks,
        emergency_meeting=emergency,
        emergency_meeting_radius=emergency_radius,
    )
