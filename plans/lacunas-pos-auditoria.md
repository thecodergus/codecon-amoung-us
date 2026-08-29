# Plano — Lacunas pós-auditoria e estado da arte (codecon-amoung-us)

Data: 2026-08-29
Status: aprovado para execução
Origem: auditoria técnica (F-01..F-08) + pesquisa de estado da arte (2026)

## 1. Resumo

Revalidadas contra os artefatos: 8 problemas da auditoria (F-01..F-08) confirmados
e re-rotulados como lacunas G-01..G-08/G-10..G-12; +1 lacuna nova encontrada na
execução (G-20: movimento WASD ausente na UI — `client.move` nunca é chamado em
`ui/`; `pygame.key.get_pressed` só existe no game over, `ui/app.py:412`); 8 itens
inconclusivos (G-13..G-19) tratados com ações de verificação.

Nenhuma lacuna P0 (sem perda de dados, sem risco crítico). Nenhuma ação introduz
dependência nova nem altera o protocolo de rede (wire-compatible).

## 2. Matriz consolidada de cobertura

| ID | Requisito/achado | Evidência interna | Classificação | Causa/hipótese | Ações | Prioridade | Confiança |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | R-01: report exige proximidade e autor vivo | `server.py:445-456` sem validação; `body_id` público (`server.py:608-611`); cliente impõe 45px (`app.py:339-345`); botão valida (`server.py:464-474`) | Não atendido | Validação server-side incompleta | A-01 | P1 | alta |
| G-02 | R-01/R-06: sem duplicata de join por conexão | `server.py:318-360` sem guard; `_connections` sobrescrito; `on_disconnect` remove só o último | Não atendido | Falta guard de estado | A-02 | P1 | alta |
| G-03 | R-01: reunião não pode travar | `meeting.voters` fixado (`server.py:526-533`); desconexão não remove (`server.py:284-287`) | Parcialmente atendido | Sem gestão de abandono em fase síncrona | A-03 | P2 | alta |
| G-04 | R-01: sem tunelamento | `server.py:240` cap dt 0.5 → passo 90px; paredes 16px; `physics.py:30-36` ponto-final | Parcialmente atendido | Colisão discreta com passo alto | A-04 | P2 | média |
| G-05 | R-11/R-01: ESC sai do jogo | `README.md:43` afirma ESC; `app.py:329-358` não trata | Atendido incorretamente | Doc divergente + handler ausente | A-05 | P2 | alta |
| G-06 | R-06: voto em alvo válido | `server.py:485-487` valida existência, não vida; `MeetingEnded{ejected=True}` sem morte possível | Não atendido | Validação de alvo incompleta | A-06 | P2 | alta |
| G-07 | R-07: teste verifica contrato do nome | `test_integration.py:158-171` não consome ProtocolError | Parcialmente atendido | Teste incompleto | A-07 | P2 | alta |
| G-08 | R-09: docstring smoke precisa | `smoke_multiplayer.py:18` documenta exit 2; `_run` só retorna 0/1 | Atendido incorretamente | Docstring imprecisa | A-09 | P3 | alta |
| G-09 | Higiene: sem código morto | `app.py:372-373` `with self._snapshot_lock: pass` | Não atendido | Resíduo de refatoração | A-08 | P3 | alta |
| G-10 | R-05: entrada robusta | `app.py:149,170` `int(...)` lança ValueError | Parcialmente atendido | Sem validação de entrada | A-08 | P3 | alta |
| G-11 | R-10: sem Any generalizado | `app.py:122` `cast(Any, ...)` (stubs pygame-menu) | Parcialmente atendido | Stubs incompletos | A-08 | P3 | média |
| G-12 | R-07: testes estáveis | `test_integration.py:199` tolerância 4px < passo 9px | Inconclusivo | Fragilidade latente | A-10 | P3 | média |
| G-13 | R-07: cobertura mensurável | addopts `--cov`; % não registrada | Inconclusivo | Falta registro | A-11 | P3 | alta |
| G-14 | R-05: UI exercitada além do boot | `test_ui_smoke.py` só renderiza | Inconclusivo | Verificação insuficiente | A-12 | P2 | média |
| G-15 | R-01: timeout de reunião funcional | `_check_meeting_timeout` sem teste dedicado | Inconclusivo | Falta teste com timeout reduzido | A-03 | P2 | média |
| G-16 | R-05: rede real além de loopback | smoke usa 127.0.0.1 | Inconclusivo | Ambiente local | A-15 | P3 | média |
| G-17 | Compat: datas de release das deps dev vs corte 2026-08-08 | lockfile; datas não consultadas | Inconclusivo | Falta consulta PyPI | A-13 | P3 | média |
| G-18 | Segurança: vulnerabilidades transitivas | `uv audit` nunca executado | Inconclusivo | Falta varredura | A-14 | P3 | média |
| G-19 | Repro: suíte pós-edição cosmética | mypy/pytest não re-executados após docstring | Inconclusivo | Falta re-execução | A-16 | P3 | alta |
| G-20 | R-01: movimento jogável na UI | `client.move` nunca chamado em `ui/`; `get_pressed` só em `app.py:412` (game over); README/hints afirmam WASD | Não atendido | Handler de movimento ausente no App | A-17 | P1 | alta |

## 3. Síntese da pesquisa (estado da arte)

- **Validação server-side (G-01/G-02/G-06):** revisão sistemática de anti-cheat
  (Alangari & Alharbi, 2025, arXiv:2512.21377v1) posiciona detecção server-side
  como baseline de baixa intrusão; RACS (Webb, Soh & Lau, 2007) demonstra que a
  autoridade de estado do servidor bloqueia "invalid commands" e "information
  exposure". Recomendação: completar validação no handler. Confiança: alta.
- **CCD/tunelamento (G-04):** SOTA 2024-2025 (Joho et al. ICRA 2024
  arXiv:2402.15281; Son et al. CoRL 2025 arXiv:2509.00499; Sui et al. ICRA 2025
  arXiv:2409.09918) é robótica/GPU/neural — inaplicável a 2D ponto-vs-AABB.
  Técnica clássica de limitação de passo (Ericson 2005) via subpassos:
  recomendada. Lacuna bibliográfica 2026 declarada. Confiança: média.
  (Requaliﬁcação — G-29: texto integral de Ericson (2005) não acessível na
  auditoria; a técnica é validada por teste determinístico —
  `tests/test_physics.py` — e a citação permanece como referência canônica, não
  como fonte direta verificada.)
- **Quit handling em jogos de dedução social (G-03/G-15):** nenhuma literatura
  2026 aplicável encontrada (buscas em searchmesh e arXiv; API arXiv com range
  de data retornou HTTP 500). Decisão de robustez: remover desconectado dos
  votantes. Confiança: média.
- **UI dirigida por eventos (G-14):** eventos sintéticos via `pygame.event.post`
  (documentação oficial do pygame). Sem alegação científica. Confiança: média.

## 4. Fases e ações

### Fase 1 — Integridade do servidor (P1)

#### A-01 — Validar report de corpo no servidor
- **Lacunas:** G-01.
- **Solução:** `config.py` nova constante `report_radius=50.0` (>= kill_radius 40,
  preserva testes/smoke existentes); função pura `can_report(state, reporter_id,
  body_id, report_radius)` em `game/rules.py`; usar em `_on_report` com
  `ActionDenied` ("corpo fora de alcance"/"jogador morto não pode reportar").
- **Componentes:** `config.py`, `game/rules.py`, `net/server.py::_on_report`,
  `tests/test_rules.py`, `tests/test_integration.py`.
- **Testes:** unit `can_report` (vivo/morto, perto/longe, corpo inexistente);
  integração "report de longe é negado" e "morto não reporta".
- **Aceitação:** testes novos verdes; `test_report_triggers_meeting` e smoke verdes.
- **Esforço:** pequeno. **Confiança:** alta.

#### A-02 — Rejeitar JoinRequest duplicado
- **Lacunas:** G-02.
- **Solução:** em `_on_join`, se `conn.player_id is not None` → `ProtocolError(
  code="already_joined")` + `conn.close()` (padrão do método).
- **Testes:** integração "join duplicado não cria segundo player" (ProtocolError +
  `len(players)==4`).
- **Aceitação:** teste novo verde; suíte verde. **Esforço:** pequeno.

#### A-17 — Movimento WASD na UI (G-20)
- **Lacunas:** G-20.
- **Solução:** função pura `_movement_direction(keys) -> tuple[float,float] | None`
  (WASD, normalizada) em `ui/app.py`; `_handle_game_movement()` chamado em
  `_render_game` envia `client.move(dx, dy)` quando há direção (60 fps; servidor
  usa o último input por tick).
- **Testes:** unit `_movement_direction` (só W, diagonal normalizada, nenhuma
  tecla → None); integração UI com evento ESC (A-12).
- **Aceitação:** testes verdes; mypy/ruff verdes. **Esforço:** pequeno.

### Fase 2 — Robustez de gameplay (P2)

#### A-03 — Desconexão em reunião + teste de timeout
- **Lacunas:** G-03, G-15.
- **Solução:** `Meeting.remove_voter(voter_id) -> bool` em `game/meeting.py`
  (remove de voters e votes); em `on_disconnect`, quando phase MEETING, remover
  votante e, se `all_voted`, `_finish_meeting` (dentro do lock existente).
- **Testes:** integração "desconexão durante reunião encerra imediatamente"
  (demais votantes votaram; restantes recebem MeetingEnded + GameOver);
  integração "reunião termina por timeout" com `GameConfig(
  meeting_vote_timeout_seconds=1.0)` (servidor próprio no teste).
- **Aceitação:** 2 testes novos verdes. **Esforço:** pequeno.

#### A-04 — Subpassos de movimento (anti-tunelamento)
- **Lacunas:** G-04.
- **Solução:** `resolve_movement_steps(x, y, dx, dy, walls, max_step, margin=0.0)`
  em `game/physics.py` (subpassos ≤ max_step; `config.py` `max_movement_step=8.0`
  < 16px de parede); `_advance_physics` usa a nova função.
- **Testes:** `tests/test_physics.py` novo: passo 90px não transpõe parede 16px;
  passo normal sem parede preserva; deslizamento preservado.
- **Aceitação:** testes novos verdes; navegação integração/smoke inalterada.

#### A-05 — ESC na tela de jogo
- **Lacunas:** G-05.
- **Solução:** em `_handle_game_key`, `K_ESCAPE` → `_shutdown_connection()` +
  `screen_name="main"` + `_current_menu=menu_main` (padrão do game over).
- **Testes:** via A-12. **Esforço:** pequeno.

#### A-06 — Rejeitar voto em alvo morto
- **Lacunas:** G-06.
- **Solução:** em `_on_vote`, se alvo existe mas não está vivo → `ActionDenied(
  reason="alvo morto")`.
- **Testes:** integração "voto em alvo morto é negado e não registrado".
- **Esforço:** pequeno.

#### A-07 — Assertar ProtocolError no teste malformed
- **Lacunas:** G-07.
- **Solução:** em `test_integration.py:158-171`, após `sendall`, `wait_for(
  ProtocolError, timeout=5.0)` no ofensor.
- **Esforço:** pequeno.

#### A-12 — Teste de UI dirigido por eventos sintéticos
- **Lacunas:** G-14 (valida A-05, A-17).
- **Solução:** `tests/test_ui_events.py` novo: App conectado a GameServer local
  (SDL dummy), `_handle_game_key(K_ESCAPE)` volta ao menu; `_movement_direction`
  unit; clique em `Button` via `MOUSEBUTTONDOWN` postado.
- **Esforço:** médio.

### Fase 3 — Higiene, documentação e verificação (P2/P3)

#### A-08 — Higiene da UI
- **Lacunas:** G-09, G-10, G-11.
- **Solução:** remover `with self._snapshot_lock: pass` (`app.py:372-373`); tratar
  `ValueError` de porta em `_create_game`/`_join_game` com `_show_error("Porta
  inválida")`; manter `cast(Any, ...)` em `app.py:122` com comentário
  justificativo (stubs do pygame-menu; diretriz R-10 admite exceção localizada
  documentada).
- **Esforço:** pequeno.

#### A-09 — Docstring do smoke
- **Lacunas:** G-08.
- **Solução:** `smoke_multiplayer.py:18`: "0 = sucesso; 1 = falha de verificação
  ou infraestrutura".

#### A-10 — Tolerância de navegação dos testes
- **Lacunas:** G-12.
- **Solução:** `test_integration.py:199` `dist <= 4.0` → `<= 12.0` (mesmo valor
  do smoke) + comentário.

#### A-11 — Registrar cobertura
- **Lacunas:** G-13.
- **Solução:** `uv run pytest tests/ -q --cov-report=term-missing`; registrar % na
  seção 5 deste plano.

#### A-13 — Datas de release das deps dev (corte 2026-08-08)
- **Lacunas:** G-17.
- **Solução:** consultar `pypi.org/pypi/<pkg>/<ver>/json` para pytest 9.1.1,
  hypothesis 6.165.10, ruff 0.16.5, mypy 2.3.1, pytest-cov 6.3.0,
  pytest-timeout 2.4.0, coverage 7.16.0; registrar.

#### A-14 — Varredura de vulnerabilidades transitivas
- **Lacunas:** G-18.
- **Solução:** `uv audit` (read-only); registrar; avaliar achados com processo de
  depsec se houver.

#### A-15 — Verificação de rede entre máquinas (não executável neste ambiente)
- **Lacunas:** G-16.
- **Solução:** roteiro manual: `--host 0.0.0.0`, 2 máquinas na mesma LAN.
  Registrada como NÃO EXECUTADA (1 máquina disponível).

#### A-16 — Validação final completa
- **Lacunas:** G-19.
- **Solução:** `uv run ruff format .`; `uv run ruff check .`; `uv run mypy .`;
  `uv run pytest tests/ -q`; `uv lock --check`; smoke 5 execuções; registrar.

## 5. Estratégia de verificação

Regressão obrigatória após cada fase: `uv run ruff check .` + `uv run ruff format
--check .` + `uv run mypy .` + `uv run pytest tests/ -q` + smoke multiplayer.

Cobertura registrada (A-11): **78%** (1680 stmts, 290 miss, 101 partial) —
`uv run pytest tests/ -q --cov-report=term`, 2026-08-29.

## 6. Riscos e questões inconclusivas

- A-01: raio < 40px quebraria testes → constante 50px.
- A-03: voters vazio → reunião termina sem ejeção (comportamento definido e
  testado).
- A-07: corrida close-vs-recv → wait_for com timeout e falha informativa.
- G-04/G-12: hipóteses não reproduzidas; correções preventivas determinísticas.
- G-16/G-17/G-18: dependem de ambiente/registro externo (LAN/PyPI/OSV).

## 7. Definição global de concluído

Todas as lacunas encerradas quando: servidor rejeita report remoto/morto, join
duplicado e voto em morto; reunião não trava com desconexão e timeout testado;
passo 90px não transpõe parede 16px; ESC sai do jogo; movimento WASD funcional
na UI; ProtocolError assertado; tolerância 12px; cobertura registrada; UI
exercitada por eventos; datas dev e uv audit registrados; suíte completa e
smoke verdes com saídas registradas.

## 8. Referências

- Alangari & Alharbi (2025), *A Systematic Review of Technical Defenses Against
  Software-Based Cheating in Online Multiplayer Games*, preprint,
  https://arxiv.org/abs/2512.21377v1
- Bertin, Dacier & Bromberg (2026), *Cheating in Multiplayer Online Games: a
  Dataset*, preprint, https://arxiv.org/abs/2606.06013v1
- Webb, Soh & Lau (2007), *RACS: A referee anti-cheat scheme for P2P gaming*,
  NOSSDAV, https://openalex.org/W2103269902
- Son, Jung & Kim (2025), *NeuralSVCD for Efficient Swept Volume Collision
  Detection*, CoRL, https://arxiv.org/abs/2509.00499v1
- Ericson (2005), *Real-Time Collision Detection*, Morgan Kaufmann (técnica
  clássica de limitação de passo)
- Documentação local: `plans/among-us-mvp.md`, `README.md`, `pyproject.toml`,
  `uv.lock`, `src/`, `tests/`, `scripts/smoke_multiplayer.py`
- Registro de pesquisa: searchmesh (profile scholarly) e arXiv API,
  2026-08-29; limitações: Semantic Scholar rate-limited (partial); arXiv com
  range de data → HTTP 500 (substituída por query sem range).

## 9. Resultados da execução

Executado integralmente em 2026-08-29 (modo build). Resultados:

| Ação | Status | Evidência |
| --- | --- | --- |
| A-01 report com raio/vida | ✅ | `can_report` em `game/rules.py`; `_on_report` valida; 4 testes unit + 2 integração novos |
| A-02 join duplicado | ✅ | Guard em `_on_join` (ProtocolError sem close — close expulsaria o jogador legítimo); teste novo |
| A-03 desconexão em reunião + timeout | ✅ | `Meeting.remove_voter`; `on_disconnect` encerra reunião se `all_voted`; 2 testes novos |
| A-04 subpassos anti-tunelamento | ✅ | `resolve_movement_steps` (`physics.py`); `max_movement_step=8.0`; `tests/test_physics.py` novo |
| A-05 ESC na tela de jogo | ✅ | `_handle_game_key` trata K_ESCAPE (volta ao menu) |
| A-06 voto em alvo morto | ✅ | `_on_vote` rejeita alvo morto; teste novo |
| A-07 ProtocolError assertado | ✅ | `test_malformed_frame_gets_protocol_error` agora consome ProtocolError |
| A-08 higiene UI | ✅ | bloco morto removido; porta inválida → `_show_error`; cast(Any) documentado |
| A-09 docstring smoke | ✅ | exit codes 0/1 documentados |
| A-10 tolerância 12px | ✅ | `_move_to_point` dos testes com `<= 12.0` |
| A-11 cobertura | ✅ | 78% (1680 stmts) registrada |
| A-12 UI eventos sintéticos | ✅ | `tests/test_ui_events.py` novo (movimento, botão, ESC) |
| A-13 datas deps dev | ✅ | ver abaixo |
| A-14 uv audit | ✅ | "Found no known vulnerabilities and no adverse project statuses in 24 packages" |
| A-15 rede entre máquinas | ⏸️ NÃO EXECUTADA | ambiente com 1 máquina; roteiro manual registrado |
| A-16 validação final | ✅ | ruff format=0, ruff check=0, mypy=0, uv lock=0, pytest=0, smoke=0 |

**Contagem de testes:** 110 → **129 passed** (`uv run pytest tests/ -q --no-cov`,
42.6 s, exit 0); smoke multiplayer 3+ execuções "SMOKE MULTIPLAYER OK".

**Datas de release das deps dev (PyPI, registro atual; corte da auditoria
2026-08-08):** pytest 9.1.1 = 2026-06-19 (≤ corte); pytest-cov 6.3.0 =
2025-09-06 (≤); pytest-timeout 2.4.0 = 2025-05-05 (≤); hypothesis 6.165.10 =
2026-08-16 (> corte); ruff 0.16.5 = 2026-08-27 (>); mypy 2.3.1 = 2026-08-15
(>); coverage 7.16.0 = 2026-08-28 (>). 4 deps dev são posteriores ao corte da
auditoria — limitação metodológica da auditoria confirmada (o projeto foi
implementado em 2026-08-29); sem impacto funcional.

**Correção adicional durante a execução:** caminhos de rejeição do join
(`bad_version`/`lobby_full`/`game_in_progress`) enviavam a resposta pelo outbox
e fechavam a conexão imediatamente — o `ProtocolError` se perdia (socket
fechado antes do flush). Corrigido com `_reject_connection` (send direto +
close), detectado pelo novo teste de join duplicado.