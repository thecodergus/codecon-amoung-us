"""Propriedade Hypothesis do framing: fragmentação TCP é transparente.

O parser deve produzir exatamente as mesmas mensagens independentemente
de como os bytes tenham sido fragmentados, incluindo múltiplas mensagens
concatenadas no mesmo ``recv``.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from codecon_amoung_us.config import PROTOCOL_VERSION
from codecon_amoung_us.framing import FrameDecoder, encode_frame
from codecon_amoung_us.protocol import (
    JoinRequest,
    MovementInput,
    ProtocolError,
    VoteRequest,
)

_VALID_MESSAGES = [
    JoinRequest(nickname="gus", protocol_version=PROTOCOL_VERSION),
    MovementInput(dx=0.5, dy=-0.25, tick=7),
    MovementInput(dx=0.0, dy=1.0, tick=8),
    VoteRequest(meeting_id=1, target_id=3),
    VoteRequest(meeting_id=1, target_id=None),
    ProtocolError(code="x", message="erro de teste"),
]


@settings(max_examples=500, deadline=None)
@given(
    messages=st.lists(st.sampled_from(_VALID_MESSAGES), min_size=0, max_size=8),
    cut_points=st.lists(st.integers(min_value=1, max_value=1000), max_size=20),
)
def test_chunking_is_lossless(messages: list[object], cut_points: list[int]) -> None:
    payload = b"".join(encode_frame(m) for m in messages)  # type: ignore[arg-type]
    decoder = FrameDecoder()
    if not payload:
        assert decoder.feed(b"") == []
        return
    points = sorted({0, len(payload)} | {p % (len(payload) + 1) for p in cut_points})
    out: list[object] = []
    for start, end in zip(points, points[1:], strict=False):
        out.extend(decoder.feed(payload[start:end]))
    assert out == messages


@settings(max_examples=300, deadline=None)
@given(
    messages=st.lists(st.sampled_from(_VALID_MESSAGES), min_size=1, max_size=6),
)
def test_concatenated_messages_in_single_feed(messages: list[object]) -> None:
    payload = b"".join(encode_frame(m) for m in messages)  # type: ignore[arg-type]
    decoder = FrameDecoder()
    assert decoder.feed(payload) == messages


@settings(max_examples=200, deadline=None)
@given(
    messages=st.lists(st.sampled_from(_VALID_MESSAGES), min_size=1, max_size=6),
)
def test_empty_line_padding_is_ignored(messages: list[object]) -> None:
    """Linhas vazias ao redor das mensagens são descartadas pelo parser."""
    payload = b"".join(encode_frame(m) for m in messages)  # type: ignore[arg-type]
    padded = b"\n\n" + payload + b"\n"
    decoder = FrameDecoder()
    assert decoder.feed(padded) == messages
