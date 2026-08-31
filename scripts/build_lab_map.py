"""Regenera os assets do mapa padrão a partir do gerador procedural por seed.

Wrapper fino sobre ``codecon_amoung_us.map.generator`` (geometria + gates,
puro) e ``codecon_amoung_us.map.scene`` (cena pastel, pygame): emite
``assets/maps/lab.json`` (schema Tiled, object layers), ``lab_scene.png``,
``lab_menu.png`` (crop 1280x704 do hub, fundo dos menus) e
``models/mapa/overlay-lab.png`` (cena + paredes + marcadores, QA humana).
Em gameplay o mapa é gerado por partida no servidor e reconstruído nos
clientes a partir da seed do protocolo — estes assets existem para os menus
do cliente e para o gate de frescor do CI.

O script é determinístico e reexecutável (idempotente). ``--seed N`` gera os
assets de outra seed (default: ``DEFAULT_SEED``); ``--check`` regenera em
memória e compara com os commitados (JSON byte-a-byte; PNGs por pixels
decodificados, imune a variação de encoder), sem escrever nada — exit != 0
com a lista de assets dessincronizados.

Sem dependências novas: usa apenas pygame para ler/escrever pixels.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame  # noqa: E402

from codecon_amoung_us.map.generator import generate_map, to_tiled_json  # noqa: E402
from codecon_amoung_us.map.scene import menu_crop, overlay_surface, render_scene  # noqa: E402

# Seed dos assets commitados (mapa padrão de menus/lobby).
DEFAULT_SEED = 42

_REPO = Path(__file__).resolve().parent.parent
_OUT_MAP = _REPO / "assets" / "maps" / "lab.json"
_OUT_SCENE = _REPO / "assets" / "maps" / "lab_scene.png"
_OUT_MENU = _REPO / "assets" / "maps" / "lab_menu.png"
_OUT_OVERLAY = _REPO / "models" / "mapa" / "overlay-lab.png"


def _png_pixels_equal(path: Path, surface: pygame.Surface) -> bool:
    """True se o PNG em ``path`` decodifica para os mesmos pixels de ``surface``.

    Comparação por RGB decodificado (PNG é lossless): imune a diferenças de
    encoder entre versões de SDL/libpng e plataformas. O canal alfa é
    ignorado de propósito: as superfícies geradas são 32 bits sem SRCALPHA e
    o PNG commitado é 24 bits — o alfa é descartado na escrita e não carrega
    conteúdo.
    """
    if not path.is_file():
        return False
    loaded = pygame.image.load(str(path))
    return loaded.get_size() == surface.get_size() and (
        pygame.image.tobytes(loaded, "RGB") == pygame.image.tobytes(surface, "RGB")
    )


def _parse_seed() -> tuple[int, bool]:
    """(seed, check_mode) a partir de ``--seed N`` / ``--check``."""
    seed = DEFAULT_SEED
    check = "--check" in sys.argv
    if "--seed" in sys.argv:
        index = sys.argv.index("--seed")
        try:
            seed = int(sys.argv[index + 1])
        except (IndexError, ValueError):
            print("ERRO: uso: build_lab_map.py [--seed N] [--check]")
            raise SystemExit(2) from None
    return seed, check


def check_freshness(seed: int) -> int:
    """Gate de frescor: regenera os artefatos e compara com os commitados."""
    pygame.init()
    try:
        game_map = generate_map(seed)
        map_text = json.dumps(to_tiled_json(game_map), indent=2)
        scene = render_scene(game_map, seed)
        stale: list[str] = []
        if not _OUT_MAP.is_file() or _OUT_MAP.read_text(encoding="utf-8") != map_text:
            stale.append(_OUT_MAP.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_SCENE, scene):
            stale.append(_OUT_SCENE.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_MENU, menu_crop(scene, game_map)):
            stale.append(_OUT_MENU.relative_to(_REPO).as_posix())
        if not _png_pixels_equal(_OUT_OVERLAY, overlay_surface(scene, game_map)):
            stale.append(_OUT_OVERLAY.relative_to(_REPO).as_posix())
        if stale:
            print(f"ERRO: assets dessincronizados com o builder: {', '.join(stale)}")
            print("regenere com: uv run python scripts/build_lab_map.py")
            return 1
        print(f"assets sincronizados com o builder (seed={seed}: lab.json + 3 PNGs)")
        return 0
    finally:
        pygame.quit()


def main(seed: int) -> int:
    pygame.init()
    try:
        game_map = generate_map(seed)
        scene = render_scene(game_map, seed)
        _OUT_MAP.parent.mkdir(parents=True, exist_ok=True)
        _OUT_MAP.write_text(json.dumps(to_tiled_json(game_map), indent=2), encoding="utf-8")
        pygame.image.save(scene, str(_OUT_SCENE))
        pygame.image.save(menu_crop(scene, game_map), str(_OUT_MENU))
        pygame.image.save(overlay_surface(scene, game_map), str(_OUT_OVERLAY))

        print(f"lab.json -> {_OUT_MAP.relative_to(_REPO)}")
        print(f"scene    -> {_OUT_SCENE.relative_to(_REPO)}")
        print(f"menu     -> {_OUT_MENU.relative_to(_REPO)}")
        print(f"overlay  -> {_OUT_OVERLAY.relative_to(_REPO)}")
        world_w = game_map.width * game_map.tile_width
        world_h = game_map.height * game_map.tile_height
        print(
            f"seed={seed}; mundo {world_w}x{world_h}; salas: {len(game_map.rooms)}; "
            f"paredes: {len(game_map.walls)}; spawns: {len(game_map.spawn_points)}; "
            f"tasks: {len(game_map.task_points)}"
        )
        return 0
    finally:
        pygame.quit()


if __name__ == "__main__":
    _seed, _check = _parse_seed()
    sys.exit(check_freshness(_seed) if _check else main(_seed))
