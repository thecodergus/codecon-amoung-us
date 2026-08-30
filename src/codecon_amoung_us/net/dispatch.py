"""Distribuição confidencial das mensagens de resultado da votação.

Função pura: dado o desfecho da reunião e a lista de destinatários,
retorna as mensagens exatas por destinatário. É o núcleo da propriedade
de votação secreta — testada sobre os bytes serializados em
``tests/test_secrecy_properties.py``.

Ponto único da política de visibilidade do resultado da votação (contrato
em ``MeetingEnded``, ``protocol.py``): nenhum outro código do servidor
decide quem recebe ``Ejected``.
"""

from __future__ import annotations

from ..game.meeting import MeetingOutcome
from ..protocol import Ejected, MeetingEnded, Message

__all__ = ["dispatch_ejection"]


def dispatch_ejection(outcome: MeetingOutcome, recipients: list[int]) -> dict[int, list[Message]]:
    """Mensagens por destinatário após o fim da reunião.

    - Apenas o ejetado recebe ``Ejected`` (identidade + papel) — visão
      privada do ejetado.
    - Todos os destinatários (inclusive o ejetado) recebem ``MeetingEnded``
      com somente ``meeting_id`` — a mensagem não revela quem foi ejetado
      nem se houve ejeção (visão dos demais, idêntica para ejeção, empate
      e skip). O estado vivo/morto do ejetado é público no snapshot
      seguinte (``alive=False``), indistinguível de morte por kill —
      cláusula explícita do contrato, por decisão de design.
    """
    dispatch: dict[int, list[Message]] = {
        player_id: [MeetingEnded(meeting_id=outcome.meeting_id)] for player_id in recipients
    }
    if (
        outcome.ejected_id is not None
        and outcome.ejected_role is not None
        and outcome.ejected_id in dispatch
    ):
        dispatch[outcome.ejected_id].insert(
            0,
            Ejected(player_id=outcome.ejected_id, role=outcome.ejected_role),
        )
    return dispatch
