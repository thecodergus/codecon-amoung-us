# Plano — Lacunas dos VERIFICADO COM RESSALVAS (frescor de assets, QA visual, cantos)

> Status: em execução (2026-08-30). Origem: auditoria técnica de 2026-08-30
> sobre o trabalho de mapa expandido + câmera 2D (`mapa-expandido-camera-2d.md`),
> que concluiu 6 VERIFICADO e 2 VERIFICADO COM RESSALVAS (M-02 builder/assets,
> M-06 wiring da câmera). Este plano cobre as lacunas dessas ressalvas e os
> achados associados (F-01..F-03 + licença do tileset).

## Diagnóstico consolidado

| Lacuna | Origem | Classificação | Ação |
| ------ | ------ | ------------- | ---- |
| G-01: câmera/mapa/menu verificados só headless (SDL dummy) | F-01 / M-06 | inconclusivo (sem evidência de defeito; verificação ausente) | A-02, A-03, A-04 |
| G-02: determinismo da regeneração dos assets não demonstrado continuamente | F-02 / M-02 | parcialmente atendido | A-01 |
| G-03: testes de clamp cobrem 2 de 4 cantos | F-03 | parcialmente atendido | A-05 |
| G-04: licença do tileset não verificada | auditoria §7 item 3 | **atendido** (resolvido por fonte primária local) | A-06 (opcional) |

Causa-raiz compartilhada: ausência de verificação contínua/automatizada para
frescor dos assets gerados (G-02) e fidelidade visual/windowing (G-01). O CI
existe (`.github/workflows/ci.yml`, matrix ubuntu+windows) e o determinismo de
pixels já é provado nele (teste de HUD pixel-exato) — faltam os gates.

## Pesquisa aplicada (2026-08-30)

- **Xvfb + xvfb-run/PyVirtualDisplay**: prática padrão para testes GUI/pygame
  em CI headless com servidor X real (driver x11, eventos de janela reais).
- **Regressão visual golden-image**: baselines commitadas + comparação por
  pixels; ferramentas pytest maduras (pytest-image-snapshot,
  pytest-regressions); neste codebase a comparação pode ser pixel-exata.
- **Freshness check de arquivos gerados**: rodar o gerador no CI e falhar com
  diff — padrão consolidado (git diff --exit-code). PNGs comparados por pixels
  decodificados (imune a variação de encoder entre plataformas).
- **SOTA acadêmico 2026 de teste de jogos (LLM-agent playtesting)**: SAGE
  (Cai et al., 2026, DOI 10.1007/s10515-026-00635-8) e KLPEG (Mu et al., 2026,
  DOI 10.1587/transinf.2025kbp0004) — **rejeitados por desproporcionalidade**
  (exigem infra de LLM; alvo são jogos complexos; o gap é uma câmera 2D
  determinística). Lacuna bibliográfica: literatura revisada por pares sobre
  regressão visual de renderização 2D é escassa; evidência aplicável é a
  prática de engenharia documentada.
- **pytest.mark.parametrize**: mecanismo canônico (doc oficial) para G-03.
- **Licença do tileset** (`models/mapa/Top Down Lab files/public-license.txt`,
  Luis Zuno/@ansimuz): uso pessoal/comercial, modificação e redistribuição
  permitidas; crédito não exigido, apreciado.

## Ações

### Fase 1 — Gate de frescor dos assets (P2)

- **A-01 (G-02)**: modo `--check` em `scripts/build_lab_map.py` — regenera em
  memória e compara com os assets commitados (`lab.json` byte-a-byte;
  `lab_scene.png`/`lab_menu.png`/`overlay-lab.png` por pixels decodificados via
  `pygame.image.load` + `tobytes("RGBA")`), exit≠0 com relatório de
  divergência. Fatorar `_generate()` (prelúdio comum), `menu_crop()` e
  `overlay_surface()` (de `save_menu_crop`/`draw_overlay`, que passam a só
  salvar). Job ubuntu-only no CI. Comportamento padrão do builder inalterado.

### Fase 2 — Verificação visual automatizada (P2)

- **A-02 (G-01)**: `tests/test_visual_regression.py` + baselines commitadas em
  `tests/baselines/` — gameplay com câmera no centro e nos 4 cantos + menu
  principal, comparação pixel-exata via `pygame.image.tobytes` (padrão já
  provado pelo teste de HUD). Determinismo: `pygame.time.get_ticks` fixado por
  monkeypatch (pulsação/animação dependem de ticks); `renderer.reduced_motion`
  forçado. Escape: `UPDATE_BASELINES=1` regenera baselines.
- **A-03 (G-01)**: job Xvfb no CI (ubuntu-only): `apt-get install xvfb`,
  `SDL_VIDEODRIVER=x11 xvfb-run -a uv run pytest <subconjunto UI>`. Os testes
  usam `os.environ.setdefault` — `x11` no ambiente é respeitado.

### Fase 3 — Residual manual, refinos e higiene (P3)

- **A-04 (G-01 residual)**: estender `plans/checklist-ambiente-real.md` com
  seção "Câmera 2D" (centro, 4 cantos, HUD fixo, menu, suavização sem jitter,
  sem travelling inicial). Execução manual aguarda hardware (funde-se ao G-13).
- **A-05 (G-03)**: fundir `test_clamp_left_top`/`test_clamp_right_bottom` em
  `test_clamp_corners` parametrizado (4 cantos: posição, offset esperado).
- **A-06 (G-04, opcional)**: crédito do tileset "Top Down Lab" (Luis
  Zuno/@ansimuz) no README.

## Definição de concluído

1. CI com gate de frescor (A-01) verde no HEAD e falhando sob divergência
   artificial;
2. regressão visual (A-02) e job Xvfb (A-03) verdes no CI;
3. checklist estendido (A-04) executado em hardware real ou bloqueio
   explicitado com a parte automatizável coberta por 2;
4. 4 cantos parametrizados e verdes (A-05);
5. crédito do tileset no README (A-06);
6. gates do projeto verdes: `uv run ruff format --check . && uv run ruff
   check . && uv run mypy && uv run pytest && uv run python
   scripts/smoke_multiplayer.py`.

## Riscos e mitigações

- **Falso positivo de PNG por encoder** (libpng/SDL entre plataformas):
  comparação por pixels decodificados; job de frescor ubuntu-only.
- **Golden-images frágeis a mudanças legítimas de arte**: processo de update
  documentado (`UPDATE_BASELINES=1`); escopo inicial no renderer + menu.
- **Flake de timing sob X real**: subconjunto UI reduzido; reversão trivial
  (remover job).
- **Windows no CI**: teste de HUD pixel-exato já passa na matrix — evidência
  de que comparação pixel-exata é viável nos 2 SOs; se o menu divergir,
  ajustar baselines/escopo.
