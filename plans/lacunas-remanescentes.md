# Plano — Lacunas remanescentes pós-implantação (codecon-amoung-us)

Data: 2026-08-29
Status: aprovado para execução
Origem: diagnóstico consolidado (m0035) após a execução de A-01..A-17

## 1. Resumo

Revalidação completa do estado do projeto após a fase anterior (A-01..A-17
executadas e verdes: 129 testes, mypy/ruff/lock, smoke, cobertura 78%). O núcleo
do MVP e as 17 ações anteriores estão **atendidos**. Todo o trabalho remanescente
é endurecimento P3, em 4 famílias:

1. **Robustez de fronteira do servidor/CLI** (G-23, G-25, G-26): validação de
   argumentos da CLI (hoje `--tick-rate 0` → `ZeroDivisionError`), close explícito
   de socket no caminho de erro, e testes dos caminhos de rejeição do join
   (incluindo o branch `bad_version`, inalcançável via wire por constraint do
   protocolo).
2. **Robustez e consistência da UI** (G-21, G-22, G-27): ESC na tela de votação
   (README promete, código não trata), teardown de rede ao receber `ProtocolError`
   (host embutido pode ficar ativo), e unificação das constantes de alcance
   (45 px mágicos vs 40/50 do servidor).
3. **Testes e documentação** (G-14, G-19, G-24, G-29): teste de ESC com servidor
   real, glue WASD, README alinhado à semântica de `already_joined`, e
   requalificação da citação Ericson (2005).
4. **Bloqueio de ambiente** (G-16): verificação LAN entre máquinas — sem ação de
   código, registrada como NÃO EXECUTADA.

Regras transversais: **sem dependências novas, sem mudança de protocolo
(wire-compatible), sem alteração de `uv.lock`**.

## 2. Matriz consolidada de cobertura

| ID | Requisito/achado | Evidência interna | Classificação | Causa/hipótese | Ações | Prioridade | Confiança |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G-01 | R-01: report com raio/vida | `rules.py::can_report`; `server.py:466-476`; 6 testes | atendido | — | (A-01) | P1 | alta |
| G-02 | R-01: join duplicado sem fantasma | `server.py:332-338`; teste | atendido | — (doc = G-24) | (A-02) | P1 | alta |
| G-03 | R-01: reunião não trava | `meeting.py:64-74`; `server.py:287-290`; 2 testes | atendido | — | (A-03) | P2 | alta |
| G-04 | R-01: anti-tunelamento | `physics.py:41-65`; `test_physics.py` | atendido | — | (A-04) | P2 | alta |
| G-05 | R-05/R-11: ESC no jogo | `app.py:363-368`; teste | atendido | — (votação = G-21) | (A-05) | P2 | alta |
| G-06 | R-01/R-06: voto em morto | `server.py:510-512`; teste | atendido | — | (A-06) | P2 | alta |
| G-07 | R-04/R-07: ProtocolError assertado | `test_integration.py:161-175` | atendido | — | (A-07) | P2 | alta |
| G-08 | R-08: docstring smoke | `smoke_multiplayer.py:18` | atendido | — | (A-09) | P3 | alta |
| G-09 | R-05: sem código morto | `app.py` | atendido | — | (A-08) | P3 | alta |
| G-10 | R-05: porta inválida tratada | `app.py:166-170,191-195` | atendido | — | (A-08) | P3 | alta |
| G-11 | R-10: Any localizado | `app.py:136-139` | atendido | — | (A-08) | P3 | média |
| G-12 | R-07: estabilidade testes | `test_integration.py:203-206` | atendido | — | (A-10) | P3 | média |
| G-13 | R-04: cobertura registrada | plano §5 (78%) | atendido | — | (A-11) | P3 | alta |
| G-14 | R-05: UI por eventos | `test_ui_events.py`; ESC sem conexão real; `pygame.init()` sem quit | parcialmente atendido | Simplificação do teste vs desenho A-12 | A-23 | P3 | média |
| G-15 | R-01: timeout reunião | teste dedicado verde | atendido | — | (A-03) | P2 | média |
| G-16 | R-05: rede além de loopback | roteiro registrado; não executado | bloqueado | 1 máquina disponível | A-28 | P3 | baixa |
| G-17 | R-09: datas deps dev | PyPI; 4 pós-corte | atendido | — | (A-13) | P3 | alta |
| G-18 | R-09: vulnerabilidades | `uv audit` 24 pkgs, 0 | atendido | — | (A-14) | P3 | alta |
| G-19 | R-04: suíte pós-cosmética | registros A-16 | atendido | — | (A-16) | P3 | alta |
| G-20 | R-01/R-11: WASD jogável | `app.py:49-59,347-353`; 3 unit | atendido | — (glue → A-26) | (A-17) | P1 | alta |
| G-21 | R-05/R-11: ESC na votação | `app.py:401-423` sem KEYDOWN; README:43 promete ESC geral | parcialmente atendido | Handler ESC só em game/gameover | A-18 | P3 | alta |
| G-22 | R-05: teardown no erro de protocolo | `app.py:272-273` (`_show_error` sem shutdown); `_back_to_main` não limpa | não atendido | Caminho de erro não encerra client/server | A-21 | P3 | média |
| G-23 | R-01: CLI valida entrada | `server.py:703-727` sem validação; `tick_rate=0` → `ZeroDivisionError` (`server.py:237`); `max_players=0` → lobby rejeita todos | não atendido | argparse sem validação; `GameConfig` sem `__post_init__` | A-22 | P3 | alta |
| G-24 | R-11: doc × código (already_joined) | `server.py:332-338` vs `README.md:85-87`; plano A-02 prescrevia close | atendido incorretamente | Decisão de execução documentada no plano §9; README não atualizado | A-19 | P3 | alta |
| G-25 | R-01: close explícito do socket | `server.py:84-103`: `FrameError` → `break` sem `close()`; close via GC | parcialmente atendido | Caminho de erro fora da rotina de close | A-20 | P3 | média |
| G-26 | R-04/R-01: caminhos de rejeição do join | 1 de 4 paths testado; `bad_version` inalcançável (constraint `protocol.py:67,117`) | inconclusivo | Sem teste parametrizado; branch morto por constraint | A-24 | P3 | média |
| G-27 | R-01/R-11: constantes de alcance da UI | `app.py:382,395` (45 px) vs `config.py` (40/50) | parcialmente atendido | Números mágicos duplicados | A-25 | P3 | média |
| G-29 | R-09: citação Ericson verificável | plano §8; livro não acessível | inconclusivo | Obra canônica sem texto integral | A-27 | P3 | baixa |

## 3. Síntese da pesquisa por lacuna

### 3.1 Robustez de sessão e quit handling (G-03/G-15/G-16/G-22)
- **Pesquisa:** literatura 2026 sobre abandono/desconexão e encerramento de sessão
  em jogos multiplayer (searchmesh, profile scholarly, 2026-08-29): nenhum
  trabalho aplicável — resultados apenas de retenção/engajamento (Loria et al.
  2020; Park et al. 2017) e ruído. arXiv API com range de data → HTTP 429/500
  (limitação registrada). **Lacuna bibliográfica 2026 declarada.**
- **Baseline:** decisão de robustez implementada e testada; teardown da UI
  incompleto (G-22).
- **Recomendação:** manter mecanismo; completar teardown (A-21); LAN (A-28)
  bloqueado.
- **Confiança:** média.

### 3.2 Colisão discreta e tunelamento (G-04/G-29)
- **Pesquisa:** SOTA 2024-25 de CCD é robótica/GPU/neural (arXiv:2402.15281,
  2509.00499, 2409.09918) — inaplicável a 2D ponto-vs-AABB. Nova busca 2026:
  ruído.
- **Baseline:** subpassos ≤ 8 px < 16 px da parede, teste determinístico verde.
- **Recomendação:** manter; requalificar a citação Ericson (2005) como prática
  clássica não integralmente verificável (A-27).
- **Confiança:** alta (solução), baixa (citação).

### 3.3 Validação server-side (G-01/G-02/G-06/G-26)
- **Pesquisa:** anti-cheat server-side (Alangari & Alharbi 2025, arXiv:2512.21377;
  Webb, Soh & Lau 2007, RACS; Bertin et al. 2026, arXiv:2606.06013) sustenta a
  direção adotada; nenhuma fonte 2026 adiciona requisito novo.
- **Recomendação:** testar `lobby_full`/`game_in_progress` via wire; decidir o
  branch `bad_version` (inalcançável por constraint `ProtocolVersion` le=1;
  manter como defesa em profundidade + teste direto) (A-24).
- **Confiança:** alta.

### 3.4 Engenharia e documentação (G-21/G-23/G-24/G-25/G-27)
- **Pesquisa:** decisões determinadas por requisito interno e prática padrão
  (argparse; `socket.close` explícito; doc como fonte de verdade). Sem alegação
  científica; lacuna bibliográfica declarada para validação de entrada de
  servidores de jogo.
- **Confiança:** alta.

## 4. Plano de implementação faseado

### Fase 1 — Robustez do servidor e da CLI (P3)

#### A-20 — Close explícito no caminho de erro do `ClientConnection._run`
- **Lacunas:** G-25.
- **Objetivo:** fechamento determinístico do socket em todos os exits do recv loop.
- **Solução:** em `net/server.py::ClientConnection._run`, no `finally` (que hoje só
  chama `on_disconnect`), chamar `self.close()` antes de `on_disconnect` — cobre
  `FrameError`, EOF e `OSError`. `close()` é idempotente e suprime `OSError`.
- **Componentes:** `net/server.py` (método `_run`).
- **Impacto:** nenhum contrato; fechamento determinístico.
- **Testes:** suíte completa; `test_malformed_frame_gets_protocol_error` segue
  verde (envio antes do close).
- **Aceitação:** inspeção mostra `close()` em todos os exits; suíte verde.
- **Risco/reversão:** mínimo; remover chamada.
- **Esforço:** pequeno. **P3 / média.**

#### A-22 — Validação de argumentos da CLI do servidor
- **Lacunas:** G-23.
- **Objetivo:** impedir configurações inválidas que matam o servidor
  (`--tick-rate 0` → `ZeroDivisionError`; `--max-players 0`; porta fora do range).
- **Solução:** função pura `_server_config(args) -> GameConfig` em `net/server.py`
  que valida `1 <= port <= 65535`, `tick_rate >= 1`, `1 <= max_players <=
  MAX_PLAYERS` e levanta `ValueError`; `main()` converte em `parser.error(...)`
  (exit 2). `GameConfig` permanece sem validação própria (não muda semântica de
  testes existentes).
- **Componentes:** `net/server.py` (`main`, nova `_server_config`); novo
  `tests/test_cli.py`.
- **Testes:** `_server_config` válidos/inválidos; `main(argv)` inválido → `SystemExit(2)`.
- **Aceitação:** testes verdes; `--tick-rate 0` encerra com mensagem clara.
- **Esforço:** pequeno. **P3 / alta.**

#### A-24 — Testes dos caminhos de rejeição do join + decisão `bad_version`
- **Lacunas:** G-26.
- **Objetivo:** exercitar `lobby_full` e `game_in_progress` via wire; decidir e
  testar `bad_version`.
- **Solução:** helper `_raw_join(port, nickname, protocol_version)` (socket cru +
  `encode_frame` + leitura da linha) em `tests/test_integration.py`:
  - `lobby_full`: servidor próprio `GameConfig(max_players=1)` → 2º join →
    `ProtocolError("lobby_full")` + conexão fechada;
  - `game_in_progress`: partida iniciada com 4 clientes → join novo →
    `ProtocolError("game_in_progress")` + close;
  - `bad_version`: **inalcançável via wire** (constraint `protocol.py:67,117`
    rejeita ≠1 no decode → cai em `bad_frame`); manter o branch como defesa em
    profundidade com comentário e testar por chamada direta
    `server._on_join(conn, JoinRequest(nickname="x", protocol_version=0), outbox)`
    via `socket.socketpair(AF_INET)` (msgspec não valida constraints na
    construção).
- **Componentes:** `tests/test_integration.py`; comentário em `server.py:344-349`.
- **Aceitação:** 3 casos verdes; suíte verde.
- **Esforço:** pequeno. **P3 / média.**

### Fase 2 — Robustez e consistência da UI (P3)

#### A-18 — ESC na tela de votação
- **Lacunas:** G-21.
- **Objetivo:** README promete "Sair do jogo | ESC"; a votação ignora teclado.
- **Solução:** extrair `_exit_to_main()` (shutdown + `screen_name="main"` +
  `menu_main`) em `ui/app.py`, reutilizado por `_handle_game_key`, `_render_voting`
  (novo handler KEYDOWN ESC) e `_render_gameover`.
- **Componentes:** `ui/app.py`.
- **Testes:** novo teste ESC na votação em `test_ui_events.py`.
- **Aceitação:** teste verde; suíte verde.
- **Esforço:** pequeno. **P3 / alta.**

#### A-21 — Teardown de rede ao receber ProtocolError na UI
- **Lacunas:** G-22.
- **Objetivo:** `ProtocolError` durante a sessão encerra client e server embutido
  antes de mostrar o erro (hoje o host embutido pode ficar ativo e um novo host na
  mesma porta falha).
- **Solução:** no branch `ProtocolError` de `_handle_message`, chamar
  `_shutdown_connection()` antes de `_show_error(...)`.
- **Componentes:** `ui/app.py::_handle_message`.
- **Testes:** teste em `test_ui_events.py` (App com client/server reais, injetar
  `ProtocolError`, assert `client is None`/`server is None`/`screen_name == "error"`).
- **Aceitação:** teste verde; suíte verde.
- **Esforço:** pequeno. **P3 / média.**

#### A-23 — Completar testes de UI (ESC com servidor real; higiene)
- **Lacunas:** G-14.
- **Objetivo:** cumprir o desenho de A-12 ("App conectado a GameServer local").
- **Solução:** reescrever `test_escape_in_game_returns_to_main` conectando
  `GameServer` local + `SimulatedClient` e verificando `client is None` e
  `server is None` após ESC; balancear `pygame.init()` com `pygame.quit()` no
  teste de botão.
- **Componentes:** `tests/test_ui_events.py`.
- **Aceitação:** testes verdes; sem janela real (SDL dummy).
- **Esforço:** pequeno-médio. **P3 / média.**

#### A-25 — Unificar constantes de alcance da UI
- **Lacunas:** G-27.
- **Objetivo:** eliminar 45 px mágicos divergentes do servidor (kill 40, report 50).
- **Solução:** módulo `config.py` ganha `KILL_RADIUS = 40.0` e
  `REPORT_RADIUS = 50.0` (usados como defaults de `GameConfig`); `ui/app.py`
  importa e usa nos gates de R/Space.
- **Componentes:** `config.py`; `ui/app.py` (import + 2 usos).
- **Impacto:** gate de kill passa 45→40 (alinhado ao servidor); report 45→50
  (cliente passa a enviar report que o servidor aceitaria).
- **Testes:** suíte + smoke.
- **Aceitação:** nenhum 45 residual na UI; suíte/smoke verdes.
- **Esforço:** pequeno. **P3 / média.**

### Fase 3 — Documentação e verificação (P3)

#### A-19 — Documentar a semântica de `already_joined` no README
- **Lacunas:** G-24.
- **Solução:** novo bullet em "Decisões de protocolo" do README: JoinRequest
  duplicado → `ProtocolError` `already_joined`, conexão mantida.
- **Aceitação:** README consistente com o código.
- **Esforço:** pequeno. **P3 / alta.**

#### A-26 — Teste do glue WASD
- **Lacunas:** G-20 (residual).
- **Solução:** em `test_ui_events.py`, `monkeypatch` de `pygame.key.get_pressed`
  (W) + `SimulatedClient` com `move` espiada; chamar `_handle_game_movement()`;
  assert direção normalizada `(0, -1)`.
- **Aceitação:** teste verde.
- **Esforço:** pequeno. **P3 / média.**

#### A-27 — Requalificação da citação Ericson
- **Lacunas:** G-29.
- **Solução:** registrar no plano §3 do plano anterior que a técnica de subpassos
  é prática clássica, validada por teste determinístico; a citação Ericson (2005)
  permanece como referência canônica não integralmente verificável.
- **Aceitação:** plano sem citação direta não verificada.
- **Esforço:** pequeno. **P3 / baixa.**

#### A-28 — Roteiro LAN entre máquinas (bloqueado)
- **Lacunas:** G-16.
- **Solução:** roteiro manual já registrado (`--host 0.0.0.0` + 2 máquinas na LAN).
  **NÃO EXECUTADA** (1 máquina disponível); reavaliar ao final das demais fases.

## 5. Estratégia de verificação

| Ação | Verificações | Critério de aceitação |
| --- | --- | --- |
| A-20 | Inspeção; suíte | `close()` em todos os exits de `_run`; suíte verde |
| A-22 | `tests/test_cli.py`; execução CLI | exit ≠ 0 com mensagem; testes verdes |
| A-24 | 2 testes wire + 1 direto | 3 casos verdes; suíte verde |
| A-18 | Teste ESC votação | volta a `main`; suíte verde |
| A-21 | Teste ProtocolError com conexões | client/server None; `screen_name=="error"` |
| A-23 | Teste ESC com servidor real; quit no botão | testes verdes |
| A-25 | Grep 45; suíte + smoke | sem 45 residual; smoke OK |
| A-19 | Leitura README | sem divergência doc×código |
| A-26 | Teste glue WASD | teste verde |
| A-27 | Registro no plano | plano requalificado |
| A-28 | 2 máquinas | roteiro completo registrado |

Regressão transversal obrigatória: `uv run ruff format .`; `uv run ruff check .`;
`uv run mypy .`; `uv run pytest tests/ -q`; `uv run python
scripts/smoke_multiplayer.py`; `uv lock --check` — todos com saída registrada.

## 6. Riscos, dependências e questões inconclusivas

- **Riscos confirmados (baixos):** A-24 usa método interno (`server._on_join`) —
  consistente com o padrão dos testes (`server._state`); A-22 não valida dentro de
  `GameConfig` (evita mudar semântica de testes); A-25 altera levemente a UX de
  interação (decisão documentada).
- **Hipóteses (não reproduzidas):** causas prováveis de G-21/G-22/G-25/G-27 =
  handlers e teardowns implementados para fluxos felizes, sem edge-cases.
- **Dependências externas:** G-16 (LAN — 2ª máquina); G-29 (Ericson — acesso ao
  texto).
- **Inconclusivos com ação de verificação:** G-26 → A-24; G-29 → A-27; G-14 → A-23.
- **Divergências de revalidação:** G-05 reclassificado (jogo atendido; votação = G-21);
  G-02 funcional atendido, documental = G-24; A-16 registrou "smoke 3+" vs prescrição
  "5" (cosmético, sem impacto).

## 7. Definição global de concluído

Todas as lacunas encerradas quando observável:

1. G-21: ESC na votação retorna ao menu e derruba a conexão (teste com servidor real).
2. G-22: `ProtocolError` na UI encerra client/server (teste verde).
3. G-23: CLI rejeita tick-rate/max-players/porta inválidos com exit ≠ 0 e mensagem.
4. G-24: README descreve `already_joined`; sem divergência doc×código.
5. G-25: todos os exits de `_run` chamam `close()`.
6. G-26: testes de `lobby_full`/`game_in_progress`/`bad_version` verdes; decisão
   registrada no código.
7. G-27: nenhuma constante de alcance mágica na UI.
8. G-14: teste ESC com servidor real; `pygame.init()` balanceado.
9. G-16: roteiro LAN executado ou reclassificado por decisão explícita.
10. G-29: citação requalificada no plano.
11. Regressão transversal re-executada nesta rodada (ruff/mypy/pytest/smoke/lock).
12. Invariantes: sem dependência nova; `uv.lock` inalterado; wire-compatible;
    sem `Any` novo.

## 8. Referências

- Fontes internas: `src/codecon_amoung_us/` (server, client, dispatch, protocol,
  framing, game/*, ui/app, config, map/model), `tests/`, `plans/among-us-mvp.md`,
  `plans/lacunas-pos-auditoria.md`, `README.md`, `pyproject.toml`, `uv.lock`,
  `assets/maps/skeld.json`.
- Pesquisa (2026-08-29): searchmesh scholarly (desconexão/abandono, colisão 2D,
  dedução social) — sem trabalho aplicável; arXiv API com range → HTTP 429/500
  (limitação); Semantic Scholar rate-limited (parcial).
- Citações externas já verificadas (auditoria m0032): Alangari & Alharbi 2025
  (arXiv:2512.21377v1); Bertin et al. 2026 (arXiv:2606.06013v1); Webb, Soh & Lau
  2007 (RACS, NOSSDAV, OpenAlex W2103269902); Joho et al. 2024 (arXiv:2402.15281);
  Son et al. 2025 (arXiv:2509.00499); Sui et al. 2025 (arXiv:2409.09918); Ericson
  2005 (não integralmente verificável — G-29); PyPI (versões das deps).

## 9. Resultados da execução

Executado integralmente em 2026-08-29 (modo build). Resultados:

| Ação | Status | Evidência |
| --- | --- | --- |
| A-20 close explícito | ✅ | `server.py::_run` — `self.close()` no `finally` (antes de `on_disconnect`); suíte verde |
| A-22 validação CLI | ✅ | `_server_config` pura em `server.py`; `main` converte em `parser.error`; `tests/test_cli.py` novo (13 testes: 2 unit + 7 param inválidos + 4 param `SystemExit(2)`) |
| A-24 rejeições do join | ✅ | `_raw_join` helper; `lobby_full` (servidor `max_players=1`), `game_in_progress`, `bad_version` direto (socketpair) — 3 testes novos; branch `bad_version` comentado como defesa em profundidade |
| A-18 ESC na votação | ✅ | `_exit_to_main()` extraído; `_render_voting` trata KEYDOWN ESC; game/gameover reutilizam |
| A-21 teardown ProtocolError | ✅ | `_handle_message` chama `_shutdown_connection()` antes de `_show_error`; teste com servidor real |
| A-23 testes UI | ✅ | ESC com `GameServer` local + `SimulatedClient` (assert client/server None); **desvio documentado**: `pygame.quit()` removido da fixture e do teste de botão — ciclo quit→init corrompe o cache global de fontes do pygame-menu e segfaulta (exit 0xC0000005 observado); comentário no código |
| A-25 constantes de alcance | ✅ | `config.py` +`KILL_RADIUS`/`REPORT_RADIUS` (defaults de `GameConfig`); UI usa nos gates de R/Space; grep: nenhum 45 residual |
| A-19 README | ✅ | Novo bullet "Join duplicado" em Decisões de protocolo |
| A-26 glue WASD | ✅ | `test_game_movement_sends_normalized_move` (monkeypatch `get_pressed` + `move` espiada) |
| A-27 Ericson requalificado | ✅ | Nota em `lacunas-pos-auditoria.md` §3 (G-29): técnica validada por teste determinístico; citação canônica não verificada integralmente |
| A-28 LAN | ⏸️ NÃO EXECUTADA | ambiente com 1 máquina; roteiro registrado |

**Contagem de testes:** 129 → **148 passed** (`uv run pytest tests/ -q --no-cov`,
41.6 s, exit 0). Novos: `tests/test_cli.py` (13), rejeições do join (3),
UI (3 novos + 1 reescrito com servidor real).

**Cobertura:** 78% → **81%** (1698 stmts, 258 miss, 498 partial) —
`uv run pytest tests/ -q --cov-report=term`, 2026-08-29.

**Validação final (exit codes):** ruff format=0, ruff check=0, mypy=0
(37 source files), `uv lock --check`=0, pytest=0 (148 passed), smoke=0 (2
execuções "SMOKE MULTIPLAYER OK").

**Divergências registradas durante a execução:**
- A-23: o critério "pygame.init() balanceado com quit" foi **revertido por
  evidência**: após `pygame.quit()` + `pygame.init()`, o cache global de fontes
  do pygame-menu mantém objetos SDL liberados e o próximo `Menu.__init__`
  segfaulta (0xC0000005). Decisão: nenhum `pygame.quit()` no meio da suíte;
  SDL dummy encerra no processo. Custo: higiene reduzida, robustez maior
  (documentado no código do teste).
- A-24: `bad_version` confirmado inalcançável via wire (constraint
  `ProtocolVersion` `ge=1, le=1` — `protocol.py`); mantido como defesa em
  profundidade e testado por chamada direta (o teste comprova que, se a
  constraint mudar, o caminho responde corretamente).