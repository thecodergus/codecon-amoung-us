# Plano — Fechamento do redesign de UI/UX, sigilo e QA final

**Status:** em execução (2026-08-29)
**Origem:** documento do usuário "Fechamento do redesign de UI/UX, sigilo e QA final" + investigação do repositório
**Decisão-chave (registrada com o usuário):** contrato de sigilo = **formalizar o comportamento atual** (Opção A). Ver Fase 1.

## Objetivo

Concluir o redesign existente de forma corretiva: formalizar o contrato de sigilo da
ejeção, tornar hover/pressed/focus funcionais, persistir a navegação por teclado,
expor reduced motion na interface, limpeza arquitetural leve, QA visual das capturas
e regressão completa. Nenhum redesign novo, nenhuma feature além da tela de
configurações.

## Contexto confirmado (investigação 2026-08-29)

**Sigilo (já implementado e travado por testes):**

- `protocol.py:228-238` — `MeetingEnded{meeting_id}` apenas; docstring já declara que
  `alive=False` torna-se público no snapshot seguinte "por decisão de design".
  `Ejected{player_id, role}` é privado (protocol.py:241-245).
- `net/dispatch.py:17-38` — função pura `dispatch_ejection`: todos recebem
  `MeetingEnded`, só o ejetado recebe `Ejected`.
- `net/server.py:838-863` — `_finish_meeting`: `ejected_player.alive = False` (855) +
  dispatch. `server.py:886-896` — `_build_snapshot` gera um snapshot único
  broadcastado a todos; não há projeção por destinatário. `server.py:312` —
  desconexão em jogo também publica `alive=False`.
- Negações já são uniformes: `NOT_ALIVE` em kill (server.py:522), report (611),
  emergency (648-651), voto em alvo morto (720-727), tarefa (773-774) — nenhuma
  menciona ejeção.
- Testes existentes: `tests/test_secrecy_properties.py` (3 testes Hypothesis sobre
  bytes serializados); `tests/test_integration.py:498-532` (sigilo over-the-wire),
  `:536-564` `test_ejected_player_is_dead_in_next_snapshot_by_design` (= Teste C),
  `:790-797` (voto em morto negado); `tests/test_ui_events.py:454-474`
  (Ejected+GameOver no mesmo drain → tela ejected preservada).

**Botões/foco:**

- `components.py:105-114` — `Button.handle_event` só trata `MOUSEBUTTONDOWN` →
  `activate()` imediato. HOVER/PRESSED existem no enum (34-43) mas só são exercitados
  via `draw`.
- Botões são reconstruídos a cada frame em: lobby (app.py:769-780), voting
  (983-994), connecting (1077-1081), gameover (1171-1175), error (1198-1200).
- `FocusManager` (components.py:117-168) recriado por frame no lobby (app.py:783) →
  foco reseta. Anel de foco só é desenhado com `state == FOCUSED`
  (components.py:97-100) e nada no lobby atribui FOCUSED → foco invisível no lobby.
- Voting tem navegação própria persistente (`_voting_cursor`, app.py:230, 1010-1031)
  — funciona; não usa FocusManager.
- `_render_error` não trata ESC; `_render_gameover` usa `pygame.key.get_pressed()`
  (1179-1181) em vez de evento.

**Settings/motion:**

- `UiSettings` frozen dataclass (theme.py:58-62); `settings_from_env()` (65-70).
  `Renderer.reduced_motion` é atributo mutável consultado a cada draw (render.py:97 —
  pulsação de marcadores, único motion contínuo).
- Menus main/host/join são pygame-menu (app.py:287-310); branch de render de menu em
  app.py:683-687. Não existe tela de configurações.
- `menu_buttons` (app.py:260, 996) atribuído mas aparentemente nunca lido.

**Viewmodel:** `derive_interaction_context` (viewmodel.py:53-92) recebe
`kill_cooldown_until`, `snapshot`, `now` e não usa nenhum no corpo. Call site:
app.py:866-874; helper de teste: test_ui_viewmodel.py:193-208.

**Infra de teste:** UI headless com `SDL_VIDEODRIVER=dummy` antes do import do pygame
(test_ui_events.py:20); fixture `app` não chama `pygame.quit()` (corrupção do cache
de fontes do pygame-menu). Marcadores `ui`/`integration`.
`scripts/capture_ui_states.py` renderiza 13 estados headless em `captures/`.
`scripts/smoke_multiplayer.py` cobre fluxo completo + asserções v2.

**Toolchain:** mypy strict com `files = ["src", "tests"]` (pyproject.toml:40-45) —
usar `uv run mypy` sem `.` (`mypy .` varreria `scripts/`). `uv run pytest` já inclui
cobertura via addopts (pyproject.toml:56-58).

## Fases

### Fase 1 — Contrato de sigilo (P0)

Decisão registrada: formalizar o contrato atual (escopo do sigilo =
identidade/papel/resultado no encerramento; `alive=False` público no snapshot
seguinte). Não criar `build_public_snapshot` — projeção por destinatário avaliada e
rejeitada (vazamento residual por comportamento: posição congelada, `NOT_ALIVE`,
lista `voters` de reuniões seguintes, desconexão pública; custo arquitetural alto).

1. Documentar os três estados (autoritativo / visão do ejetado / visão dos demais)
   nos docstrings de `protocol.py` (`MeetingEnded`, `Ejected`, `WorldSnapshot`) e
   `net/dispatch.py`; seção "Sigilo da votação" no README respondendo: *um cliente
   não ejetado recebe, após a votação: `MeetingEnded{meeting_id}` e, no próximo
   snapshot, `alive=false` do ejetado — nada mais sobre a votação.*
2. Teste D — `test_denials_for_dead_players_do_not_reveal_ejection`
   (tests/test_integration.py): jogador morto por kill vs. por ejeção → mesmo
   `DenialCode.NOT_ALIVE`, razões sem padrão `"ejet"` (case-insensitive), nos caminhos
   kill/report/voto/tarefa. Reusar fixtures `server`/`four_clients` e helpers
   `_start_game`/`_impostor_kills_and_reports`.
3. Preservar e rotular Testes A/B/C existentes; docstring do teste C referencia a
   cláusula do contrato.

### Fase 2 — Máquina de estados dos botões (P1)

4. `components.py` — separar estado semântico de interação:
   - `ButtonState` permanece como estado semântico atribuído pela tela
     (DEFAULT/SELECTED/DISABLED/COOLDOWN; HOVER/FOCUSED/PRESSED ficam para uso visual
     direto em capturas/testes).
   - Novo `InteractionState(StrEnum)`: IDLE/HOVER/PRESSED; `Button.interaction`
     (inicia IDLE) e `Button.focused: bool = False`.
   - Propriedade `activatable`: `state not in {DISABLED, COOLDOWN}`.
   - `handle_event`: MOUSEMOTION → hover entra/sai só se ativável; MOUSEBUTTONDOWN(1)
     dentro + ativável → PRESSED, consome, sem callback; MOUSEBUTTONUP(1): PRESSED e
     dentro → `activate()` + HOVER; PRESSED e fora → IDLE (cancela).
   - `draw`: visual efetivo = semântico se ≠ DEFAULT, senão mapeado de `interaction`;
     anel de foco como overlay quando `self.focused`. COOLDOWN: não ativável, visual
     esmaecido (paleta disabled); texto/contador continua na tela.
5. `app.py` — botões persistentes por tela (construir na entrada; atribuir só `state`
   semântico por frame; rect de votação só muda com a página). Eliminar reconstrução
   por frame nos 5 pontos.
6. Testes (tests/test_ui_components.py): atualizar `test_button_click_fires_callback`
   (DOWN não dispara; DOWN+UP dentro dispara; DOWN+UP fora não) + hover enter/leave,
   pressed até mouse-up, disabled ignora ponteiro, cooldown não ativa nem hover,
   selected preserva identidade sob hover, focused ≠ hover.

### Fase 3 — Persistência de foco (P1; depende da etapa 5)

7. `FocusManager` persistente por tela (lobby, connecting, gameover, error), criado
   junto dos botões persistentes; eventos roteados primeiro a `focus.handle_event`;
   a cada frame `b.focused = (i == manager.index)`.
8. error ganha ESC → `_back_to_main`; gameover passa a tratar ESC por evento. Voting
   mantém o modelo de cursor (já persistente; não migrar nesta fase).
   Ejected/meeting_ended: documentadas como ESC-only.
9. Testes (tests/test_ui_events.py): `test_lobby_focus_persists_between_frames`
   (render → Tab → render com `[]` → foco no 2º controle → render → persiste); focus
   skips disabled; Shift+Tab wrap; Enter ativa foco persistido;
   `test_custom_screens_have_keyboard_navigation` parametrizado
   (lobby/connecting/gameover/error).

### Fase 4 — Reduced motion na interface (P1/P2; independente de 2–3)

10. `_build_settings_menu()` (pygame-menu): selector "Reduzir movimento"
    `[("NÃO", False), ("SIM", True)]`, default de `ui_settings.reduced_motion`;
    `onchange` aplica imediatamente: `dataclasses.replace(self.ui_settings, ...)` +
    `self.renderer.reduced_motion = v`. Botão "Voltar" → `_back_to_main`.
11. Menu principal: "Configurações" entre "Entrar em partida" e "Sair" →
    `_open_settings` (`screen_name = "settings"`, `_current_menu = menu_settings`);
    incluir `"settings"` no branch de menu de `_render` (app.py:683).
12. README: tela passa a ser o controle primário; env var vira default inicial.
13. Testes: toggle ON/OFF atualiza renderer + ui_settings em runtime (ambas direções);
    default do selector reflete a env var; pulsação desabilitada com ON.

### Fase 5 — Limpeza arquitetural (P2; após Fases 2–4)

14. `Screen(StrEnum)` com MAIN/HOST/JOIN/LOBBY/CONNECTING/GAME/VOTING/EJECTED/
    MEETING_ENDED/GAME_OVER/ERROR/SETTINGS; substituir literais de `screen_name`.
    `StrEnum` mantém comparações `== "lobby"` válidas em testes/capturas.
15. `derive_interaction_context`: remover `kill_cooldown_until`/`snapshot`/`now`;
    atualizar call site (app.py:866-874) e helper de teste
    (test_ui_viewmodel.py:193-208).
16. Remover `menu_buttons` se confirmado morto. Não extrair abstração de toast/modal
    (um único mecanismo, reusado por game e voting; critério "≥2 usos" não se aplica).

### Fase 6 — QA visual (P1; após Fases 2–5)

17. Estender `scripts/capture_ui_states.py`: estados `settings`, `lobby_focused` e um
    de interação (hover/pressed injetado). Rodar
    `uv run python scripts/capture_ui_states.py`.
18. Auditoria das capturas contra o checklist (hierarquia, layout, tipografia,
    componentes nos 7 estados, cor/contraste, gameplay, votação 8–10 jogadores,
    estados especiais). Somente correções justificáveis (spacing, hierarquia,
    selected×hover, focus ring, HUD secundário). Proibido: nova identidade visual,
    assets, animações ornamentais, troca de paleta/tipografia.

### Fase 7 — Multiplayer real (P1; último; execução do usuário em hardware)

19. Estender `plans/checklist-ambiente-real.md`: sigilo observado conforme contrato
    da Fase 1, experiência privada do ejetado, resize/letterbox com clique,
    cancelamento de conexão. Proxy automatizado:
    `uv run python scripts/smoke_multiplayer.py`.

## Riscos e decisões

- Mudança de clique DOWN→UP: comportamento pedido (§5.3 do documento); validar no QA.
- Botões persistentes alteram render das 5 telas — mitigado pela suíte `ui` (40
  testes) + novos testes de foco.
- COOLDOWN com visual esmaecido: contraste validado na Fase 6.
- Voting fora do FocusManager: inconsistência de implementação, não de comportamento.
- `uv run mypy` (config-driven), não `mypy .` (incluiria `scripts/`).
- Contradição resolvida: o documento pedia reavaliar `alive=False` público; o
  repositório já o documentava como contrato com teste travando. Decisão do usuário:
  formalizar como está (Opção A).

## Verificação

Por fase: `uv run pytest -k "<padrão>" -v` + `uv run ruff format --check . &&
uv run ruff check . && uv run mypy`.

Completa (ao final):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest                                  # já inclui --cov via addopts
uv run python scripts/smoke_multiplayer.py
uv run python scripts/capture_ui_states.py     # + auditoria visual das PNGs
```

Sem relaxar assertions, lint ou strictness.

## Questões em aberto

Nenhuma bloqueante. O checklist LAN (Fase 7) depende de hardware do usuário.
