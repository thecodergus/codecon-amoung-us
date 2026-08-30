# Estações de tarefa como objetos, mais estações e animação fluida

Plano aprovado em 2026-08-30 (decisões do usuário: 28 estações = 4 por tipo;
raio de interação "bem maior" com assets construídos de bom design; 6 tarefas
por tripulante; tipo da animação como `enum.StrEnum`).

## Objetivo

1. Mapa com **28 estações de tarefa** (4 instâncias de cada um dos 7 tipos —
   tipos se repetem, como hoje), raio de interação generoso.
2. Estações renderizadas como **objetos reais por tipo de tarefa** (asset
   próprio, coerente com o pack ansimuz) — nunca mais pontos/losangos — com
   signifiers de interatividade claros e separáveis por luminância/geometria
   (CVD). Botão de emergência idem (pedestal + botão, não círculo vermelho).
3. **6 tarefas por tripulante** (hoje 2).
4. Animação de andar **fluida** e transição idle→walk **sem salto**: hoje a
   detecção de movimento pisca (snapshots a 20 Hz vs render a 60 fps) e o
   frame vem de um relógio global compartilhado.

## Contexto confirmado

- **Mapa**: `scripts/build_lab_map.py` — `_TASKS` (14 células) vira
  `task_points` no `lab.json` com `task_type = TASK_TYPES[index % 7]`
  (round-robin) e `interaction_radius = 20.0`. Gates de validação (≥1,5
  célula entre pontos, ≥6 salas, alcançabilidade BFS) em `validate()`. CI tem
  gate de frescor: `build_lab_map.py --check` (job `assets-freshness`).
- **Células novas verificadas** contra as funções reais do builder: todas no
  caminhável, ≥1,5 célula de qualquer ponto, 11 salas cobertas (hub sem, por
  ser área de reunião).
- **Marcadores atuais**: `render.py` `_draw_task_marker` desenha losangos
  amarelos pequenos (7-14 px) por estado; emergência é círculo vermelho +
  anel. `TaskMarkerView` não carrega `task_type` — pré-requisito para desenhar
  objeto por tipo.
- **Animação**: `render.py` `draw_players` — `moving` = delta de posição
  entre frames de render consecutivos; posições só mudam a 20 Hz (snapshot) e
  o render roda a 60 fps → ~2/3 dos frames têm delta 0 → idle/walk piscando.
  Frame index = relógio global (`pygame.time.get_ticks`), todos os jogadores
  em lockstep e fase arbitrária na troca de anim.
- **Verificação do projeto**: `uv run ruff check .` / `ruff format --check .`,
  `uv run mypy .` (strict, src+tests), `uv run pytest` (com `--cov`),
  `scripts/build_lab_map.py --check`, `scripts/smoke_multiplayer.py`,
  baselines visuais (`UPDATE_BASELINES=1`), `test_marker_cvd.py`
  (distinguibilidade CVD por estado de marcador), `test_visual_regression.py`.

## Etapas

### Etapa 1 — Mapa: 28 estações + raios de interação

- `scripts/build_lab_map.py`: append de 14 células em `_TASKS` (preserva ids
  1-14 e tipos atuais; loader atribui `task_id = index+1`):

  ```
  (6,16), (10,18),   # seguranca
  (61,16),           # oxigenio
  (26,32),           # analise
  (60,4), (53,7),    # navegacao
  (56,31),           # motores
  (34,29),           # armazem
  (9,28), (12,29),   # reator
  (64,32), (61,33),  # comunicacao
  (38,8), (33,5),    # eletrica
  ```

  → 28 pontos; `index % 7` dá exatamente 4 instâncias por tipo.
- `interaction_radius`: 20.0 → **56.0** nas tarefas (o servidor usa o raio do
  mapa automaticamente — `rules.can_complete_task`; sem mudança no domínio).
- Botão de emergência: raio 25.0 → **44.0** (objeto novo maior).
- Regenerar: `uv run python scripts/build_lab_map.py` + `--check`. `lab_scene.png`/
  `lab_menu.png` não mudam de conteúdo (tarefas não são desenhadas na cena); `lab.json` e
  `overlay-lab.png` mudam.
- Testes: `tests/test_map_loader.py` (14 → 28; 20.0 → 56.0).

### Etapa 2 — Seis tarefas por tripulante

- `game/tasks.py`: `min(2, len(task_pool))` → `min(6, len(task_pool))` (o `min` protege fixtures com
  pools pequenos).
- `tests/test_integration.py` (`== 2` → `== 6`) e docstring de `assign_tasks`; varredura por
  asserts de contagem em tests/.

### Etapa 3 — Assets das estações (sprites por tipo)

- Novo `scripts/build_task_props.py`: gera `assets/tasks/<task_type>.png` (7 estações) +
  `assets/tasks/emergency.png`, canvas 64×64 px de mundo (grade 16×16 ×4, igual à cena),
  compondo tiles de maquinário do `Tileset.png` + detalhes pixel-art por tipo (fios, lâmpadas
  3×3, slot de cartão, gauges, pads 2×2, monitor com asteroide, filtro, totem de cartão,
  gauges, pads 2×2; emergência = pedestal + botão abobadado vermelho. Determinístico, só
  pygame, saída commitada em `assets/tasks/`, modo `--check` (padrão de frescor idêntico ao
  de `build_lab_map.py`).
- CI: `build_task_props.py --check` no job `assets-freshness`.
- Testes novos `tests/test_task_props.py`: determinismo, 8 sprites 64×64,
  tipos distintos entre si.

### Etapa 4 — Viewmodel: `task_type` no marcador

- `TaskMarkerView` ganha `task_type: str` (obrigatório, após `state`);
  `derive_task_markers` preenche com `point.task_type`.
- Atualizar construções em `tests/test_marker_cvd.py` e
  `tests/test_ui_components.py`.

### Etapa 5 — Render: estações como objetos + estados

- Novo `ui/task_props.py`: `load_task_props(assets_dir)` (7 tipos +
  `"emergency"`), variante dim pré-computada por sprite, `FileNotFoundError` se ausente.
- `render.py` `_draw_task_marker` (assinatura preservada — `test_marker_cvd.py`
  depende): sprite 64×64 centrado + overlays de estado **dentro dos 64 px**:
  UNASSIGNED dim/translúcido; ASSIGNED + tag amarela estática; NEAR + halo
  contornado; INTERACTABLE + halo preenchido pulsante (separável com
  pulse=0) + glifo "!" no canto; DONE dim + check verde.
- `draw_map` ganha `emergency_active: bool = False`; app calcula (jogador
  vivo dentro do raio) em `_render_game`; votação usa o default.
- Restrição CVD: cada par ASSIGNED/NEAR/INTERACTABLE/DONE diverge ≥20 px em
  luminância no crop 64 px sob os 3 déficits (gate existente).

### Etapa 6 — Animação: `PlayerAnim` StrEnum + máquina de estado + suavização

- `ui/sprites.py`: `class PlayerAnim(StrEnum): IDLE/WALK/DEATH`; `_ANIMATIONS`,
  `frame`/`frame_count` tipados com o enum (elimina literais em sprites/render/app).
- `render.py` `draw_players`: ganha `dt: float = 1/60` (keyword-only); estado
  por jogador `{render_x, render_y, last_tx, last_ty, moving_until_ms,
  clock_s, anim: PlayerAnim, flip}`; relógio interno do Renderer avança por
  `dt` (determinístico, sem `get_ticks`).
  - Histerese: mudança >0,5 px → `moving_until = now + 150 ms` (cobre 3
    períodos de snapshot) → sem flicker idle/walk.
  - Transição: entrar em WALK zera o clock (ciclo começa no frame 0);
    cadências atuais (walk 0,13 s; idle 0,42 s).
  - Suavização de posição: `alpha = 1 - exp(-14*dt)`; teleporte >96 px →
    snap; `reduced_motion` → sem suavização.
  - `app.py` passa `dt=self._dt`.
- Testes novos: parado → IDLE; movimento intercalado com frames parados →
  WALK contínuo; transição zera o clock; suavização converge, teleporte
  snapa; `reduced_motion` desativa suavização.

### Etapa 7 — Baselines, capturas e docs

- `UPDATE_BASELINES=1 uv run pytest tests/test_visual_regression.py` e commitar baselines
  (mudança de arte intencional, fluxo documentado no próprio teste).
- `scripts/capture_ui_states.py` → regenera `captures/`.
- README: 14→28 tarefas, `assets/tasks/` + `build_task_props.py`, 6 tarefas por tripulante.

## Riscos e decisões

- Assets construídos (não baixados): determinístico, sem licença nova, coerente com o tileset.
- Estações UNASSIGNED ficam visíveis (dim) como móveis do mundo; CVD pode exigir ajuste de
  contraste de estados (gate `test_marker_cvd.py` deve ficar verde, nunca desligado).
- Baselines quebram por design (arte nova) — regeneração faz parte do plano.
- Raio 56 px > kill radius (40 px): decisão aceita, ajustável no builder.

## Verificação

1. `build_lab_map.py --check` + `build_task_props.py --check` — sincronizados.
2. `uv run ruff check . && uv run ruff format --check . && uv run mypy .`.
3. `uv run pytest` — incluindo loader (28/56), lab_map, CVD, baselines,
   integração (6 tarefas), animação e props.
4. `uv run python scripts/smoke_multiplayer.py` — E2E multiplayer.
5. QA visual: `captures/game_crew.png` + inspeção dos objetos/estados.
