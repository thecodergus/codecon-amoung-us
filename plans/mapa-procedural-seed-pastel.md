# Mapas procedurais por seed com estética pastel (runtime por partida)

Data: 2026-08-30. Status: em execução.

## Objetivo

Substituir o builder de layout fixo (`scripts/build_lab_map.py`) por um **gerador
procedural dirigido por seed** que produz mapas distintos, validados e com
estética "fofa" (paletas pastel, formas arredondadas, props decorativos),
gerado **no início de cada partida pelo servidor** e reconstituído
deterministicamente nos clientes a partir da seed enviada no protocolo. Os
assets commitados continuam existindo (seed padrão) para menus e para o gate
de frescor do CI.

## Contexto confirmado (evidência no repositório)

- `scripts/build_lab_map.py` (745 linhas): layout autorado à mão (12 salas + 8
  corredores, `_ROOMS`/`_CORRIDORS`), gates de validação robustos (BFS de
  componente único, ciclos via union-find, distâncias mínimas, cobertura de
  tipos de tarefa — `validate()`), emissão de Tiled JSON, composição de cena
  com tileset sci-fi, modo `--check` (gate em `.github/workflows/ci.yml`, job
  `assets-freshness`).
- `src/codecon_amoung_us/map/model.py`: `GameMap` é dataclass frozen —
  construível diretamente sem parser Tiled.
- Servidor (`net/server.py`): carrega o mapa no `__init__` (linha 167); spawns
  atribuídos no **join** (linha 440); `_state.tasks` derivado do mapa no init
  (linha 174); snapshots **só são broadcast na fase PLAYING** (linhas 311-317)
  — posições de lobby são irrelevantes, então spawn pode mover para o start
  sem impacto.
- Protocolo: `StartGame(map_name, players)` (protocol.py:201);
  `PROTOCOL_VERSION = 2` (config.py:15); `JoinRequest` tem constraint
  `ProtocolVersion` (ge=1, le=2) — bump para 3 exige atualizar a constraint.
- Cliente (`ui/app.py`): carrega mapa commitado no `__init__` (linha 254);
  handler de `StartGame` (linha 734) hoje só troca de tela.
  `Renderer.__init__` carrega `lab_scene.png` de caminho fixo
  (`ui/render.py:140`).
- Testes: `tests/test_lab_map.py` espelha os gates contra o asset;
  `tests/test_visual_regression.py` compara screenshots com baselines
  commitadas (docstring prevê regeneração intencional).
- Pesquisa MCP (estado da arte): survey AIIDE 2024 "PCG in Games" (DOI
  10.1609/aiide.v20i1.31877 — taxonomia construtiva/search-based/constraint/
  ML); PCGML (DOI 10.1109/TG.2018.2846639); GAN condicionado (Scientific
  Reports 2026) — abordagens ML **rejeitadas** aqui: exigem dataset, GPU e
  quebram determinismo leve servidor↔cliente. Estética cozy/kawaii (fontes
  web): pastel de alta luminosidade, contornos arredondados, ornamento whimsy
  de baixo contraste.

**Decisões do usuário:** runtime por partida; sprites procedurais pastel via
pygame (sem assets externos, sem dependências novas); substituir o builder
atual.

## Plano

### 1. Núcleo do gerador — `src/codecon_amoung_us/map/generator.py` (novo, sem pygame)

Módulo puro e determinístico. Todo consumo de aleatoriedade via
`random.Random(seed)`; sub-RNGs por estágio derivados com
`rng.getrandbits(64)` — **nunca `hash()`** (randomizado por processo) e sempre
iterando coleções **ordenadas** antes de sortear.

API: `generate_map(seed: int, *, config: GenConfig = DEFAULT) -> GameMap` e
`to_tiled_json(game_map, walls_cells) -> dict` (para o script de assets).

Pipeline interno (generate-and-test construtivo, cf. survey AIIDE 2024):

1. **Salas**: 12 salas (nomes de um pool fixo) posicionadas por amostragem com
   rejeição — retângulos 7–14 células, gap mínimo 2–3 células, tentativas
   limitadas.
2. **Conectividade**: grafo completo sobre centroides → MST de Prim (desempate
   pela seed) + 3–5 arestas extras mais curtas (garante ciclos — mesmo
   invariante do gate atual).
3. **Corredores**: carving em L (largura 2–3 células, ordem do cotovelo
   sorteada) entre pontos de borda das salas ligadas.
4. **Pontos de gameplay**: hub = sala mais central → botão de emergência;
   spawns por max-min greedy (≥ `MAX_PLAYERS`); tarefas distribuídas
   round-robin embaralhado por salas, cobrindo todos os `TASK_TYPES`
   (atribuição cíclica como hoje).
5. **Gates**: portar `validate()` do builder quase verbatim (área ≥6×,
   caminhável ≥1000 células, ≥10 salas, componente único BFS, alcançabilidade,
   distâncias ≥1,5 célula, ≥6 salas com tarefa, ciclo, paredes válidas via
   `blocked_rects` run-length). Falha de gate → nova tentativa com sub-seed
   derivada (limite ~200; depois `BuildError`).
6. **Emissão**: construir `GameMap` diretamente (paredes, floor, spawns,
   tasks, emergência, rooms) — sem roundtrip Tiled em runtime.

### 2. Renderer pastel — `src/codecon_amoung_us/map/scene.py` (novo, pygame)

`render_scene(game_map, seed) -> pygame.Surface` + `menu_crop(scene, game_map)`.
Estética fofa determinística (mesma seed → mesmos pixels; usar **apenas
`pygame.draw`** — evitar gfxdraw/antialiasing, risco de divergência entre
plataformas no gate de pixels do CI):

- Paleta pastel por sala: matiz base sorteado (esquema análogo), saturação
  média, luminosidade alta (conversão HSL→RGB própria).
- Pisos com cantos arredondados por sala e textura sutil (xadrez/sprinkles de
  baixo contraste por célula).
- Paredes como faixas arredondadas com sombra suave e "tampa" mais clara
  (leitura top-down).
- Props decorativos seedados (flores, estrelas, corações, arbustos) desenhados
  com primitivas, posicionados por grade jittered evitando raio dos pontos de
  gameplay.
- Limiar de porta nas células corredor↔sala (faixa contrastante, como hoje).

### 3. Script de assets — `scripts/build_lab_map.py` (reescrever como wrapper fino)

Mantém o nome (CI invoca `build_lab_map.py --check`). Seed padrão fixa
(constante documentada) + flag `--seed N`. Regenera `lab.json` (via
`to_tiled_json`), `lab_scene.png`, `lab_menu.png`, `overlay-lab.png`;
`--check` com a mesma comparação byte-a-byte/pixels. O tileset "Top Down Lab"
deixa de ser usado pela cena (arquivo permanece em `models/`, sem custo).
README: atualizar a seção de geração de mapa.

### 4. Protocolo e config

- `protocol.py`: `StartGame` ganha `map_seed: int`; constraint
  `ProtocolVersion` para `le=3`; `config.py`: `PROTOCOL_VERSION = 3`;
  `GameConfig.map_seed: int | None = None` + `--seed` no CLI do servidor
  (`server.py` main, ao lado de `--map`).
- `map_name`: gerador emite nome derivado da seed (ex.: `mapa-<seed>`),
  preservando o campo.

### 5. Servidor — geração por partida (`net/server.py`)

- `__init__`: gera o mapa inicial via `generate_map(config.map_seed or
  seed_aleatória)` substituindo `load_map(...)`; `_flat_walls` como hoje.
- `_start_game`: sorteia a seed da partida (`config.map_seed` fixa se
  configurada — caminho de teste/demo — senão `random.SystemRandom`); se
  houver partidas subsequentes no mesmo processo, regenera `self._game_map`,
  `self._flat_walls`, `self._state.tasks`; **move a atribuição de posições de
  spawn do `_on_join` para aqui** (round-robin pelos `spawn_points` do mapa
  gerado — seguro: lobby não transmite posições). Envia
  `StartGame(map_name=..., map_seed=seed, ...)`.
- `_on_join`: posição inicial passa a ser o primeiro spawn do mapa corrente
  (cosmético).

### 6. Cliente (`ui/render.py`, `ui/app.py`)

- `Renderer.__init__`: aceita `scene: pygame.Surface | None = None`; `None` →
  fallback ao `lab_scene.png` commitado (menus continuam funcionando).
- `app.py` handler de `StartGame`: `self.game_map =
  generate_map(message.map_seed)`; reconstruir `Renderer(game_map,
  scene=render_scene(game_map, message.map_seed))` e `Camera2D` com os novos
  bounds; `_camera_needs_snap = True` (já existe).

### 7. Testes

- `tests/test_map_generator.py` (novo): gates sobre amostra fixa de seeds;
  **determinismo** (mesma seed → mesma geometria); **distinção** (seeds
  diferentes → layouts diferentes); cobertura de `TASK_TYPES`; distribuição.
- `tests/test_lab_map.py`: manter validando o asset commitado (seed padrão)
  via loader — sem mudança conceitual.
- Protocolo/framing: roundtrip de `StartGame` com `map_seed`; versão 3 aceita,
  2 rejeitada.
- Integração (`test_ws_integration.py` ou smoke): servidor com seed fixa;
  cliente aplica a seed do `StartGame` e a geometria resultante é idêntica à
  do servidor (hash de paredes/tarefas) — valida determinismo **entre
  processos**.
- `test_visual_regression.py`: regenerar baselines (mudança intencional de
  arte — procedimento já documentado no próprio teste).
- Atualizar testes que construíam `StartGame(map_name=...)`.

## Riscos e decisões

- **Determinismo servidor↔cliente é o invariante central**: geometria só com
  `random.Random(int)` e iteração ordenada; o teste de integração
  cross-processo é o gate que o protege. Python pinado 3.13 em
  `.python-version`, então `random` é estável entre as partes.
- **Pixels da cena entre plataformas** (CI roda ubuntu+windows): mitigado
  restringindo a cena a `pygame.draw`; o `--check` compara RGB decodificado,
  já imune a encoder. Risco residual aceito: se algum primitiva divergir entre
  SDLs, o gate de frescor acusa — tratar se aparecer.
- **Custo de geração no start**: orçamento <1 s (geração + render de
  4480×2432). Medir; se exceder, otimizar o render (cache por tile).
- **PCGML/GAN descartados**: sem dataset, quebrariam determinismo leve e
  adicionariam dependências pesadas — o generate-and-test construtivo com
  gates fortes é o estado da arte aplicável a este projeto.
- Mapa por seed muda a cada partida: **rejoin mid-game não é afetado** (mapa
  regenerado só em `_start_game`; partida em andamento usa o mapa em memória).

## Verificação

1. `uv run ruff check . && uv run ruff format --check .` e `uv run mypy .`.
2. `uv run pytest` com `SDL_VIDEODRIVER=dummy` — suíte completa verde.
3. `uv run python scripts/build_lab_map.py --check` — gate de frescor.
4. `uv run python scripts/smoke_multiplayer.py` — E2E.
5. Aceite: seeds 1 e 2 produzem overlays visualmente distintos, fofos e
   navegáveis; servidor com `--seed 42` gera geometria idêntica em duas
   execuções.
