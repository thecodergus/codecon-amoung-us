# Plano — Redesign de UI/UX, correções de sigilo e feedback (codecon-amoung-us)

Data: 2026-08-29
Status: aprovado para execução
Origem: plano do usuário (redesign completo) validado contra o estado real do repositório

## 1. Resumo

Reexecutar o caminho crítico: **sigilo do protocolo → confirmação de ações →
tarefas → Ejected → design system → HUD/contexto → votação → responsividade →
acessibilidade → polish**. O servidor permanece autoritativo; domínio, mapa,
sprites Duckee e stack (pygame 2.6.1, msgspec, pytiled-parser, pygame-menu,
pytest/Hypothesis/ruff/mypy) são preservados. Sem novas dependências de runtime.

## 2. Contexto confirmado no código (evidência)

- `PROTOCOL_VERSION = 1` (`src/codecon_amoung_us/config.py:15`);
  `ProtocolVersion` constraint `ge=1, le=1` (`protocol.py:67`);
  `MeetingEnded` carrega `ejected: bool` (`protocol.py:198-200`);
  `dispatch.py:26` envia `ejected=outcome.ejected_id is not None` a todos;
  `Ejected(player_id, role)` existe (`protocol.py:203-207`).
- UI ignora `Ejected` (`app.py:357-358`) e `ActionDenied` fora do lobby
  (`app.py:367-371`).
- Voto otimista: `self.voted.add(self.my_id)` antes da confirmação
  (`app.py:585-591`).
- Sem interação de tarefa na UI (`_handle_game_key` só R/E/Space,
  `app.py:473-505`); `client.complete_task` existe (`client.py:157-160`) e o
  servidor **silencia** falha de tarefa (`server.py:525-552`).
- Sem cooldown visível: `SnapshotPlayer` não transporta cooldown; servidor
  responde `ActionDenied(reason="kill inválido")` genérico (`server.py:448-462`).
- Janela fixa 1280×960 (`app.py:63`), mundo 1280×704 (`render.py:40`),
  HUD = 256 px (`render.py:206-208`); branding no HUD (`render.py:254`).
- `Button` mínimo (`render.py:43-73`); cores planas `COLOR_*` (`render.py:24-37`);
  fontes: Open Sans nos menus (`app.py:117`), `Font(None, ...)` no gameplay.
- Todas as tarefas e o botão de emergência pulsam continuamente (`render.py:119-131`).
- Lobby é string (`app.py:413-418`); menus misturam idiomas; starfield via
  tempfile (`app.py:79-121`); conexão síncrona `connect(timeout=5.0)` no fluxo
  da UI (`app.py:227-267`).
- Gates: ruff `E,F,I,UP,B,SIM`; mypy strict (`files = ["src","tests"]`);
  pytest `--strict-markers --cov`; markers `slow/integration/ui`; timeout 15.
- Pontos de quebra do Protocol v2 (inventário): `test_protocol.py:43,77,138-140`;
  `test_framing.py:14,86-89`; `test_framing_properties.py:22`;
  `test_secrecy_properties.py:35-45`; `test_integration.py:518,528,534,552,800,826`;
  `smoke_multiplayer.py:283-284,295-296`; `test_ui_events.py:138`.
- Auditoria anterior (`plans/lacunas-pos-auditoria.md`) executada: 129 testes
  verdes; WASD na UI já corrigido (`_movement_direction` + `_handle_game_movement`).
- Repositório não é git repo (sem commits).

## 3. Blocos

### Bloco 0 — Baseline

Gates completos + smoke; registrar contagem/duração/saídas para comparação.

### Bloco 1 — Protocol v2 + sigilo de `MeetingEnded` (P0.1)

1. `config.py`: `PROTOCOL_VERSION = 2`.
2. `protocol.py`:
   - `ProtocolVersion` → `ge=1, le=2` (v1 decodifica; rejeição no servidor).
   - `MeetingEnded` → somente `meeting_id`.
   - Novos StrEnum: `ActionKind` (KILL, REPORT, TASK, EMERGENCY, VOTE, START_GAME)
     e `DenialCode` (OUT_OF_RANGE, COOLDOWN, INVALID_TARGET, ALREADY_DONE,
     NOT_ASSIGNED, ALREADY_VOTED, INVALID_PHASE, NOT_HOST,
     INSUFFICIENT_PLAYERS, NOT_ALIVE).
   - `ActionAccepted(action, cooldown_seconds=None)` — privada ao autor.
   - `ActionDenied(action, code, reason, retry_after_seconds=None)`.
   - União `Message` e `__all__` atualizados.
3. `dispatch.py`: `MeetingEnded(meeting_id=...)` para todos; `Ejected` antes,
   somente ao ejetado.
4. `server.py`: denials tipadas em todos os handlers (preservar substrings de
   reason assertadas: "kill", "alcance", "morto", "host"); `_on_kill` classifica
   COOLDOWN com `retry_after_seconds`; `ActionAccepted(KILL, cooldown_seconds)`
   após kill; `ActionAccepted(VOTE)` após voto; **`_on_task` deixa de silenciar**
   falha (ActionDenied TASK).
5. Testes: roundtrips v2; v1 rejeitada via wire (`bad_version`); framing v3
   inválido; sigilo reescrito (`{type, meeting_id}`); integração sem `.ejected`;
   bytes idênticos de MeetingEnded entre ejeção/empate/skip; smoke e README
   atualizados.

### Bloco 2 — Toasts + cooldown do impostor (P0.4, UI)

`Toast` não modal em `App`; `ActionDenied` fora do lobby → toast por `code`;
estado `kill_cooldown_until` alimentado por `ActionAccepted(KILL)` e
`ActionDenied(KILL, COOLDOWN, retry_after_seconds)`; testes.

### Bloco 3 — Interação contextual de tarefas (P0.3)

`ui/viewmodel.py` (novo, puro): `InteractionContext` + `derive_interaction_context`
(tarefa atribuída/incompleta no raio → TASK; corpo no raio → REPORT; botão de
emergência → EMERGENCY; sobreposição → mais próximo, desempate por task_id;
morto → None). `K_e` executa o contexto via `client.complete_task`/`emergency`.
Testes unit + evento E dentro/fora do raio.

### Bloco 4 — Ejeção privada + transições (P0.2, UI)

Estados `private_ejection`, `pending_game_over`, relógios de apresentação;
`Ejected` → tela EJECTED (duração mínima 2,5 s); `MeetingEnded` → transição
genérica MEETING_ENDED (1,2 s) idêntica para ejeção/empate/skip; `GameOver` →
pending; transições dirigidas por relógio no loop (sem `sleep()`). Telas em
`ui/screens.py`. Testes: ordens no mesmo drain.

### Bloco 5 — Design system (P1)

`ui/theme.py` (tokens semânticos, paleta preservada, `UiSettings.reduced_motion`);
`FontBook` (Open Sans via pygame-menu; sem `Font(None, ...)` em tela funcional);
`ui/layout.py` (`ViewportTransform` puro + `fit_viewport` letterbox + grids);
`ui/motion.py` (easing/lerp/durações FAST/NORMAL/EMPHASIS + reduced motion).
Testes de layout em 4 resoluções + roundtrip de coordenadas.

### Bloco 6 — Componentes + foco (P1)

`ui/components.py`: `ButtonState` (DEFAULT/HOVER/FOCUSED/PRESSED/SELECTED/
DISABLED/COOLDOWN), `Button` (sem regras do jogo, hover por eventos), 
`FocusManager` (Tab/Shift+Tab/Enter/Space/Escape), `Keycap`, `ProgressBar`,
`Toast`, `Modal`, `PlayerCard`, `ActionPrompt`. Alvo mínimo 40×40 px.
Testes por estado, foco, teclado, targets.

### Bloco 7 — View models + HUD + marcadores + ActionPrompt (P1)

`GameHudView`, `VoteView`, `LobbyView`, `GameOverView`, `TaskMarkerView` +
`derive_*` puras; HUD de ~64 px dirigido por viewmodel; `draw_map(markers)`
contextual (não atribuída discreta / atribuída estática / próxima highlight /
interagível pulse / concluída check); remover branding do HUD; cooldown
numérico + label (nunca só cor). Testes de viewmodel.

### Bloco 8 — Votação (P1)

`VoteUiState` (SELECTING/SUBMITTING/SUBMITTED), card inteiro selecionável,
`[PULAR] [VOTAR]`, SUBMITTING bloqueia duplo envio, `ActionAccepted(VOTE)` →
SUBMITTED "VOTO REGISTRADO", `ActionDenied` → SELECTING + toast; remover
`self.voted` otimista. Testes do fluxo visual.

### Bloco 9 — Lobby, Game Over, erros, menus, conexão assíncrona (P2)

Lobby custom com `PlayerCard` (grid 2×2 / 2×5, `MAX_PLAYERS=10`, badge HOST,
slot vazio); Game Over com PlayerCard WINNER/LOSER + "VOLTAR AO MENU";
hierarquia de erros (inline/toast/modal/fatal); menus pygame-menu com tema do
`theme.py` e fundo `lab_scene.png` escurecido (sem tempfile); copy PT-BR
centralizada + `DISPLAY_NAME`; conexão em worker thread com
`ConnectionState` (IDLE/CONNECTING/CONNECTED/FAILED) + `SimpleQueue` de
`ConnectionSuccess`/`ConnectionFailure`; tela "Conectando…" com cancelar.

### Bloco 10 — Viewport responsivo + input (P2)

`LOGICAL 1280×768`; janela `RESIZABLE`; render em superfície lógica →
`fit_viewport` → blit escalado com letterbox (sem `SCALED`); input físico →
`screen_to_logical` em caminho único (componentes não convertem); testes de
clique no letterbox e em 4 resoluções.

### Bloco 11 — Acessibilidade, reduced motion, ícones, performance (P2/P3)

Foco em todas as telas custom; estados com cue além da cor; toggle de reduced
motion (env + tela de configurações); iconografia mínima única com texto;
cache de fontes/superfícies (FontBook + backgrounds); testes de contraste
heurístico e redundância de estados.

### Bloco 12 — Captura, limpeza, QA final

`scripts/capture_ui_states.py` (SDL dummy, estados determinísticos → PNGs em
`captures/`); limpeza (Button antigo, COLOR_* legados, `self.voted`, starfield,
strings duplicadas, imports); grep final `Font(None` e branding; QA manual
(crew/impostor/votação/privacidade 4 clientes/resoluções/reduced motion).

## 4. Gates de regressão

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest tests/ -q
```

Após blocos de protocolo/gameplay: `uv run python scripts/smoke_multiplayer.py`.

Gates específicos (sigilo/gameplay/voting/visual/responsive) conforme plano do
usuário: `MeetingEnded` = exatamente `{type, meeting_id}`; nenhum payload
público com `ejected`/`ejected_id`/`role`/`vote_count`/`votes`; tarefa
completável pela UI; toda denial com feedback; voto registrado só após
`ActionAccepted`; sem duplo envio; layout com 10 jogadores; sem `Font(None` em
tela funcional; resize preserva aspect; letterbox sem interação.

## 5. Riscos e decisões

- `ActionAccepted` mínimo (KILL + VOTE): REPORT/EMERGENCY confirmam via
  `MeetingStarted`; TASK via `TaskState` per-player.
- v1 decodifica (le=2), rejeitada no `_on_join` (`bad_version`); framing inválido
  passa a usar v3.
- `MeetingEnded` idêntico nos três desfechos é consequência do schema novo;
  teste de bytes idênticos protege a transição uniforme.
- Menus pygame-menu desenhados na superfície lógica com eventos traduzidos;
  risco de widgets que consultam `pygame.mouse.get_pos()` internamente —
  fallback: menus em resolução física, transformação aplicada às telas custom.
- Durações mínimas (2,5 s ejeção / 1,2 s reunião encerrada) são atributos da
  App, sobrescrevíveis em teste.
- PT-BR como idioma único; `DISPLAY_NAME` centralizado.
- Reduced motion por env var + toggle (sem persistência — projeto não tem).
- FontBook usa o Open Sans bundled do pygame-menu; nenhuma dependência nova.

## 6. Resultados da execução

| Bloco | Status | Evidência |
| --- | --- | --- |
| 0 — Baseline | ✅ | 153 testes verdes; smoke OK (2026-08-29) |
| 1 — Protocol v2 | ✅ | `PROTOCOL_VERSION=2`; `MeetingEnded{meeting_id}`; `ActionKind`/`DenialCode`; `ActionAccepted`/`ActionDenied` tipado; `_on_task` deixa de silenciar; 166 testes verdes (+13); smoke OK; v1 rejeitada via wire |
| 2 — Toasts + cooldown | ✅ | `toasts`/`_push_toast`/`_denial_text`; `kill_cooldown_until` via `ActionAccepted(KILL)`/`ActionDenied(COOLDOWN)`; 6 testes novos |
| 3 — Interação contextual | ✅ | `ui/viewmodel.py` (InteractionContext + derive_*); `K_e` executa TASK/EMERGENCY; `K_r`/`K_SPACE` via viewmodel; 15 testes viewmodel + 4 de evento |
| 4 — Ejeção privada | ✅ | `private_ejection`/`pending_game_over`/`_update_transitions(now)`; telas `ejected`/`meeting_ended`; 5 testes de transição; **P0 concluídos: 195 testes + smoke OK** |
| 5 — Design system | ✅ | `theme.py`/`motion.py`/`layout.py`/`fonts.py` (FontBook Open Sans); 19 testes de layout/contraste/motion |
| 6 — Componentes | ✅ | `components.py`: Button 7 estados, FocusManager (Tab/Shift+Tab/Enter/Space), PlayerCard, Keycap, ActionPrompt, ProgressBar; alvo 40px; 9 testes |
| 7 — HUD + marcadores | ✅ | `GameHudView`/`TaskMarkerView`/`derive_*`; HUD 64px via tokens; `draw_map(markers)` contextual; branding removido; 7 testes de viewmodel (22 no total) |
| 8 — Votação | ✅ | `VoteUiState` (SELECTING/SUBMITTING/SUBMITTED); card inteiro selecionável; `[PULAR][VOTAR]`; sem voto otimista; `ActionAccepted(VOTE)`→SUBMITTED; `ActionDenied(VOTE)`→SELECTING+toast; sem duplo envio; 6 testes; Button legado removido de render.py |
| 9 — Lobby/GameOver/erros/menus/conexão | ✅ | Conexão assíncrona (`ConnectionState`+worker+`SimpleQueue`+tela "Conectando…"+cancelar, 3 testes); GameOver com PlayerCard WINNER/LOSER + "VOLTAR AO MENU"; lobby custom com grid de PlayerCard + badge HOST + foco; menus com lab_scene escurecida (sem starfield), `DISPLAY_NAME`, copy PT-BR; **237 testes verdes** |
| 10 — Viewport responsivo | ✅ | Canvas lógico 1280×768 + janela RESIZABLE + `_present` letterbox + `_translate_events` (caminho único); 3 testes de input; fonts da App via FontBook (sem `Font(None` no src/ui) |
| 11 — Acessibilidade + reduced motion | ✅ | `Renderer(reduced_motion=...)` sem pulse contínuo; `settings_from_env`; testes de env e render |
| 12 — Captura + limpeza + QA | ✅ | `scripts/capture_ui_states.py` (13 PNGs em `captures/`); Button legado/`_game_hint*`/constantes mortas removidos; README atualizado; **242 testes verdes + smoke OK** |