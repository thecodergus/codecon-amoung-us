# Plano — Mapa expandido + Câmera 2D

> Status: executado (2026-08-29). Fonte de verdade: código executável; este
> plano registra a estratégia aprovada. Desvio relevante: `blocked_rects`
> passou a cobrir todo o vazio (mundo hermético) em vez de apenas a
> vizinhança do caminhável — elimina bolsões "livres" inalcançáveis e torna
> o componente livre único.

## Objetivo

Substituir o mapa lab atual (1280×704, uma única cena) por um mapa de
2560×1408 com 7 salas, corredores em anel e validação por alcançabilidade
(BFS); e introduzir uma `Camera2D` cliente-only que segue o jogador local com
amortecimento exponencial dependente de `dt`, com clamp nos bounds do mapa,
sem tocar protocolo, servidor, votação ou UI/HUD.

## Contexto confirmado

- **Mapa/asset**: `assets/maps/lab.json` — 20×11 tiles de 64 px (1280×704);
  layers: `floor` (1 rect), `walls` (7 rects), `spawn_points` (4),
  `task_points` (5, raio 20), `emergency_meeting` (raio 25); `tilesets: []`.
  `GameMap.bounds()` deriva de `width*tile_width`
  (`src/codecon_amoung_us/map/model.py:84`). Background `lab_scene.png`
  (1280×704) blitado inteiro em `(0,0)`
  (`src/codecon_amoung_us/ui/render.py:94`). Nenhum gate de linha reta existe
  no código atual — a navegação dos testes já é BFS
  (`tests/test_integration.py:250`); o docstring do builder menciona linha
  reta mas está desatualizado.
- **Builder**: `scripts/build_lab_map.py` deriva a geometria do preview fixo
  321×176 — não gera mapa maior por construção. Gates atuais: componente ≥60
  células, pontos no componente, distância mínima, paredes válidas.
  Reutilizável: `largest_component` (BFS), `blocked_rects` (run-length merge),
  emissão do JSON Tiled.
- **Física/servidor**: colisão ponto-vs-rects com subpassos
  (`game/physics.py`); servidor faz clamp em `bounds()`
  (`net/server.py:918-920`) e spawns round-robin (`net/server.py:391`) — sem
  constantes de tamanho de mundo. `MAX_PLAYERS = 10` (`config.py:18`).
- **Render/App**: mundo == tela hoje. `WORLD_HEIGHT = 704` (`render.py:42`);
  canvas lógico 1280×768 (`app.py:108`); `_present` faz smoothscale+letterbox
  (`app.py:706-717`); `clock.tick(60)` tem retorno descartado (`app.py:677`);
  `_render_game` chama `draw_map/draw_bodies/draw_players/draw_hud`
  (`app.py:889-922`); votação também chama `draw_map` (`app.py:1001`). Menu
  usa `lab_scene.png` com smoothscale para 1280×768 (`app.py:183-193`).
- **Tileset**: `models/mapa/Top Down Lab files/Tileset.png` (240×176 = 15×11
  tiles de 16 px). Amostragem: linha 1 cols 1-8 = banda de maquinário cinza;
  linha 2 cols 1-8 = face frontal; linhas 4-9 cols 1-8 = piso teal (lisos e
  com faixa de segurança); vazio = preto.
- **Testes**: `test_map_loader.py` fixa dims 20×11, bounds (0,0,1280,704), 4
  spawns, 5 tarefas — precisará de atualização. `test_ui_events.py` usa
  `spawn_points[0]` vs `task_points[0]` (depende só de distância mínima).
  `test_integration.py` e `smoke_multiplayer.py` navegam por BFS derivado do
  mapa — agnósticos de layout. `test_physics.py` usa paredes sintéticas.
- **Pygame 2.6.1** (docstrings confirmadas): `Clock.tick(60)` retorna ms;
  `Surface.blit(source, dest, area=...)` desenha sub-região; `Rect.clamp`
  existe; `Vector2.lerp` existe.

## Decisões de design

1. **Opção A** — manter `GameMap + object layers + background
   pré-renderizado`. O builder passa a ser dirigido por layout (salas +
   corredores em grade) em vez de derivado do preview; a cena 2560×1408 é
   composta deterministicamente a partir do `Tileset.png`. Colisão vem do
   JSON, nunca da imagem.
2. **Dimensões**: 40×22 tiles de 64 px = 2560×1408 (4× a área; câmera
   desloca 1280 px em X e 704 px em Y).
3. **Salas explícitas**: object layer `rooms` no `lab.json` (rects nomeados),
   carregada como `GameMap.rooms: list[Room]` (opcional no loader —
   `skeld.json` continua válido).
4. **Câmera**: módulo novo `ui/camera.py`, sem pygame (floats puros).
   Estado em float; `offset()` inteiro puro derivado do estado.

## Etapas

### 1 — Modelo e loader: salas

- `map/model.py`: `Room(name, rect)` + `GameMap.rooms` com
  `field(default_factory=list)`.
- `map/loader.py`: object layer opcional `rooms` (rectangles; `name` →
  `Room.name`; ausência → `[]`).

### 2 — Reescrita do builder (`scripts/build_lab_map.py`)

Contrato mantido: determinístico, idempotente, exit≠0 se gate falhar, só
pygame.

- **Layout declarado** (grade 40×22, `_TILE=64`): 7 salas — `medbay`
  (3,3,8×5), `reator` (3,14,8×5), `eletrica` (29,3,8×5), `armazem`
  (29,14,8×5), `laboratorio` (16,2,8×4), `analise` (16,16,8×4), `hub`
  (16,9,8×5) com o botão — mais corredores em anel + radiais ao hub (≥1 ciclo
  no grafo sala↔corredor). Caminhável = união dos rects.
- **Geometria**: walls = células não-caminháveis adjacentes, merge
  run-length parametrizado para 40×22. floor = 1 rect; decorative = vazio.
- **Pontos autorados**: 10 spawns (`MAX_PLAYERS`) hub+salas; ~10 tarefas
  (≥1 por sala não-hub, 5 tipos ciclando, raio 20); emergência no centro do
  hub (raio 25).
- **Gates (BFS)**:
  - mundo > viewport em X e Y; área ≥ 2× 1280×704;
  - ≥6 salas, interior majoritariamente caminhável;
  - caminhável = componente único (BFS 4-vizinhança);
  - spawns/tarefas/emergência caminháveis, fora de paredes, mutuamente
    alcançáveis;
  - ≥10 spawns; tarefas em ≥4 salas;
  - distância ≥1,5 célula entre pontos; ≥2 células spawn↔emergência;
  - grafo sala↔corredor com ≥1 ciclo;
  - paredes ≥3 e não degeneradas.
- **Cena** (`lab_scene.png` 2560×1408): cada célula 64 px = 4×4 tiles de 16
  px. Caminhável → piso teal (variante `(x+y) mod n`); porta → faixa de
  segurança; parede com vizinho caminhável ao sul → maquinário (linha 1) +
  face (linha 2); demais → preto. Índices partem das linhas amostradas;
  ajuste visual dentro dessas linhas.
- **Saídas**: `assets/maps/lab.json` (com `rooms`),
  `assets/maps/lab_scene.png`, `assets/maps/lab_menu.png` (crop 1280×704 do
  hub), `models/mapa/overlay-lab.png`.

### 3 — `Camera2D` (`src/codecon_amoung_us/ui/camera.py`, novo)

- Sem pygame, floats puros. `viewport_size` (1280×704), `bounds`,
  centro x/y float, `follow_rate = 8.0`, `DT_MAX = 0.1` s.
- `snap_to(cx, cy)`: posiciona clampado (sem travelling).
- `update(target_xy, dt)`: `dt = min(dt, DT_MAX)`; alvo clampado a
  [vw/2, right−vw/2] por eixo (eixo ≤ viewport → centro fixo);
  `alpha = 1 − exp(−follow_rate·dt)`; `pos += (alvo − pos)·alpha`.
- `offset() -> (int, int)`: `(round(cx − vw/2), round(cy − vh/2))` — puro.
- `world_to_screen` / `screen_to_world`: `p ∓ offset`.

### 4 — Renderer (`src/codecon_amoung_us/ui/render.py`)

- `draw_map(surface, camera, markers=None)`, `draw_players(surface, camera,
  players, me_id, *, nicknames=None)`, `draw_bodies(surface, camera, bodies)`.
  `draw_hud` inalterado.
- `draw_map`: `surface.blit(bg, (0,0), area=Rect(ox, oy, 1280,
  WORLD_HEIGHT))`; marcadores/emergência via `world_to_screen` + culling.
- players/bodies: mesma transformação centralizada; culling.
- fallback de background usa `game_map.width*tile_width` ×
  `game_map.height*tile_height`.
- `WORLD_HEIGHT` permanece (altura do viewport de gameplay).

### 5 — App (`src/codecon_amoung_us/ui/app.py`)

- `__init__`: `self.camera = Camera2D(viewport_size=(WINDOW_W, WORLD_HEIGHT),
  bounds=self.game_map.bounds())`; `self._dt = 1/60`;
  `self._camera_needs_snap = True`.
- `run()`: `self._dt = self.clock.tick(60) / 1000.0`.
- `_render_game`: `me` presente → snap na primeira vez, senão
  `camera.update((me.x, me.y), self._dt)`; passa `self.camera` aos draws.
  Reset do snap em `StartGame` e em `_exit_to_main`. Câmera segue `me`
  também morto (posição no snapshot).
- `_render_voting`: `draw_map(self.screen, self.camera, markers)`.
- `_menu_theme`: preferir `lab_menu.png`, fallback `lab_scene.png`.

### 6 — Testes

- `tests/test_camera.py` (novo): centralização; clamp esquerdo/superior e
  direito/inferior; snap sem travelling; suavização monótona sem overshoot
  com convergência; independência de FPS (30/60/120 Hz, tolerância ~2%);
  roundtrip world↔screen.
- HUD fixo (SDL dummy): dois offsets de câmera → faixa
  `Rect(0, 704, 1280, 64)` pixel-idêntica.
- `tests/test_map_loader.py`: novo baseline — 40×22, bounds
  (0,0,2560,1408), 10 spawns `[0..9]`, ≥8 tarefas com 5 tipos, raio 20,
  `len(rooms) >= 6`; manter floor==1, decorative==0, erros de arquivo/layer.
- `tests/test_lab_map.py` (novo): gates estruturais contra o asset — mundo >
  viewport; área ≥2×; componente único; todo spawn alcança toda tarefa e a
  emergência; nenhum ponto em parede; ≥`MAX_PLAYERS` spawns; tarefas em ≥4
  salas.
- Nenhum teste existente removido; apenas constantes do baseline antigo
  substituídas.

### 7 — Integração, regressão e QA

- Builder + `uv run ruff format --check .` + `uv run ruff check .` +
  `uv run mypy` + `uv run pytest` +
  `uv run python scripts/smoke_multiplayer.py`.
- QA visual headless: `uv run python scripts/capture_ui_states.py` +
  inspeção de capturas e overlay.
- Perf: nenhuma surface grande criada/escalada por frame.

## Riscos e decisões

- **Qualidade visual da cena composta** (maior risco): tabela de tiles
  derivada por amostragem de cor. Mitigação: regras restritas às linhas
  identificadas + overlay + capturas; colisão independe da imagem. Fallback
  documentado: retângulos da paleta do pack.
- **Suposição**: câmera segue o jogador local também morto/fora de reunião;
  durante votação o mapa fica congelado sob o overlay.
- **Suposição**: 40×22/7 salas é o baseline; qualquer layout que passe nos
  gates é aceitável.
- **`lab_menu.png`**: novo asset (crop do hub); fallback para
  `lab_scene.png` mantém o menu funcionando.
- **Contradição resolvida**: docstring do builder cita linha reta, código
  não tem; spec manda BFS — docstring atualizado.
- **`skeld.json`** permanece carregável (`rooms` opcional).

## Gates

| Gate                    | Comando                                                      |
| ----------------------- | ------------------------------------------------------------ |
| Builder + gates de mapa | `uv run python scripts/build_lab_map.py` (exit 0)            |
| Lint/format             | `uv run ruff format --check . && uv run ruff check .`        |
| Tipos (strict)          | `uv run mypy`                                                |
| Suíte completa          | `uv run pytest`                                              |
| Smoke multiplayer       | `uv run python scripts/smoke_multiplayer.py`                 |
| QA visual               | `uv run python scripts/capture_ui_states.py` + inspeção      |
