"""Benchmark do carregamento de sprites: oráculo get_at vs kernel de pixels.

Mede o processamento dos 72 frames usados por ``DuckeeSprites`` (o custo
real do startup) em três variantes:

1. ``oracle``: algoritmo original (``get_at``/``set_at`` por pixel) — baseline
   histórico medido em 0,28 s na auditoria (2026-08-30);
2. ``buffer``: mesmo caminho de produção (buffer RGBA + kernel), que roda
   Python puro quando a extensão não está compilada;
3. ``init``: ``DuckeeSprites()`` completo (como o jogo faz).

Uso: ``uv run python scripts/bench_sprites.py [runs]`` (padrão: 7).
"""

from __future__ import annotations

import os
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.config import default_models_dir
from codecon_amoung_us.ui import _native_pixels
from codecon_amoung_us.ui._native_pixels import apply_background_removal
from codecon_amoung_us.ui.sprites import (
    _ANIMATIONS,
    DUCKEE_COLORS,
    PlayerAnim,
    _border_background,
)

_KERNEL_COMPILED = _native_pixels.__file__.endswith(".so")


def _frame_filename(anim: PlayerAnim, index: int) -> str:
    if anim is PlayerAnim.DEATH:
        return "duckee_death.png"
    base = "walk_run" if anim is PlayerAnim.WALK else anim.value
    return f"duckee_{base}{index + 1}.png"


def _frame_paths() -> list[Path]:
    base = default_models_dir() / "duckee"
    paths: list[Path] = []
    for color in DUCKEE_COLORS:
        for anim, (folder, count) in _ANIMATIONS.items():
            for index in range(count):
                paths.append(
                    base
                    / color
                    / "individual_animations"
                    / folder
                    / "png_sequence"
                    / _frame_filename(anim, index)
                )
    return paths


def _oracle(path: Path) -> None:
    raw = pygame.image.load(str(path))
    w, h = raw.get_size()
    border: Counter[tuple[int, int, int]] = Counter()
    for x in range(w):
        border[_rgb(raw.get_at((x, 0)))] += 1
        border[_rgb(raw.get_at((x, h - 1)))] += 1
    for y in range(h):
        border[_rgb(raw.get_at((0, y)))] += 1
        border[_rgb(raw.get_at((w - 1, y)))] += 1
    background = border.most_common(1)[0][0]
    reachable = [[False] * w for _ in range(h)]
    stack: list[tuple[int, int]] = []
    for x in range(w):
        stack.extend([(x, 0), (x, h - 1)])
    for y in range(h):
        stack.extend([(0, y), (w - 1, y)])
    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h) or reachable[y][x]:
            continue
        reachable[y][x] = True
        if _rgb(raw.get_at((x, y))) != background:
            continue
        stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    out = pygame.Surface((w, h), pygame.SRCALPHA)
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if not reachable[y][x]:
                out.set_at((x, y), raw.get_at((x, y)))
                if out.get_at((x, y))[3] > 0:
                    minx = min(minx, x)
                    miny = min(miny, y)
                    maxx = max(maxx, x)
                    maxy = max(maxy, y)
    if maxx >= 0:
        out.subsurface((minx, miny, maxx - minx + 1, maxy - miny + 1)).copy()


def _rgb(pixel: pygame.Color) -> tuple[int, int, int]:
    return (pixel.r, pixel.g, pixel.b)


def _buffer(path: Path) -> None:
    raw = pygame.image.load(str(path))
    raw.set_colorkey(None)
    w, h = raw.get_size()
    work = pygame.Surface((w, h), pygame.SRCALPHA)
    work.blit(raw, (0, 0))
    data = bytearray(pygame.image.tostring(work, "RGBA"))
    background = _border_background(data, w, h)
    bbox = apply_background_removal(data, w, h, *background)
    out = pygame.image.fromstring(bytes(data), (w, h), "RGBA")
    if bbox is not None:
        minx, miny, maxx, maxy = bbox
        out.subsurface((minx, miny, maxx - minx + 1, maxy - miny + 1)).copy()


def _time(label: str, fn: Callable[[Path], object], paths: list[Path], runs: int) -> float:
    samples: list[float] = []
    for _ in range(runs):
        start = time.perf_counter()
        for path in paths:
            fn(path)
        samples.append(time.perf_counter() - start)
    median = statistics.median(samples)
    print(f"{label:>10}: {median * 1e3:8.1f} ms  (min {min(samples) * 1e3:.1f}, {runs} runs)")
    return median


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    paths = _frame_paths()
    print(f"frames: {len(paths)} | kernel compilado: {_KERNEL_COMPILED}")
    _time("oracle", _oracle, paths, 1)  # warm-up do cache de imagens
    oracle = _time("oracle", _oracle, paths, runs)
    buffer = _time("buffer", _buffer, paths, runs)
    from codecon_amoung_us.ui.sprites import DuckeeSprites

    init = _time("init", lambda _p: DuckeeSprites(), paths[:1], runs)
    speedup = oracle / buffer if buffer else float("inf")
    print(f"speedup buffer vs oracle: {speedup:.1f}x | init total: {init * 1e3:.1f} ms")


if __name__ == "__main__":
    main()
