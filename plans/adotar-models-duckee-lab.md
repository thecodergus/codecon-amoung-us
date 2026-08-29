# Adotar models/duckee + models/mapa e reformar a UI

## Objetivo

1. O mapa do jogo passa a ser a **cena do lab** (`models/mapa`, "Top Down Lab" de
   ansimuz): mundo 1280×704 (cena 20×11 tiles de 16px, escalada ×4 → tile 64px),
   com colisão/spawns/tarefas extraídos da cena por script.
2. Personagens passam a usar os **sprites duckee** (`models/duckee`, 8 cores,
   animações idle/walk/death).
3. UI reformada: menus com tema customizado, HUD inferior (papel, tarefas,
   vivos, dica), votação em cards, game over e erro estilizados.

## Contexto confirmado

- Renderer atual é flat (retângulos/círculos): `ui/render.py` (paleta + `Button`
  + `Renderer.draw_map/draw_players/draw_bodies/draw_hud`); `ui/app.py` desenha
  HUD como texto no topo, votação como lista de botões, gameover/erro mínimos.
- Mapa atual: `assets/maps/skeld.json` (40×30 tiles de 32px = 1280×960),
  carregado por `map/loader.py` (exige layers `floor`, `walls`, `spawn_points`,
  `task_points`; opcionais `emergency_meeting`, `decorative`) → `GameMap`.
  `config.py` `DEFAULT_MAP_RELPATH = "maps/skeld.json"`; servidor usa
  `map_name = game_map.name` (stem do arquivo).
- Assets:
  - `models/duckee/{8 cores}/individual_animations/{idle,walk_run,death}/png_sequence/duckee_*.png`
    — frames 64×64 (idle: 4, walk_run: 4, death: 1).
  - `models/mapa/Top Down Lab files/` — `Tileset.png` 240×176 (15×11 tiles de
    16px), `previews/preview.png` 321×176, `previews/preview-export-x9.png`
    2568×1408, `aseprite-file.ase`, `public-license.txt`. **Não há arquivo
    Tiled** — a cena existe só como render PNG.
  - Histograma do preview (preview.png): fundo preto (39%), chão teal escuro
    `004040`/`206060`/`062C31` (39%), paredes azul-acinzentado
    `606080`/`3A3A5A`/`202040`/`283962`/`3D5772`/`404060` (16%), objetos
    `806000`/`00A080`/`6D9CCD`/`FFFCFF`/`A4AEC1` (6%).
- Protocolo: `SnapshotBody` carrega `player_id` → corpos usam a cor do morto;
  `SnapshotPlayer` carrega `nickname`. Sem cor no protocolo → mapeamento local
  `player_id % 8`.
- Testes dependentes do layout skeld: `test_map_loader.py` (nome/tamanho/16
  paredes/4 spawns/5 tarefas/emergency 640,480/bounds); `test_integration.py`
  (`start.map_name == "skeld"`; `_move_to_point` com waypoint (640,400);
  `test_emergency_meeting_requires_proximity` spawn (500,400) vs botão
  (640,480)); `test_protocol.py:61` literal "skeld";
  `scripts/smoke_multiplayer.py` waypoint (640,400).
- Física: `max_movement_step = 8.0` (subpasso anti-tunelamento). Paredes do lab
  têm ~4-8px mundo → reduzir para 2.0 + dilatar paredes na extração.
- Gotcha dos testes de UI: ciclos `pygame.quit()→init()` corrompem o cache de
  fontes do pygame-menu (segfault) — não introduzir quit/init nesses testes.
- Modelo sem suporte a imagem: extração da cena e seleção de cores são
  programáticas com gates quantitativos; QA visual é humana (overlay gerado).

## Etapas

### 1. Script de extração da cena → `assets/maps/lab.json`

`scripts/build_lab_map.py` (utilitário commitado, reexecutável, sem novas
dependências — usa pygame para ler pixels):

1. Carregar `models/mapa/Top Down Lab files/previews/preview.png` (321×176);
   detectar e cortar a margem/borda de 1px se houver → grade alinhada a tiles
   de 16px (20×11).
2. Classificar pixels por cor (constantes no topo do script, tolerância RGB):
   - `WALL`: família azul-acinzentado + pretos adjacentes (contorno);
   - `FLOOR`: teal escuro;
   - `OBJECT` (decorativo, não-colidível): âmbar/verde/claro.
3. Paredes: runs de WALL agrupados em rects (merge com gap ≤1px), dilatação de
   1px (espessura mínima ~8px mundo). Chão: rect único (o fundo é a imagem).
   Decorativos: rects de OBJECT (layer `decorative`).
4. Gameplay em pontos validados walkable (BFS pelo chão menos paredes):
   4 spawns distantes entre si; 5 tarefas (wires, swipe_card, fix_wiring,
   calibrate, clean_filter — mesmos tipos); `emergency_meeting` no centro da
   maior região de chão com `interaction_radius` 25.
5. Emitir `assets/maps/lab.json` no mesmo schema do skeld.json (object layers
   `floor`, `walls`, `spawn_points`, `task_points`, `emergency_meeting`,
   `decorative`; `tilewidth/tileheight = 64`, `width=20`, `height=11`,
   coordenadas ×4 da grade de 16px) — loader e domínio não mudam.
6. Gates (exit ≠ 0 se falhar): BFS conecta cada spawn a cada tarefa e ao
   emergency; nenhum gameplay point dentro de parede; paredes com
   width/height ≥ 4; contagens (4 spawns, 5 tarefas, ≥10 paredes); linha reta
   livre do hub até cada tarefa (para os testes de navegação). Escrever
   `models/mapa/overlay-lab.png` (cena + rects de parede em magenta + marcadores)
   para QA humano.

### 2. Config

`config.py`: `default_models_dir()` (override `CODECON_AMONG_US_MODELS_DIR`,
fallback `<repo>/models`); `DUCKEE_DIRNAME = "duckee"`;
`DEFAULT_MAP_RELPATH = "maps/lab.json"`; `GameConfig.max_movement_step = 2.0`.
Manter `skeld.json` no repo (loader continua suportando); atualizar help do CLI
`--map` em `net/server.py` ("default: lab").

### 3. Testes/smoke dependentes do layout (checkpoint verde com renderer antigo)

- `tests/test_map_loader.py`: asserções para o lab (nome "lab", 20×11, tile 64,
  bounds (0,0,1280,704), 4 spawns ids [0..3], 5 tarefas com os 5 tipos e raio
  20, emergency com raio 25, ≥10 paredes, 1 floor rect). Testes de erro
  intactos.
- `test_protocol.py:61` e `test_integration.py:125,159`: `"skeld"` → `"lab"`.
- `test_integration.py`: `_move_to_point` deriva o hub do mapa carregado
  (`emergency_meeting` com fallback `spawn_points[0]`); waypoints = [hub,
  destino]. `test_emergency_meeting_requires_proximity` usa coordenadas reais
  do lab.
- `scripts/smoke_multiplayer.py`: waypoint derivado do mapa carregado.

Checkpoint: `ruff check . && ruff format --check . && mypy . && pytest` verdes
com o renderer antigo (mapa já é o lab).

### 4. Sprites duckee + renderização do jogo

- `ui/sprites.py`: `DUCKEE_COLORS` (8 cores), `color_for(player_id)`; classe
  `DuckeeSprites` carrega `individual_animations/{idle,walk_run,death}/png_sequence`
  para cada cor, com `convert_alpha()` (fallback `convert()`), 64px nativo;
  API `frame(color, anim, index, flip_x)` e `anim_frames(color, anim)`.
- `Renderer`: pré-renderiza o fundo (cena do lab escalada para 1280×704) no
  `__init__`; `draw_map` blita o fundo + marcadores de tarefa (âmbar pulsante) e
  botão de emergência (anel vermelho pulsante); paredes não são desenhadas (a
  cena já mostra).
- `draw_players`: duckee animado (idle/walk por distância entre snapshots,
  flip por sinal do dx, timer via `pygame.time.get_ticks()`), nome com contorno
  acima, anel ciano no próprio jogador. `draw_bodies`: frame `death` da cor do
  morto (`body.player_id`) + X vermelho.
- `App`: rastrear `TaskState` (hoje ignorado) para o progresso de tarefas.

### 5. HUD + telas + menus

- HUD inferior (janela 1280×960; mapa 1280×704): chip de papel
  (TRIPULANTE/IMPOSTOR), dica de controles, "Tarefas X/Y" (de RoleAssigned +
  TaskState) e "Vivos N" (do snapshot).
- Votação: fundo da cena escurecido + painel; cards por votante (avatar duckee
  + nickname do snapshot; fallback P{id}), estado "votou", botão Skip, título
  com motivo e contagem regressiva.
- Game over: banner do vencedor + grade de papéis com avatar/nickname/papel.
- Erro: painel estilizado.
- Menus: tema customizado do pygame-menu (starfield procedural + acento
  laranja), **mantendo os mesmos widgets/atributos** usados pelos testes
  (`nickname_input`, `port_input`, `join_*`, `lobby_list_label`,
  `lobby_warning_label`).

### 6. README + verificação final

- `README.md`: mapa lab 20×11 tiles de 64px (1280×704), sprites duckee, UI;
  remover menções ao skeld como mapa único (skeld.json segue suportado).
- Verificação completa: `ruff check . && ruff format --check .`, `mypy .`,
  `pytest` (suíte completa), `uv run python scripts/smoke_multiplayer.py` (exit
  0), `build_lab_map.py` reexecutável e idempotente; sem TODOs/comentados/debug
  prints.

## Riscos e decisões

- **Extração por cor sem visão humana**: classificação com gates quantitativos
  (BFS, contagens, linha reta). Se uma classe ficar ambígua, iterar constantes
  até os gates passarem; se paredes internas bloquearem conectividade, reduzir
  paredes extraídas (manter borda + partições que não cortem o grafo).
- **Paredes finas vs anti-tunelamento**: `max_movement_step = 2.0` + dilatação
  de 1px.
- **Navegação reta dos testes**: hub = ponto validado walkable, sem coordenada
  mágica; gate de linha reta livre do hub até cada tarefa.
- **Mundo menor que a janela**: 1280×704 + barra HUD de 256px; sem câmera.
- **Escala do duckee**: 64px nativo (1 tile), sem redimensionamento.
- **Cor por `player_id % 8`**: sem mudança de protocolo; seletor de cor no
  lobby fora de escopo.
- **Licenças**: desconsideradas a pedido do usuário.