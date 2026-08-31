"""Testes do protocolo msgspec: roundtrip e rejeição de mensagens malformadas."""

from __future__ import annotations

import msgspec
import pytest

from codecon_amoung_us.game.meeting import MeetingReason
from codecon_amoung_us.game.model import Role, Team
from codecon_amoung_us.protocol import (
    ActionAccepted,
    ActionDenied,
    ActionKind,
    BodyReported,
    DenialCode,
    Ejected,
    EmergencyMeetingRequest,
    GameOver,
    JoinAccepted,
    JoinRequest,
    KillRequest,
    LobbyPlayer,
    MeetingEnded,
    MeetingStarted,
    MovementInput,
    PlayerDisconnected,
    PlayerInfo,
    PlayerJoined,
    ProtocolError,
    RoleAssigned,
    SnapshotBody,
    SnapshotPlayer,
    StartGame,
    StartGameRequest,
    TaskActionRequest,
    TaskInfo,
    TaskState,
    VoteRequest,
    WorldSnapshot,
    decode,
    encode,
)

# Todos os tipos de mensagem com valores válidos mínimos (roundtrip).
MESSAGES = [
    JoinRequest(nickname="gus", protocol_version=2),
    StartGameRequest(),
    MovementInput(dx=1.0, dy=-1.0, tick=3),
    KillRequest(target_id=2),
    BodyReported(body_id=1),
    EmergencyMeetingRequest(),
    VoteRequest(meeting_id=1, target_id=3),
    VoteRequest(meeting_id=1, target_id=None),  # Skip
    TaskActionRequest(task_id=1),
    JoinAccepted(
        game_id="g1",
        player_id=0,
        host_player_id=0,
        players=[LobbyPlayer(player_id=0, nickname="gus")],
    ),
    PlayerJoined(player=LobbyPlayer(player_id=1, nickname="ana")),
    PlayerDisconnected(player_id=2),
    StartGame(
        map_name="mapa-42",
        map_seed=42,
        players=[PlayerInfo(player_id=0, nickname="gus"), PlayerInfo(player_id=1, nickname="ana")],
    ),
    RoleAssigned(role=Role.IMPOSTOR, task_ids=[]),
    WorldSnapshot(
        tick=1,
        players=[SnapshotPlayer(player_id=0, x=1.0, y=2.0, alive=True)],
        bodies=[SnapshotBody(body_id=1, player_id=2, x=3.0, y=4.0)],
    ),
    TaskState(tasks=[TaskInfo(task_id=1, task_type="wires", done=False)]),
    MeetingStarted(
        meeting_id=1,
        reason=MeetingReason.EMERGENCY,
        voters=[0, 1, 2, 3],
        vote_timeout_seconds=30.0,
    ),
    MeetingEnded(meeting_id=1),
    Ejected(player_id=2, role=Role.CREW),
    GameOver(
        winner=Team.IMPOSTOR,
        players=[PlayerInfo(player_id=0, nickname="gus")],
        roles={0: Role.IMPOSTOR},
    ),
    ActionAccepted(action=ActionKind.KILL, cooldown_seconds=15.0),
    ActionAccepted(action=ActionKind.VOTE),
    ActionDenied(
        action=ActionKind.KILL,
        code=DenialCode.COOLDOWN,
        reason="kill em recarga",
        retry_after_seconds=7.0,
    ),
    ProtocolError(code="bad_frame", message="frame inválido"),
]


@pytest.mark.parametrize("message", MESSAGES)
def test_roundtrip_every_message(message: object) -> None:
    """Qualquer mensagem válida sobrevive encode -> decode intacta."""
    decoded = decode(encode(message))  # type: ignore[arg-type]
    assert decoded == message


def test_encoded_json_is_readable_text() -> None:
    raw = encode(MovementInput(dx=0.5, dy=0.0, tick=7))
    assert b"MovementInput" in raw  # tag = nome da classe
    assert b'"tick":7' in raw


def test_unknown_tag_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"NaoExiste","nickname":"gus"}')


def test_unknown_field_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"gus","protocol_version":1,"hack":true}')


def test_missing_required_field_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"gus"}')


def test_wrong_type_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"MovementInput","dx":"x","dy":0.0,"tick":1}')


def test_nickname_with_newline_rejected() -> None:
    # '\n' quebraria o framing JSON Lines; é bloqueado pelo pattern
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"gus\\nana","protocol_version":1}')


def test_nickname_empty_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"","protocol_version":1}')


def test_nickname_too_long_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"abcdefghijklm","protocol_version":1}')


def test_protocol_version_unsupported_rejected() -> None:
    # v3 é a versão corrente; v1 e v2 ainda decodificam (ge=1); v4 é rejeitada.
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"JoinRequest","nickname":"gus","protocol_version":4}')


def test_protocol_version_1_still_decodes() -> None:
    msg = decode(b'{"type":"JoinRequest","nickname":"gus","protocol_version":1}')
    assert isinstance(msg, JoinRequest)
    assert msg.protocol_version == 1


def test_meeting_ended_serializes_only_type_and_meeting_id() -> None:
    import json

    raw = encode(MeetingEnded(meeting_id=7))
    payload = json.loads(raw)
    assert set(payload.keys()) == {"type", "meeting_id"}
    assert payload["meeting_id"] == 7


def test_meeting_ended_rejects_ejected_field() -> None:
    # O booleano de ejeção foi removido no protocolo v2 (confidencialidade).
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"MeetingEnded","meeting_id":1,"ejected":true}')


def test_action_denied_requires_action_and_code() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"ActionDenied","reason":"fora de alcance"}')


def test_negative_player_id_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"type":"KillRequest","target_id":-1}')


def test_players_list_too_large_rejected() -> None:
    import json

    many = [{"player_id": i, "nickname": f"p{i}"} for i in range(11)]
    payload = json.dumps(
        {
            "type": "JoinAccepted",
            "game_id": "g",
            "player_id": 0,
            "host_player_id": 0,
            "players": many,
        }
    ).encode()
    with pytest.raises(msgspec.ValidationError):
        decode(payload)


def test_plain_json_not_a_message_rejected() -> None:
    with pytest.raises(msgspec.ValidationError):
        decode(b'{"hello":"world"}')
