"""Captura determinística de estados da UI em PNG (review humano).

Renderiza estados fixos com SDL dummy e salva em ``captures/`` para
comparação antes/depois e identificação de regressão visual. Não é um gate
de pixels entre sistemas (diferenças de fonte/renderização); é ferramenta
de QA visual.

Uso:
    uv run python scripts/capture_ui_states.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

from codecon_amoung_us.game.meeting import MeetingReason
from codecon_amoung_us.game.model import Role, Team
from codecon_amoung_us.protocol import (
    Ejected,
    GameOver,
    LobbyPlayer,
    MeetingStarted,
    PlayerInfo,
    SnapshotPlayer,
    WorldSnapshot,
)
from codecon_amoung_us.ui.app import App, Screen
from codecon_amoung_us.ui.components import InteractionState
from codecon_amoung_us.ui.viewmodel import VoteUiState

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


def _save(app: App, name: str) -> None:
    CAPTURES_DIR.mkdir(exist_ok=True)
    path = CAPTURES_DIR / f"{name}.png"
    pygame.image.save(app.screen, str(path))
    print(f"capturado: {path.name}")


def main() -> int:
    app = App()
    try:
        # menus (run() atribuiria _current_menu; a captura injeta direto)
        app._current_menu = app.menu_main
        app._render([])
        _save(app, "main")
        app._open_host()
        app._render([])
        _save(app, "host")
        app._open_join()
        app._render([])
        _save(app, "join")
        app._open_settings()
        app._render([])
        _save(app, "settings")

        # lobby: 1 e 4 jogadores (visão do host, com Iniciar habilitado)
        app._enter_lobby()
        app.is_host = True
        app.lobby_players = [
            LobbyPlayer(player_id=0, nickname="gustavo"),
            LobbyPlayer(player_id=1, nickname="ana"),
            LobbyPlayer(player_id=2, nickname="bruno"),
            LobbyPlayer(player_id=3, nickname="carla"),
        ]
        app.my_id = 0
        app.host_id = 0
        app._render([])
        _save(app, "lobby_4_players")
        app.lobby_players = [app.lobby_players[0]]
        app._render([])
        _save(app, "lobby_1_player")

        # lobby: estados de interação dos botões (foco no 2º, pressed no 1º)
        controls = app._lobby_ui_state
        assert controls is not None
        lobby_buttons, lobby_focus = controls
        lobby_focus.index = 1
        app._render([])
        _save(app, "lobby_focused")
        lobby_focus.index = 0
        lobby_buttons[0].interaction = InteractionState.PRESSED
        app._render([])
        _save(app, "lobby_pressed")
        lobby_buttons[0].interaction = InteractionState.IDLE

        # conectando (tela não bloqueante, cancelável)
        app.screen_name = Screen.CONNECTING
        app._single_ui_states.pop("connecting", None)
        app._render([])
        _save(app, "connecting")

        # gameplay crew / impostor / cooldown
        app.screen_name = Screen.GAME
        app.my_id = 0
        app.role = Role.CREW
        app.my_task_ids = [1]
        app.tasks_state = None
        app.last_snapshot = WorldSnapshot(
            tick=1,
            players=[
                SnapshotPlayer(player_id=0, x=400.0, y=352.0, alive=True),
                SnapshotPlayer(player_id=1, x=500.0, y=352.0, alive=True),
            ],
            bodies=[],
        )
        app._nicknames = {0: "gustavo", 1: "ana"}
        app._render([])
        _save(app, "game_crew")

        app.role = Role.IMPOSTOR
        app.last_snapshot = WorldSnapshot(
            tick=1,
            players=[
                SnapshotPlayer(player_id=0, x=400.0, y=352.0, alive=True),
                SnapshotPlayer(player_id=1, x=430.0, y=352.0, alive=True),
            ],
            bodies=[],
        )
        app._render([])
        _save(app, "game_impostor")

        app.kill_cooldown_until = time.monotonic() + 7.0
        app.last_snapshot = WorldSnapshot(
            tick=1,
            players=[
                SnapshotPlayer(player_id=0, x=400.0, y=352.0, alive=True),
                SnapshotPlayer(player_id=1, x=430.0, y=352.0, alive=True),
            ],
            bodies=[],
        )
        app._render([])
        _save(app, "game_impostor_cooldown")
        app.kill_cooldown_until = None

        # votação: selecionada e submetida
        app.meeting = MeetingStarted(
            meeting_id=1,
            reason=MeetingReason.KILL_REPORTED,
            voters=[0, 1, 2],
            vote_timeout_seconds=30.0,
        )
        app.screen_name = Screen.VOTING
        app._meeting_started_at = 0.0
        app.selected_vote_target = 1
        app._render([])
        _save(app, "voting_selected")
        app.vote_ui_state = VoteUiState.SUBMITTED
        app._render([])
        _save(app, "voting_submitted")

        # votação com o máximo de jogadores (paginação, página 2)
        app.vote_ui_state = VoteUiState.SELECTING
        app.selected_vote_target = None
        app.meeting = MeetingStarted(
            meeting_id=2,
            reason=MeetingReason.EMERGENCY,
            voters=list(range(10)),
            vote_timeout_seconds=30.0,
        )
        app._voting_buttons = None
        app._voting_page = 1
        app._render([])
        _save(app, "voting_many_players")
        app._voting_page = 0

        # ejeção privada
        app.screen_name = Screen.EJECTED
        app.private_ejection = Ejected(player_id=0, role=Role.CREW)
        app._render([])
        _save(app, "ejected")

        # transição genérica de fim de reunião (idêntica para todo desfecho);
        # é overlay-only — a captura limpa o buffer para representar o fundo
        app.screen.fill((14, 16, 26))
        app.screen_name = Screen.MEETING_ENDED
        app._render([])
        _save(app, "meeting_ended")

        # game over
        app.screen_name = Screen.GAME_OVER
        app.game_over = GameOver(
            winner=Team.CREW,
            players=[
                PlayerInfo(player_id=0, nickname="gustavo"),
                PlayerInfo(player_id=1, nickname="ana"),
            ],
            roles={0: Role.CREW, 1: Role.IMPOSTOR},
        )
        app._render([])
        _save(app, "game_over")

        # game over com o máximo de jogadores (duas colunas)
        app.game_over = GameOver(
            winner=Team.IMPOSTOR,
            players=[PlayerInfo(player_id=i, nickname=f"jogador{i}") for i in range(10)],
            roles={i: (Role.IMPOSTOR if i == 0 else Role.CREW) for i in range(10)},
        )
        app._single_ui_states.pop("gameover", None)
        app._render([])
        _save(app, "game_over_many_players")

        # erro
        app.screen_name = Screen.ERROR
        app.error_message = "Não foi possível conectar: conexão recusada"
        app._render([])
        _save(app, "error")

        print(f"capturas em: {CAPTURES_DIR}")
        return 0
    finally:
        app._shutdown_connection()
        pygame.quit()


if __name__ == "__main__":
    sys.exit(main())
