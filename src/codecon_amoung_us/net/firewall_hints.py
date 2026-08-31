"""Dicas de diagnóstico para falhas de rede ligadas a firewall de host.

Firewalls bloqueiam conexões de entrada por padrão (Microsoft Learn: o bind
em modo listen exige regra inbound explícita) e o prompt do Windows pode ser
descartado pelo usuário. As mensagens são orientadas por SO e nunca sobem
exceção: são texto para a UI, não tratamento de erro.
"""

from __future__ import annotations

import errno
import sys

__all__ = [
    "hint_for_bind_error",
    "discovery_empty_tips",
]

_BIND_PERMISSION_ERRNOS = frozenset({errno.EACCES, errno.EPERM})
# WSAEACCES: bind/listen negado no Windows (firewall ou porta privilegiada).
_WINERROR_ACCESS_DENIED = 10013


def hint_for_bind_error(exc: OSError) -> str | None:
    """Mensagem de firewall para falha de bind/listen; ``None`` se não se aplicar.

    Só aponta firewall para erros de permissão — "endereço em uso" e afins
    têm causas distintas e merecem mensagens próprias.
    """
    winerror: int | None = getattr(exc, "winerror", None)
    if exc.errno not in _BIND_PERMISSION_ERRNOS and winerror != _WINERROR_ACCESS_DENIED:
        return None
    if sys.platform == "win32":
        return (
            "O Windows pode estar bloqueando o jogo: use 'Corrigir permissões "
            "de rede' na tela de criar partida (ou permita o Python no "
            "Windows Defender Firewall)."
        )
    return (
        "O firewall do sistema pode estar bloqueando a porta: libere com "
        "'sudo ufw allow <porta>' (ou equivalente da sua distro)."
    )


def discovery_empty_tips() -> tuple[str, ...]:
    """Dicas exibidas quando a busca de partidas não encontra nada."""
    return (
        "Confira se o host criou a partida na mesma rede.",
        "Firewall do host pode estar bloqueando a descoberta — no menu de "
        "criar partida, use 'Corrigir permissões de rede'.",
        "Em Wi-Fi com isolamento de clientes, só a conexão manual por IP funciona.",
    )
