"""Propriedade Hypothesis da votação secreta, sobre bytes serializados.

Para qualquer votação válida com ejeção: as mensagens efetivamente
destinadas a cada cliente são inspecionadas na representação serializada
(JSON Lines). Clientes não-ejetados só podem receber ``MeetingEnded`` com
exatamente os campos {type, meeting_id} — sem identidade do ejetado, sem
booleano de ejeção, sem votos individuais, sem contagem final e sem papel.
Protocolo v2: o booleano ``ejected`` foi removido da mensagem pública.
"""

from __future__ import annotations

import json

from hypothesis import given, settings
from hypothesis import strategies as st

from codecon_amoung_us.framing import encode_frame
from codecon_amoung_us.game.meeting import MeetingOutcome
from codecon_amoung_us.game.model import Role
from codecon_amoung_us.net.dispatch import dispatch_ejection
from codecon_amoung_us.protocol import Ejected, MeetingEnded

PLAYER_IDS = st.integers(min_value=0, max_value=3)
ROLES = st.sampled_from([Role.CREW, Role.IMPOSTOR])

# Chaves proibidas em qualquer mensagem pública do desfecho da reunião.
_FORBIDDEN_KEYS = {"ejected", "ejected_id", "role", "vote_count", "votes", "counts"}


def _frame_to_dict(message: object) -> dict[str, object]:
    """Representação serializada (on-the-wire) da mensagem."""
    raw = encode_frame(message)  # type: ignore[arg-type]
    payload = json.loads(raw.rstrip(b"\n"))
    assert isinstance(payload, dict)
    return {str(k): v for k, v in payload.items()}


def _assert_only_meeting_ended_without_identity(
    serialized: dict[str, object],
    *,
    meeting_id: int,
) -> None:
    # Somente MeetingEnded, com exatamente os campos do schema v2
    assert serialized["type"] == "MeetingEnded"
    assert set(serialized.keys()) == {"type", "meeting_id"}
    assert serialized["meeting_id"] == meeting_id
    assert _FORBIDDEN_KEYS.isdisjoint(serialized.keys())


@settings(max_examples=300, deadline=None)
@given(
    ejected=PLAYER_IDS,
    role=ROLES,
    meeting_id=st.integers(min_value=1, max_value=1000),
)
def test_secrecy_over_serialized_messages(ejected: int, role: Role, meeting_id: int) -> None:
    recipients = [0, 1, 2, 3]
    outcome = MeetingOutcome(meeting_id=meeting_id, ejected_id=ejected, ejected_role=role)
    dispatch = dispatch_ejection(outcome, recipients)

    assert set(dispatch.keys()) == set(recipients)
    for recipient in recipients:
        messages = dispatch[recipient]
        serialized_list = [_frame_to_dict(m) for m in messages]
        if recipient == ejected:
            # O ejetado recebe Ejected (com identidade e papel) + MeetingEnded
            assert len(serialized_list) == 2
            ejected_msg = serialized_list[0]
            assert ejected_msg["type"] == "Ejected"
            assert set(ejected_msg.keys()) == {"type", "player_id", "role"}
            assert ejected_msg["player_id"] == ejected
            assert ejected_msg["role"] == role.value
            _assert_only_meeting_ended_without_identity(serialized_list[1], meeting_id=meeting_id)
        else:
            # Clientes demais: APENAS MeetingEnded, sem qualquer identidade
            assert len(serialized_list) == 1
            _assert_only_meeting_ended_without_identity(serialized_list[0], meeting_id=meeting_id)
    # Nenhuma mensagem pública (nem a do ejetado, exceto seu Ejected privado)
    # contém chaves proibidas: identidade, papel, contagem ou resultado.
    for recipient in recipients:
        for index, serialized in enumerate(_frame_to_dict(m) for m in dispatch[recipient]):
            if recipient == ejected and index == 0:
                continue  # Ejected privado legitima identidade + papel
            assert _FORBIDDEN_KEYS.isdisjoint(serialized.keys())


@settings(max_examples=200, deadline=None)
@given(
    meeting_id=st.integers(min_value=1, max_value=1000),
)
def test_no_ejection_sends_only_meeting_ended(meeting_id: int) -> None:
    recipients = [0, 1, 2, 3]
    outcome = MeetingOutcome(meeting_id=meeting_id, ejected_id=None, ejected_role=None)
    dispatch = dispatch_ejection(outcome, recipients)
    for recipient in recipients:
        messages = dispatch[recipient]
        assert len(messages) == 1
        assert isinstance(messages[0], MeetingEnded)
        _assert_only_meeting_ended_without_identity(
            _frame_to_dict(messages[0]), meeting_id=meeting_id
        )


def test_ejected_only_for_the_ejected_player_type() -> None:
    """Apenas o destinatário ejetado recebe mensagens do tipo Ejected."""
    recipients = [0, 1, 2, 3]
    outcome = MeetingOutcome(meeting_id=5, ejected_id=2, ejected_role=Role.CREW)
    dispatch = dispatch_ejection(outcome, recipients)
    for recipient, messages in dispatch.items():
        kinds = [type(m) for m in messages]
        if recipient == 2:
            assert Ejected in kinds
        else:
            assert Ejected not in kinds
