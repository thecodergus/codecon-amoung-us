"""Minigames de tarefa (puzzles modais client-side).

Importar o pacote registra todos os minigames no ``base._REGISTRY``;
``create_minigame`` despacha pelo tipo de tarefa do catálogo.
"""

from . import asteroids, calibrate, clean_filter, fix_wiring, start_reactor, swipe_card, wires
from .base import TASK_DISPLAY, Minigame, create_minigame

__all__ = ["TASK_DISPLAY", "Minigame", "create_minigame"]
