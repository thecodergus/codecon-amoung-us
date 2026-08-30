"""Protocolo de rede com msgspec: schemas tipados, tagged union, validação.

Toda mensagem é um ``msgspec.Struct`` tagado (campo ``type``), com
``forbid_unknown_fields`` e constraints declarativas. Nenhum
``dict[str, Any]`` transita pelo protocolo; a serialização/desserialização
acontece exclusivamente aqui (e o framing em ``framing.py``).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

import msgspec

from .config import MAX_PLAYERS, NICKNAME_MAX_LENGTH, NICKNAME_MIN_LENGTH
from .game.meeting import MeetingReason
from .game.model import Role, Team

__all__ = [
    "Nickname",
    "PlayerId",
    "MessageId",
    "Tick",
    "ActionKind",
    "DenialCode",
    "MessageBase",
    "LobbyPlayer",
    "PlayerInfo",
    "SnapshotPlayer",
    "SnapshotBody",
    "TaskInfo",
    "JoinRequest",
    "JoinAccepted",
    "PlayerJoined",
    "PlayerDisconnected",
    "StartGameRequest",
    "StartGame",
    "RoleAssigned",
    "MovementInput",
    "WorldSnapshot",
    "TaskState",
    "KillRequest",
    "BodyReported",
    "EmergencyMeetingRequest",
    "MeetingStarted",
    "MeetingEnded",
    "Ejected",
    "VoteRequest",
    "GameOver",
    "ActionAccepted",
    "ActionDenied",
    "ProtocolError",
    "Message",
    "encode",
    "decode",
]

# Aliases de tipo com constraints do msgspec (Meta).
type Nickname = Annotated[
    str,
    msgspec.Meta(
        min_length=NICKNAME_MIN_LENGTH,
        max_length=NICKNAME_MAX_LENGTH,
        pattern=r"^[^\x00-\x1f\x7f]+$",  # sem caracteres de controle (protege o JSON Lines)
    ),
]
type PlayerId = Annotated[int, msgspec.Meta(ge=0, lt=2**31)]
type MessageId = Annotated[int, msgspec.Meta(ge=1, lt=2**31)]
type Tick = Annotated[int, msgspec.Meta(ge=0, lt=2**31)]
type ProtocolVersion = Annotated[int, msgspec.Meta(ge=1, le=2)]
type FloatRange = Annotated[float, msgspec.Meta(ge=-1e6, le=1e6)]


class ActionKind(StrEnum):
    """Ação de jogo executável por um jogador (usada em feedback tipado)."""

    KILL = "kill"
    REPORT = "report"
    TASK = "task"
    EMERGENCY = "emergency"
    VOTE = "vote"
    START_GAME = "start_game"


class DenialCode(StrEnum):
    """Motivo fechado de uma ação recusada (para a UI apresentar feedback)."""

    OUT_OF_RANGE = "out_of_range"
    COOLDOWN = "cooldown"
    INVALID_TARGET = "invalid_target"
    ALREADY_DONE = "already_done"
    NOT_ASSIGNED = "not_assigned"
    ALREADY_VOTED = "already_voted"
    INVALID_PHASE = "invalid_phase"
    NOT_HOST = "not_host"
    INSUFFICIENT_PLAYERS = "insufficient_players"
    NOT_ALIVE = "not_alive"


class MessageBase(msgspec.Struct, tag=True, forbid_unknown_fields=True, kw_only=True):
    """Base comum das mensagens de rede (tagged union no campo ``type``)."""


# ---------------------------------------------------------------------------
# Estruturas aninhadas (não tagadas; usadas dentro de mensagens)
# ---------------------------------------------------------------------------


class LobbyPlayer(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    player_id: PlayerId
    nickname: Nickname


class PlayerInfo(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    player_id: PlayerId
    nickname: Nickname


class SnapshotPlayer(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    player_id: PlayerId
    x: FloatRange
    y: FloatRange
    alive: bool


class SnapshotBody(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    body_id: MessageId
    player_id: PlayerId
    x: FloatRange
    y: FloatRange


class TaskInfo(msgspec.Struct, forbid_unknown_fields=True, kw_only=True):
    task_id: MessageId
    task_type: str
    done: bool


# ---------------------------------------------------------------------------
# Cliente -> Servidor
# ---------------------------------------------------------------------------


class JoinRequest(MessageBase):
    nickname: Nickname
    protocol_version: ProtocolVersion


class StartGameRequest(MessageBase):
    pass


class MovementInput(MessageBase):
    dx: FloatRange
    dy: FloatRange
    tick: Tick


class KillRequest(MessageBase):
    target_id: PlayerId


class BodyReported(MessageBase):
    body_id: MessageId


class EmergencyMeetingRequest(MessageBase):
    pass


class VoteRequest(MessageBase):
    meeting_id: MessageId
    target_id: PlayerId | None  # None = Skip


class TaskActionRequest(MessageBase):
    task_id: MessageId


# ---------------------------------------------------------------------------
# Servidor -> Cliente
# ---------------------------------------------------------------------------


class JoinAccepted(MessageBase):
    game_id: str
    player_id: PlayerId
    host_player_id: PlayerId
    players: Annotated[list[LobbyPlayer], msgspec.Meta(max_length=MAX_PLAYERS)]


class PlayerJoined(MessageBase):
    player: LobbyPlayer


class PlayerDisconnected(MessageBase):
    player_id: PlayerId


class StartGame(MessageBase):
    map_name: str
    players: Annotated[list[PlayerInfo], msgspec.Meta(max_length=MAX_PLAYERS)]


class RoleAssigned(MessageBase):
    role: Role
    task_ids: Annotated[list[MessageId], msgspec.Meta(max_length=32)]


class WorldSnapshot(MessageBase):
    """Estado do mundo em um tick — mensagem idêntica para todos (broadcast).

    ``alive`` é público por decisão de design: mortes por kill e por ejeção
    aparecem aqui da mesma forma, sem marcador de causa (ver o contrato de
    sigilo da votação em ``MeetingEnded``).
    """

    tick: Tick
    players: Annotated[list[SnapshotPlayer], msgspec.Meta(max_length=MAX_PLAYERS)]
    bodies: Annotated[list[SnapshotBody], msgspec.Meta(max_length=MAX_PLAYERS)]


class TaskState(MessageBase):
    tasks: Annotated[list[TaskInfo], msgspec.Meta(max_length=32)]


class MeetingStarted(MessageBase):
    meeting_id: MessageId
    reason: MeetingReason
    voters: Annotated[list[PlayerId], msgspec.Meta(max_length=MAX_PLAYERS)]
    vote_timeout_seconds: Annotated[float, msgspec.Meta(ge=1.0, le=600.0)]


class MeetingEnded(MessageBase):
    """Fim da reunião — encerramento idêntico para todos os desfechos.

    Contrato de sigilo da votação (protocolo v2). Três estados após a reunião:

    1. **Estado autoritativo (servidor):** conhece o resultado real — o
       ejetado está eliminado (``alive=False``): não executa tarefas, não
       vota, não mata, não reporta e não conta como jogador ativo na
       condição de vitória.
    2. **Visão do ejetado:** recebe ``Ejected`` (privado, identidade + papel)
       antes desta mensagem e entra no modo espectador.
    3. **Visão dos demais:** recebe SOMENTE esta mensagem — estruturalmente
       idêntica para ejeção, empate e skip (somente ``meeting_id``). Nenhum
       campo revela quem foi ejetado, o papel ou a contagem de votos.

    O estado vivo/morto do ejetado torna-se público no ``WorldSnapshot``
    seguinte (``alive=False``), indistinguível de uma morte por kill — como
    no Among Us original. É cláusula explícita do contrato (decisão de
    design), não vazamento: o sigilo proíbe entregar o resultado pela
    mensagem; inferência decorrente do comportamento futuro da partida está
    fora de escopo. Garantido por ``dispatch_ejection`` e testado sobre os
    bytes serializados em ``tests/test_secrecy_properties.py``.
    """

    meeting_id: MessageId


class Ejected(MessageBase):
    """Identificação explícita do ejetado — SOMENTE enviada ao próprio ejetado.

    É a única mensagem do protocolo que revela o resultado da votação, e vai
    apenas para o jogador ejetado (visão privada — ver o contrato em
    ``MeetingEnded``). Clientes não ejetados nunca a recebem.
    """

    player_id: PlayerId
    role: Role


class GameOver(MessageBase):
    winner: Team
    players: Annotated[list[PlayerInfo], msgspec.Meta(max_length=MAX_PLAYERS)]
    roles: Annotated[dict[int, Role], msgspec.Meta(max_length=MAX_PLAYERS)]


class ActionAccepted(MessageBase):
    """Confirmação privada de uma ação aceita (autor da ação).

    ``cooldown_seconds`` indica o cooldown iniciado (ex.: kill); a UI usa
    para mostrar o contador local sem expor estado do impostor a terceiros.
    """

    action: ActionKind
    cooldown_seconds: float | None = None


class ActionDenied(MessageBase):
    """Ação recusada com motivo fechado (``code``) e texto (``reason``)."""

    action: ActionKind
    code: DenialCode
    reason: str
    retry_after_seconds: float | None = None


class ProtocolError(MessageBase):
    code: str
    message: str


# ---------------------------------------------------------------------------
# Union tagada e codec centralizado
# ---------------------------------------------------------------------------

type Message = (
    JoinRequest
    | JoinAccepted
    | PlayerJoined
    | PlayerDisconnected
    | StartGameRequest
    | StartGame
    | RoleAssigned
    | MovementInput
    | WorldSnapshot
    | TaskState
    | KillRequest
    | BodyReported
    | EmergencyMeetingRequest
    | MeetingStarted
    | MeetingEnded
    | Ejected
    | VoteRequest
    | TaskActionRequest
    | GameOver
    | ActionAccepted
    | ActionDenied
    | ProtocolError
)

_decoder: msgspec.json.Decoder[Message] = msgspec.json.Decoder(Message)


def encode(message: Message) -> bytes:
    """Serializa uma mensagem em JSON (representação on-the-wire do MVP)."""
    return msgspec.json.encode(message)


def decode(data: bytes) -> Message:
    """Desserializa validando estrutura, tipos e constraints (estrito).

    Levanta ``msgspec.ValidationError`` para mensagens que não
    correspondem ao schema (incluindo campos desconhecidos).
    """
    return _decoder.decode(data)
