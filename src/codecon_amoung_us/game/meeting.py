"""Reunião de emergência e distribuição confidencial do resultado da votação.

O domínio (``Meeting``) não conhece o protocolo de rede. A tradução para
mensagens (``Ejected``/``MeetingEnded``) fica em ``net/dispatch.py``,
mantendo a lógica de sigilo testável por serialização.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .model import Role
from .voting import VoteResult, count_votes

__all__ = ["MeetingReason", "Meeting", "MeetingOutcome"]


class MeetingReason(StrEnum):
    """Motivo que iniciou a reunião."""

    EMERGENCY = "emergency"
    KILL_REPORTED = "kill_reported"


@dataclass(frozen=True)
class MeetingOutcome:
    """Desfecho da reunião: quem foi ejetado (se alguém) e seu papel.

    Este dado é usado SOMENTE pelo servidor para construir as mensagens
    confidenciais; nunca é enviado na íntegra aos clientes.
    """

    meeting_id: int
    ejected_id: int | None
    ejected_role: Role | None


@dataclass
class Meeting:
    """Estado de uma reunião em andamento."""

    meeting_id: int
    reason: MeetingReason
    started_at: float
    vote_timeout_seconds: float
    # Votantes elegíveis (jogadores vivos no início da reunião).
    voters: set[int] = field(default_factory=set)
    # votante -> alvo; None representa Skip.
    votes: dict[int, int | None] = field(default_factory=dict)

    def add_vote(self, voter_id: int, target_id: int | None) -> bool:
        """Registra o voto se o votante é elegível e ainda não votou."""
        if voter_id not in self.voters:
            return False
        if voter_id in self.votes:
            return False
        self.votes[voter_id] = target_id
        return True

    def has_voted(self, voter_id: int) -> bool:
        return voter_id in self.votes

    def remove_voter(self, voter_id: int) -> bool:
        """Remove um votante elegível (ex.: desconectado) e seu voto.

        Retorna False se o jogador não era elegível. Usado para a reunião
        não ficar bloqueada esperando quem abandonou a partida.
        """
        if voter_id not in self.voters:
            return False
        self.voters.discard(voter_id)
        self.votes.pop(voter_id, None)
        return True

    @property
    def all_voted(self) -> bool:
        """Todos os elegíveis já votaram (Skip conta como voto)."""
        return self.voters <= self.votes.keys()

    def timeout_expired(self, now: float) -> bool:
        return now - self.started_at >= self.vote_timeout_seconds

    def result(self) -> VoteResult:
        return count_votes(self.votes, self.voters)

    def outcome(self, ejected_role: Role | None) -> MeetingOutcome:
        """Desfecho com o papel do ejetado (somente para o servidor)."""
        return MeetingOutcome(
            meeting_id=self.meeting_id,
            ejected_id=self.result().ejected_id,
            ejected_role=ejected_role,
        )
