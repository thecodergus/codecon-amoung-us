"""Testes da contagem de votos (determinismo, empate, skip, inelegíveis)."""

from __future__ import annotations

from codecon_amoung_us.game.voting import VoteResult, count_votes


def test_plurality_elects_single_winner() -> None:
    votes = {0: 1, 1: 1, 2: 2, 3: None}  # Skip do votante 3
    result = count_votes(votes, eligible={0, 1, 2, 3})
    assert result.ejected_id == 1
    assert result.total_valid_votes == 3
    assert result.counts == {1: 2, 2: 1}


def test_tie_produces_no_ejection() -> None:
    votes = {0: 1, 1: 2, 2: 1, 3: 2}
    result = count_votes(votes, eligible={0, 1, 2, 3})
    assert result.ejected_id is None
    assert result.tie


def test_all_skip_produces_no_ejection() -> None:
    votes = {0: None, 1: None, 2: None, 3: None}
    result = count_votes(votes, eligible={0, 1, 2, 3})
    assert result.ejected_id is None
    assert result.total_valid_votes == 0


def test_ineligible_votes_are_ignored() -> None:
    # Votante 0 está morto (inelegível); o resultado ignora seu voto
    votes_with_ineligible = {0: 1, 1: 1, 2: 2, 3: 2}
    eligible = {1, 2, 3}
    result = count_votes(votes_with_ineligible, eligible)
    without_ineligible = count_votes({1: 1, 2: 2, 3: 2}, eligible)
    assert result == without_ineligible
    assert result.ejected_id == 2
    assert result.counts == {1: 1, 2: 2}
    assert result.total_valid_votes == 3


def test_each_voter_contributes_at_most_one_vote() -> None:
    # Um dict não pode ter chave duplicada; mas o mesmo alvo contado por votante único
    votes = {0: 2, 1: 2, 2: 2, 3: 2}
    result = count_votes(votes, eligible={0, 1, 2, 3})
    assert result.total_valid_votes == 4
    assert result.counts == {2: 4}


def test_result_is_deterministic() -> None:
    votes = {0: 3, 1: None, 2: 3, 3: 1}
    eligible = {0, 1, 2, 3}
    first = count_votes(votes, eligible)
    second = count_votes(votes, eligible)
    assert first == second
    assert isinstance(first, VoteResult)


def test_votes_for_nonexistent_target_count_for_that_target() -> None:
    # Protocolo: target é int; servidor valida existência. Contagem apenas soma.
    votes = {0: 99, 1: 99, 2: None, 3: None}
    result = count_votes(votes, eligible={0, 1, 2, 3})
    assert result.ejected_id == 99
