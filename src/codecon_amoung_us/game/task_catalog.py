"""Catálogo canônico de tipos de tarefa e parâmetros de dificuldade.

Fonte única dos tipos de tarefa do jogo: o builder de mapa
(``scripts/build_lab_map.py``) e a factory de minigames (``ui/puzzles``)
consomem daqui. A dificuldade é declarada como parâmetros explícitos e
mensuráveis (duração estimada, número de alvos/etapas, velocidade base),
de forma que balancear um minigame é editar uma entrada deste módulo —
sem tocar em lógica de domínio, protocolo ou renderização.

Domínio puro: este módulo não importa pygame nem UI.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["TASK_DIFFICULTY", "TASK_TYPES", "DifficultyParams", "difficulty_for"]


@dataclass(frozen=True)
class DifficultyParams:
    """Parâmetros mensuráveis de dificuldade de um minigame.

    ``estimated_seconds`` é a duração típica esperada para resolver o
    puzzle; ``targets`` é o número de elementos/etapas (fios, detritos,
    asteroides, pads...); ``speed`` é a velocidade base do elemento
    dinâmico principal (px/s ou rad/s, conforme o minigame; 0 quando o
    puzzle é estático).
    """

    estimated_seconds: float
    targets: int
    speed: float


TASK_TYPES: tuple[str, ...] = (
    "wires",
    "fix_wiring",
    "swipe_card",
    "calibrate",
    "clean_filter",
    "start_reactor",
    "asteroids",
)

TASK_DIFFICULTY: dict[str, DifficultyParams] = {
    # Ligar 4 fios coloridos aos terminais correspondentes (arrastar).
    "wires": DifficultyParams(estimated_seconds=8.0, targets=4, speed=0.0),
    # Lights-Out 3x3: acender os 9 painéis (5 cliques embaralham a solução).
    "fix_wiring": DifficultyParams(estimated_seconds=15.0, targets=9, speed=0.0),
    # Timing: 1 acerto na zona-alvo em até 3 tentativas; agulha a 360 px/s.
    "swipe_card": DifficultyParams(estimated_seconds=6.0, targets=1, speed=360.0),
    # 3 anéis com agulha rotativa (rad/s crescente por anel, base 2.0).
    "calibrate": DifficultyParams(estimated_seconds=12.0, targets=3, speed=2.0),
    # Arrastar 6 detritos para fora do filtro.
    "clean_filter": DifficultyParams(estimated_seconds=8.0, targets=6, speed=0.0),
    # Simon-says: repetir sequência de 5 pads (exibição a 1.6 pads/s).
    "start_reactor": DifficultyParams(estimated_seconds=12.0, targets=5, speed=1.6),
    # Destruir 8 asteroides antes que cruzem o painel (base 120 px/s).
    "asteroids": DifficultyParams(estimated_seconds=10.0, targets=8, speed=120.0),
}


def difficulty_for(task_type: str) -> DifficultyParams:
    """Retorna os parâmetros de dificuldade de ``task_type``.

    Levanta ``ValueError`` para tipo desconhecido — falha explícita em vez
    de dificuldade padrão silenciosa.
    """
    try:
        return TASK_DIFFICULTY[task_type]
    except KeyError:
        known = ", ".join(TASK_TYPES)
        raise ValueError(
            f"tipo de tarefa desconhecido: {task_type!r} (conhecidos: {known})"
        ) from None
