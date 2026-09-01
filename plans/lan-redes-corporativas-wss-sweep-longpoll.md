# Plano: LAN resiliente em redes corporativas — wss, sweep unicast, long polling HTTP

Data: 2026-08-31. Status: em execução. Decisões do usuário (2026-08-31):
Etapa 3 = implementar AGORA; Tailscale = escape hatch documentado.

## Objetivo

Cascata de transporte e descoberta que maximiza a chance de conectar em redes
corporativas restritivas, sem admin/sudo e sem infra própria:
**descoberta** broadcast → sweep unicast; **transporte** wss (TLS, pin por
beacon) → ws → HTTP long polling → TCP cru. Tailscale userspace documentado
como último recurso manual.

## Contexto confirmado (OBSERVADO)

- `net/ws.py`: `WSClientConnection` replica a interface de `ClientConnection`
  (`run/send/close/player_id/nickname`); servidor sobre
  `websockets.sync.server.serve` (websockets ≥17.1) — `ssl_context` do
  `serve()` dá wss sem mudar o game loop.
- `net/discovery.py`: beacon UDP com `GameAnnouncement(msgspec,
  forbid_unknown_fields=True)` — campos novos quebram decode em binários
  antigos (ver Riscos). O host hoje **só envia**; não há listener UDP do lado
  do host (o cliente escuta passivamente) — o sweep unicast exige responder
  do host.
- `net/client.py`: `connect_auto` (client.py:93) tenta `("ws", ws_port)` →
  `("tcp", tcp_port)` e propaga `ConnectionError` encadeada.
- `net/server.py::start_host_server` (server.py:1094): cascata sem admin
  `(tcp, ws)` → `(tcp, sem ws)` → `(efêmera, sem ws)`; bind `0.0.0.0`.
- `config.py`: constantes de discovery centralizadas; `GameConfig` imutável.
- `cryptography` **não está no lockfile**; stdlib `ssl` não gera certificado.

## Contexto de execução (2026-08-31)

- WIP pré-existente do protocolo v4 (`map_seed` opcional/modo asset) toca os
  mesmos arquivos (`config.py`, `server.py`, `ui/app.py`, README) — staging
  parcial: **apenas os hunks deste plano** entram nos commits.

## Etapa 1 — wss:// com cert self-signed + pin por beacon

1. **Dependência:** `uv add cryptography` após vetting supply-chain
   (depscope indisponível → verificação manual: nome exato, projeto pyca,
   auditoria do ambiente após instalação). Fallback honesto: subprocess
   `openssl req -x509`; sem nenhum dos dois, listener sobe sem TLS e o
   anúncio não leva fingerprint (cascata segue em ws/tcp).
2. **Novo `net/tls.py`:** cert self-signed em memória (EC, validade curta) +
   `fingerprint()` (SHA-256 do DER, hex).
3. **`net/ws.py`:** `WSListener`/`serve` recebe `ssl_context`; com TLS, a
   ws_port serve **apenas wss**.
4. **Beacon:** `GameAnnouncement` ganha `tls_fingerprint: str | None` e
   `http_port: int | None`; `DiscoveredGame` espelha. Cliente constrói
   `SSLContext` confiando **só** no cert anunciado (pin). Join manual sem
   beacon: sem pin (documentado).
5. **`net/client.py`:** `connect_wss(...)` espelhando `connect_ws`;
   `connect_auto` vira `wss → ws → http (Etapa 3) → tcp`.
6. **Verificar:** unitários de geração/fingerprint; integração wss com pin
   correto + rejeição de fingerprint errado; suíte ws verde.

## Etapa 2 — Descoberta por sweep unicast (fallback do broadcast)

1. **Host (responder):** thread em `net/discovery.py` com socket UDP
   `0.0.0.0:5557` + `SO_REUSEADDR`: recebe probe e responde **unicast** com o
   `GameAnnouncement` corrente.
2. **Cliente (sweeper):** escuta passiva vazia → probes unicast
   `x.x.x.1–254:5557`, pacing ~20 pps (constantes em `config.py`); respostas
   alimentam a lista de `DiscoveredGame`.
3. **UI:** busca vazia dispara o sweep ("varrendo a rede…") antes das dicas
   de diagnóstico.
4. **Verificar:** unitários do gerador de alvos/parser (mock de socket);
   integração responder↔sweeper em loopback; `tests/test_discovery.py` verde.

## Etapa 3 — HTTP long polling como transporte (decisão do usuário: agora)

1. **Novo `net/http_poll.py`**, sem dependência nova
   (`ThreadingHTTPServer` da stdlib):
   - `POST /connect` (nickname) → sessão (`session_id` UUID); não faz join.
   - `POST /send?session=…` — corpo JSON Lines (mesmos frames do TCP).
   - `GET /poll?session=…` — long poll: retorna quando há mensagens ou
     ~25 s (heartbeat).
   - GC de sessão por inatividade (60 s) → `on_disconnect`.
   - `HttpPollClientConnection` com a interface de `WSClientConnection`.
2. **Porta:** `http_port = tcp_port + 2` (evita colisão conceitual com a UDP
   5557 da descoberta); cascata em `start_host_server` estende com degraus de
   porta efêmera; anúncio divulga `http_port`.
3. **Cliente:** `connect_http_poll(host, port, nickname)`; entra no
   `connect_auto` **antes** do TCP. Tick efetivo reduzido — documentar como
   "modo compatibilidade: jogável, não competitivo".
4. **Verificar:** integração sobre HTTP puro; smoke na cascata completa;
   timeouts de sessão.

## Etapa 4 — Documentação (README + firewall_hints)

- Seção "Redes corporativas": cascata completa e por que cada degrau existe.
- **Tailscale (decidido):** escape hatch manual — modo userspace sem admin
  (tailscale#2791 no Windows; userspace-networking com SOCKS5 no Linux),
  fora do escopo de suporte, sujeito a política da empresa.
- Limites honestos: client isolation sem contorno LAN; CONNECT de proxy não
  alcança IPs LAN; descoberta não autenticada.

Ordem: 1 e 2 independentes; 3 depende do contrato do anúncio da Etapa 1
(`http_port`); 4 fecha.

## Riscos e decisões

- **Compat do anúncio:** `forbid_unknown_fields=True` faz cliente antigo
  rejeitar beacon novo → descoberta entre versões mistas degrada para IP
  manual. Aceito (mesmo build em evento). Bump de `PROTOCOL_VERSION`
  desnecessário.
- **wss na ws_port:** cliente antigo (ws puro) não conecta em host novo com
  TLS ativo. Mesma classe de risco; aceito.
- **Pin via beacon só é tão confiável quanto o beacon** (descoberta não
  autenticada): TLS compra **sigilo contra inspeção passiva** e
  atravessabilidade, não autenticação do host — documentar assim.
- **Sweep pode parecer scan para IDS** — pacing baixo; documentado.
- **Long polling** a 20 Hz multiplicaria requisições: long poll responde
  assim que há dados (sem polling cego); latência > ws/tcp.

## Verificação

1. `uv run ruff check --fix . && uv run ruff format .` + `uv run mypy .`.
2. `uv run pytest -v` — suíte completa + novos testes.
3. `uv run python scripts/smoke_multiplayer.py`.
4. Manual em rede corporativa restritiva quando disponível (fora do repo).

## Fontes de pesquisa (searchmesh, 2026-08-31)

- websocket.org/reference/wss-vs-ws — wss opaco a intermediários; ws falha
  silenciosamente atrás de firewall corporativo.
- websockets.readthedocs.io/en/stable/howto/encryption.html — cliente
  configurável para confiar em cert self-signed.
- rtcquickstart.org + nginx.org/en/docs/http/websocket.html — CONNECT de
  proxy restrito a 443; Upgrade é hop-by-hop.
- techinterview.org / SignalR — long polling é o fallback canônico quando WS
  é bloqueado; proxies com buffering matam SSE.
- salivity.github.io + adhdecode.com — QUIC/UDP 443 bloqueado em redes
  corporativas → WebTransport rejeitado.
- GitHub tailscale#2791 + docs userspace-networking — Tailscale sem admin;
  ZeroTier exige adapter (rejeitado).
- Cisco/Aruba (VLAN docs) — broadcast filtrado entre VLANs, unicast
  intra-subnet passa → sweep unicast (INFERIDO).
