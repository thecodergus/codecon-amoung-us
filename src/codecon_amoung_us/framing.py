"""Framing JSON Lines: serialização + extração de frames completos.

Centraliza encode/framing/buffering/extração/decode. Nenhuma outra parte
da aplicação chama ``msgspec.json`` diretamente.

``\n`` nunca aparece dentro de um frame porque o JSON serializado por
msgspec sempre escapa caracteres de controle em strings.
"""

from __future__ import annotations

from msgspec import MsgspecError

from .config import MAX_FRAME_BYTES
from .protocol import Message, decode, encode

__all__ = ["FrameError", "encode_frame", "FrameDecoder"]


class FrameError(Exception):
    """Erro de framing (frame muito grande, JSON inválido ou schema rejeitado)."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


def encode_frame(message: Message) -> bytes:
    """Serializa a mensagem e a emoldura como uma linha JSON + ``\\n``."""
    payload = encode(message)
    if len(payload) > MAX_FRAME_BYTES:
        raise FrameError(f"frame excede o limite de {MAX_FRAME_BYTES} bytes")
    return payload + b"\n"


class FrameDecoder:
    """Acumula bytes recebidos e extrai mensagens completas (por ``\\n``).

    Chamadas ``recv`` podem conter zero, um ou vários frames (ou partes);
    o buffer interno resolve tudo.
    """

    def __init__(self, max_frame_bytes: int = MAX_FRAME_BYTES) -> None:
        self._buffer = bytearray()
        self._max_frame_bytes = max_frame_bytes

    def feed(self, data: bytes) -> list[Message]:
        """Alimenta bytes e retorna as mensagens completas extraídas."""
        self._buffer.extend(data)
        messages: list[Message] = []
        while True:
            newline = self._buffer.find(b"\n")
            if newline == -1:
                break
            line = bytes(self._buffer[:newline])
            del self._buffer[: newline + 1]
            if not line.strip():
                continue  # linha vazia (ping/envio acidental) é ignorada
            if len(line) > self._max_frame_bytes:
                raise FrameError(f"frame excede o limite de {self._max_frame_bytes} bytes")
            try:
                messages.append(decode(line))
            except MsgspecError as exc:
                raise FrameError("frame não corresponde ao schema do protocolo", cause=exc) from exc
        if len(self._buffer) > self._max_frame_bytes:
            raise FrameError(f"buffer parcial excede o limite de {self._max_frame_bytes} bytes")
        return messages
