"""Votação secreta: contagem pura, determinística e sem efeitos colaterais.

O resultado expõe apenas o necessário ao servidor; a distribuição
confidencial das mensagens é responsabilidade de ``ejection_messages``
(ver ``meeting.py``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["VoteResult", "count_votes"]


@dataclass(frozen=True)
class VoteResult:
    """Resultado determinístico de uma rodada de votação.

    ``ejected_id`` é ``None`` quando não há ejetado (empate ou nenhum voto
    válido para alguém). ``counts`` é somente do servidor — nunca é
    serializado para clientes.
    """

    total_valid_votes: int
    counts: dict[int, int]
    ejected_id: int | None

    @property
    def tie(self) -> bool:
        return self.ejected_id is None


def count_votes(votes: Mapping[int, int | None], eligible: set[int]) -> VoteResult:
    """Conta votos: cada votante contribui no máximo um voto efetivo.

    - Votos de jogadores inelegíveis são ignorados.
    - ``None`` (Skip) não conta para nenhum candidato.
    - Pluralidade: o candidato com mais votos vence.
    - Empate (máximo não único, ou zero votos para candidatos) -> sem ejeção.
    """
    counts: Counter[int] = Counter()
    total = 0
    for voter_id, target_id in votes.items():
        if voter_id not in eligible:
            continue
        if target_id is None:
            continue
        total += 1
        counts[target_id] += 1

    ejected_id: int | None = None
    if counts:
        top_count = max(counts.values())
        top_candidates = [c for c, n in counts.items() if n == top_count]
        if len(top_candidates) == 1:
            ejected_id = top_candidates[0]
    return VoteResult(total_valid_votes=total, counts=dict(counts), ejected_id=ejected_id)
