"""Kernel de pixels para carga de sprites (Cython Pure Python Mode).

Opera sobre um buffer RGBA contíguo (``bytearray``, layout linha-major
``w * 4`` bytes por linha) produzido pelo caller via
``pygame.image.tostring(surface, "RGBA")``. Executa como Python puro;
compilado, os loops internos viram C: ``cython.declare`` converte os
buffers em typed memoryviews uma única vez na entrada e os índices são
``Py_ssize_t``. As assinaturas públicas usam tipos Python reais
(``bytearray``) — memoryviews ficam no interior do kernel, mantendo o
mypy strict útil nos callers.

A paridade interpretado/compilado é garantida pela suíte (job test-pure
do CI) e pela equivalência byte a byte em ``tests/test_native_pixels.py``.

Semântica (idêntica ao algoritmo original de ``sprites._load_frame``):

1. flood fill a partir das bordas: um pixel visitado é "alcançável";
   a expansão só atravessa pixels cuja cor RGB é exatamente a do fundo;
2. pixels alcançáveis viram transparentes (RGBA zerado — o ``out`` original
   nascia transparente, então os bytes finais são idênticos);
3. bounding box sobre os pixels restantes com alpha > 0.
"""

from __future__ import annotations

import cython

__all__ = ["apply_background_removal"]


@cython.cfunc
def _apply(
    px: bytearray,
    reachable: bytearray,
    stack: list[int],
    w: cython.Py_ssize_t,
    h: cython.Py_ssize_t,
    bg_r: cython.uchar,
    bg_g: cython.uchar,
    bg_b: cython.uchar,
) -> tuple[int, int, int, int] | None:
    # Cast único por chamada: daqui em diante o acesso é C puro (compilado).
    pxv = cython.declare(cython.uchar[::1], px)
    rv = cython.declare(cython.uchar[::1], reachable)

    x: cython.Py_ssize_t
    y: cython.Py_ssize_t
    i: cython.Py_ssize_t
    p: cython.Py_ssize_t
    n: cython.Py_ssize_t

    # Semeia toda a borda (cantos entram duas vezes, como no original — o
    # `reachable` na saída da pilha absorve duplicatas).
    for x in range(w):
        stack.append(x)
        stack.append((h - 1) * w + x)
    for y in range(h):
        stack.append(y * w)
        stack.append(y * w + (w - 1))

    while stack:
        p = stack.pop()
        if rv[p]:
            continue
        rv[p] = 1
        i = p * 4
        if pxv[i] != bg_r or pxv[i + 1] != bg_g or pxv[i + 2] != bg_b:
            continue  # fronteira de cor diferente: alcançável, mas não expande
        x = p % w
        y = p // w
        if x + 1 < w:
            stack.append(p + 1)
        if x > 0:
            stack.append(p - 1)
        if y + 1 < h:
            stack.append(p + w)
        if y > 0:
            stack.append(p - w)

    minx: cython.Py_ssize_t = w
    miny: cython.Py_ssize_t = h
    maxx: cython.Py_ssize_t = -1
    maxy: cython.Py_ssize_t = -1
    for y in range(h):
        n = y * w
        for x in range(w):
            i = (n + x) * 4
            if rv[n + x]:
                # RGBA zerado: idêntico ao `out` transparente do algoritmo
                # original (permite equivalência byte a byte).
                pxv[i] = 0
                pxv[i + 1] = 0
                pxv[i + 2] = 0
                pxv[i + 3] = 0
            elif pxv[i + 3] > 0:
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y

    if maxx < 0:
        return None
    return minx, miny, maxx, maxy


@cython.ccall
def apply_background_removal(
    px: bytearray,
    w: cython.Py_ssize_t,
    h: cython.Py_ssize_t,
    bg_r: cython.uchar,
    bg_g: cython.uchar,
    bg_b: cython.uchar,
) -> tuple[int, int, int, int] | None:
    """Remove o fundo (alpha zero) e retorna o bbox (minx, miny, maxx, maxy).

    ``px`` é o buffer RGBA mutável (``w * h * 4`` bytes); ``bg_*`` é a cor
    exata do fundo. Retorna ``None`` quando nenhum pixel sobrou (frame
    inteiramente fundo).
    """
    # Alocados por chamada: frames são pequenos (64x64) e a alternativa
    # (buffers reutilizáveis) quebraria a segurança de reentrância a custo
    # de complexidade — sem benefício medido.
    return _apply(px, bytearray(w * h), [], w, h, bg_r, bg_g, bg_b)
