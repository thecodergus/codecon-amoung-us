# Plano: mundo triplicado + 7 minigames obrigatórios

Status: em execução (build agent, 2026-08-30).

## Objetivo

1. **Triplicar o mundo jogável**: grade ~70×38 células de 64 px (mundo ~4480×2432,
   ≈3× a área atual de 2560×1408), mantendo densidade ~42% → ~1100 células
   caminháveis (~3× o baseline medido de 370 células / 1.515.520 px²).
2. **7 minigames obrigatórios**: completar tarefa deixa de ser instantâneo (tecla E)
   e passa a abrir um puzzle modal por tipo de tarefa. Servidor e protocolo **não
   mudam** — o `TaskActionRequest` existente é enviado só após o jogador resolver o
   puzzle client-side.
3. **Signifiers acessíveis**: marcadores de tarefa distinguíveis por forma/glifo,
   não só por cor.

Suposição declarada: "triplicar o mundo" = ~3× a área total mantendo a proporção
(70×38 = 3,02× as 880 células). Se a intenção era 3× por dimensão (9× área), basta
ajustar `_MAP_W`/`_MAP_H` no builder — o restante do plano é invariante.

## Contexto confirmado

- `TaskInfo.task_type: str` (protocol.py:136); `task_type` é string livre em toda a
  cadeia (game/model.py:78, map/model.py:61, map/loader.py:110) — 2 tipos novos não
  exigem bump de protocolo. `TaskState`/`RoleAssigned.task_ids` max 32.
- Servidor já valida `complete_task` (game/rules.py: vivo + atribuída + não feita +
  distância ≤ raio); server.py `_on_task` broadcasta `TaskState` por jogador.
- scripts/build_lab_map.py: grade 40×22 (`_MAP_W`/`_MAP_H`), 7 salas, 8 corredores,
  `_TASK_TYPES` 5 tipos, gates embutidos + `--check` (CI), importa do pacote
  (`codecon_amoung_us.config`). Emite lab.json + lab_scene.png + lab_menu.png
  (crop 1280×704 do hub) + overlay-lab.png, determinístico.
- Dims 2560×1408 fixas apenas em testes: test_camera.py, test_map_loader.py,
  test_visual_regression.py (`_POSITIONS`). Camera2D recebe bounds dinamicamente.
- UI: precedente de overlay modal = votação (overlay SRCALPHA + painel centrado);
  app.py `_render_game`/`_handle_game_key`; marcadores em render.py
  `_draw_task_marker` (hoje quase só cor) + viewmodel.py `derive_task_markers`;
  regressão visual força `reduced_motion` e ticks fixos.
- `assign_tasks` dá `min(2, len)` tarefas por tripulante (game/tasks.py) — mantido.
- skeld.json é asset legado (só citado em comentários); DEFAULT_MAP=maps/lab.json.
- Pesquisa aplicada: dificuldade mensurável por parâmetros explícitos
  (Xiao & Yang 2025); feedback multimodal/progressão estruturada (Kamath et al.
  2025); não depender só de cor (Game Accessibility Guidelines / Xbox AG);
  signifiers/affordances (Norman).

## Fases

### Fase A — Catálogo de tarefas (domínio)

1. Novo `src/codecon_amoung_us/game/task_catalog.py`: `TASK_TYPES` canônico (7:
   wires, fix_wiring, swipe_card, calibrate, clean_filter, start_reactor, asteroids)
   + `TASK_DIFFICULTY` (dataclass frozen `DifficultyParams`: estimated_seconds,
   targets, speed) — dificuldade mensurável e ajustável num único lugar. Sem UI.
   Teste: tests/test_task_catalog.py (7 tipos únicos, dificuldade para todo tipo).

### Fase B — Mapa triplicado

2. Builder: `_MAP_W`/`_MAP_H` → 70×38; `_TASK_TYPES` passa a importar `TASK_TYPES`
   do catálogo (fonte única); `_ROOMS` 7 → 12–14 salas (anel + raios ao hub,
   mantendo ciclo); `_TASKS` 10 → 14 (2 por tipo, ≥6 salas); `_SPAWNS` ≥ 10;
   gates recalibrados (mundo ≥ 6× `_OLD_AREA`, células caminháveis ≥ 1000,
   salas ≥ 10, tarefas em ≥ 6 salas; manter BFS, alcançabilidade, distâncias,
   ciclo, paredes herméticas).
3. Regerar assets commitados (lab.json, lab_scene.png, lab_menu.png,
   overlay-lab.png); `--check` verde em seguida.
4. Atualizar testes dependentes de dimensão: test_lab_map.py (gates espelhados),
   test_map_loader.py (bounds), test_camera.py (BOUNDS/cantos),
   test_visual_regression.py (`_POSITIONS` + baselines via UPDATE_BASELINES=1).

### Fase C — Framework de minigames + integração modal

5. Novo pacote `ui/puzzles/`: `base.py` com `Minigame` (handle_event, update, draw,
   `done`) + factory `create_minigame(task_type, task_id, *, seed)`. Lógica pura
   separada da renderização (testes headless com eventos sintéticos). Respeitar
   `motion.reduced_motion`; reutilizar theme/fonts; painel padrão do overlay de
   votação. Tipo desconhecido → erro explícito.
6. app.py: `self._active_puzzle`; `K_e` em tarefa interagível abre overlay (em vez
   de completar); input vai ao puzzle; WASD bloqueado; mundo segue ativo (jogador
   vulnerável); morte/reunião/fim fecham overlay sem completar; ESC abandona
   (progresso perdido); `done` → `client.complete_task(task_id)`. Prompt da tecla E
   passa a "iniciar tarefa".

### Fase D — Os 7 minigames (paralelizável após etapa 5)

Cada um: lógica pura + draw + parâmetros de `TASK_DIFFICULTY` + teste headless
(vitória, falha/reset, determinismo por seed). Feedback por forma+animação+texto.

7. **wires** — 4 fios coloridos esq→terminais embaralhados dir; arrastar pares.
8. **fix_wiring** — Lights-Out 3×3 (clique alterna célula+vizinhos); estado inicial
   gerado da solução via seed (solubilidade garantida).
9. **swipe_card** — indicador varre a fenda; pressionar na zona-alvo; 3 tentativas
   com feedback "rápido/lento demais".
10. **calibrate** — 3 anéis, agulha rotativa em velocidades crescentes; clicar na
    zona marcada; erro reinicia o anel atual.
11. **clean_filter** — arrastar N detritos para fora do painel.
12. **start_reactor** — Simon-says 3×3, sequência de 4–5 pads; erro reexibe.
13. **asteroids** — destruir K asteroides clicando antes que saiam do painel
    (respawn até cumprir a cota).

### Fase E — Signifiers de marcadores

14. render._draw_task_marker + viewmodel: forma por estado além de cor —
    ASSIGNED=losango contorno; NEAR=losango+anel; INTERACTABLE=losango preenchido
    pulsante + glifo "!"; DONE=check (manter); UNASSIGNED invisível. Paleta
    Okabe-Ito; pulso desligado sob reduced_motion. Testes de viewmodel + baselines.

### Fase F — Fechamento

15. Docs: atualizar descrições do fluxo instantâneo (README/seções de gameplay, se
    existirem); docstring do builder na etapa 2.
16. Validação integrada (ver abaixo) + commits por fase (conventional, sem push).

## Riscos e decisões

- Protocolo/servidor intocados (RECOMENDADO): projeto já confia no cliente para
  posições; anti-cheat de tempo mínimo seria escopo novo (só faz sentido com
  partidas públicas competitivas).
- ESC abandona o puzzle e perde progresso (RECOMENDADO): fiel ao Among Us; salvar
  estado por tarefa seria complexidade sem pedido.
- Puzzle não pausa o mundo: loop de eventos de servidor segue ativo com overlay
  aberto (morte/reunião fecham o overlay) — mesmo padrão da votação.
- Solubilidade por construção: puzzles procedurais (fix_wiring, start_reactor)
  geram estado a partir da solução via seed.
- Som: não verificado se o projeto tem áudio (DESCONHECIDO); plano não promete
  feedback sonoro — forma+texto+animação bastam.
- 7 minigames é a maior fatia: arquitetura permite entrega em lotes (factory falha
  explicitamente para tipo não implementado), mas o critério de pronto são os 7.
- Regressão visual muda por 3 causas (mapa, marcadores, prompts): regerar baselines
  uma única vez ao final.

## Verificação

1. `uv run ruff check --fix . && uv run ruff format .` — zero erros.
2. `uv run basedpyright .` — strict verde.
3. `uv run pytest -v` — suíte completa (novos: catálogo, factory, 7 minigames;
   atualizados: mapa, loader, camera; integração existente inalterada).
4. `python scripts/build_lab_map.py --check` — assets frescos e determinísticos.
5. Baselines: regerar com UPDATE_BASELINES=1, re-rodar sem a flag — estável.
6. Smoke manual recomendado: partida local — E abre puzzle, resolver completa e
   avança HUD; ESC abandona sem completar.
