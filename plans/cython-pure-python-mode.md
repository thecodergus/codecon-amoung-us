# Plano de adoção do Cython Pure Python Mode como padrão de projeto

Status: em execução (Etapa 0 → 5)
Decisão: **arquitetural** — `import cython` (Pure Python Mode, Cython 3.3.0) é extensão
cotidiana do Python tipado neste repositório, não ferramenta reservada a otimizações.
Substitui `plans/auditoria-cython-2026-08-30.md` (auditoria que embasou esta decisão).

## Decisão

Arquivos continuam `.py` executáveis pelo interpretador; a tipagem C é adicionada
progressivamente nos caminhos computacionais. Fronteiras com frameworks (msgspec,
pygame/pygame-menu, pytiled-parser) mantêm semântica Python e, se compiladas, usam
`@cython.annotation_typing(False)`. Nenhum `.pyx` é necessário neste projeto.

## Ambiente verificado (2026-08-30)

| Fato | Estado |
|---|---|
| Python | 3.13.12 (`requires-python = "==3.13.*"`), build convencional, **GIL ativo** (medido) |
| Cython | 3.3.0 em `[project.dependencies]` + `uv.lock` (runtime: shadow module importável) |
| Shadow module | sem `py.typed` → mypy strict falha (`import-untyped` + `untyped-decorator`, reproduzido) |
| Venv | sem setuptools/distutils (uv não instala; 3.13 removeu distutils) → `cythonize` falha sem setuptools |
| `uv_build` | só Python puro (doc oficial) → troca de backend obrigatória |
| Toolchain nativo | gcc 13.3.0 + Python.h 3.13 + Cython 3.3.0 → `.so` + annotation HTML (comprovado em /tmp) |
| Cython 3.3 | `match` (PEP-634) implementado; free-threading e `prange`-com-GIL experimentais (irrelevante: GIL ativo) |

## Baselines medidos (referência para benchmarks)

| Caminho | Tempo Python | Contexto |
|---|---:|---|
| `DuckeeSprites.__init__` (72 frames 64×64) | **0,28 s/processo** | único custo Python material (loops por pixel em `sprites._load_frame`) |
| `resolve_movement_steps` | 1,99 µs/chamada | física 10 jogadores ≈ 19,3 µs/tick vs 50 ms (0,04%) |
| `encode_frame` snapshot 10p / `FrameDecoder.feed` | 1,56 / 1,96 µs | msgspec/bytes já são C |
| `derive_task_markers` / `derive_game_hud` | 15,2 / 3,8 µs por frame | vs 16,6 ms (60 FPS) |
| Mapa lab.json | 36 paredes, 28 task points | dimensões dos loops |

## Arquitetura alvo

```text
protocol.py (msgspec) · fronteiras pygame/pytiled
        PYTHON PURO SEMÂNTICO — não compilar (protocol) ou
        compilar com @cython.annotation_typing(False)
                    ↓
api pública .py: def / @cython.ccall  (nunca @cython.cfunc)
                    ↓
kernels internos: @cython.cfunc, escalares cython.double/int/Py_ssize_t,
memoryviews T[::1], diretivas locais com invariante comprovado
                    ↓
(cython -a: zero C-API residual nos loops internos)
```

## Convenções (vocabulário do projeto)

- `x: int` ≠ `x: cython.int`. Tipos C só em escalares com faixa comprovada
  (coords ≤ ±1e6 pelo `FloatRange` do protocolo → `double`; ids < 2³¹ → `cython.int` só em kernels).
- Disciplina `def` → `@ccall` → `@cfunc`: API pública nunca `@cfunc` (paridade interpretado/compilado).
- `boundscheck/wraparound/cdivision(False)`: nunca globais nem no módulo; apenas em `@cfunc`
  com invariante comentado + teste cobrindo o invariante.
- `@cython.annotation_typing(False)` em módulo compilado cujas annotations são consumidas em runtime.
- `cython.compiled` apenas para diagnóstico/benchmark — nunca divergir comportamento.
- `nogil`/`prange` **fora do vocabulário inicial por governança**: game loop single-thread,
  startup single-thread, loops abaixo do ponto de equilíbrio do prange. Adição futura exige
  justificativa + benchmark.
- Kernel novo exige: annotation report sem C-API residual no loop + benchmark antes/depois.

## Etapas

### Etapa 0 — Build backend e toolchain
1. `pyproject.toml`: `[build-system]` → setuptools (requires: setuptools, wheel, cython>=3.3.0);
   `[tool.setuptools]` src-layout. `setuptools` no `dependency-groups.dev` (para `cythonize -i`).
2. `setup.py`: `cythonize` de todos os módulos de `src/codecon_amoung_us/` **exceto `protocol.py`**
   (msgspec.Struct + Annotated/Meta — risco de semântica; experimento futuro exige
   `annotation_typing(False)` + `test_protocol`/`test_secrecy` verdes).
   `language_level="3str"`; `annotate` via `CYTHON_ANNOTATE=1`; escape `CODECON_SKIP_NATIVE=1`.
3. Stub `typings/cython.pyi` + `mypy_path = ["src", "typings"]` (decoradores identidade genéricos,
   `int/double/bint` → aliases, `Py_ssize_t` → int, subscrição de memoryview, `compiled`, `declare`/`cast`).
4. CI: `uv sync` já compila; adicionar modo puro (`CODECON_SKIP_NATIVE=1`, `PYTHONPATH=src`)
   → paridade interpretado/compilado obrigatória. Windows: MSVC no runner.

Verificação: `uv sync && uv run pytest` verde (compilado) e modo puro verde; ruff/format/mypy verdes;
`uv build` produz wheel com `.so`.

### Etapa 1 — Convenções
Este documento (seção acima) é a referência; revisão de kernels exige annotation report no PR.

### Etapa 2 — Kernel de pixels (único custo material medido: 0,28 s/startup)
5. Antes: mesmo algoritmo com `memoryview` stdlib puro como comparador de benchmark.
6. Novo `ui/_native_pixels.py`: flood fill por cor exata + cópia de não-fundo + bbox sobre
   `Surface.get_view("2")` (`cython.uint[:, :]`; doc pygame: BufferProxy exporta buffer protocol).
   Surface de trabalho em formato 32-bit fixo. `@ccall` na fronteira, `@cfunc` nos passes;
   `boundscheck/wraparound(False)` só nos cfuncs com invariantes comentados.
7. `ui/sprites.py::_load_frame` delega os passes ao kernel (fallback puro sem a extensão).
Equivalência: bytes de cada surface final idênticos (via `get_view`) baseline vs novo, 72 frames
+ `test_visual_regression.py`. Benchmark: wall-time `DuckeeSprites()`, N≥15, baseline 0,28 s.
Adoção do kernel Cython somente se ≥ 2× o comparador stdlib.

### Etapa 3 — Kernel de colisão (melhor formato Cython; ganho absoluto hoje pequeno)
8. Novo `game/_native_collision.py`: paredes achatadas em 4 arrays contíguos `double`
   (derivados uma vez — nunca por tick), resolve por eixo + laço de subpassos como `@cfunc`.
9. `game/physics.py` vira fronteira `@ccall` preservando assinaturas públicas; `Rect` intocado.
Equivalência: hypothesis — posições finais bit-idênticas vs implementação atual, incluindo
dx/dy anômalos; `test_physics.py` verde. Benchmark: baseline 1,99 µs/chamada.

### Etapa 4 — Tipagem progressiva
10. `ui/camera.py` + `ui/motion.py`: `cython.double`, `@ccall`; manter dataclass (não `@cclass`).
11. `ui/viewmodel.py`: tipar escalares/loops dos `derive_*`; não achatar pontos por frame
    (conversão custaria mais que os 15 µs medidos).
12. Compilação sem tipagem adicional do restante (`net/`, `game/`, `map/`, `ui/`, `framing.py`);
    `server.py` valida `match` via `test_integration.py` + smoke E2E. Regressão → excluir módulo.

### Etapa 5 — Gates permanentes
13. Benchmarks versionados (`scripts/bench_*.py` ou marker `slow`) com os baselines acima.
14. CI publica annotation HTML dos kernels; loops internos sem amarelo.

## Critérios de aprovação/rejeição

- Paridade: suíte verde nos dois modos (puro e compilado), Ubuntu e Windows, incluindo
  `test_secrecy_properties.py`, `test_physics.py`, `test_visual_regression.py`, smoke E2E.
- Toolchain: ruff/format/mypy strict verdes; `uv build` com extensões; `CODECON_SKIP_NATIVE=1` funcional.
- Cada kernel: equivalência + benchmark controlado (N≥15) com ganho material vs baseline;
  caso contrário o kernel é rejeitado e reverte para a forma Python simples.

## Riscos

- Editable install + extensões: mudança em `.py` exige rebuild (`uv sync --reinstall` / `cythonize -i`).
- Stub `typings/cython.pyi` pode dessincronizar do shadow module — cobrir com teste de import/tipo.
- `Surface.get_view`: lifetime do BufferProxy e pitch/formato — surface intermediária de formato
  conhecido; validado por equivalência de bytes.
- msgspec compilado: comportamento desconhecido → `protocol.py` fora do escopo de compilação.

## Incertezas

- Stub mypy com `cython.double[::1]` em assinaturas: desenhado para cobrir, validar na Etapa 0.
- Ganho por módulo da compilação sem tipagem: medir na Etapa 4; excluir o que degradar.
