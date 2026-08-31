"""Dicas de diagnóstico para falhas de rede ligadas a firewall de host.

Firewalls bloqueiam conexões de entrada por padrão (Microsoft Learn: o bind
em modo listen exige regra inbound explícita). Restrição do público-alvo:
os usuários NUNCA têm admin/sudo — as dicas nunca mandam elevar privilégios;
apontam para o que se resolve sem admin (aceitar o alerta do Windows, porta
efêmera, descoberta) ou para o que só o administrador da rede pode fazer.
"""

from __future__ import annotations

import errno
import sys

__all__ = [
    "hint_for_bind_error",
    "discovery_empty_tips",
]

_BIND_PERMISSION_ERRNOS = frozenset({errno.EACCES, errno.EPERM})
# WSAEACCES: bind/listen negado no Windows (firewall ou porta reservada).
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
            "Firewall do Windows bloqueou a escuta: se aparecer o alerta de "
            "segurança, clique em 'Permitir acesso' (não precisa de "
            "administrador). Sem o alerta, só o administrador da máquina "
            "pode liberar."
        )
    return (
        "Firewall do sistema bloqueou a porta: liberar exige o administrador "
        "(sudo). Alternativa sem admin: rodar em rede sem firewall de host."
    )


def discovery_empty_tips() -> tuple[str, ...]:
    """Dicas exibidas quando a busca de partidas não encontra nada."""
    return (
        "Confira se o host criou a partida na mesma rede.",
        "Firewall do host pode estar bloqueando a descoberta — no Windows, "
        "aceite o alerta 'Permitir acesso' na primeira escuta.",
        "Em Wi-Fi com isolamento de clientes, só a conexão manual por IP funciona.",
    )
