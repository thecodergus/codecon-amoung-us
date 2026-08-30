"""Gates do catálogo canônico de tipos de tarefa."""

from __future__ import annotations

import pytest

from codecon_amoung_us.game.task_catalog import (
    TASK_DIFFICULTY,
    TASK_TYPES,
    difficulty_for,
)


def test_sete_tipos_unicos() -> None:
    assert len(TASK_TYPES) == 7
    assert len(set(TASK_TYPES)) == len(TASK_TYPES)


def test_todo_tipo_tem_dificuldade() -> None:
    assert set(TASK_DIFFICULTY) == set(TASK_TYPES)
    for task_type in TASK_TYPES:
        params = TASK_DIFFICULTY[task_type]
        assert params.estimated_seconds > 0, task_type
        assert params.targets > 0, task_type
        assert params.speed >= 0, task_type


def test_tipos_sao_estaveis() -> None:
    """Os tipos são contrato de dados (mapa, protocolo, UI) — não renomear."""
    assert TASK_TYPES == (
        "wires",
        "fix_wiring",
        "swipe_card",
        "calibrate",
        "clean_filter",
        "start_reactor",
        "asteroids",
    )


def test_difficulty_for_retorna_params_do_tipo() -> None:
    for task_type in TASK_TYPES:
        assert difficulty_for(task_type) is TASK_DIFFICULTY[task_type]


def test_difficulty_for_tipo_desconhecido_falha_explicito() -> None:
    with pytest.raises(ValueError, match="desconhecido"):
        difficulty_for("nao_existe")
