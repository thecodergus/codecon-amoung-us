"""Correção de firewall em um clique: construção do comando e fluxo fora do Windows."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codecon_amoung_us.net.firewall_fix import (
    RULE_NAME,
    build_manual_hint,
    build_netsh_command,
    netsh_rule_arguments,
    run_network_fix,
)


def test_netsh_rule_arguments_contents() -> None:
    program = Path("/caminho/python.exe")
    args = netsh_rule_arguments(program)
    assert RULE_NAME in args
    assert "dir=in action=allow" in args
    assert f'program="{program}"' in args
    assert "enable=yes" in args
    assert "profile=any" in args


def test_build_netsh_command_is_reproducible() -> None:
    program = Path("/caminho/python.exe")
    command = build_netsh_command(program)
    assert command.startswith("netsh ")
    assert command == f"netsh {netsh_rule_arguments(program)}"


def test_manual_hint_covers_game_and_discovery_ports() -> None:
    hint = build_manual_hint(5555)
    assert "5555/tcp" in hint
    assert "5557/udp" in hint


@pytest.mark.skipif(sys.platform == "win32", reason="no Windows o fluxo tenta elevar de verdade")
def test_run_network_fix_off_windows_returns_manual_command() -> None:
    result = run_network_fix(5555)
    assert result.success is False
    assert "ufw" in result.message
    assert "5555/tcp" in result.message
