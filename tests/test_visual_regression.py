"""Regressão visual golden-image (SDL dummy, comparação pixel-exata).

Compara estados-chave renderizados — menu principal e gameplay com a câmera
no centro e nos quatro cantos do mapa 2560x1408 — com baselines commitadas
em ``tests/baselines/``. Converte a inspeção manual de capturas em gate
automatizado: qualquer mudança de renderização (cena, câmera, sprites, HUD,
menu) falha o teste.

Determinismo: ``pygame.time.get_ticks`` fixado por monkeypatch (pulsação de
marcadores e índice de animação dos sprites derivam de ticks) e
``renderer.reduced_motion`` forçado. A viabilidade de comparação pixel-exata
entre processos/SOs neste codebase é demonstrada pelo teste de HUD
(``test_hud_stays_fixed_when_camera_moves``), verde na matrix do CI.

Para atualizar as baselines após mudança intencional de arte/layout:

    UPDATE_BASELINES=1 uv run pytest tests/test_visual_regression.py
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.game.model import Role
from codecon_amoung_us.protocol import SnapshotPlayer, WorldSnapshot
from codecon_amoung_us.ui.app import App, Screen

BASELINES_DIR = Path(__file__).parent / "baselines"

# Posições da câmera/jogador local por estado (coordenadas de mundo).
_POSITIONS: dict[str, tuple[float, float]] = {
    "cam_center": (1248.0, 700.0),  # hub: jogador centralizado no viewport
    "cam_corner_tl": (40.0, 40.0),
    "cam_corner_tr": (2520.0, 40.0),
    "cam_corner_bl": (40.0, 1368.0),
    "cam_corner_br": (2520.0, 1368.0),
}
_STATES = ["main_menu", *_POSITIONS]


@pytest.fixture(scope="module")
def app() -> Iterator[App]:
    instance = App()
    instance.renderer.reduced_motion = True  # marcadores estáticos
    yield instance
    instance._shutdown_connection()
    # Sem pygame.quit() aqui: ciclos quit->init corrompem o cache global de
    # fontes do pygame-menu (ver nota em tests/test_ui_events.py).


def _render_state(app: App, state: str) -> None:
    if state == "main_menu":
        app.screen_name = Screen.MAIN
        app._current_menu = app.menu_main
    else:
        x, y = _POSITIONS[state]
        app.screen_name = Screen.GAME
        app.my_id = 0
        app.role = Role.CREW
        app.my_task_ids = [1]
        app.tasks_state = None
        app.last_snapshot = WorldSnapshot(
            tick=1,
            players=[
                SnapshotPlayer(player_id=0, x=x, y=y, alive=True),
                SnapshotPlayer(player_id=1, x=x + 44.0, y=y, alive=True),
            ],
            bodies=[],
        )
        app._nicknames = {0: "gustavo", 1: "ana"}
        app.camera.snap_to(x, y)
        app._camera_needs_snap = False
    app._render([])


@pytest.mark.parametrize("state", _STATES)
def test_visual_baseline(app: App, monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 0)
    _render_state(app, state)
    baseline = BASELINES_DIR / f"{state}.png"
    if os.environ.get("UPDATE_BASELINES") == "1":
        BASELINES_DIR.mkdir(exist_ok=True)
        pygame.image.save(app.screen, str(baseline))
        return
    assert baseline.is_file(), f"baseline ausente: {baseline}"
    rendered = pygame.image.tobytes(app.screen, "RGB")
    expected = pygame.image.tobytes(pygame.image.load(str(baseline)), "RGB")
    assert rendered == expected, (
        f"estado '{state}' diverge da baseline; se a mudança for intencional, "
        "atualize com: UPDATE_BASELINES=1 uv run pytest tests/test_visual_regression.py"
    )
