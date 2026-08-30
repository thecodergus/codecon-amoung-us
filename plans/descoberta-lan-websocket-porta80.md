# Plano: Descoberta LAN + Transporte WebSocket (porta 80)

Data: 2026-08-30. Status: em execução.

> Diretriz adicional (2026-08-30, durante o build): **WebSocket é o
> transporte padrão ouro; TCP cru é o fallback**. O cliente tenta WS primeiro
> (`connect_auto`), o anúncio de descoberta carrega ambas as portas e a UI
> assume WS como padrão.

## Objetivo

1. **Eliminar a necessidade de IP manual em LAN**: o jogo anuncia-se via UDP
   broadcast e o cliente lista partidas abertas para conexão com um clique.
2. **Atravessar firewalls corporativos sem criar regras**: transporte WebSocket
   (padrão da web, porta 80/443) como alternativa ao TCP cru, com fallback
   automático. Cenário confirmado: **mesma rede local (evento/empresa)**;
   relay/hole-punching (internet) fora de escopo.

## Contexto confirmado

- Servidor TCP thread-por-conexão, game loop 20 Hz, framing JSON Lines
  (`framing.py`), protocolo `msgspec` (`protocol.py`).
- O host embutido na UI faz bind em `127.0.0.1` (`ui/app.py:457`) — hoje
  ninguém na LAN consegue conectar nem sabendo o IP.
- Join exige IP+porta digitados (`ui/app.py:347-354`); porta padrão 5555;
  CLI do servidor aceita `--host/--port` (`net/server.py:986-992`).
- `GameServer` só toca `ClientConnection` via interface pública pequena:
  `player_id`, `nickname`, `start()`, `send(Message)`, `close()`,
  `join(timeout)`, além de `enqueue()`/`on_disconnect()`. Um irmão WebSocket
  com a mesma interface exige zero mudança no game loop.
- PESQUISADO (web): WebSocket atravessa proxies/firewalls corporativos —
  começa como HTTP GET + Upgrade; `wss://` (443) é o mais robusto, `ws://`
  (80) passa em firewalls por porta e pela maioria dos proxies, mas proxies
  com inspeção podem remover o Upgrade em tráfego não criptografado
  (websocket.org/reference/wss-vs-ws).
- PESQUISADO: `websockets` >=13 oferece API `websockets.sync.server.serve()` /
  `sync.client.connect()` baseada em threads
  (websockets.readthedocs.io/en/stable/reference/sync) — encaixa na
  arquitetura atual sem asyncio.
- PESQUISADO: mDNS/multicast falha com frequência em redes corporativas/de
  evento (multicast dropado, client isolation em APs). UDP broadcast simples
  + fallback manual é a escolha minimalista; **com client isolation nada
  ponto-a-ponto funciona** (nem discovery, nem porta 80) — documentado como
  limitação, não como bug.
- Toolchain: `uv` + ruff + **mypy strict** + pytest (markers `integration`,
  timeout 15s).

## Etapas

### Etapa 1 — Host embutido acessível pela LAN

- `ui/app.py` (`_connect_worker`): `GameServer(host="0.0.0.0", ...)`; o
  cliente local continua conectando em `127.0.0.1:port`.

### Etapa 2 — Módulo de descoberta `net/discovery.py` (novo)

1. Constantes em `config.py`: `DISCOVERY_PORT = 5557` (UDP),
   `DISCOVERY_MAGIC` (campo `magic` no payload), intervalo de beacon 1 s,
   escuta de 2.5 s, `MAX_DISCOVERY_BYTES = 512`.
2. `GameAnnouncement` (msgspec Struct): `magic`, `protocol_version`,
   `host_name`, `players`, `max_players`, `tcp_port`, `ws_port: int | None`.
3. `DiscoveryBeacon` (host): thread daemon que envia o anúncio para
   `255.255.255.255:DISCOVERY_PORT` a cada 1 s enquanto o servidor estiver em
   `Phase.LOBBY` (estado via callback fornecido pelo `GameServer`).
   `SO_BROADCAST`; shutdown idempotente via `threading.Event`.
4. `discover_games(timeout)` (cliente): socket UDP com `SO_REUSEADDR`
   (+ `SO_REUSEPORT` sob `contextlib.suppress(OSError)`) em
   `("", DISCOVERY_PORT)`; coleta por `timeout`, valida via msgspec, descarta
   datagramas malformados/versão incompatível, deduplica por
   `(ip, tcp_port)`, retorna `list[DiscoveredGame]`.
5. `GameConfig` ganha `announce: bool = True`; `GameServer.start()` sobe o
   beacon quando `announce`, `stop()` o derruba.
- Testes: unitários de encode/decode e rejeição de payload; integração
  (marker `integration`) com datagrama unicast para `127.0.0.1:DISCOVERY_PORT`.

### Etapa 3 — Transporte WebSocket (porta 80/443)

1. Dependência: `uv add "websockets>=15,<18"` (única dep nova).
2. `net/ws.py` (novo):
   - `WSClientConnection`: mesma interface pública de `ClientConnection`;
     recv loop itera `for data in ws:` e alimenta o mesmo `FrameDecoder` com
     `data.encode() + b"\n"` — reutiliza toda a validação do protocolo.
     `send()` serializa com `framing.encode_frame()` menos o `\n` final e
     envia como texto WS.
   - `serve_ws(server, host, port)`: `websockets.sync.server.serve()` em
     thread daemon; handler espelha o `_accept_loop`.
3. `GameConfig` ganha `ws_port: int | None = None`; `GameServer.start()` sobe
   o listener WS quando definido; CLI ganha `--ws-port`. TCP cru permanece.
4. `GameClient.connect_ws(host, port, nickname, timeout)` usando
   `websockets.sync.client.connect()`; mesmo `FrameDecoder`.
5. Porta 80: configuração (`--ws-port 80`); README documenta
   `sudo setcap 'cap_net_bind_service=+ep' <python do venv>` (Linux) e a
   autorização de um clique do firewall de host. TLS/wss fora de escopo.
- Testes: `tests/test_ws_integration.py` (marker `integration`) — join,
  movimento, snapshot via WS.

### Etapa 4 — UI: lista de partidas + conexão sem IP

1. Menu "Entrar em partida": botão "Buscar partidas na rede" — worker
   não-bloqueante (mesmo padrão de `_start_connect_worker`) roda
   `discover_games(2.5s)` e publica resultados.
2. Tela de resultados: uma entrada por partida
   (`"<host_name> — <ip> (<players>/<max_players>)"`); selecionar preenche
   `join_ip`/`join_port` e dispara `_join_game`. Mensagem "Nenhuma partida
   encontrada" com campos manuais como fallback.
3. Fallback de transporte: partida descoberta tenta TCP em `tcp_port`; em
   `OSError`/`TimeoutError` e `ws_port` anunciada, tenta WS. Nos campos
   manuais, seletor "Transporte: TCP/WebSocket" (default TCP).
4. Menu "Criar partida": exibir IP local da interface (socket UDP sem
   tráfego: `connect(("192.0.2.1", 80))` + `getsockname()`) como fallback de
   compartilhamento; campo porta aceita `80`; seletor "WebSocket na porta:"
   (vazio = desligado).
- Testes: padrão de `test_ui_smoke.py`/`test_ui_events.py` para a nova tela,
  sem rede real (lista injetada).

### Etapa 5 — Docs e fechamento

- README: seção "Jogar em rede" — descoberta, limitação de client isolation,
  porta 80 e `setcap`, quando usar WS.
- Suíte completa + lint + tipos.

## Riscos e decisões

- **Client isolation (Wi-Fi de evento/empresa)**: bloqueia broadcast E
  conexões diretas — nenhuma implementação ponto-a-ponto resolve. Campo
  manual permanece; se nem IP manual funcionar, a rede exigiria relay público
  (fora de escopo; WebRTC/STUN/TURN pesquisado como caminho futuro).
- **Firewall de host**: escutar porta 80 não dispensa a autorização do
  firewall do próprio host; o ganho real é contra firewalls de rede entre
  segmentos e proxies, que tipicamente liberam 80/443. Comunicado no README.
- **`ws://` vs `wss://`**: proxies com inspeção podem remover o Upgrade em
  `ws://`. `wss://` exige certificado confiável (domínio + Let's Encrypt) —
  inválido para uso ad-hoc. Decisão: `ws://` agora; TLS como extensão futura.
- **Porta 80 ocupada/privilegiada**: falha de bind vira mensagem clara na UI
  (`_show_error`), não crash.
- **Dependência nova**: `websockets` é a única; nome exato conferido no
  `uv add` (typosquatting) e lockfile no commit.
- Suposição: broadcast `255.255.255.255` basta no cenário-alvo; broadcast por
  interface (múltiplas NICs/VPN) é melhoria futura se houver relato.

## Verificação

1. `uv run pytest -m "not slow"` — suíte rápida verde com os novos testes.
2. `uv run pytest -m integration` — TCP cru e WS: join, movimento, snapshot.
3. `uv run ruff check . && uv run mypy` — zero erros (strict).
4. Smoke manual: host anuncia → cliente lista e conecta sem digitar IP.
5. Aceite: (a) partida aparece na lista em <=3 s na mesma LAN; (b) conexão
   por um clique sem IP; (c) servidor com `--ws-port 80` aceita cliente WS;
   (d) suíte TCP existente inalterada e verde.
