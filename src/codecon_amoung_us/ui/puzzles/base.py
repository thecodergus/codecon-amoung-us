"""Framework de minigames de tarefa (puzzles modais, client-side).

Cada tarefa do mapa abre um minigame modal; a tarefa só é completada no
servidor quando o jogador resolve o puzzle (``done``). A lógica de cada
puzzle vive numa classe ``*Logic`` pura (sem pygame — testável headless)
e o wrapper ``Minigame`` traduz eventos do pygame e desenha o estado.

Coordenadas: a lógica trabalha no espaço local da área de jogo
(``CONTENT_W`` x ``CONTENT_H`` px lógicos); o wrapper subtrai a origem de
``play_area`` (retângulo atribuído pelo host a cada frame, antes de
``handle_event``/``draw``). ``reduced_motion`` desativa animações
decorativas (o puzzle permanece funcional).
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from collections.abc import Callable

import pygame

from ...game.task_catalog import difficulty_for
from ..fonts import FontBook

__all__ = [
    "CONTENT_H",
    "CONTENT_W",
    "TASK_DISPLAY",
    "Minigame",
    "create_minigame",
    "register",
]

# Área de jogo canônica dentro do painel modal (px lógicos). O host (app)
# fornece exatamente este tamanho; os puzzles são desenhados para ele.
CONTENT_W = 560
CONTENT_H = 420

# (título, instrução) por tipo de tarefa — cabeçalho do painel modal.
TASK_DISPLAY: dict[str, tuple[str, str]] = {
    "wires": ("Ligar fios", "Arraste cada fio até o terminal da mesma cor"),
    "fix_wiring": ("Reparar circuito", "Clique nos painéis até acender todas as luzes"),
    "swipe_card": ("Passar cartão", "Pressione quando o indicador estiver na zona verde"),
    "calibrate": ("Calibrar sensores", "Clique quando a agulha cruzar a faixa marcada"),
    "clean_filter": ("Limpar filtro", "Arraste os detritos para fora do filtro"),
    "start_reactor": ("Reativar reator", "Memorize a sequência e repita nos painéis"),
    "asteroids": ("Destruir asteroides", "Clique nos asteroides antes que escapem"),
}


class Minigame(ABC):
    """Minigame modal de uma tarefa.

    O host define ``play_area`` a cada frame, alimenta ``handle_event``
    com eventos traduzidos para o canvas lógico, chama ``update(dt)`` e
    ``draw(surface)``; quando ``done`` é verdadeiro, envia a conclusão da
    tarefa ao servidor.
    """

    task_type: str  # preenchido pela factory após a construção

    def __init__(
        self,
        task_id: int,
        *,
        fonts: FontBook,
        seed: int | None = None,
        reduced_motion: bool = False,
    ) -> None:
        self.task_id = task_id
        self.fonts = fonts
        self.reduced_motion = reduced_motion
        self.rng = random.Random(seed)
        self.play_area = pygame.Rect(0, 0, CONTENT_W, CONTENT_H)
        self._done = False

    @property
    def done(self) -> bool:
        return self._done

    def _to_local(self, pos: tuple[float, float]) -> tuple[float, float]:
        """Converte posição de tela (canvas lógico) para o espaço local."""
        return (pos[0] - self.play_area.x, pos[1] - self.play_area.y)

    @abstractmethod
    def handle_event(self, event: pygame.event.Event) -> None: ...

    def update(self, dt: float) -> None:
        """Avança a simulação (puzzles estáticos ignoram)."""

    @abstractmethod
    def draw(self, surface: pygame.Surface) -> None: ...


# Registro tipo -> construtor (preenchido pelos módulos de cada puzzle).
_REGISTRY: dict[str, Callable[..., Minigame]] = {}


def register(task_type: str, cls: Callable[..., Minigame]) -> None:
    """Registra o construtor do minigame de ``task_type``."""
    _REGISTRY[task_type] = cls


def create_minigame(
    task_type: str,
    task_id: int,
    *,
    fonts: FontBook,
    seed: int | None = None,
    reduced_motion: bool = False,
) -> Minigame:
    """Cria o minigame de ``task_type``; falha explícita se desconhecido."""
    difficulty_for(task_type)  # valida contra o catálogo (ValueError se inválido)
    cls = _REGISTRY.get(task_type)
    if cls is None:
        raise ValueError(f"minigame não implementado para o tipo: {task_type!r}")
    instance = cls(task_id, fonts=fonts, seed=seed, reduced_motion=reduced_motion)
    instance.task_type = task_type
    return instance
