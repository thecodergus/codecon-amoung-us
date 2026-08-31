"""Dicas de firewall: mapeamento de erro de bind e dicas de descoberta vazia."""

from __future__ import annotations

import errno

from codecon_amoung_us.net.firewall_hints import discovery_empty_tips, hint_for_bind_error


def test_hint_for_permission_denied() -> None:
    exc = OSError(errno.EACCES, "Permission denied")
    hint = hint_for_bind_error(exc)
    assert hint is not None
    assert "firewall" in hint.lower()


def test_hint_for_eperm() -> None:
    assert hint_for_bind_error(OSError(errno.EPERM, "Operation not permitted")) is not None


class _WindowsStyleOSError(OSError):
    """OSError com ``winerror`` como no Windows (o attr não existe no Linux)."""

    winerror: int

    def __init__(self) -> None:
        super().__init__("boom")
        self.winerror = 10013


def test_windows_access_denied_winerror() -> None:
    assert hint_for_bind_error(_WindowsStyleOSError()) is not None


def test_no_hint_for_address_in_use() -> None:
    assert hint_for_bind_error(OSError(errno.EADDRINUSE, "Address already in use")) is None


def test_no_hint_for_plain_oserror() -> None:
    assert hint_for_bind_error(OSError("sem detalhe")) is None


def test_discovery_empty_tips_are_actionable() -> None:
    tips = discovery_empty_tips()
    assert len(tips) >= 3
    assert all(tip.strip() for tip in tips)
    assert any("isolamento" in tip for tip in tips)
