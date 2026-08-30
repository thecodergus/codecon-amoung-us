"""Gera os sprites das estações de tarefa (objetos do mundo) a partir do pack.

Cada estação é um objeto 64x64 px de mundo (grade 16x16 escalada 4x, como a
cena do lab): um console/pedestal coerente com o tileset "Top Down Lab"
(ansimuz) — mesma paleta teal/navy — com um detalhe pixel-art por tipo de
tarefa (fios, lâmpadas, slot de cartão, gauges, pads, monitor, filtro) e um
pedestal com botão abobadado vermelho para a reunião de emergência.

O script é determinístico e reexecutável (idempotente). Saída commitada em
``assets/tasks/<task_type>.png`` + ``assets/tasks/emergency.png``. Modo
``--check`` (gate de frescor para CI): regenera em memória e compara com os
commitados por pixels decodificados, sem escrever nada — exit != 0 com a
lista de assets dessincronizados.

Sem dependências novas: usa apenas pygame para desenhar/escrever pixels.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from codecon_amoung_us.game.task_catalog import TASK_TYPES  # noqa: E402

_GRID = 16  # resolução de desenho (pixel art)
_SCALE = 4  # 1 tile da cena = 16 px x4 -> 64 px de mundo
_SIZE = _GRID * _SCALE

_REPO = Path(__file__).resolve().parent.parent
_OUT_DIR = _REPO / "assets" / "tasks"

# ---------------------------------------------------------------------------
# Paleta (amostrada do Tileset.png do pack — coerência visual com a cena).
# ---------------------------------------------------------------------------
_TEAL_DARK = (6, 44, 49)
_TEAL = (0, 64, 64)
_METAL = (96, 96, 128)
_METAL_DARK = (58, 58, 90)
_METAL_DEEP = (32, 32, 64)
_LIGHT = (164, 174, 193)
_WHITE = (255, 252, 255)
_SCREEN = (61, 87, 114)
_SCREEN_DEEP = (40, 57, 98)
_RED = (242, 74, 74)
_RED_LIGHT = (255, 140, 140)
_GREEN = (96, 210, 96)
_BLUE = (96, 196, 255)
_YELLOW = (255, 212, 92)
_AMBER = (255, 180, 60)


class BuildError(Exception):
    """Falha de geração/validação dos sprites (o script sai com código != 0)."""


# ---------------------------------------------------------------------------
# Desenho em grade 16x16 (fundo transparente — o objeto flutua sobre o piso).
# ---------------------------------------------------------------------------
def _canvas() -> pygame.Surface:
    return pygame.Surface((_GRID, _GRID), pygame.SRCALPHA)


def _console_base(surf: pygame.Surface, *, left: int = 2, right: int = 13) -> None:
    """Console/pedestal padrão: moldura metálica, painel teal, topo claro."""
    pygame.draw.rect(surf, _METAL_DARK, (left, 4, right - left + 1, 12))
    pygame.draw.rect(surf, _TEAL, (left + 1, 5, right - left - 1, 10))
    pygame.draw.line(surf, _LIGHT, (left + 1, 5), (right - 1, 5))
    pygame.draw.line(surf, _METAL_DEEP, (left, 15), (right, 15))


def _draw_wires(surf: pygame.Surface) -> None:
    _console_base(surf)
    pygame.draw.rect(surf, _METAL_DEEP, (4, 6, 8, 7))  # painel aberto
    colors = (_RED, _YELLOW, _BLUE, _GREEN)
    for i, color in enumerate(colors):
        x = 5 + i * 2
        end = 11 if i % 2 == 0 else 9  # metade dos fios desconectados (mais curtos)
        pygame.draw.line(surf, color, (x, 6), (x, end))
        if i % 2 == 1:
            surf.set_at((x, end + 1), _LIGHT)  # terminal solto


def _draw_fix_wiring(surf: pygame.Surface) -> None:
    _console_base(surf)
    lit = {(0, 0), (1, 1), (2, 0), (0, 2), (2, 2)}  # padrão determinístico
    for row in range(3):
        for col in range(3):
            x, y = 4 + col * 3, 6 + row * 3
            if (col, row) in lit:
                pygame.draw.rect(surf, _YELLOW, (x, y, 2, 2))
                surf.set_at((x, y), _WHITE)  # núcleo quente da lâmpada
            else:
                pygame.draw.rect(surf, _METAL_DEEP, (x, y, 2, 2))


def _draw_swipe_card(surf: pygame.Surface) -> None:
    _console_base(surf, left=4, right=11)
    pygame.draw.line(surf, _GREEN, (10, 6), (10, 12))  # faixa de status
    pygame.draw.rect(surf, _METAL_DEEP, (5, 7, 4, 1))  # slot
    pygame.draw.rect(surf, _WHITE, (5, 8, 4, 3))  # cartão parcialmente inserido
    pygame.draw.line(surf, _AMBER, (5, 9), (8, 9))  # tarja do cartão


def _draw_calibrate(surf: pygame.Surface) -> None:
    _console_base(surf)
    for cx, cy, needle in ((5, 9, (7, 7)), (10, 9, (10, 6))):
        pygame.draw.circle(surf, _LIGHT, (cx, cy), 3)
        pygame.draw.circle(surf, _SCREEN_DEEP, (cx, cy), 2)
        pygame.draw.line(surf, _AMBER, (cx, cy), needle)


def _draw_clean_filter(surf: pygame.Surface) -> None:
    _console_base(surf)
    for y in (6, 8, 10, 12):  # grade do filtro
        pygame.draw.line(surf, _METAL, (4, y), (11, y))
    for x, y, color in ((5, 7, _AMBER), (9, 9, _RED), (7, 11, _YELLOW)):
        surf.set_at((x, y), color)  # detritos presos na grade
        surf.set_at((x + 1, y), color)


def _draw_start_reactor(surf: pygame.Surface) -> None:
    _console_base(surf)
    pads = ((4, 6, _RED), (8, 6, _BLUE), (4, 10, _GREEN), (8, 10, _YELLOW))
    for x, y, color in pads:
        pygame.draw.rect(surf, _METAL_DEEP, (x - 1, y - 1, 4, 4))  # rebordo do pad
        pygame.draw.rect(surf, color, (x, y, 3, 3))


def _draw_asteroids(surf: pygame.Surface) -> None:
    _console_base(surf)
    pygame.draw.rect(surf, _SCREEN, (4, 6, 8, 7))  # moldura do monitor
    pygame.draw.rect(surf, _SCREEN_DEEP, (5, 7, 6, 5))
    for x, y in ((6, 8), (10, 11)):
        surf.set_at((x, y), _WHITE)  # estrelas de fundo
    rock = [(8, 8), (9, 8), (7, 9), (8, 9), (9, 9), (8, 10), (7, 10)]
    for x, y in rock:
        surf.set_at((x, y), _METAL)
    surf.set_at((9, 10), _METAL_DARK)  # cratera
    pygame.draw.line(surf, _AMBER, (5, 9), (6, 9))  # mira
    pygame.draw.line(surf, _AMBER, (10, 9), (11, 9))


def _draw_emergency(surf: pygame.Surface) -> None:
    pygame.draw.rect(surf, _METAL_DARK, (2, 9, 12, 7))  # mesa/pedestal
    pygame.draw.line(surf, _LIGHT, (3, 9), (12, 9))
    pygame.draw.line(surf, _METAL_DEEP, (2, 15), (13, 15))
    pygame.draw.circle(surf, _LIGHT, (8, 7), 4, 1)  # anel de proteção (vidro)
    pygame.draw.rect(surf, _METAL, (5, 8, 6, 2))  # base do botão
    pygame.draw.circle(surf, _RED, (8, 6), 3)  # botão abobadado
    surf.set_at((7, 5), _RED_LIGHT)  # brilho da cúpula
    surf.set_at((8, 5), _RED_LIGHT)


_BUILDERS = {
    "wires": _draw_wires,
    "fix_wiring": _draw_fix_wiring,
    "swipe_card": _draw_swipe_card,
    "calibrate": _draw_calibrate,
    "clean_filter": _draw_clean_filter,
    "start_reactor": _draw_start_reactor,
    "asteroids": _draw_asteroids,
    "emergency": _draw_emergency,
}


# ---------------------------------------------------------------------------
# Geração e gates.
# ---------------------------------------------------------------------------
def generate() -> dict[str, pygame.Surface]:
    """Sprites 64x64 (pixel art 16x16 x4) por tipo de tarefa + emergência."""
    if set(_BUILDERS) - {*TASK_TYPES, "emergency"}:
        raise BuildError("builder de sprite para tipo fora do catálogo")
    missing = [t for t in TASK_TYPES if t not in _BUILDERS]
    if missing:
        raise BuildError(f"tipos do catálogo sem sprite: {missing}")
    sprites: dict[str, pygame.Surface] = {}
    for name, builder in _BUILDERS.items():
        canvas = _canvas()
        builder(canvas)
        sprite = pygame.Surface((_SIZE, _SIZE), pygame.SRCALPHA)
        pygame.transform.scale(canvas, (_SIZE, _SIZE), sprite)
        sprites[name] = sprite
    return sprites


def _png_pixels_equal(path: Path, surface: pygame.Surface) -> bool:
    """True se o PNG em ``path`` decodifica para os mesmos pixels de ``surface``."""
    if not path.is_file():
        return False
    loaded = pygame.image.load(str(path))
    return loaded.get_size() == surface.get_size() and (
        pygame.image.tobytes(loaded, "RGBA") == pygame.image.tobytes(surface, "RGBA")
    )


def check_freshness() -> int:
    """Gate de frescor: regenera os sprites e compara com os commitados."""
    pygame.init()
    try:
        stale = [
            f"assets/tasks/{name}.png"
            for name, sprite in generate().items()
            if not _png_pixels_equal(_OUT_DIR / f"{name}.png", sprite)
        ]
        if stale:
            print(f"ERRO: sprites dessincronizados com o builder: {', '.join(stale)}")
            print("regenere com: uv run python scripts/build_task_props.py")
            return 1
        print(f"sprites sincronizados com o builder ({len(_BUILDERS)} PNGs)")
        return 0
    except BuildError as exc:
        print(f"ERRO: {exc}")
        return 1
    finally:
        pygame.quit()


def main() -> int:
    pygame.init()
    try:
        sprites = generate()
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        for name, sprite in sprites.items():
            pygame.image.save(sprite, str(_OUT_DIR / f"{name}.png"))
            print(f"{name} -> {_OUT_DIR.relative_to(_REPO) / f'{name}.png'}")
        print(f"{len(sprites)} sprites {_SIZE}x{_SIZE} gerados")
        return 0
    except BuildError as exc:
        print(f"ERRO: {exc}")
        return 1
    finally:
        pygame.quit()


if __name__ == "__main__":
    sys.exit(check_freshness() if "--check" in sys.argv else main())
