# Auditoria técnica de otimização com Cython — 2026-08-30

Auditoria e plano (não é implementação). Escopo: oportunidades de Cython
(Pure Python Mode prioritário) para reduzir overhead de bytecode Python,
latência CPU-bound e/ou aumentar throughput.

## 0. Status de execução (atualizado durante a implementação)

| Etapa do roadmap | Estado |
|---|---|
| 1. Otimizar `ui/sprites.py::_load_frame` SEM Cython (PixelArray/memoryview/buffer) | **executada** — ver commits |
| 2. Kernel Cython de pixels (somente se etapa 1 falhar no critério) | pendente — gate de benchmark |
| 3. Kernel Cython de colisão (`game/physics.py`) | pendente — gatilho de escala |
| 4. Broadcast encode-uma-vez (`net/server.py`, não-Cython) | pendente — gatilho de MAX_PLAYERS |

## 1. Resumo executivo

MVP multiplayer estilo Among Us: servidor autoritativo TCP (game loop 20 Hz)
e cliente Pygame (60 FPS), ~7k linhas. O trabalho pesado já está em código
nativo: msgspec (C), pygame/SDL (C), pytiled-parser (startup). O resíduo de
tempo em bytecode Python foi **medido nesta sessão**:

| Caminho medido | Tempo Python | Orçamento do ciclo | Fração |
|---|---:|---:|---:|
| Física do tick, 10 jogadores movendo (36 paredes, lab.json) | 19,3 µs/tick | 50.000 µs (20 Hz) | 0,04% |
| `encode_frame` de snapshot (10 jogadores) | 1,56 µs | — | msgspec já é C |
| `FrameDecoder.feed` (1 snapshot) | 1,96 µs | — | bytes/msgspec já são C |
| `derive_task_markers` por frame (28 pontos) | 15,2 µs | 16.666 µs (60 FPS) | 0,09% |
| `derive_game_hud` por frame | 3,8 µs | 16.666 µs | 0,02% |
| **`DuckeeSprites.__init__` (72 frames 64×64, loops por pixel)** | **0,28 s, 1×/processo** | startup | **único custo Python material** |

**Priorização: P0 = 0, P1 = 1, P2 = 3, Experimental = 0.**

- Única oportunidade com custo Python material medido: loops por pixel de
  `ui/sprites.py::_load_frame` (flood fill + cópia + bounding box com
  `get_at`/`set_at`, 72 frames na inicialização). Ganho absoluto limitado
  (~0,28 s 1×/processo). Alternativa sem Cython (buffer de
  `Surface.get_view()` + stdlib) é o comparador obrigatório do benchmark.
- Candidatos estruturalmente adequados mas imateriais hoje (P2):
  `game/physics.py` (melhor "formato Cython" do repo), `ui/camera.py` +
  `ui/motion.py`, `ui/viewmodel.py`. Todos na casa de µs/ciclo. Só viram
  relevantes se a escala mudar (centenas de paredes, dezenas de jogadores,
  tick rate maior).
- Cython NÃO recomendado em: protocolo/framing (msgspec já é C), rede
  (I/O + locks), render (blits em C), orquestração app, puzzles (loops
  ≤9 elementos), domínio reunião/votação/tarefas (eventos raros), loader,
  config, scripts.
- Riscos: (1) `uv_build` só suporta Python puro (doc oficial) — Cython
  exige trocar o backend e adicionar build nativo no CI Windows+Ubuntu,
  custo desproporcional ao ganho disponível hoje; (2) `protocol.py` usa
  `msgspec.Struct` com introspecção de annotations — compilar esses
  módulos pode alterar semântica de validação; manter puros; (3) mypy
  strict + testes precisam cobrir a variante compilada.

**Conclusão:** não há hot path onde Cython produza benefício material
comprovável no estado atual. Recomendação: não adotar Cython agora;
resolver `sprites._load_frame` primeiro sem build nativo; Cython apenas se
o benchmark mostrar que a alternativa pura não basta.

## 2. Ambiente e fonte de verdade

| Item | Estado | Evidência |
|---|---|---|
| Python efetivo | **3.13.12** (venv), `requires-python = "==3.13.*"` | `pyproject.toml`, `.python-version` |
| Discrepância | Tarefa menciona "Python 3.14"; o projeto fixa 3.13 → análise para 3.13 | código como fonte de verdade |
| GIL / free-threaded | Build convencional, **GIL habilitado** (`sys._is_gil_enabled()` → True) | execução na venv |
| Cython | **não instalado, ausente do `uv.lock`** | grep `uv.lock`/`pyproject.toml` |
| Versão Cython se adotado | estável atual **3.3.0** (2026-08-22); suporte free-threading básico/**experimental** desde 3.1 (doc oficial) | docs Cython 3.3.0 |
| SO/arch/compilador | Linux x86_64 (Ubuntu 24.04), gcc 13.3.0 | `uname`, `gcc --version` |
| Build | `uv_build>=0.12.7,<0.13`; doc oficial: "only supports pure Python code" | `pyproject.toml`, docs.astral.sh |
| Deps | `pygame==2.6.1` (C/SDL), `msgspec>=0.21,<0.22` (C), `pytiled-parser`, `pygame-menu`; **sem NumPy/asyncio/multiprocessing/OpenMP/BLAS** | `pyproject.toml` |
| Concorrência | `threading` apenas (thread/conexão TCP + game loop + recv); `queue.Queue` com backpressure | `net/server.py`, `net/client.py` |
| Testes | pytest 9 + hypothesis, timeout=15, markers slow/integration/ui, branch coverage; CI Ubuntu+Windows | `pyproject.toml`, `.github/workflows/ci.yml` |
| Benchmarks | **não existem**; evidência prévia: A-06 (2026-08) em `net/server.py:72-76` — flood ~133k msg/s loopback manteve 20 ticks/s | — |
| Frameworks c/ introspecção | **msgspec.Struct** (tagged union, `Annotated`/`Meta`) em `protocol.py`; dataclasses; StrEnum | — |

Não confirmado (read-only na época): suíte executada nesta sessão;
annotation report do Cython; mypy strict sobre `import cython`.

## 3. Matriz de cobertura

Todos os módulos de `src/codecon_amoung_us/` revisados (28/28) + `scripts/`
(4/4 por categoria) + testes (estrutura).

| Módulo/área | Revisado | Hot path | Candidatos | Prioridade máx | Observação |
|---|:-:|:-:|---:|---|---|
| `game/physics.py` | ✅ | servidor, por jogador/tick | 1 | **P2** | 19,3 µs/tick medidos — imaterial hoje |
| `map/model.py` (`Rect.contains`) | ✅ | via física | 1 | **P2** | frozen dataclass; properties recalculadas |
| `ui/sprites.py::_load_frame` | ✅ | startup, 72× | 1 | **P1** | **0,28 s/processo medidos** |
| `ui/camera.py` | ✅ | 60 FPS | 1 | P2 | ~µs/frame |
| `ui/motion.py` | ✅ | via UI | 1 | P2 | easing trivial |
| `ui/viewmodel.py` | ✅ | 60 FPS | 2 | P2 | 15,2 µs/frame medidos; loops ≤28 itens |
| `framing.py` | ✅ | por mensagem | 0 | — | ~2 µs; já é C |
| `protocol.py` | ✅ | por mensagem | 0 | — | **não compilar**: msgspec introspeciona annotations |
| `net/server.py` | ✅ | loop 20 Hz | 0 | — | orquestração dicts/filas/locks |
| `net/client.py`, `net/dispatch.py` | ✅ | I/O/evento | 0 | — | I/O-bound |
| `game/rules.py` | ✅ | por comando (raro) | 0 | — | custo desprezível |
| `game/model.py` | ✅ | — | 0 | — | dataclasses cruzam p/ msgspec — manter Python |
| `game/meeting.py`, `voting.py`, `tasks.py` | ✅ | 1×/reunião | 0 | — | eventos raros |
| `game/task_catalog.py` | ✅ | não | 0 | — | dados estáticos |
| `map/loader.py` | ✅ | startup I/O | 0 | — | parse único |
| `config.py` | ✅ | não | 0 | — | configuração |
| `ui/app.py` | ✅ | loop 60 FPS | 0 | — | orquestração; `_present` = smoothscale em C |
| `ui/render.py` | ✅ | 60 FPS | 0 | — | blits em C; resíduo mínimo |
| `ui/components.py`, `layout.py`, `theme.py`, `fonts.py`, `task_props.py` | ✅ | draw/frame | 0 | — | glue de UI |
| `ui/puzzles/*` (8) | ✅ | 60 FPS modal | 0 | — | loops de 4–9 elementos |
| `__init__.py`, `__main__.py` | ✅ | não | 0 | — | entry points |
| `scripts/*.py` (4) | ✅ | não | 0 | — | codegen/smoke one-off |
| `tests/` | ✅ | — | 0 | — | suporte |

## 4. Matriz de oportunidades

| # | Prioridade | Arquivo/símbolo | Evidência | Gargalo | Proposta | `.py` Pure Mode? | nogil/paralelo | Impacto | Risco | Confiança | Validação |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **P1** | `ui/sprites.py::_load_frame` | medido 0,28 s (72 frames) | get_at/set_at por pixel; flood fill e bbox em bytecode | kernel de pixels sobre buffer da Surface (`get_view`) | sim (se Cython) | nogil-eligible; prange não (64×64 pequeno) | alto no trecho; absoluto baixo | médio (pitch, lock, alpha) | média-alta | wall-time init + superfícies idênticas |
| 2 | P2 | `game/physics.py::resolve_movement(_steps)` + `Rect.contains` | medido 1,99 µs/chamada | `any()` + properties por parede por subpasso | paredes achatadas em arrays C (`double`), `@cython.cfunc` | sim | nogil-eligible; **liberar GIL não ajuda** (loop single-thread) | baixo hoje; alto se escala ×100 | baixo | alta | micro-bench + equivalência hypothesis |
| 3 | P2 | `ui/camera.py` + `ui/motion.py` | estático + ~µs/frame medido | dataclass + properties + tuples | `double`, cfunc | sim | n/a | baixo | baixo | média | micro-bench; testes de câmera |
| 4 | P2 | `ui/viewmodel.py::derive_*` | medido 15,2 µs/frame | loops ≤28 pontos c/ `hypot` | loops C sobre pontos achatados | sim | não | baixo | baixo | média-alta | micro-bench; equivalência |
| 5 | Não recomendado | `protocol.py`, `framing.py` | medido ~2 µs/msg | já em C | — | — | — | improvável | — | alta | — |
| 6 | Não recomendado | `net/server.py` tick/dispatch | estático + A-06 | orquestração/locks | — | — | — | improvável | — | alta | — |
| 7 | Não recomendado | `ui/render.py`, `app.py`, `puzzles/*`, demais UI | estático | blits/draw em C | — | — | — | improvável | — | alta | — |
| 8 | Não recomendado | `game/rules.py`, `meeting.py`, `voting.py`, `tasks.py`, `loader.py`, `config.py`, `scripts/*` | estático | eventos raros/startup | — | — | — | improvável | — | alta | — |
| 9 | Experimental → rejeitado | `prange`/OpenMP em qualquer loop | estático | loops de 36 paredes, ≤28 pontos, 64×64 px | — | — | overhead de prange domina; risco de oversubscription com SDL/threads | improvável | — | alta | — |
| 10 | Experimental → rejeitado | projetar p/ free-threaded 3.13/3.14 | GIL habilitado (medido) | — | — | — | build convencional | — | — | alta | — |

Achado não-Cython relevante: `GameServer._broadcast` re-codifica a mesma
mensagem por conexão (`conn.send` → `encode_frame`), N× por tick. Correção
correta: codificar uma vez e enviar os mesmos bytes (refactor puro). Hoje
~0,3 ms/s — imaterial; primeiro gargalo se MAX_PLAYERS crescer.

## 5. Detalhe das oportunidades P1/P2

### 5.1 (P1) `ui/sprites.py::_load_frame` — kernel de pixels

Comportamento atual (`sprites.py:96-146`): por frame (72×, 64×64):
(a) conta cores da borda via `get_at` pixel a pixel; (b) flood fill por cor
exata a partir da borda com pilha Python; (c) copia pixels não-fundo com
`get_at`/`set_at` por pixel; (d) varre tudo de novo para o bounding box.
≈1,2 M de chamadas C-API de pixel. Medido: 0,28 s no init do `Renderer`.

Transformação proposta (etapa 1, SEM Cython):

```text
get_at/set_at por pixel
  ↓ buffer da Surface UMA vez (Surface.get_view — BufferProxy exporta
    buffer protocol, doc oficial pygame) + bytes/memoryview/bytearray stdlib
  ↓ flood fill sobre bytes planos + bytearray reachable + pilha de ints
  ↓ saída RGBA montada em bytearray + pygame.image.frombuffer (C)
  ↓ bbox via Surface.get_bounding_rect (C) ou varredura por linhas com
    bytes.index (C) — sem passada por pixel em Python
```

Riscos: formato/pitch do buffer (normalizar formato conhecido ou ler
strides); ciclo de vida do BufferProxy; equivalência da comparação de cor
(RGB empacotado vs tupla). Critério de adoção do Cython (etapa 2): só se a
variante pura não atingir ≥ 2× e redução ≥ 150 ms do startup.

Benchmark: wall-time de `DuckeeSprites()` com `SDL_VIDEODRIVER=dummy`,
N ≥ 15: (i) baseline; (ii) variante pura; (iii) Cython (só se necessário).

Equivalência: bytes de surface idênticos entre baseline e otimizado para
todos os frames; `test_visual_regression.py` verde.

### 5.2 (P2) `game/physics.py` + `Rect.contains` — kernel de colisão

Atual: subpassos (tipicamente 2) × 2 eixos × `any(wall.contains(...))` sobre
36 paredes; `contains` recomputa `left/right/top/bottom` via properties.
Medido: 19,3 µs/tick (10 jogadores) = 0,04% do orçamento.

Proposta (somente se a escala mudar): achatar paredes no load em 4 arrays
contíguos (`array('d')`/memoryview `double[:]`), teste como `@cython.cfunc`
com `cython.Py_ssize_t`/`cython.double`, early-exit preservado, ordem de
eixos (deslizamento) preservada. `double` é seguro (coordenadas ±1e6 pelo
`FloatRange` do protocolo). Sem `.pyx`. Gatilho: física > 5% do orçamento
do tick.

### 5.3 (P2) `ui/camera.py` + `ui/motion.py` · 5.4 (P2) `ui/viewmodel.py`

Matemática escalar de floats por frame, medida em µs/frame (pior caso
15 µs). Compilariam bem (`double`, cfunc), mas ganho imaterial vs 16,6 ms.
Gatilho: +1 ordem de grandeza no número de entidades por frame.

## 6. Onde Cython NÃO deve ser utilizado

- `protocol.py`: msgspec introspeciona `Annotated`/`Meta`; encode/decode já é C.
- `framing.py`: resíduo mínimo sobre `bytearray.find` (C) + msgspec (C).
- `net/*`: I/O-bound (sockets, threads, locks, fila); ~200 msg/s legítimos (A-06).
- `ui/app.py`, `ui/render.py`: custo real é smoothscale/blits/flip em C.
- `ui/puzzles/*`: loops de 4–9 elementos.
- `ui/components.py`, `layout.py`, `theme.py`, `fonts.py`, `task_props.py`: glue.
- `game/rules.py` (por ação, não por tick), `meeting/voting/tasks` (1×/reunião),
  `map/loader.py`, `config.py`, `scripts/*`, entry points: raros/startup/one-off.
- `prange`/OpenMP: workloads (36 paredes, 28 pontos, 64×64 px) ordens abaixo do
  ponto de equilíbrio do overhead; risco de oversubscription com SDL.
- `nogil` como "otimização": os dois kernels nogil-eligible rodam single-thread
  (startup; game loop único) — não há consumidor concorrente para a liberação.

## 7. Arquitetura Python ↔ Cython (se um dia adotada)

```text
ui/app.py · net/* · protocol/framing · game/* — PYTHON PURO (não compilar)
        ↓ fronteira estável (dados já achatados; conversão 1× no load)
kernels novos e pequenos, compilados:
  ui/_sprite_pixels.py   (flood fill + bbox sobre buffer)
  game/_collision.py     (paredes achatadas, subpassos)
        ↓
loops C: double / Py_ssize_t / memoryviews, @cython.cfunc,
diretivas locais com invariantes documentados
```

Kernels em módulos próprios (não Cythonizar arquivos com APIs públicas);
fallback de import puro (testes/dev sem compilar).

## 8. Integração de build (proposta — não implementada)

1. Trocar `[build-system]` (uv_build → hatchling/setuptools + cython em
   build-requires); uv continua como frontend PEP 517.
2. `uv add --dev cython` (≥3.3, no lockfile; vetting de dependência).
3. Compilar somente os kernels (Pure Python Mode; nenhum `.pyx` necessário).
4. CI: build nativo em ubuntu-latest e windows-latest; suíte contra variante
   compilada e pura.
5. Wheels passam a ser por plataforma — mudança material de distribuição;
   **não fazer sem P1 confirmado por benchmark**.
6. Annotation report: `uv run cython -a <kernel>.py` (ou `cythonize -a`);
   zero linhas amarelas nos loops internos antes de merge.

## 9. Roadmap

1. **(sem Cython, risco mínimo)** Reescrever `_load_frame` com buffer/
   memoryview stdlib; medir vs baseline 0,28 s. — **EXECUTADA**
2. **(P1 condicional)** Kernel Cython de pixels + swap de backend + CI
   nativo — somente se etapa 1 falhar no critério (≥2× e ≥150 ms).
3. **(P2, gatilho de escala)** Kernel de colisão quando física > 5% do
   orçamento do tick (medir como nesta auditoria).
4. **(contínuo)** Broadcast encode-uma-vez quando MAX_PLAYERS crescer.

## 10. Plano de validação

- Benchmarks reproduzíveis, N ≥ 15, mesma máquina, `SDL_VIDEODRIVER=dummy`.
  Baselines: sprites 0,28 s/init; física 1,99 µs/chamada; markers 15,2 µs.
- Aprovação: testes verdes + ganho material medido; rejeitar caso contrário.
- Equivalência: bytes de surface idênticos (sprites); posições finais
  idênticas via hypothesis (física); suíte existente verde nas duas variantes.
- Annotation reports obrigatórios para qualquer kernel Cython.
- GIL/thread safety: nenhum kernel nogil toca objeto Python; nenhum consumidor
  fora das threads atuais (game loop único; init do Renderer).
- Build: wheel com extensão em linux+windows; pytest verde com e sem extensão.

## 11. Incertezas e limitações

- Suíte não executada durante a auditoria (era read-only); baselines de CPU
  medidos diretamente. (Executada na implementação — ver commits.)
- Annotation reports não gerados na auditoria (Cython ausente).
- Profiling de processo inteiro não realizado; números são micro-benchmarks
  dos únicos loops encontrados por inspeção exaustiva.
- Versão Cython: estável atual 3.3.0 (doc oficial); free-threading do Cython
  experimental — irrelevante aqui (GIL habilitado, medido).
- Layout real dos buffers de surface (24 vs 32 bits, pitch) depende dos PNGs;
  kernel deve normalizar o formato.
- Discrepância "3.14" vs "==3.13.*": resolvida a favor do código. Se houver
  migração para 3.14, refazer análise de ambiente; nenhuma recomendação muda
  de natureza.

Comandos de benchmark usados na auditoria: ver git history / seção 1
(micro-benchmarks `timeit` read-only na venv do projeto).
