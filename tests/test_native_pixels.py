"""Equivalência do kernel de pixels (``ui/_native_pixels``) com o oráculo.

O algoritmo original de remoção de fundo (``get_at``/``set_at`` por pixel)
é mantido aqui como oráculo: o caminho novo (buffer RGBA contíguo + kernel
Cython Pure Python Mode) deve produzir bytes e bounding box **idênticos**
para todo PNG de ``models/``. Roda igual nos modos puro e compilado —
é a garantia de paridade do kernel.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame
import pytest

from codecon_amoung_us.config import default_models_dir
from codecon_amoung_us.ui._native_pixels import apply_background_removal
from codecon_amoung_us.ui.sprites import _border_background

_MODEL_PNGS = sorted((default_models_dir() / "duckee").rglob("*.png"))


def _oracle(path: Path) -> tuple[bytes, tuple[int, int, int, int] | None]:
    """Algoritmo original (get_at/set_at por pixel) — oráculo de equivalência."""
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
    bbox = None if maxx < 0 else (minx, miny, maxx, maxy)
    return pygame.image.tostring(out, "RGBA"), bbox


def _rgb(pixel: pygame.Color) -> tuple[int, int, int]:
    return (pixel.r, pixel.g, pixel.b)


def _new_path(path: Path) -> tuple[bytes, tuple[int, int, int, int] | None]:
    """Caminho de produção: buffer RGBA + kernel (mesmo de sprites._load_frame)."""
    raw = pygame.image.load(str(path))
    raw.set_colorkey(None)  # ver sprites._load_frame: blit não pode aplicar a chave
    w, h = raw.get_size()
    work = pygame.Surface((w, h), pygame.SRCALPHA)
    work.blit(raw, (0, 0))
    data = bytearray(pygame.image.tostring(work, "RGBA"))
    background = _border_background(data, w, h)
    bbox = apply_background_removal(data, w, h, *background)
    return bytes(data), bbox


@pytest.mark.parametrize("path", _MODEL_PNGS, ids=lambda p: p.name)
def test_kernel_matches_oracle(path: Path) -> None:
    expected_bytes, expected_bbox = _oracle(path)
    actual_bytes, actual_bbox = _new_path(path)
    assert actual_bbox == expected_bbox
    assert actual_bytes == expected_bytes


def test_all_background_returns_none() -> None:
    data = bytearray([9, 9, 9, 255] * (8 * 8))
    assert apply_background_removal(data, 8, 8, 9, 9, 9) is None
    assert not any(data)  # tudo virou (0, 0, 0, 0)


def test_no_background_keeps_everything() -> None:
    # borda vermelha, centro verde: fundo = vermelho. A borda é removida e —
    # semântica do algoritmo original — o anel verde ADJACENTE ao fundo
    # também é marcado alcançável (fronteira de cor diferente não expande,
    # mas é visitada). Sobram só os pixels verdes a partir de (2, 2).
    w = h = 8
    data = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            i = (y * w + x) * 4
            on_border = x in (0, w - 1) or y in (0, h - 1)
            data[i : i + 4] = bytes((200, 0, 0, 255) if on_border else (0, 200, 0, 255))
    bbox = apply_background_removal(data, w, h, 200, 0, 0)
    assert bbox == (2, 2, w - 3, h - 3)
    # núcleo preservado
    center = ((h // 2) * w + w // 2) * 4
    assert tuple(data[center : center + 4]) == (0, 200, 0, 255)
