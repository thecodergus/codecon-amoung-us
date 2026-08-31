# Plano: LAN sem atrito de firewall — descoberta resiliente + correção em um clique

Data: 2026-08-31. Status: em execução.

## Objetivo

Manter a experiência "criar sala / selecionar sala da lista" já implementada
(`net/discovery.py` + lista de salas em `ui/app.py`) e reduzir o atrito de
firewall ao mínimo possível **em LAN pura**: descoberta que sobrevive a mais
filtros de rede, diagnóstico claro quando algo bloqueia e correção de
permissão automatizada em um clique (opt-in).

**Verdade fundamental da pesquisa (searchmesh, 2026-08-31):** em LAN pura o
atrito nunca chega a zero. O host precisa escutar conexões de entrada, e
firewalls (Windows Defender incluso, por padrão — learn.microsoft.com:
"default block action... must create inbound exception rules") bloqueiam
`listen()` com prompt/exceção. Conexões *outbound* passam livres; o único
desenho sem nenhum prompt é o relay público (padrão Among Us), descartado
por decisão do usuário (sem infra externa).

## Contexto confirmado

- Descoberta por UDP broadcast implementada: `net/discovery.py` (beacon em
  `255.255.255.255:5557`, listener deduplicando por `(ip, tcp_port)`);
  constantes em `config.py` (`DISCOVERY_PORT = 5557` etc.).
- UI já tem lista de salas: "Buscar partidas na rede" (`ui/app.py:378`),
  "Nenhuma partida encontrada" (`ui/app.py:448`), host em `0.0.0.0`
  (`ui/app.py:589`) com fallback WS→TCP em erro de bind (`ui/app.py:590-599`)
  e `_show_error` (`ui/app.py:498`).
- Transporte WS (porta 80/443) já implementado como padrão ouro (`net/ws.py`).
- README já documenta setcap/ufw para porta 80.

**Achados de pesquisa:**

1. mDNS/zeroconf sofre dos mesmos bloqueios do broadcast (multicast 5353
   dropado em redes corporativas, falha silenciosa, nunca cruza VLAN por
   design — 5353.io, dev.to/whetlan). Confirma a decisão registrada em
   `plans/descoberta-lan-websocket-porta80.md`. Não adotar.
2. **Client isolation** bloqueia todo tráfego ponto-a-ponto e não tem
   contorno legítimo para um jogo (AirSnitch, NDSS 2026, é ataque de injeção
   em monitor mode). Limitação mantida.
3. Regra de firewall pode ser criada por programa: Windows via
   `netsh advfirewall firewall add rule` com elevação UAC (ShellExecuteEx
   "runas", stdlib `ctypes`); Linux via `ufw allow`/`setcap` exibido pronto.
4. Broadcast **dirigido à sub-rede** (ex.: `192.168.1.255`) atravessa filtros
   que derrubam o broadcast global `255.255.255.255` e vice-versa
   (hackaday.com/udp-broadcasting) — envio dual aumenta a taxa de descoberta
   sem dependência nova.

## Etapas

### Etapa 1 — Envio dual de broadcast (descoberta mais resiliente)

- **Onde:** `net/discovery.py` (`DiscoveryBeacon._run`), novo helper
  testável `local_broadcast_addresses() -> list[str]`.
- **O que muda:** o beacon envia o anúncio para o broadcast global **e** para
  o broadcast dirigido da(s) sub-rede(s) local(is), derivado do IP local via
  socket UDP `connect(("192.0.2.1", 80))` + `getsockname()` (sem tráfego).
  Deduplicar endereços; falha de envio por destino continua suprimida por
  iteração.
- **Verificar:** unitários do helper; `tests/test_discovery.py` verde.

### Etapa 2 — Diagnóstico de firewall na UI

- **Onde:** `ui/app.py` (falha do `_connect_worker` → `_show_error`; tela de
  descoberta vazia), helper novo `net/firewall_hints.py`.
- **O que muda:** mapear `OSError` de bind para mensagem orientada por SO —
  Windows: permitir o Python no firewall (prompt pode ter sido descartado);
  Linux: comando `ufw allow`/`setcap` pronto. Na tela "Nenhuma partida
  encontrada", acrescentar dicas curtas (mesma rede? client isolation?
  firewall do host?).
- **Verificar:** unitários do mapeamento; smoke de UI segue verde.

### Etapa 3 — Correção de rede em um clique (opt-in, com elevação)

- **Onde:** módulo novo `net/firewall_fix.py` + botão na UI (tela de criar
  partida / tela de erro).
- **O que muda:** botão "Corrigir permissões de rede (requer admin)":
  - Windows: construir
    `netsh advfirewall firewall add rule name="Codecon Among Us" dir=in
    action=allow program=<sys.executable> enable=yes profile=any` e executar
    com elevação UAC via `ctypes.windll.shell32.ShellExecuteW` ("runas").
    Usar `sys.executable` (funciona com venv e binário empacotado).
  - Linux: exibir o comando pronto (`sudo ufw allow <porta>` / `setcap`) —
    sem executar sudo por baixo do usuário.
- **Restrições:** nunca automático (só clique explícito); recusa de elevação
  vira mensagem clara, não crash; separar **construção** do comando da
  **execução** para testar sem elevar.
- **Dependência:** Etapa 2 (a dica aponta para o botão).
- **Verificar:** unitários da construção do comando por SO; execução real com
  elevação é verificação manual (não automatizável em CI).

### Etapa 4 — Documentação

- README, seção "Jogar em rede": fluxo novo (correção em um clique,
  diagnóstico), reforçar que client isolation continua sem solução LAN.

## Riscos e decisões

- **100% sem firewall é impossível em LAN pura** (escuta inbound é inerente
  ao host de jogo) — a alternativa real era o relay, descartada por decisão
  do usuário (2026-08-31).
- **mDNS rejeitado** (mesmos bloqueios + dependência nova + falha
  silenciosa); **UPnP rejeitado** (mapeia roteador, não resolve firewall de
  host); **ARP-scan rejeitado** (raw sockets/privégios, custo
  desproporcional).
- Dual broadcast **não** ajuda sob client isolation — limitação existente
  permanece documentada.
- Elevação UAC não é testável em CI — fronteira construção/execução na
  Etapa 3.
- Arquivos sobrepostos a WIP pré-existente (protocolo v4) recebem staging
  parcial: apenas os hunks deste plano entram nos commits.

## Verificação integrada

1. `uv run ruff check --fix . && uv run ruff format .` + type checker.
2. `uv run pytest -v` — suíte completa, incluindo `tests/test_discovery.py`
   e novos unitários.
3. **Manual (duas máquinas/VMs na mesma rede):** criar sala → corrigir
   permissão no host → segunda máquina vê a sala na lista e entra sem
   digitar IP; repetir com firewall do host ativado para validar o
   diagnóstico.
