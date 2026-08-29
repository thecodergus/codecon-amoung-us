# Plano — MVP Among Us-like (codecon-amoung-us)

Data: 2026-08-29
Status: aprovado para execução

## Objetivo

Construir do zero, em `C:\Users\gustavo.camargo\codecon-amoung-us`, um jogo multiplayer TCP autoritativo estilo Among Us: lobby (host/join), partida com papéis (impostor/tripulante), movimento com colisão, tarefas, kill, corpos, reuniões de emergência, votação secreta com ejeção confidencial e game over.

- Protocolo 100% tipado com `msgspec` + framing JSON Lines centralizado.
- Mapa carregado de asset Tiled via `pytiled-parser` (asset hand-authored, editor Tiled não necessário).
- Servidor e clientes simulados testáveis sem Pygame.
- UI Pygame implementada por último.
- Toda validação automatizada (pytest + Hypothesis + Ruff + mypy) deve passar.

## Stack

- Python 3.13.x, uv.
- Runtime: pygame==2.6.1, msgspec>=0.21,<0.22, pytiled-parser>=2.2.9,<3.
- Dev: pytest>=9,<10, hypothesis>=6,<7, ruff>=0.16,<0.17, mypy>=2,<3, pytest-timeout==2.4.0.
- pygame-menu 4.5.2: avaliado via smoke test; mantido somente se compatível com pygame 2.6.1 no ambiente efetivo. Nunca usar `pygame_gui`/`pygame-ce`.

## Avaliação de ferramentas adicionais (2026-08-29, durante execução)

Analisadas candidatas para reduzir carga de trabalho sem violar a regra "não introduzir
dependências quando o stack atual resolve".

| Ferramenta | Veredicto | Motivo |
| --- | --- | --- |
| pygame-menu 4.5.2 | ✅ Adicionada (runtime) | Smoke test OK no ambiente efetivo (janela+botão+text input+eventos, `PYGAME_MENU_SMOKE_OK`). Substitui dezenas de telas/widgets manuais (menu/host/join/nickname/IP/porta/lobby/modais). |
| pytest-cov 6.3.0 (+coverage 7.16.0) | ✅ Adicionada (dev) | Nada no stack media cobertura; localiza caminhos de domínio sem teste onde bugs se escondem. Dev-only, estável, suporta 3.13. Config `[tool.coverage]` + `--cov` no addopts. |
| pytest-asyncio | ❌ | Stack usa threads, não asyncio. |
| numpy | ❌ | Movimento/colisão resolvem com `pygame.Vector2`/`Rect` + math puro; dep pesada. |
| rich | ❌ | Logs do servidor resolvem com format string; evita dep runtime desnecessária. |
| pre-commit | ❌ | Projeto não é repositório git. |
| pytest-xdist/randomly/sugar | ❌ | Suíte pequena; cosmético. |
| pydantic/attrs | ❌ | `msgspec.Struct` cobre. |
| `ty` | ❌ | Experimental; não é requisito de aceitação. |

## Decisões de protocolo (confirmadas)

1. Framing: JSON Lines (`<json>\n`). Strings do protocolo excluem caracteres de controle via constraint `pattern` (protege o framing).
2. `Ejected` (com `player_id` e `role`) é enviado SOMENTE ao jogador ejetado. Todos — incluindo o ejetado — recebem `MeetingEnded` com `{meeting_id, ejected: bool}`. Revelação de papéis ocorre apenas no `GameOver`.
3. Votação: pluralidade; empate (máximo não único) → nenhuma ejeção; votos de inelegíveis (mortos) ignorados; `target_id = None` = Skip.
4. Host embute o servidor em thread no mesmo processo; existe também servidor standalone via CLI (`codecon-amoung-us-server`).
5. Frame inválido (malformado/ValidationError) → `ProtocolError` + fechamento da conexão. Ações de gameplay inválidas → `ActionDenied` (sem fechar conexão).

## Arquitetura-alvo

```
src/codecon_amoung_us/
  __init__.py          main() → ui/app.py
  __main__.py          python -m codecon_amoung_us → cliente
  config.py            GameConfig (tick_rate, speed, kill_radius, cooldowns, max_players, impostor_count, map path)
  protocol.py          msgspec: mensagens, enums, aliases, Message union, encoder/decoder
  framing.py           JSON Lines: encode_frame, FrameDecoder (buffer + extração)
  game/                domínio puro (sem pygame/msgspec): model, rules, voting, meeting, tasks
  map/                 model.py (GameMap, Rect, SpawnPoint, TaskPoint) + loader.py (pytiled_parser → GameMap)
  net/                 server.py (GameServer, ClientConnection) + client.py (SimulatedClient) + server/__main__.py
  ui/                  app.py, screens.py, widgets.py, render.py
assets/maps/skeld.json
tests/                 conftest.py, test_protocol, test_framing, test_voting, test_secrecy,
                       test_map_loader, test_rules, test_integration
plans/                 este plano
```

## Etapas de execução (com verificação)

1. **pyproject.toml + uv sync + smoke imports**
   - `requires-python = "==3.13.*"`, dependências runtime e dev conforme stack; `[tool.ruff] target-version="py313"`, line-length 100, select E/F/I/UP/B/SIM, fixable ALL; `[tool.mypy] strict`, python_version 3.13, files src+tests; `[tool.pytest.ini_options]` strict-markers, testpaths tests, timeout default 15 (pytest-timeout), markers slow/integration/ui.
   - Console scripts: `codecon-amoung-us` (cliente) e `codecon-amoung-us-server` (servidor standalone).
   - `uv sync` (preservar `uv.lock`), `uv lock --check`, smoke import de todas as dependências.

2. **Smoke test pygame-menu 4.5.2** — janela + botão + text input + eventos; se falhar, remover e implementar widgets próprios em pygame puro.

3. **Estrutura de pacotes + config** — árvore acima; `GameConfig` frozen dataclass.

4. **Domínio + regras** (`game/`) — `Role`/`Team` StrEnum; `PlayerState`, `Body`, `GameState`; `can_kill` (impostor vivo, alvo vivo, alcance, cooldown), `apply_kill`, `complete_task` (proximidade), `check_win` (impostores ≥ tripulantes vivos → impostores; tarefas todas ou 0 impostores → tripulantes). Testes unitários.

5. **Votação + reunião** — `count_votes(votes, eligible) -> VoteResult` puro/determinístico; `Meeting` (elegíveis = vivos, deadline, add_vote, is_complete); `ejection_messages(result) -> dict[recipient, list[Message]]` (núcleo do sigilo). Testes determinísticos.

6. **Protocolo msgspec** — tagged union `Message` (base `tag=True, forbid_unknown_fields=True, kw_only=True`); mensagens cliente→servidor: JoinRequest, StartGameRequest, MovementInput, KillRequest, BodyReported, EmergencyMeetingRequest, VoteRequest, TaskActionRequest; servidor→cliente: JoinAccepted, PlayerJoined, PlayerDisconnected, StartGame, RoleAssigned, WorldSnapshot, TaskState, MeetingStarted, MeetingEnded, Ejected, GameOver, ActionDenied, ProtocolError. Constraints: nickname (1..12, sem controle), ids ge=0, coleções max_length, protocol_version ==1. Zero `dict[str, Any]`. Testes roundtrip + rejeição.

7. **Framing JSON Lines** — `encode_frame`; `FrameDecoder.feed(data) -> list[Message]`; MAX_FRAME_BYTES; linha vazia ignorada; erro com causa. Testes de fragmentação/truncamento/múltiplos frames.

8. **Mapa Tiled + loader** — `assets/maps/skeld.json` (orthogonal, 40x30, 32px, object layers: floor, walls[collidable], spawn_points[spawn_id], task_points[task_type, interaction_radius], emergency_meeting, decorative[color]); `loader.load_map(path) -> GameMap` via `pytiled_parser.parse_map`; erros claros para layers ausentes. Testes sobre o asset real.

9. **Servidor autoritativo** — thread por conexão (recv loop com settimeout, FrameDecoder, fila de envio com lock), game loop 20 Hz (movimento+colisão por eixo, validações via rules, broadcast WorldSnapshot), estados lobby→playing→reunião→game over, shutdown limpo (context manager, stop idempotente). CLI standalone.

10. **Cliente simulado + lobby/início** — `SimulatedClient` (thread recv timeout 0.2s, wait_for(msg_type, timeout), send); teste de integração: 4 clientes → lobby → start → StartGame + RoleAssigned (1 impostor). Timeout por teste.

11. **Hypothesis** — votação (≤1 voto efetivo, determinismo, empate sem ejeção, ≤1 ejetado, inelegíveis não alteram); sigilo sobre bytes serializados por cliente (não-ejetado só recebe MeetingEnded com campos {type, meeting_id, ejected}); framing (chunks arbitrários → mesma sequência).

12. **Integração multiplayer completa** — kill (alcance/cooldown), report → MeetingStarted, votação com empate e com maioria, Ejected só ao ejetado (asserção sobre mensagens recebidas), tarefa por proximidade, GameOver.

13. **UI Pygame** — App com pilha de telas; menu principal/host/join/lobby/game/reunião/modais; widgets (pygame-menu ou próprios); main() delega.

14. **Smoke multiplayer 4 instâncias** — servidor standalone + 4 clientes; roteiro documentado no README.

15. **Validação final + README** — `uv sync`, `uv lock --check`, `uv run pytest`, `uv run ruff format .`, `uv run ruff check .`, `uv run mypy .`; sem TODOs/comentado/debug prints; README com stack, execução, arquitetura, testes e limitações.

## Riscos e mitigações

- `\n` em strings quebrando JSON Lines → pattern excluindo controles no nickname; demais strings controladas pelo servidor.
- Mypy strict vs stubs ausentes (pygame, pygame-menu, pytiled-parser) → overrides localizados `ignore_missing_imports`; nunca desabilitação global.
- Threads presas → shutdown correto (stop events, settimeout, close idempotente) + pytest-timeout como rede de segurança.
- Versões → conferir no momento do `uv add`; ajustar limites se não resolver.

## Critérios de aceitação (executar todos, não declarar sem rodar)

1. `uv sync` + `uv lock --check` consistentes; `uv.lock` preservado.
2. Mensagens de rede com schemas msgspec tipados; malformadas rejeitadas; sem `dict[str, Any]` no protocolo.
3. Mapa e interações carregados de asset (nada hard-coded).
4. `uv run pytest` verde; nenhum teste de rede pode travar indefinidamente.
5. `uv run ruff format --check .` e `uv run ruff check .` limpos.
6. `uv run mypy .` limpo.
7. Hypothesis (votação, sigilo sobre bytes serializados por cliente, framing) verde.
8. Smoke multiplayer 4 instâncias executado e documentado no README.