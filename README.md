# codecon-amoung-us

MVP multiplayer estilo Among Us: servidor TCP autoritativo, protocolo 100%
tipado (`msgspec`), mapa orientado a dados (Tiled via `pytiled-parser`),
personagens com sprites duckee e cliente Pygame com menus, HUD e votação
secreta. O mapa padrão é a cena do lab (pack "Top Down Lab") com colisão,
spawns e tarefas extraídos programaticamente.

## Stack

- Python 3.13.x (projeto `uv`)
- Runtime: `pygame` 2.6.1, `msgspec` ≥0.21, `pytiled-parser` ≥2.2.9, `pygame-menu` 4.5.2
- Dev: `pytest` ≥9, `hypothesis` ≥6, `ruff` ≥0.16, `mypy` ≥2, `pytest-timeout`, `pytest-cov`

## Execução

```bash
uv sync                                    # instala dependências (preserva uv.lock)

uv run codecon-amoung-us                   # cliente: menus (host/join), lobby e jogo
uv run codecon-amoung-us-server            # servidor standalone (porta 5555 padrão)
uv run python scripts/smoke_multiplayer.py # smoke headless: servidor + 4 clientes
```

No cliente, o host pode iniciar uma partida direto pelo menu Criar partida (o
servidor é embutido em thread no mesmo processo); a opção Entrar em partida
conecta em um servidor standalone (`127.0.0.1:5555` por padrão, configurável
na tela de join). A conexão acontece em thread própria (a interface continua
responsiva e exibe "Conectando ao servidor…", cancelável). A tela de jogo
mostra a cena do lab com os personagens duckee (8 cores, animações
idle/walk/death) e um HUD inferior compacto (~64 px) com papel, progresso de
tarefas, vivos, cooldown do impostor e prompt contextual de ação.

Servidor standalone:

```bash
uv run codecon-amoung-us-server --host 0.0.0.0 --port 5555 \
    --max-players 10 --tick-rate 20
```

## Controles (tela de jogo)

| Ação | Tecla |
| --- | --- |
| Mover | WASD |
| Interagir (abrir minigame da tarefa próxima ou botão de reunião) | E |
| Jogar minigame da tarefa | Mouse (arrastar/clicar) ou Espaço, conforme o puzzle |
| Abandonar minigame (sem completar a tarefa) | ESC (com o puzzle aberto) |
| Reportar corpo | R (perto de um corpo) |
| Matar (impostor) | Espaço (alvo próximo e cooldown respeitado; recusas viram toast) |
| Votar | Mouse (card inteiro selecionável; Skip para pular) |
| Foco de teclado (menus/lobby/votação) | Tab / Shift+Tab / Enter |
| Sair do jogo | ESC |

Tarefas são minigames obrigatórios (7 tipos: ligar fios, reparar circuito,
passar cartão, calibrar sensores, limpar filtro, reativar reator, destruir
asteroides): a conclusão só vai ao servidor depois de resolver o puzzle.
O mundo não pausa com o puzzle aberto — morrer ou iniciar reunião fecha o
minigame sem completar a tarefa.

Recusas de ação (`ActionDenied` tipado) sempre geram feedback: toast no
gameplay/votação ou aviso no lobby. O cooldown de eliminação aparece no HUD
do impostor ("Kill: Ns" + contador no prompt).

## Janela e acessibilidade

- A janela é redimensionável (RESIZABLE): o jogo renderiza em resolução
  lógica 1280×768 e aplica letterbox preservando o aspect (sem esticar).
- Redução de movimento: menu **Configurações** → "Reduzir movimento" (aplica
  imediatamente, sem reiniciar). O valor inicial pode ser definido por
  `CODECON_AMONG_US_REDUCED_MOTION=1`. Desativa a pulsação contínua dos
  marcadores e animações ornamentais.
- Captura determinística de estados da UI para QA visual:
  `uv run python scripts/capture_ui_states.py` (grava PNGs em `captures/`).

## Smoke multiplayer (4 instâncias)

`scripts/smoke_multiplayer.py` sobe o **servidor standalone real** (subprocesso,
mesmo venv, porta efêmera) e conecta 4 clientes simulados, executando o roteiro:

1. 4 clientes conectam no lobby (JoinAccepted + PlayerJoined);
2. o host inicia a partida (StartGame + RoleAssigned, exatamente 1 impostor);
3. o impostor navega até um tripulante, mata e o corpo aparece no snapshot;
4. o impostor reporta o corpo → MeetingStarted (`kill_reported`);
5. votação: o impostor pula, os tripulantes votam nele → ejetado;
6. verificação: `Ejected` (com papel) chega **somente** ao ejetado; todos
   recebem `MeetingEnded` `{meeting_id}` (sem resultado); `GameOver` revela
   os papéis (tripulantes vencem).

Exit code 0 = sucesso (a saída do servidor é impressa no stderr em caso de falha).
Rodar com `uv run python scripts/smoke_multiplayer.py`.

## Arquitetura

```
src/codecon_amoung_us/
  __init__.py        main() → ui/app.py (cliente)
  __main__.py        python -m codecon_amoung_us
  config.py          GameConfig (tick_rate, speed, kill_radius, cooldowns, limites)
  protocol.py        msgspec: mensagens tipadas, união Message, encoder/decoder
  framing.py         JSON Lines: encode_frame, FrameDecoder (fragmentação)
  game/              domínio puro: model, rules, physics, tasks, voting, meeting
  map/               model.py (Rect, SpawnPoint, TaskPoint, GameMap) + loader.py
  net/               server.py (GameServer autoritativo + CLI) + client.py
                     (GameClient: usado pela UI; helpers p/ testes e smoke)
                     + dispatch.py (sigilo)
  ui/                app.py (App, menus, jogo, votação) + render.py +
                     sprites.py (duckee) + puzzles/ (7 minigames de tarefa:
                     lógica pura testável + wrapper pygame)
assets/maps/lab.json      mapa Tiled (70x38, 64px, 4480x2432): paredes, spawns,
                          14 tarefas (7 tipos), botão de emergência, 12 salas —
                          gerado pelo build_lab_map.py
assets/maps/lab_scene.png cena do lab em resolução de mundo (fundo do jogo)
assets/maps/skeld.json    mapa Tiled legado (40x30, 32px) — suportado pelo
                          loader, não é mais o padrão
models/duckee/            sprites dos personagens (8 cores, idle/walk/death)
models/mapa/              pack do mapa "Top Down Lab", de Luis Zuno
                          (@ansimuz — ansimuz.itch.io; licença permissiva em
                          "Top Down Lab files/public-license.txt"): tileset
                          da cena + overlay de QA
scripts/build_lab_map.py  gera assets/maps/lab.json + cena 2560x1408 a
                          partir do layout declarado de salas/corredores
scripts/smoke_multiplayer.py   smoke headless da Etapa 14
tests/               pytest: unitários, Hypothesis, integração, UI smoke
plans/among-us-mvp.md plano de execução (decisões de protocolo e etapas)
```

Decisões de protocolo principais:

- **Framing:** JSON Lines (`<json>\n`); frame malformado → `ProtocolError` +
  fechamento da conexão; ações de jogo inválidas → `ActionDenied` (conexão
  mantida).
- **Join duplicado:** um segundo `JoinRequest` na mesma conexão recebe
  `ProtocolError` `already_joined` e a conexão é mantida — o cliente legítimo
  não é expulso (erro de sessão, não ação de jogo).
- **Servidor autoritativo:** thread por conexão (recv + fila de comandos) e
  game loop 20 Hz (movimento com colisão por eixo, validações, broadcast de
  `WorldSnapshot`); fases LOBBY → PLAYING → MEETING → ENDED.
- **Ejeção confidencial (protocolo v2):** `Ejected` (identidade + papel) vai
  somente ao ejetado; todos recebem `MeetingEnded` `{meeting_id}` — sem
  booleano de ejeção, sem votos, sem contagem; papéis só são revelados no
  `GameOver`. Ver "Sigilo da votação" abaixo para o contrato completo.

## Sigilo da votação

Contrato formal (protocolo v2) — o que cada parte sabe após uma votação:

1. **Estado autoritativo (servidor):** conhece o resultado real. O ejetado
   está eliminado (`alive=False`): não executa tarefas, não vota, não mata,
   não reporta e não conta como jogador ativo na condição de vitória.
2. **Visão do ejetado:** recebe `Ejected{player_id, role}` (privado) antes do
   `MeetingEnded` e entra no modo espectador.
3. **Visão dos demais:** recebe **somente** `MeetingEnded{meeting_id}`,
   estruturalmente idêntico para ejeção, empate e skip. Nenhuma mensagem ou
   campo revela quem foi ejetado, o papel ou a contagem de votos.

Cláusula explícita: o estado vivo/morto do ejetado torna-se público no
`WorldSnapshot` seguinte (`alive=False`), indistinguível de uma morte por
kill — como no Among Us original. É decisão de design, não vazamento: o
sigilo proíbe entregar o resultado pela mensagem; inferência decorrente do
comportamento futuro da partida (ex.: quem parou de se mover) está fora de
escopo. Recusas de ação (`ActionDenied`) contra jogadores mortos usam código
e razão uniformes (`NOT_ALIVE`), sem distinguir morte por kill de ejeção.

Resposta à pergunta-chave: **um cliente não ejetado recebe, após a votação,
`MeetingEnded{meeting_id}` e, no próximo snapshot, `alive=false` do ejetado —
nada mais sobre a votação.** Garantido por `net/dispatch.py`
(`dispatch_ejection`, ponto único da política) e por testes sobre os bytes
serializados (`tests/test_secrecy_properties.py`,
`tests/test_integration.py`).
- **Feedback de ações:** ações aceitas confirmam com `ActionAccepted`
  (privado; `KILL` carrega o cooldown iniciado); recusas usam `ActionDenied`
  tipado (`ActionKind` + `DenialCode` + motivo textual + `retry_after_seconds`
  quando aplicável).
- **Votação:** pluralidade; empate → sem ejeção; votos de mortos (inelegíveis)
  ignorados; `target_id = None` = Skip.

## Testes

```bash
uv run pytest                       # suíte completa (unitários + integração + Hypothesis + UI smoke)
uv run ruff format --check . && uv run ruff check .
uv run mypy
```

- Unidade: regras (kill, tarefas, vitória), votação, protocolo (roundtrip +
  rejeição), framing (fragmentação/truncamento), loader do mapa real.
- Hypothesis: votação (5 invariantes), sigilo sobre bytes serializados por
  cliente, framing com chunks arbitrários.
- Integração: 4 clientes simulados contra o servidor real (lobby, início,
  snapshots, kill, reunião, ejeção secreta, empate, tarefa, game over,
  malformed frame).
- UI smoke: headless (SDL dummy) com pygame-menu.

## Limitações conhecidas

- Partida única por servidor: sem rotação de partidas após o game over (é
  preciso reiniciar o servidor para uma nova rodada).
- Mapa padrão é o lab (`assets/maps/lab.json`, mundo 2560x1408 com 7 salas),
  gerado pelo `build_lab_map.py` a partir do tileset do pack "Top Down Lab";
  o loader aceita outros Tiled (ex.: `skeld.json`), mas a navegação dos
  testes/smoke assume o layout gerado pelo `build_lab_map.py`. O gameplay usa
  câmera 2D que segue o jogador local (viewport lógico 1280x704).
- Sem reconexão: desconectar durante a partida remove o jogador (com
  promoção de host no lobby).
- Sem persistência: sem histórico, ranking ou contas.
- Colisão ponto-único (sem raio do jogador): física mínima suficiente para o MVP.