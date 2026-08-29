# Plano de implementação — lacunas pós-auditoria (2026-08-29)

Base: auditoria concluída em 2026-08-29 (6 achados AUD, 1 suspeita, 5 dívidas DT, 1 bloqueio
ambiental) + pesquisa de estado da arte executada na mesma sessão. Auditorias anteriores
(G-01..G-29, A-01..A-28 em `lacunas-pos-auditoria.md` / `lacunas-remanescentes.md`) estão
implementadas e foram revalidadas.

## Matriz de lacunas

| ID   | Origem  | Classificação           | Ações       | Prioridade |
| ---- | ------- | ----------------------- | ----------- | ---------- |
| G-01 | AUD-001 | Atendido incorretamente | A-01        | P1         |
| G-02 | AUD-002 | Não atendido            | A-03        | P1         |
| G-03 | AUD-003 | Atendido incorretamente | A-04        | P2         |
| G-04 | AUD-004 | Atendido incorretamente | A-05        | P2         |
| G-05 | AUD-005 | Não atendido            | A-02        | P2         |
| G-06 | AUD-006 | Atendido incorretamente | A-03        | P2         |
| G-07 | SUS-001 | Inconclusivo            | A-06 → A-07 | P2         |
| G-08 | DT-001  | Não atendido            | A-08        | P3         |
| G-09 | DT-002  | Não atendido            | A-02        | P3         |
| G-10 | DT-003  | Não atendido            | A-09        | P3         |
| G-11 | DT-004  | Não atendido            | A-10        | P3         |
| G-12 | DT-005  | Não atendido            | A-11        | P3         |
| G-13 | —       | Bloqueado (hardware)    | A-12        | P3         |

## Ações (resumo executável)

- **A-01** (G-01): `tests/test_integration.py:748` — `socket.socketpair(socket.AF_INET)` →
  `socket.socketpair()` (família padrão portátil; docs.python.org: AF_UNIX onde definido,
  senão AF_INET; Windows desde 3.5).
- **A-02** (G-05, G-09): criar `.gitignore` (`__pycache__/`, `*.pyc`, `.coverage`, `.venv/`,
  `captures/`) + `git rm -r --cached` dos `.pyc` e `captures/*.png`. Captures viram artefato
  local não versionado (decisão documentada).
- **A-03** (G-02, G-06): votação (ui/app.py:897-933) paginada — 5 cards/página, rodapé fixo
  com PULAR/VOTAR sempre dentro de 1280×768; paginação por ←/→, PageUp/Down e roda; foco de
  teclado via FocusManager existente (zonas: cards + botões); gameover (:1056-1057) em duas
  colunas quando ≥8 jogadores. Testes: geometria N∈{4,7,8,10}, paginação, foco; captura
  headless 8/10 jogadores. Refs: WCAG 2.2 SC 2.1.1; LogRocket pagination-vs-scroll; guia 2026.
- **A-04** (G-03): cancelamento cooperativo real — `threading.Event` consultado pelo worker
  antes de publicar resultado + token de geração na fila de resultados (descarte no
  `_poll_connection`) + teardown no próprio worker em sucesso-tardio. Testes: cancelar hosting
  → sem EADDRINUSE; cancelar join → sem cliente fantasma. Ref: docs.python.org threading.
- **A-05** (G-04): estreitar promessa de sigilo (docstring MeetingEnded, README, server.py)
  ao escopo real + teste de contrato (snapshot pós-ejeção marca alive=false). Refs: Panja et
  al. 2020 (custo de sigilo criptográfico); Fang & Zhu 2020 (channel leakage, moldura).
- **A-06** (G-07): medição de flood em `/tmp` (tick Hz, fila, RSS) — decide A-07.
- **A-07** (G-07, condicional a A-06): teto de drain/tick por conexão + teto de pendentes por
  conexão com desconexão em overflow sustentado; limites derivados da medição. Ref: Yu & Neely
  2017 (backpressure/filas limitadas).
- **A-08** (G-08): try/except no corpo do tick com `logging.exception` e continuação do loop;
  teste de injeção de falha.
- **A-09** (G-10): GitHub Actions matrix ubuntu+windows, uv, ruff/mypy/pytest (+SDL dummy),
  smoke E2E, `uv audit` informativo.
- **A-10** (G-11): estratificar `net/client.py` — nome de produção para o cliente da UI;
  helpers de teste documentados. Sem mudança de comportamento.
- **A-11** (G-12): eliminar os 3 `# type: ignore` com Protocol/tipagem adequada ou justificar
  inline o irredutível.
- **A-12** (G-13, bloqueado): checklist manual LAN + display real em `plans/`. Desbloqueio:
  2ª máquina + monitor.

## Gates por fase

`uv run pytest` 100% verde · `uv run ruff check` 0 erros · `uv run mypy` strict 0 erros ·
`python scripts/smoke_multiplayer.py` OK (via `uv run`).

## Definição global de concluído

1. Suíte verde em Linux e Windows (CI); 2. Votação/gameover completos com 10 jogadores +
   teclado; 3. Cancelamento sem porta presa/fantasma; 4. Docs de sigilo/controles ==
   comportamento testado; 5. Flood medido e, se limitado, tick ≥18Hz + RSS estável;
6. Zero artefatos gerados rastreados; 7. Game loop sobrevive a exceção injetada;
8. Checklist LAN/display executado quando hardware disponível.

## Referências da pesquisa

1. Python docs 3.14.7 — socket.socketpair; 2. Python docs 3.14.7 — threading.Event;
3. WCAG 2.2 SC 2.1.1 (W3C, normativo); 4. LogRocket — pagination vs infinite scroll;
5. Pagination Design Best Practices (2026); 6. Yu & Neely 2017, arXiv:1701.04519 (preprint);
7. Panja et al. 2020, IEEE TEM, DOI 10.1109/TEM.2020.2986371; 8. Fang & Zhu 2020,
arXiv:2008.04893 (preprint). Lacuna bibliográfica 2026 declarada para UI de jogos de dedução
social e sigilo de ejeção.
