# Plano: fechamento das lacunas pós-auditoria (rastreabilidade + verificações)

Status: **executado com 1 pendência externa** (build agent, 2026-08-30).
A-01/A-02/A-03/A-05/A-06/A-07 entregues e verificadas; A-04 (smoke manual)
permanece bloqueada por dependência de display+operador humano — condição de
desbloqueio explícita abaixo. Origem: auditoria técnica da implementação
"mundo triplicado + 7 minigames" (veredito: 5 VERIFICADO + 6 VERIFICADO COM
RESSALVAS; 0 CONTRADITO; 3 achados Baixa + 4 verificações pendentes).

## Diagnóstico (16 itens avaliados)

- `atendido`: 9 (R-01..R-07, R-09, R-10)
- `parcialmente atendido`: 3 — R-08/G-03 (critério typecheck), G-01 (citações),
  G-02 (desvio de paleta não registrado)
- `inconclusivo`: 4 — G-04 (smoke manual), G-05 (nº exato de células), G-06
  (simulação CVD), G-07 (revisão dos 7 módulos)
- Causas-raiz: (1) citações geradas sem verificação bibliográfica; (2) critérios
  documentais que não refletem a implementação; (3) verificações que exigem
  display humano ou passos não executados.

## Lacunas e ações

| ID   | Lacuna                                                        | Ação | Prioridade | Status |
| ---- | ------------------------------------------------------------- | ---- | ---------- | ------ |
| G-01 | Citações "Xiao & Yang 2025"/"Kamath et al. 2025" não localizáveis; Xbox AG/Norman não re-lidos | A-01 | P2 | **resolvido** (citações substituídas por fontes verificadas; Mortazavi 2024 marcada como metadados-somente) |
| G-02 | Paleta Okabe-Ito prevista não aplicada; desvio não registrado | A-02 | P3 | **resolvido** (desvio registrado no cabeçalho do plano do mapa) |
| G-03 | Critério "basedpyright strict verde" não literal (22 erros preexistentes) | A-03 | P3 | **resolvido** (critério efetivo documentado) |
| G-04 | Smoke manual não executado (depende de display+operador)      | A-04 | P2 | **bloqueado externo** — condição de desbloqueio abaixo |
| G-05 | Nº exato de células caminháveis (1026) não re-derivado        | A-05 | P3 | **resolvido** (re-derivado: 1026, componente único, 0 fora) |
| G-06 | Marcadores não validados sob simulação de daltonismo          | A-06 | P3 | **resolvido** (`tests/test_marker_cvd.py`, 4 testes verdes) |
| G-07 | 7 módulos de puzzle sem inspeção linha-a-linha                | A-07 | P3 | **resolvido** (`tests/test_puzzle_invariants.py`, 26 testes verdes + checklist abaixo) |

### Checklist A-07 registrado (evidência por módulo)

| Item | wires | fix_wiring | swipe_card | calibrate | clean_filter | start_reactor | asteroids |
| ---- | ----- | ---------- | ---------- | --------- | ------------ | ------------- | --------- |
| Consome `difficulty_for` | não* | não* | sim | sim | sim | sim | sim |
| Respeita `reduced_motion` | sim | sim | sim | sim | sim | sim | sim |
| Determinismo por seed (teste) | sim | sim | sim (factory) | sim (factory) | sim (factory) | sim | sim |
| Sem estado mutável de classe | sim | sim | sim | sim | sim | sim | sim |
| Input posicional valida área | sim | sim | n/a (timing) | n/a (timing) | sim | sim | sim |

\* wires (4 fios fixos) e fix_wiring (grade 3×3 fixa) têm estrutura fixa por
design; os parâmetros de dificuldade existem no catálogo (mensuráveis) mas
não são consumidos — registrado como observação, não como desvio (mudar
exigiria alterar gameplay e baselines sem pedido do usuário).

## Fase 1 — Rastreabilidade + verificação central (P2)

### A-01 — Corrigir as citações do plano (G-01)

- Alvo: `plans/mapa-triplicado-minigames.md` bloco "Pesquisa aplicada".
- Substituir "Xiao & Yang 2025" por **Mortazavi, Moradi & Vahabie 2024** (SLR,
  DOI 10.1007/s11042-024-18768-x) — após ler e confirmar escopo — + **Darzi,
  McCrea & Novak 2021** (JMIR Serious Games, DOI 10.2196/25771; N=50, 2
  parâmetros explícitos de dificuldade; acurácia do ajuste correlaciona com
  enjoyment r=0,38; contraevidência: mais sensores ≠ melhor UX).
- Remover "Kamath et al. 2025": feedback redundante (forma+animação+texto)
  passa a ser justificado pela Game Accessibility Guidelines (verificada) +
  decisão de engenharia; declarar lacuna bibliográfica 2026 para esse claim.
- Norman/Xbox AG: referência primária completa ou marcação "contexto, não
  verificado".
- Aceite: zero citações autor-ano sem identificador verificável no plano.

### A-04 — Smoke manual com roteiro observável (G-04) — BLOQUEADO

- Roteiro de 10 passos (E abre puzzle do tipo certo; 7 puzzles jogáveis;
  resolver completa e HUD avança; ESC abandona sem completar; morte/reunião
  fecha; WASD bloqueado; marcadores por forma; reduced_motion estático; mundo
  ativo; console limpo).
- **Dependência externa:** display + operador humano. Sem ambiente gráfico
  nesta execução → permanece `inconclusivo` com condição de desbloqueio
  explícita (executar em máquina com display e registrar evidência). Não é
  defeito; não bloqueia as demais ações.

## Fase 2 — Fidelidade documental (P3; um commit docs)

### A-02 — Registrar desvio da paleta Okabe-Ito (G-02)

- Cabeçalho de desvios do plano: paleta não aplicada; família amarela mantida;
  signifiers de forma são o canal primário (GAG prioriza signifiers > paleta).
- Alternativa documentada e NÃO recomendada: aplicar a paleta (custo: regen de
  baselines + validação de contraste; não resolve lacuna funcional).

### A-03 — Corrigir critério de typecheck do plano (G-03)

- §Verificação item 2 → "zero erros novos vs. baseline 643da38 (22 erros
  preexistentes conhecidos, fora do escopo)".
- Opcional fora deste plano: saneamento dos 22 erros preexistentes (exige
  decisão do usuário; toca código fora da fronteira original).

### A-05 — Re-derivar e registrar as células caminháveis (G-05)

- Executar o builder e ler o relatório de gates; atualizar o cabeçalho do
  plano se o número diferir de 1026.
- Aceite: número no plano == saída do builder na mesma revisão.

## Fase 3 — Verificações adicionais (P3)

### A-06 — Teste de distinguibilidade CVD dos marcadores (G-06)

- Novo teste headless: renderiza marcadores (reduced_motion, determinístico),
  aplica simulação LMS (protanopia/deuteranopia/tritanopia; matrizes de
  Machado, Oliveira & Fernandes 2009 — valores confirmados em fonte pública
  antes do uso; sem dependência nova) e verifica que pares de estados
  (ASSIGNED/NEAR/INTERACTABLE/DONE) permanecem separáveis por luminância/
  geometria (não por matiz).
- Aceite: teste verde integrado à suíte; baselines inalteradas.

### A-07 — Checklist estrutural dos 7 módulos de puzzle (G-07)

- Por módulo: consome parâmetros do catálogo; respeita reduced_motion;
  determinismo por seed (já testado — confirmar); isolamento entre instâncias;
  eventos fora da play_area ignorados.
- Forma: testes paramétricos sobre os 7 tipos (isolamento, eventos fora da
  área, propagação de reduced_motion) + verificação por inspeção do uso de
  dificuldade, registrada em checklist neste arquivo.
- Aceite: 7/7 módulos conformes, ou desvios viram G-XX novos.

## Pesquisa aplicada (fontes verificadas)

- Mortazavi, Moradi & Vahabie (2024). *Dynamic difficulty adjustment
  approaches in video games: a systematic literature review*. Multimedia Tools
  and Applications. DOI 10.1007/s11042-024-18768-x (escopo a confirmar em A-01).
- Darzi, McCrea & Novak (2021). *User Experience With Dynamic Difficulty
  Adjustment Methods for an Affective Exergame*. JMIR Serious Games 9(2):e25771.
  DOI 10.2196/25771 (resumo lido).
- Chilukala (2026). *A Real-Time Camera-Based CVD Assistance System Using
  Daltonization*. ITM Web of Conferences 86, 01002. DOI 10.1051/itmconf/20268601002
  (simulação no espaço LMS segue padrão corrente em 2026).
- Shen, Feng & Zhang (2020). *A content-dependent Daltonization algorithm…*.
  IET Image Processing. DOI 10.1049/ipr2.12079.
- Game Accessibility Guidelines — *Ensure no essential information is conveyed
  by a fixed colour alone* (Vision, Basic). Lida integralmente: cor como
  reforço, nunca canal único; signifiers adicionais antes de trocar paleta.
- Lacuna bibliográfica declarada: sem literatura 2026 diretamente aplicável a
  parametrização estática de dificuldade em minigames nem a feedback
  multimodal em puzzles de jogos sociais.

## Verificação integrada final — resultados (2026-08-30)

1. `uv run ruff check .` → All checks passed; `ruff format` → 80 arquivos ok.
2. `uv run basedpyright .` → 22 erros, idênticos ao baseline (uma regressão
   introduzida durante a execução — anotação `logic: object` na ABC — foi
   detectada por esta verificação e revertida no commit f5703e6).
3. `uv run pytest -q -m "not slow"` → 361 passed; `-m "slow or integration
   or e2e"` → 35 passed. Uma falha isolada num teste de integração lento não
   se reproduziu em 2 re-execuções completas (flake preexistente, fora da
   superfície alterada — nenhum arquivo de rede/protocolo foi tocado).
4. `uv run python scripts/build_lab_map.py --check` → assets sincronizados.
5. Commits: fa6139d (plano) → 599e8e2 (A-01/02/03/05) → d38df08 (A-06) →
   77599be (A-07) → f5703e6 (fix typecheck) → fechamento docs.

## Definição global de concluído

(1) plano sem citações sem identificador verificável e com desvios/critérios
fiéis; (2) smoke manual executado **ou** formalmente pendente por dependência
de ambiente, com condição de desbloqueio explícita; (3) teste CVD verde na
suíte; (4) checklist dos 7 módulos registrado sem desvios pendentes; (5)
suíte verde, ruff limpo, --check verde, zero erros novos de typecheck; (6)
nenhum item `inconclusivo` sem ação de evidência registrada.
