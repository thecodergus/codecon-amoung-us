# Lacunas remanescentes — diagnóstico, estado da arte e plano de implementação

Data: 2026-08-31. Status: **planejado** (aguardando implementação).
Origem: auditoria técnica do recurso "mapas procedurais por seed" (commits `4fa38e5..5100e6a`) + análise de código desta sessão, que identificou um defeito adicional não coberto pela auditoria (G-06).

Pesquisa de estado da arte: searchmesh (OpenAlex/Crossref/arXiv + web), 2026-08-31.

---

## 1. Resumo executivo

**9 itens avaliados** (G-01…G-09). Distribuição: **atendido 1 · parcialmente atendido 2 · regredido 2 · inconclusivo 3 · bloqueado 1**.

**Achado principal (G-06, novo — não coberto pela auditoria anterior):** a auditoria verificou `app.py:739-743` como "conforme", mas apenas no fluxo procedural. No **modo asset** (`--map`, exposto em `server.py:1093`), o servidor envia `map_seed=0` (`server.py:563`, pois `_map_seed=None`) e o cliente reconstrói **incondicionalmente** `generate_map(0)` (`app.py:739`), descartando o lab.json carregado (`app.py:256`). Como `0` é uma seed procedural perfeitamente válida, o contrato no fio é **ambíguo por construção** — nem um cliente conforme à spec consegue distinguir. Multiplayer em modo asset **regrediu** (antes, ambos os lados carregavam o mesmo asset). **P1.**

Segundo achado: o **harness de navegação** (smoke E2E e helpers de integração) deriva o grid BFS do **asset** lab.json contra servidores que hoje rodam mapas **procedurais** — passa hoje por tolerância/timeout, mas é flakiness latente por construção. **G-07, P2.**

Causa-raiz compartilhada de G-06/G-07: o recurso introduziu duas geometrias (procedural vs asset) sem um contrato explícito no fio, e o harness continuou ancorado no asset.

---

## 2. Matriz consolidada de cobertura

| ID   | Requisito/achado                                                                                   | Evidência interna                                                                                                                               | Classificação             | Causa/hipótese                                                                              | Ações | Prioridade | Confiança                     |
| ---- | -------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | ------------------------------------------------------------------------------------------- | ----- | ---------- | ----------------------------- |
| G-01 | R-01/R-02 — determinismo de pixels da cena sem teste unitário (F-01)                               | `grep render_scene tests/` vazio; cobertura só via `--check` (ci.yml:124, seed 42, ubuntu)                                                          | parcialmente atendido     | cena adicionada junto ao gate de CI, sem teste próprio                                      | A-02  | P2         | alta                          |
| G-02 | F-02 — `.so` in-place sombreia `.py` no dev loop                                                       | plano §Desvios; erro `runpy` "No code object available" observado                                                                                 | parcialmente atendido     | `build_ext --inplace` coloca `.so` na árvore de fontes (comportamento do setuptools/import)     | A-05  | P3         | alta                          |
| G-03 | F-03 — verificação dinâmica não reproduzida na auditoria (889 passed, smoke, `--check` são registro) | auditoria §6; restrição read-only                                                                                                               | inconclusivo              | ausência de execução nesta sessão ≠ defeito                                                 | A-04  | P2         | alta                          |
| G-04 | R-05 — varredura literária pós-2024 parcial                                                        | auditoria §7.2; Semantic Scholar rate-limited                                                                                                   | inconclusivo              | cobertura de busca parcial                                                                  | A-06  | P3         | média                         |
| G-05 | R-02 — rasterização cross-platform da cena não observada                                           | `assets-freshness` só ubuntu (ci.yml:109-124); pytest c/ baselines roda no windows (ci.yml:14,36-39), mas SDL version entre runners pode divergir | inconclusivo              | gate de pixels não roda no windows; divergência SDL não observada                           | A-04  | P2         | média                         |
| G-06 | R-08 — modo asset multiplayer **regredido** no cliente                                                 | `server.py:563` (`else 0`), `server.py:1093` (`--map`), `app.py:736-744` (sem ramo), `test_integration.py:1280-1293` (só servidor)                          | **regredido**                 | sentinela `map_seed=0` ambígua (0 é seed procedural válida) + cliente incondicional           | **A-01**  | **P1**         | **alta**                          |
| G-07 | Harness de navegação usa grid do asset contra servidores procedurais                               | `smoke_multiplayer.py:84-92,240`; `test_integration.py:344,445,783,1085,1111`                                                                       | **regredido** (ferramenta de verificação)     | harness ancorado no asset, pré-feature; servidor agora procedural (seed aleatória no smoke) | A-03  | P2         | alta (fato) / média (impacto) |
| G-08 | V-05/V-06 — porta 80 / LAN multi-host (pré-existente, fora da fronteira)                           | registro da sessão de dev; sem detalhes do requisito no contexto                                                                                | bloqueado / inconclusivo  | dependência de ambiente                                                                     | A-07  | P3         | baixa                         |
| G-09 | Acoplamento seed-42 ↔ asset (trade-off documentado)                                                | plano §Desvios; gate `--check` protege                                                                                                            | atendido (registro)       | acoplamento deliberado                                                                      | —     | —          | alta                          |

---

## 3. Síntese da pesquisa por lacuna

### G-03/G-04 + validação do método construtivo (PCG 2026)

Duas fontes 2026 reais localizadas: Mao et al., *"Procedural Content Generation via Generative Artificial Intelligence"*, Interdisciplinary Information Sciences, DOI `10.4036/iis.2026.r.01` (survey; GenAI-PCG depende criticamente de dados de treino e garantia de qualidade/diversidade) e Baharvand et al., *"A deep generative approach to personalized super mario level design"*, Scientific Reports, DOI `10.1038/s41598-026-46199-1` (GANs skill-conditioned). Ambas **reforçam** a decisão do projeto: abordagens ML exigem datasets que o projeto não tem; a escolha construtiva determinística por seed atende exatamente aos requisitos (determinismo, gates estruturais, zero dataset). Lacuna remanescente: exaustividade da varredura (1 query; Semantic Scholar em cooldown). **Confiança: alta** na adequação; **média** na exaustividade.

### G-01 (determinismo de cena)

Sem literatura científica específica localizada; a prática consolidada de golden-master/visual regression é consistente: **deterministic rendering** é pré-condição de todo o resto, com gestão de baselines revisáveis e separação de ruído de ambiente de regressão real (fontes §8, itens 9 — prática de engenharia, não revisada por pares). O projeto já tem a camada de determinismo (renderer puro `pygame.draw`, RNG seedado, SDL dummy); falta o teste **unitário** que falhe cedo. **Recomendação:** teste de determinismo + manter baselines. **Confiança: alta.** (Lacuna bibliográfica científica declarada.)

### G-02 (sombreamento `.so`)

Documentação oficial do setuptools confirma o mecanismo: `build_ext --inplace` "moves the compiled shared objects into the source tree so that they are in the Python search path". O sombreamento é consequência da precedência de extensões sobre `.py` no import system (inferência própria, coerente com o erro `runpy` observado). **Recomendação:** alvo de limpeza + aviso no smoke. **Confiança: alta.**

### G-06 (contrato do protocolo)

Documentação oficial do msgspec (constraints via `Annotated` + `Meta`; campos opcionais com defaults) suporta a alternativa recomendada (`map_seed` opcional). Como o comportamento de `Meta` sobre `int | None` não foi confirmado explicitamente, o plano inclui um teste de decode como primeira verificação. **Confiança: alta** na direção; **média** no detalhe da API (a validar).

---

## 4. Plano de implementação faseado

### P1 — A-01 (G-06): contrato explícito procedural/asset + ramo no cliente

1. **Ação:** A-01 · **Lacunas:** G-06 · **Esforço:** médio · **Prioridade:** P1 · **Confiança:** alta
2. **Objetivo:** cliente e servidor concordam sobre a fonte do mapa; multiplayer em modo asset volta a funcionar.
3. **Solução recomendada (Alternativa A):** tornar `StartGame.map_seed` opcional no fio: `Annotated[int, Meta(ge=0, le=2**63-1)] | None = None`. Servidor: enviar `map_seed=None` em modo asset (remover o `else 0` de `server.py:563`). Cliente (`app.py:736-744`): se `map_seed is None` → **manter** `self.game_map` (asset carregado em `app.py:256`) e reconstruir apenas renderer/câmera com `scene=None` (fallback ao asset em `render.py:121-133`); se seed presente → caminho atual. **Bump `ProtocolVersion` para 4** (mudança de tipo de campo é wire-incompatível; cliente e servidor embarcam juntos; atualizar `test_framing`).
   - *Alternativa B (sem bump):* campo novo `map_source` — maior superfície de protocolo para o mesmo efeito. **Decisão pendente do usuário** (A com bump vs B sem bump).
   - *Validação prévia obrigatória:* teste unitário de decode confirmando que `Meta(ge=0)` sobre `int | None` aceita `None` e rejeita negativos; se o msgspec `>=0.21,<0.22` não suportar, cair para `int | None` sem `Meta` + validação no servidor (seed já validada na CLI).
4. **Arquivos:** `protocol.py` (StartGame/ProtocolVersion), `net/server.py:563`, `ui/app.py:736-744`, `tests/test_protocol.py`, `tests/test_framing.py`, novo teste de integração asset-mode.
5. **Precondições:** nenhuma. **Ordem:** teste de decode do msgspec → protocolo → servidor → cliente.
6. **Impacto:** protocolo v4 (quebra clientes antigos — aceitável, co-empacotados); nenhum dado em disco afetado.
7. **Testes:** decode/encode do novo tipo; integração asset-mode ponta-a-ponta (servidor `map_path=default`, dois clientes, asserção de que `client.game_map` **não** é procedural — comparar com `load_map(default_map_path())`); regressão do fluxo procedural (seed fixa 42); framing v3→v4.
8. **Aceitação:** com `--map`, clientes renderizam o lab.json do servidor (geometria idêntica); sem `--map`, comportamento atual inalterado; suíte verde nos dois modos.
9. **Risco/reversão:** bump de versão pode surpreender clientes externos — mitigado por co-empacotamento e changelog; reversão = revert do commit único.

### P2 — A-02 (G-01): teste unitário de determinismo da cena

**Esforço:** pequeno · **Confiança:** alta.
- Novo `tests/test_scene_determinism.py`: `render_scene(generate_map(s), s)` renderizada 2× para 3 seeds (42, aleatória, borda) → bytes via `pygame.image.tostring` idênticos; 1 caso comparando modo puro vs nativo quando aplicável.
- **Aceitação:** teste falha se qualquer mudança em `scene.py` alterar a saída; roda na suíte rápida (<100 ms); cobre seeds além da 42.
- **Risco:** nenhum funcional; custo +1 teste de render.

### P2 — A-03 (G-07): harness de navegação usa a geometria do servidor

**Esforço:** pequeno · **Confiança:** alta.
- `smoke_multiplayer.py:_move_to_point`: trocar `load_map(default_map_path())` (linha 92) pelo mapa do próprio cliente (`client.game_map`, correto por construção via StartGame). O docstring "independe do layout" era verdade pré-feature; hoje o grid deve ser o do servidor.
- `test_integration.py` helpers (linhas 344, 445, 783, 1085, 1111): idem — usar `generate_map(seed_do_servidor)` ou o `game_map` do cliente, não o asset; cada uso avaliado (o fixture seed-42 é determinístico; os de seed aleatória são os críticos).
- **Testes:** smoke ×5 execuções consecutivas sem flake; suíte de integração ×3.
- **Aceitação:** nenhum grid derivado de asset contra servidor procedural; smoke estável.
- **Risco:** baixo; reversão trivial.

### P2 — A-04 (G-03 + G-05): re-execução da verificação dinâmica + evidência cross-platform

**Esforço:** pequeno · **Confiança:** alta (procedimento).
- Re-executar: `uv run pytest -v` (esperado 889+), `uv run ruff check . && uv run basedpyright .`, `uv run python scripts/build_lab_map.py --check`, smoke ×3.
- G-05: inspecionar o resultado do job `test` (windows-latest) no CI mais recente — `test_visual_regression.py` compara baselines de tela completa no windows (SDL dummy); se verde, rasterização cross-platform observada. Se houver divergência, avaliar fixar versão SDL ou restringir baselines por SO.
- **Aceitação:** todos verdes; G-03/G-05 reclassificadas para atendido com evidência própria.

### P3 — A-05 (G-02): mitigação do sombreamento `.so`

**Esforço:** pequeno · **Confiança:** alta.
- Alvo `clean-ext` (remove `src/**/*.so`) documentado no README; aviso no smoke_multiplayer quando detectar `.so` in-place mais novo que o `.py` correspondente.
- **Aceitação:** `python -m codecon_amoung_us.net.server` executa após `clean-ext` sem rebuild; aviso aparece no cenário stale.

### P3 — A-06 (G-04): varredura literária complementar

**Esforço:** pequeno · **Confiança:** média.
- Com as fontes 2026 já localizadas, a adequação do método construtivo está sustentada. Ação restante: varredura direcionada em venues (FDG/AIIDE/IEEE ToG 2025-2026) por trabalhos sobre *determinismo/reprodutibilidade* em PCG por seed — apenas para confirmar que não há prática contraindicando o modelo atual. Parar por convergência.

### P3 — A-07 (G-08): evidência de ambiente para V-05/V-06

**Esforço:** pequeno · **Confiança:** baixa (requisito não detalhado no contexto).
- Apenas obtenção de evidência: reproduzir o bloqueio (bind porta 80 sem privilégio; descoberta LAN) e documentar o comportamento observado — sem correção, pois o requisito completo não está no contexto desta sessão.

**Ordem de execução:** A-01 → A-03 → A-02 → A-04 → (A-05, A-06, A-07 em paralelo). A-01 primeiro porque muda o protocolo e os testes de A-03/A-02 devem rodar sobre o estado final.

---

## 5. Estratégia de verificação

| Ação | Verificação                                                                                              | Critério de aceitação                                                               |
| ---- | -------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| A-01 | teste de decode msgspec; integração asset-mode ponta-a-ponta; framing v4; regressão procedural (seed 42) | asset: clientes com geometria == lab.json; procedural: inalterado; framing aceita 4 |
| A-02 | `tests/test_scene_determinism.py`                                                                          | 2 renders mesma seed → bytes idênticos; <100 ms; falha se `scene.py` mudar saída      |
| A-03 | smoke ×5; integração ×3                                                                                  | zero flake; nenhum grid de asset contra servidor procedural                         |
| A-04 | suíte completa + `--check` + smoke ×3; leitura do job windows no CI                                        | tudo verde; baselines consistentes entre SO ou decisão documentada                  |
| A-05 | `clean-ext` + execução do servidor; cenário stale                                                          | servidor executa pós-limpeza; aviso aparece                                         |
| A-06 | busca adicional direcionada                                                                              | convergência ou registro de contraindicação                                         |
| A-07 | reprodução do bloqueio de ambiente                                                                       | comportamento documentado                                                           |

Regressão global: suíte completa nos dois modos (nativo e `CODECON_SKIP_NATIVE=1`), `--check`, e o novo teste de asset-mode de A-01 como gate permanente.

---

## 6. Riscos, dependências e questões inconclusivas

- **Risco confirmado (G-06):** o sentinela `map_seed=0` é intrinsecamente ambíguo — `--seed 0` é entrada CLI válida e `SystemRandom` pode sortear 0. Correção por heurística no cliente é insustentável; só o contrato explícito resolve. (Observado no código.)
- **Hipótese (G-07):** o mismatch asset-vs-procedural no harness causa flakiness real — o fato do mismatch é observado; a taxa de falha precisa de medição (A-03 inclui smoke ×5).
- **Inconclusivo (G-05):** SDL version entre runners ubuntu/windows pode divergir a rasterização; evidência só existe após um run de CI pós-feature. A-04 resolve.
- **Inconclusivo (G-03):** métricas de execução (889 passed, smoke) permanecem alegações de sessão até A-04.
- **Dependência externa (G-08):** V-05/V-06 dependem de ambiente (privilégios de porta/rede) fora do alcance desta sessão.
- **API a validar (A-01):** comportamento de `Meta` sobre `int | None` no msgspec 0.21 — primeira verificação do Build Agent; alternativa documentada acima.

---

## 7. Definição global de concluído

1. **G-06:** com `--map`, uma partida multiplayer ponta-a-ponta tem clientes renderizando exatamente o asset do servidor (teste de integração permanente); sem `--map`, fluxo procedural idêntico ao atual; protocolo v4 com framing atualizado.
2. **G-01:** teste unitário de determinismo da cena verde e no gate de regressão.
3. **G-07:** smoke e helpers de integração navegam exclusivamente pela geometria do servidor; 5 execuções consecutivas sem flake.
4. **G-03/G-05:** suíte completa, `--check` e smoke executados com resultado registrado; job windows do CI verde pós-feature (baselines consistentes).
5. **G-02:** mitigação documentada e aviso operando.
6. **G-04:** varredura complementar registrada (ou convergência documentada).
7. **G-08:** comportamento de ambiente documentado (sem correção prometida).
8. Tudo commitado com `ruff` + type checker + pytest verdes nos dois modos, sem TODOs pendentes nos arquivos alterados.

---

## 8. Referências

**Científicas (verificadas via searchmesh/OpenAlex em 2026-08-31):**
1. Mao, X. et al. *Procedural Content Generation via Generative Artificial Intelligence*. Interdisciplinary Information Sciences, 2026. DOI: `10.4036/iis.2026.r.01` (arXiv:2407.09013).
2. Baharvand, D. et al. *A deep generative approach to personalized super mario level design*. Scientific Reports, 2026. DOI: `10.1038/s41598-026-46199-1`.
3. Farrokhi Maleki, M.; Zhao, R. *PCG in Games: A Survey with Insights on Emerging LLM Integration*. AIIDE 2024. DOI: `10.1609/aiide.v20i1.31877`.
4. Summerville, A. et al. *Procedural Content Generation via Machine Learning (PCGML)*. IEEE ToG, 2018. DOI: `10.1109/TG.2018.2846639`.

**Documentação oficial / prática de engenharia:**
5. msgspec — Constraints (`Annotated` + `Meta`): https://msgspec.dev/constraints
6. msgspec — Structs (campos opcionais/defaults): https://msgspec.dev/structs
7. setuptools — Building Extension Modules: https://setuptools.pypa.io/en/latest/userguide/ext_modules.html
8. c-extension-tutorial — Building and Importing (`--inplace` coloca `.so` na árvore de fontes): https://llllllllll.github.io/c-extension-tutorial/building-and-importing.html
9. Golden-file/visual-regression practice (não revisado por pares): https://qaskills.sh/blog/regression-testing-golden-file-management · https://www.javascript-testing.com/component-integration-testing-frameworks/visual-regression-testing/reducing-flaky-screenshots-with-deterministic-rendering · https://bugbench.com/how-to-debug-flaky-visual-regression-tests-without-blaming-the-screenshot-tool

**Evidência interna (lida em 2026-08-31):** `app.py:256,736-744` · `server.py:168-174,563,1093` · `protocol.py:72-75,205-208` · `smoke_multiplayer.py:84-92,239-245` · `test_integration.py:344,445,1227-1293` · `ci.yml:9-14,36-47,109-124` · `render.py:121-133` · `plans/mapa-procedural-seed-pastel.md`.

---

## Questão em aberto (decisão do usuário antes de A-01)

A correção A-01 envolve **bump do protocolo para v4** (mudança de tipo do campo `map_seed`). Cliente e servidor embarcam juntos, então é seguro internamente; porém, se existir cliente externo/antigo que precise continuar conectando, prefira a Alternativa B (campo novo `map_source`, mantendo `map_seed: int` e sem bump). A-01 só deve iniciar após essa escolha.
