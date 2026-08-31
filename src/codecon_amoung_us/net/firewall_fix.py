"""Correção de permissões de rede (firewall de host) em um clique.

Windows: cria uma regra inbound ``allow`` para o executável atual (venv ou
binário empacotado, via ``sys.executable``) com ``netsh advfirewall`` e
elevação UAC (``ShellExecuteW`` com verbo ``runas``). Outros sistemas: apenas
devolve o comando manual pronto — nunca executa ``sudo`` por baixo do usuário.

A construção do comando é separada da execução: assim os testes cobrem a
construção sem exigir elevação (que não é automatizável em CI). A correção é
sempre opt-in: só roda quando o usuário clica no botão.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FirewallFixResult",
    "RULE_NAME",
    "build_manual_hint",
    "build_netsh_command",
    "netsh_rule_arguments",
    "run_network_fix",
]

RULE_NAME = "Codecon Among Us"


@dataclass(frozen=True)
class FirewallFixResult:
    """Resultado da tentativa de correção (texto pronto para a UI)."""

    success: bool
    message: str


def netsh_rule_arguments(program: Path) -> str:
    """Argumentos do netsh (sem o executável) — fronteira testável."""
    return (
        f'advfirewall firewall add rule name="{RULE_NAME}" dir=in action=allow '
        f'program="{program}" enable=yes profile=any'
    )


def build_netsh_command(program: Path) -> str:
    """Linha completa documentada (reproduzível à mão em shell admin)."""
    return f"netsh {netsh_rule_arguments(program)}"


def build_manual_hint(port: int) -> str:
    """Comando manual pronto para Linux/macOS: jogo + porta de descoberta."""
    return f"sudo ufw allow {port}/tcp && sudo ufw allow 5557/udp"


def run_network_fix(port: int) -> FirewallFixResult:
    """Executa a correção: elevação UAC no Windows; comando manual caso contrário.

    ``ShellExecuteW`` retorna >32 quando o pedido de elevação foi lançado com
    sucesso (a decisão do UAC é assíncrona); <=32 indica recusa/falha.
    """
    if sys.platform != "win32":
        return FirewallFixResult(
            success=False,
            message=(
                "Correção automática é exclusiva do Windows. Comando manual:\n"
                f"  {build_manual_hint(port)}"
            ),
        )
    import ctypes

    shell32 = getattr(ctypes, "windll", None)
    if shell32 is None:
        return FirewallFixResult(
            success=False, message="Windows Shell indisponível; não foi possível elevar."
        )
    arguments = netsh_rule_arguments(Path(sys.executable))
    code = int(shell32.ShellExecuteW(None, "runas", "netsh", arguments, None, 1))
    if code > 32:
        return FirewallFixResult(
            success=True,
            message="Pedido de permissão enviado — aceite o UAC para criar a regra de firewall.",
        )
    return FirewallFixResult(
        success=False,
        message=f"Elevação recusada ou falhou (código {code}). "
        "Comando manual (shell de admin):\n"
        f"  {build_netsh_command(Path(sys.executable))}",
    )
