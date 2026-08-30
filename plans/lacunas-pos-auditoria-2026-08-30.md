# Plano: Lacunas remanescentes pós-auditoria (descoberta LAN + WebSocket)

Data: 2026-08-30. Status: executado (resultados na seção 6).

## 6. Resultados da execução (2026-08-30)

| Ação | Resultado | Commit |
| ---- | --------- | ------ |
| V-01 | Flake **reproduzido**: 1/6 na suíte, ~5% isolado (10/200). Causa-raiz: corrida TOCTOU probe-then-bind — `/proc/net/tcp` mostrou conexões de processos alheios (TIME_WAIT/LAST_ACK/FIN_WAIT1) na porta recém-sondada; EADDRINUSE nos dois binds do worker. **Não era** async-wait nem bug do produto | — |
| V-03 | `uv audit`: 27 pacotes, **zero advisories** | — |
| V-04 | Paridade 17.0 **refutada**: `legacy` não existe em `sync.client.connect` da 17.0 (TypeError; 5 falhas WS) → contingência aplicada: piso `websockets>=17.1,<18` | `474a900` |
| A-04 | setup.py remove `.so` de stems excluídos em todo build; `viewmodel.so` residual removido pelo próprio build; import resolve `viewmodel.py`; suíte verde | `00aa90f` |
| A-01 | Helper `_create_game_with_free_port` (retry só em EADDRINUSE, demais erros propagam). Verificação: **0/200** isolado (baseline 10/200) e **10/10** suítes completas consecutivas | `96e630c` |
| A-02 | Comentário restaurado | `271ecf9` |
| A-03 | README: amplitude do setcap + sysctl `ip_unprivileged_port_start` + descoberta não autenticada + servidor sem autenticação | `4ce15a5` |
| A-05 | Afirmação mDNS reclassificada como decisão de engenharia sem fonte | `1120d78` |
| A-06 | **Dispensada** — flake eliminado na causa-raiz; rerun seria máscara | — |
| A-07 | `uv audit` promovido a gate bloqueante no CI | `3aabbd3` |
| V-05 | **BLOQUEADO**: sem sudo/root no ambiente de execução. Protocolo pronto (seção 3) para VM descartável | — |
| V-06 | **BLOQUEADO**: sem segundo host/AP/proxy disponíveis. Protocolos prontos (seção 3) | — |
| L-01..L-03 | Aguardando decisão do usuário (reconexão, rotação, internet) | — |

Achado adicional relevante fora do escopo original: V-04 revelou que a spec
`websockets>=15` estava **incorreta** (código exige 17.1+) — corrigida antes
de afetar qualquer ambiente com resolução mais antiga.

Regressão global final: 10× suíte completa (870) verde, ruff limpo, mypy
strict limpo (75 arquivos).

> Origem: auditoria técnica independente dos commits `6173c5f..c76f131`
> (descoberta LAN via UDP broadcast + transporte WebSocket). Veredito geral
> VERIFICADO/VERIFICADO COM RESSALVAS; este plano cobre os achados F-01..F-03,
> as lacunas de verificação e as ações de endurecimento derivadas.
>
> **Regra de execução:** um commit por ação; verificação por unidade; suíte
> completa como regressão global ao final de cada fase.

## 1. Inventário de lacunas (matriz resumida)

| ID   | Achado                                                                                          | Classificação            | Ações             | Prioridade |
| ---- | ----------------------------------------------------------------------------------------------- | ------------------------ | ----------------- | ---------- |
| G-01 | Flake 1/4 em `test_create_game_populates_lobby_and_start_transitions`; causa não capturada      | inconclusivo             | V-01, A-01, A-06  | P1/P2      |
| G-02 | Comentário realocado na assinatura de `test_cancel_connecting_returns_to_main`                  | atendido incorretamente  | A-02              | P3         |
| G-03 | README omite amplitude do setcap, descoberta não autenticada, servidor sem autenticação         | parcialmente atendido    | A-03              | P3         |
| G-04 | websockets 17.1 pós-corte; paridade com 17.0 apenas inferida                                    | inconclusivo             | V-04              | P2         |
| G-05 | `viewmodel.so` residual sombreia `viewmodel.py`; setup.py só limpa em SKIP_NATIVE               | parcialmente atendido    | A-04              | P2         |
| G-06 | Bind real na porta 80 nunca exercitado                                                          | inconclusivo             | V-05              | P2         |
| G-07 | LAN multi-host / client isolation / proxy corporativo reais não testados                        | inconclusivo             | V-06              | P2/P3      |
| G-08 | Plano cita "mDNS falha com frequência" como PESQUISADO sem fonte                                | atendido incorretamente  | A-05              | P3         |
| G-09 | Auditoria de vulnerabilidades só do pacote novo (OSV); lockfile completo não auditado           | inconclusivo             | V-03, A-07        | P2         |
| L-01 | Sem reconexão de jogadores                                                                      | bloqueado (escopo)       | questão ao usuário | —          |
| L-02 | Partida única por servidor (sem rotação)                                                        | bloqueado (escopo)       | questão ao usuário | —          |
| L-03 | Jogo pela internet sem relay/hole-punching                                                      | bloqueado (escopo)       | questão ao usuário | —          |

Itens comprovadamente atendidos (R-01..R-09 da auditoria; UI sob X real via job
CI `ui-xvfb`) não geram trabalho.

## 2. Evidências da pesquisa (SOTA até 2026-08-30)

- **Reproduzir/classificar antes de corrigir flakes** — ReproFlake: 1115 flaky
  tests reproduzíveis; logs de erro guiam categoria e reparo (Rafi et al.,
  2026, preprint arXiv 2605.21677 — não revisado por pares).
- **Adaptar o wait é o reparo dominante para async-wait** — 63% das correções
  de desenvolvedores em 49 casos; reparo por tempo reduz execução (Pei et al.,
  TRaf, 2023, preprint arXiv 2305.08592 — não revisado por pares).
- **Concorrência é a categoria mais comum de flakiness** — 23% de 559 issue
  reports do SAP HANA (Berndt, Bach, Baltes, 2026, preprint arXiv 2602.03556 —
  não revisado por pares).
- **Retry é contenção sobre detecção, não reparo** — revisão CI/CD (Dhawan &
  Dhawan, 2026, Frontiers in AI, DOI 10.3389/frai.2026.1776546 — revisado;
  projeções). `pytest-rerunfailures` 16.6 (2026-08-17) é compatível com
  `pytest>=9,<10` (metadados PyPI), mas fica como último recurso.
- **`net.ipv4.ip_unprivileged_port_start` é per-namespace** — "Privileged
  ports require root or CAP_NET_BIND_SERVICE... set this to 0" (doc oficial do
  kernel, ip-sysctl) — alternativa documental ao setcap.
- Lacuna bibliográfica declarada: sem revisão sistemática de 2026 sobre repair
  de flaky tests em Python; evidência empírica por analogia de categoria.

## 3. Fases e ações

### Fase 0 — Verificações locais (desbloqueiam decisões)

**V-01 (G-01, P1, pequeno):** reproduzir o flake — loop de 10 execuções da
suíte completa com `--tb=long` e logs persistidos; complementar com loop do
teste isolado sob carga. Aceitação: traceback classificado (timeout de
deadline / estado residual / colisão de porta) **ou** 10/10 verdes (encerra
como "não reproduzido", com monitoramento). Sem alteração de arquivos.

**V-03 (G-09, P2, pequeno):** `uv audit` do lockfile completo + resultado do
job CI existente. Aceitação: zero advisories não triados.

**V-04 (G-04, P2, pequeno):** `uv run --with 'websockets==17.0' pytest
tests/test_ws_integration.py tests/test_discovery.py tests/test_cli.py`
(overlay efêmero; lockfile e `.venv` intactos) + introspecção de assinaturas.
Aceitação: verde → paridade registrada; falha → contingência: elevar piso para
`websockets>=17.1,<18` em pyproject + `uv lock`, com justificativa no commit.

### Fase 1 — Correções locais

**A-04 (G-05, P2, pequeno):** em `setup.py`, remover `*.cpython-*.so` de stems
em `_EXCLUDED_STEMS` em **todo** build (hoje só no ramo `_SKIP_NATIVE`);
remover o artefato residual `ui/viewmodel.cpython-313-*.so` (gitignored).
Aceitação: build sem `.so` residual; suíte 870 verde executando os fontes
puros; CI verde. Risco: revelar divergência pré-existente .so vs .py (é o
objetivo). Reversão: rebuild.

**A-01 (G-01, P2, médio):** somente após V-01 classificar. Se timeout de
async-wait (hipótese principal): helper de espera por condição com deadline
escalável (local 5 s / CI 15 s) substituindo deadlines fixos, com log do tempo
observado e teto sempre presente. Se estado residual: corrigir isolamento do
fixture/teardown. Se colisão de porta adjacente: reservar duas portas
adjacentes livres. Aceitação: 10 execuções completas consecutivas verdes.

**A-02 (G-02, P3, pequeno):** restaurar o comentário ao corpo de
`test_cancel_connecting_returns_to_main`. Aceitação: ruff limpo, teste verde.

**A-03 (G-03, P3, pequeno):** README "Jogar em rede" — adicionar: (a)
amplitude do setcap (capability vale para todo processo daquele binário;
alternativa: cópia dedicada); (b) alternativa sysctl
`ip_unprivileged_port_start` (por namespace; afeta todos os processos do
namespace); (c) descoberta não autenticada; (d) servidor sem autenticação
escutando em todas as interfaces. Aceitação: 4 notas consistentes com
capabilities(7)/kernel ip-sysctl/código.

**A-05 (G-08, P3, pequeno):** `plans/descoberta-lan-websocket-porta80.md` —
remover o marcador "PESQUISADO (web)" da afirmação mDNS ou anexar fonte real
se localizada; não fabricar fonte. Aceitação: nenhuma afirmação pesquisada sem
fonte.

### Fase 2 — Verificações com ambiente externo

**V-05 (G-06, P2, médio):** VM/ambiente com root — `setcap cap_net_bind_service=+ep`
no python resolvido → servidor `--ws-port 80` → `connect_auto` via WS →
`setcap -r`. Aceitação: snapshot via WS na 80; capability removida; relatório.
Se não houver root: registrar bloqueio.

**V-06 (G-07, P2/P3, médio-grande, depende de ambiente):** três protocolos de
campo: (a) dois hosts na mesma LAN (descoberta + join por um clique); (b) AP
com client isolation ligado (falha total esperada) e desligado (sucesso);
(c) proxy/firewall entre segmentos (WS passa, TCP cru bloqueado). Aceitação:
3 relatórios; desvios viram G-items novos. Se ambiente indisponível: permanece
aberto com protocolo pronto — não é defeito.

### Fase 3 — Contenção e endurecimento opcionais

**A-06 (G-01, P3, pequeno):** somente se A-01 não eliminar o flake E após
auditoria da dependência (depscope indisponível → `uv audit` + inspeção):
`pytest-rerunfailures` com `@pytest.mark.flaky(reruns=2)` **somente** no teste
afetado, com comentário citando G-01/V-01.

**A-07 (G-09, P3, pequeno):** se V-03 estiver limpo, remover
`continue-on-error: true` do step `uv audit` no CI.

## 4. Definição global de concluído

1. G-01 resolvido por causa-raiz (10 execuções consecutivas verdes, decisão
   registrada);
2. setup.py limpa `.so` de stems excluídos em qualquer build; suíte verde;
3. README com as 4 notas de segurança; plano sem afirmação órfã;
4. `uv audit` triado; decisão sobre gate CI registrada;
5. paridade websockets 17.0 confirmada ou piso corrigido;
6. V-05/V-06 executados com relatório ou marcados bloqueados-por-ambiente;
7. regressão global verde: suíte (870), ruff, mypy strict, smoke E2E, CI;
8. L-01/L-02/L-03 e autenticação decididos pelo usuário (fora de escopo
   confirmado ou novo plano).

## 5. Referências

1. Rafi S. et al. — ReproFlake — 2026, preprint — arXiv 2605.21677.
2. Berndt A., Bach T., Baltes S. — Flaky Tests SAP HANA — 2026, preprint —
   arXiv 2602.03556.
3. Pei Y. et al. — TRaf — 2023, preprint — arXiv 2305.08592.
4. Dhawan R., Dhawan M. — AI-augmented reliability in CI/CD — 2026, Frontiers
   in AI — DOI 10.3389/frai.2026.1776546.
5. Linux kernel docs — ip-sysctl (`ip_unprivileged_port_start`) —
   docs.kernel.org/networking/ip-sysctl.html.
6. Linux man-pages — capabilities(7) — man7.org.
7. pytest-rerunfailures — PyPI 16.6 (2026-08-17).
8. websockets — changelog 17.1 (2026-08-26, aditivo) — readthedocs.
9. IETF — RFC 6455 (2011), §§1.2/1.8.
