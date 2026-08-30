"""Smoke test headless da UI (SDL_VIDEODRIVER=dummy).

Exercita a criação do App, os menus e a renderização de cada tela sem
janela real nem eventos de mouse/teclado. Não valida jogabilidade —
apenas que o boot e os renders não lançam exceção.
"""

from __future__ import annotations

import os

import pytest

from codecon_amoung_us.ui.app import App, Screen

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

pytestmark = pytest.mark.ui


@pytest.fixture(scope="module")
def app() -> App:
    return App()


def test_app_boots_and_renders_every_screen(app: App) -> None:
    from codecon_amoung_us.game.meeting import MeetingReason
    from codecon_amoung_us.game.model import Role, Team
    from codecon_amoung_us.protocol import Ejected, GameOver, MeetingStarted, ProtocolError

    assert app.screen_name == "main"
    app._render([])

    # tela de host
    app._open_host()
    app._render([])
    # tela de join
    app._open_join()
    app._render([])
    # tela de configurações
    app._open_settings()
    app._render([])
    # lobby (mesmo sem conexão)
    app.screen_name = Screen.LOBBY
    app._current_menu = app.lobby_menu
    app._render([])

    # conectando (tela não bloqueante)
    app.screen_name = Screen.CONNECTING
    app._render([])

    # jogo (sem snapshot)
    app.screen_name = Screen.GAME
    app._render([])

    # votação (sem reunião -> só o fill)
    app.screen_name = Screen.VOTING
    app._render([])
    # votação com reunião
    app.meeting = MeetingStarted(
        meeting_id=1, reason=MeetingReason.EMERGENCY, voters=[0, 1, 2, 3], vote_timeout_seconds=30.0
    )
    app._render([])

    # ejeção privada
    app.screen_name = Screen.EJECTED
    app.private_ejection = Ejected(player_id=1, role=Role.CREW)
    app._render([])

    # transição genérica de reunião encerrada
    app.screen_name = Screen.MEETING_ENDED
    app._render([])

    # game over
    app.screen_name = Screen.GAME_OVER
    app.game_over = GameOver(winner=Team.CREW, players=[], roles={})
    app._render([])

    # erro
    app.screen_name = Screen.ERROR
    app.error_message = "teste"
    app._render([])

    # handler de mensagens não quebra em nenhum tipo
    app._handle_message(ProtocolError(code="x", message="y"))

    app._shutdown_connection()
    # Sem pygame.quit() aqui: quit->init corrompe o cache global de fontes do
    # pygame-menu e segfaulta o App() de módulos de teste posteriores (mesma
    # nota de tests/test_ui_events.py). SDL dummy encerra no processo.
