# Plano — Lacunas remanescentes da auditoria do modo LAN

> Origem: auditoria técnica dos commits `0af3bb4..c375a36` (2026-08-31).
> Classificação e evidências detalhadas no relatório de auditoria; este plano lista
> apenas o trabalho acionável. Itens atendidos (cascata de transportes, pin wss com
> teste em nível de socket, sweep, HTTP long polling, cascata de portas, suíte 923
> passed) não entram no plano.

## Lacunas

| ID   | Lacuna                                                                            | Status                | Prioridade |
| ---- | --------------------------------------------------------------------------------- | --------------------- | ---------- |
| G-01 | Auditoria de dependência (HC8) — `uv audit` executado nesta sessão: 0 vulns/30 pkts | atendido              | P3         |
| G-02 | README: seção Tailscale instrui fluxo inoperante sem admin (userspace = SOCKS5)   | atendido incorretamente | P1         |
| G-03 | Cliente sem suporte a proxy SOCKS5 (cenário mais duro de rede)                    | não atendido (opcional) | P3         |
| G-04 | Handler HTTP sem endurecimento (Content-Length, teto de corpo/sessões)            | parcialmente atendido | P2         |
| G-05 | Citações não verificadas (websocket.org; tailscale#2791)                          | inconclusivo          | P3         |
| G-06 | Coexistência REUSEPORT beacon+responder na mesma máquina sem teste                | inconclusivo          | P3         |
| G-07 | `assert` como guarda de fluxo em `start_host_server`                              | atendido incorretamente | P3         |
| G-08 | Condição morta em `drain()` (`http_poll.py`)                                      | atendido incorretamente | P3         |
| G-09 | Parágrafo README "Correção de permissões (requer admin)" stale desde 520be26      | atendido incorretamente | P3         |
| G-10 | Eficácia em rede restritiva real não observada                                    | bloqueado (ambiente)  | P2         |
| G-11 | "Jogável" do HTTP long polling sem métrica                                        | inconclusivo          | P3         |
| G-12 | Teste intermitente `test_solo_host_starts_and_wins_by_tasks`                      | inconclusivo          | P2         |

## Ações (fases)

### Fase 1 — P1

- **A-02** (G-02, G-09, com A-07): reescrever a seção Tailscale do README —
  modo userspace entrega o tailnet via proxy SOCKS5/HTTP (sem rota direta para
  100.x.y.z); o jogo não tem suporte a proxy; conexão direta por IP exige
  adaptador (admin). Remover o parágrafo stale "Correção de permissões (requer admin)".
- **A-07** (G-05): acessar `websocket.org/reference/wss-vs-ws` e a issue
  `tailscale#2791`; manter com ano/versão arquivada ou substituir/remover.

### Fase 2 — P2

- **A-03** (G-04): endurecer `net/http_poll.py`: `Content-Length` não numérico → 400;
  corpo > teto (64 KiB) → 413 (RFC 9110); teto de sessões simultâneas
  (`config.py`, `HTTP_POLL_MAX_SESSIONS`, 503 acima). Testes negativos.
- **A-04** (G-12): diagnosticar `test_solo_host_starts_and_wins_by_tasks` — loop
  30×; causa de timing/concorrência é hipótese (Parry 2025 arXiv:2504.16777;
  Berndt 2026 preprint arXiv:2602.03556: concorrência predominante). Sem
  correção especulativa; documentar resultado.
- **A-05** (G-10): roteiro de teste de campo (4 cenários: VLAN filtra broadcast,
  proxy com inspeção, proxy HTTP-only, isolamento de clientes) em
  `plans/protocolo-teste-campo-lan.md`; execução real depende de ambiente externo.

### Fase 3 — P3

- **A-06** (G-07, G-08): `assert` → `raise RuntimeError` em `server.py`;
  remover condição morta em `drain()`.
- **A-01** (G-01): formalizar `uv audit` no Definition of Done (AGENTS.md).
- **A-08** (G-06): teste de coexistência beacon+responder na mesma máquina
  (tolerância a distribuição de datagramas do SO_REUSEPORT).
- **A-11** (G-11): microbenchmark localhost ws vs http-poll (mediana/p95);
  documentar número ou declarar limitação.
- **A-10** (G-03): **requer decisão do usuário** — cliente SOCKS5 mínimo stdlib
  (RFC 1928: no-auth + CONNECT + IPv4) atrás de opt-in, ou dependência
  `python-socks`. Pendente de decisão; não implementado neste ciclo.

## Referências

- Tailscale, "tailscaled daemon" (2026-01-05) e "Userspace networking mode" (2025-11-12) — mecanismo userspace = proxy.
- RFC 1928 (SOCKS5), RFC 9110 (HTTP Semantics) — especificações normativas.
- Parry et al., arXiv:2504.16777 (2025); Berndt et al., arXiv:2602.03556 (2026, preprint) — flaky tests.
- `uv audit` (uv 0.11.8) — 0 vulnerabilidades em 30 pacotes (2026-08-31).
