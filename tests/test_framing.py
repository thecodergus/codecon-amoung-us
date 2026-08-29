"""Testes do framing JSON Lines (fragmentação, concatenação, malformados).

As propriedades Hypothesis de chunking ficam em test_framing_properties.py
(Etapa 11); aqui os casos determinísticos.
"""

from __future__ import annotations

import pytest

from codecon_amoung_us.framing import FrameDecoder, FrameError, encode_frame
from codecon_amoung_us.protocol import JoinRequest, MovementInput, ProtocolError, decode

MSG_A = JoinRequest(nickname="gus", protocol_version=1)
MSG_B = MovementInput(dx=0.5, dy=0.0, tick=7)
MSG_C = ProtocolError(code="x", message="erro")


def test_single_frame() -> None:
    decoder = FrameDecoder()
    out = decoder.feed(encode_frame(MSG_A))
    assert out == [MSG_A]


def test_frame_split_in_two_chunks() -> None:
    frame = encode_frame(MSG_A)
    mid = len(frame) // 2
    decoder = FrameDecoder()
    assert decoder.feed(frame[:mid]) == []
    assert decoder.feed(frame[mid:]) == [MSG_A]


def test_frame_split_at_every_byte_position() -> None:
    frame = encode_frame(MSG_A)
    for split in range(1, len(frame)):
        decoder = FrameDecoder()
        out = decoder.feed(frame[:split]) + decoder.feed(frame[split:])
        assert out == [MSG_A]


def test_multiple_frames_in_single_recv() -> None:
    decoder = FrameDecoder()
    out = decoder.feed(encode_frame(MSG_A) + encode_frame(MSG_B) + encode_frame(MSG_C))
    assert out == [MSG_A, MSG_B, MSG_C]


def test_frames_arriving_byte_by_byte() -> None:
    decoder = FrameDecoder()
    payload = encode_frame(MSG_A) + encode_frame(MSG_B)
    out: list[object] = []
    for byte in payload:
        out.extend(decoder.feed(bytes([byte])))
    assert out == [MSG_A, MSG_B]


def test_partial_frame_then_complete() -> None:
    decoder = FrameDecoder()
    frame_a = encode_frame(MSG_A)
    frame_b = encode_frame(MSG_B)
    split = len(frame_a) // 2
    # metade de A (sem newline) não produz nada ainda
    assert decoder.feed(frame_a[:split]) == []
    # resto de A + metade de B: A é extraído; B fica pendente
    assert decoder.feed(frame_a[split:] + frame_b[: len(frame_b) // 2]) == [MSG_A]
    # resto de B completa a segunda mensagem
    assert decoder.feed(frame_b[len(frame_b) // 2 :]) == [MSG_B]


def test_empty_feed_returns_nothing() -> None:
    decoder = FrameDecoder()
    assert decoder.feed(b"") == []


def test_empty_lines_ignored() -> None:
    decoder = FrameDecoder()
    out = decoder.feed(b"\n\n" + encode_frame(MSG_A) + b"\n")
    assert out == [MSG_A]


def test_invalid_json_raises_frame_error() -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError):
        decoder.feed(b"isto nao e json\n")


def test_schema_rejection_raises_frame_error() -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError):
        decoder.feed(b'{"type":"JoinRequest","nickname":"gus","protocol_version":3}\n')


def test_truncated_json_raises_frame_error() -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError):
        decoder.feed(b'{"type":"JoinRequest","nickname":"gus","protocol_versio\n')


def test_huge_frame_rejected() -> None:
    decoder = FrameDecoder(max_frame_bytes=1024)
    big = b"x" * 2048
    with pytest.raises(FrameError):
        decoder.feed(big + b"\n")


def test_oversized_partial_buffer_rejected() -> None:
    decoder = FrameDecoder(max_frame_bytes=1024)
    with pytest.raises(FrameError):
        decoder.feed(b"x" * 2048)  # sem newline: buffer parcial estourou


def test_encode_frame_appends_newline_and_decodes_back() -> None:
    frame = encode_frame(MSG_A)
    assert frame.endswith(b"\n")
    assert decode(frame[:-1]) == MSG_A
