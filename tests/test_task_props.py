"""Validação dos sprites das estações de tarefa (assets gerados).

Espelha o gate de frescor do ``scripts/build_task_props.py``: os 8 sprites
(7 tipos de tarefa + emergência) são determinísticos, têm 64x64 px, são
visualmente distintos entre si e batem com os PNGs commitados em
``assets/tasks/`` (regenerar com ``uv run python scripts/build_task_props.py``).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Protocol, cast

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.game.task_catalog import TASK_TYPES

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "build_task_props.py"


class _TaskPropsBuilder(Protocol):
    """Superfície do builder usada pelos testes (scripts não são pacote)."""

    def generate(self) -> dict[str, pygame.Surface]: ...


def _load_builder() -> _TaskPropsBuilder:
    """Importa scripts/build_task_props.py como módulo (scripts não são pacote)."""
    spec = importlib.util.spec_from_file_location("build_task_props", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast("_TaskPropsBuilder", module)


@pytest.fixture(scope="module")
def builder() -> _TaskPropsBuilder:
    pygame.init()
    return _load_builder()


def _pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGBA")


def test_generate_is_deterministic(builder: _TaskPropsBuilder) -> None:
    first = {name: _pixels(s) for name, s in builder.generate().items()}
    second = {name: _pixels(s) for name, s in builder.generate().items()}
    assert first == second


def test_all_types_and_emergency_generated(builder: _TaskPropsBuilder) -> None:
    sprites = builder.generate()
    assert set(sprites) == {*TASK_TYPES, "emergency"}
    for name, sprite in sprites.items():
        assert sprite.get_size() == (64, 64), name


def test_sprites_are_visually_distinct(builder: _TaskPropsBuilder) -> None:
    sprites = {name: _pixels(s) for name, s in builder.generate().items()}
    names = sorted(sprites)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            assert sprites[a] != sprites[b], f"sprites idênticos: {a} / {b}"


def test_committed_assets_match_builder(builder: _TaskPropsBuilder) -> None:
    stale: list[str] = []
    for name, sprite in builder.generate().items():
        path = _REPO / "assets" / "tasks" / f"{name}.png"
        if not path.is_file():
            stale.append(f"{name} (ausente)")
            continue
        loaded = pygame.image.load(str(path))
        if loaded.get_size() != sprite.get_size() or _pixels(loaded) != _pixels(sprite):
            stale.append(name)
    assert not stale, (
        f"sprites dessincronizados: {stale}; regenere com: "
        "uv run python scripts/build_task_props.py"
    )
