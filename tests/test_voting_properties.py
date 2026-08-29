"""Propriedades Hypothesis da contagem de votos (quatro jogadores).

Invariantes:
- cada votante contribui no máximo um voto efetivo;
- resultado determinístico para o mesmo conjunto válido de votos;
- empate não produz ejeção;
- somente um jogador pode ser ejetado por reunião;
- votos de inelegíveis não alteram o resultado.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from codecon_amoung_us.game.voting import count_votes

PLAYER_IDS = st.integers(min_value=0, max_value=3)
TARGET = st.one_of(st.integers(min_value=0, max_value=3), st.none())  # None = Skip


@settings(max_examples=300, deadline=None)
@given(
    votes=st.dictionaries(keys=PLAYER_IDS, values=TARGET, max_size=4),
    eligible=st.sets(PLAYER_IDS, min_size=0, max_size=4),
)
def test_each_voter_contributes_at_most_one_vote(
    votes: dict[int, int | None], eligible: set[int]
) -> None:
    result = count_votes(votes, eligible)
    eligible_voters = set(votes.keys()) & eligible
    assert result.total_valid_votes <= len(eligible_voters)


@settings(max_examples=300, deadline=None)
@given(
    votes=st.dictionaries(keys=PLAYER_IDS, values=TARGET, max_size=4),
    eligible=st.sets(PLAYER_IDS, min_size=0, max_size=4),
)
def test_result_is_deterministic(votes: dict[int, int | None], eligible: set[int]) -> None:
    assert count_votes(votes, eligible) == count_votes(votes, eligible)


@settings(max_examples=300, deadline=None)
@given(
    votes=st.dictionaries(keys=PLAYER_IDS, values=TARGET, max_size=4),
    eligible=st.sets(PLAYER_IDS, min_size=0, max_size=4),
)
def test_tie_produces_no_ejection(votes: dict[int, int | None], eligible: set[int]) -> None:
    result = count_votes(votes, eligible)
    if result.ejected_id is None:
        return  # sem ejeção: ok
    # se houve ejeção, o máximo é estritamente único
    top = result.counts[result.ejected_id]
    assert sum(1 for n in result.counts.values() if n == top) == 1


@settings(max_examples=300, deadline=None)
@given(
    votes=st.dictionaries(keys=PLAYER_IDS, values=TARGET, max_size=4),
    eligible=st.sets(PLAYER_IDS, min_size=0, max_size=4),
)
def test_at_most_one_ejected_player(votes: dict[int, int | None], eligible: set[int]) -> None:
    result = count_votes(votes, eligible)
    if result.ejected_id is not None:
        assert 0 <= result.ejected_id <= 3


@settings(max_examples=300, deadline=None)
@given(
    votes=st.dictionaries(keys=PLAYER_IDS, values=TARGET, max_size=4),
    eligible=st.sets(PLAYER_IDS, min_size=0, max_size=4),
)
def test_ineligible_votes_do_not_change_result(
    votes: dict[int, int | None], eligible: set[int]
) -> None:
    result = count_votes(votes, eligible)
    only_eligible = {v: t for v, t in votes.items() if v in eligible}
    assert result == count_votes(only_eligible, eligible)
