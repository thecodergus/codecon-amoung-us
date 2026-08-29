"""codecon-amoung-us — MVP multiplayer estilo Among Us.

Execução:
    uv run codecon-amoung-us          # cliente (menus + jogo)
    uv run codecon-amoung-us-server   # servidor standalone (opcional)
"""

from __future__ import annotations

from .ui.app import main

__all__ = ["main"]
