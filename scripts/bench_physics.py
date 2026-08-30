"""Benchmark da física: physics.resolve_movement_steps vs kernel de colisão.

Cenário 1: chamada típica (deslocamento de um tick, 2 subpassos, 36 paredes
do lab.json) — baseline da auditoria: 1,99 µs/chamada.
Cenário 2: dt anômalo (0,5 s → ~12 subpassos) — o pior caso real do servidor.
Cenário 3: tick completo com 10 jogadores movendo — baseline: 19,3 µs/tick.

O kernel recebe as paredes já achatadas (custo de ``flatten_walls`` acontece
uma vez no startup do servidor, nunca por tick — por isso não entra na conta).

Uso: ``uv run python scripts/bench_physics.py [number]`` (padrão: 20000).
"""

from __future__ import annotations

import statistics
import sys
import timeit
from collections.abc import Callable

from codecon_amoung_us.game import _native_collision
from codecon_amoung_us.game._native_collision import (
    flatten_walls,
    resolve_movement_steps_flat,
)
from codecon_amoung_us.game.physics import resolve_movement_steps
from codecon_amoung_us.map.loader import load_map


def _bench(label: str, stmt: Callable[[], object], number: int, repeat: int = 7) -> float:
    samples = timeit.repeat(stmt, number=number, repeat=repeat)
    per_call = statistics.median(samples) / number
    print(f"{label:>34}: {per_call * 1e6:8.3f} µs/chamada")
    return per_call


def main() -> None:
    number = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    walls = load_map("assets/maps/lab.json").walls
    flat = flatten_walls(walls)
    print(f"paredes: {len(walls)} | kernel compilado: {_native_collision.__file__.endswith('.so')}")

    # típico: 1 tick a 180 px/s (9 px de deslocamento)
    ref = _bench(
        "típico | referência (physics)",
        lambda: resolve_movement_steps(100.0, 100.0, 8.5, 3.0, walls, max_step=8.0),
        number,
    )
    ker = _bench(
        "típico | kernel (flat)",
        lambda: resolve_movement_steps_flat(100.0, 100.0, 8.5, 3.0, flat, max_step=8.0),
        number,
    )
    print(f"  speedup: {ref / ker:.2f}x")

    ref = _bench(
        "dt anômalo | referência",
        lambda: resolve_movement_steps(100.0, 100.0, 85.0, 30.0, walls, max_step=8.0),
        number,
    )
    ker = _bench(
        "dt anômalo | kernel",
        lambda: resolve_movement_steps_flat(100.0, 100.0, 85.0, 30.0, flat, max_step=8.0),
        number,
    )
    print(f"  speedup: {ref / ker:.2f}x")

    def tick_ref() -> None:
        for i in range(10):
            resolve_movement_steps(100.0 + i, 100.0, 8.5, 3.0, walls, max_step=8.0)

    def tick_ker() -> None:
        for i in range(10):
            resolve_movement_steps_flat(100.0 + i, 100.0, 8.5, 3.0, flat, max_step=8.0)

    ref = _bench("tick 10 jogadores | referência", tick_ref, number // 10)
    ker = _bench("tick 10 jogadores | kernel", tick_ker, number // 10)
    print(f"  speedup: {ref / ker:.2f}x")


if __name__ == "__main__":
    main()
