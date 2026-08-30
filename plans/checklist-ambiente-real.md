# Checklist de verificação em ambiente real (G-13)

Bloqueio: exige 2 máquinas na mesma LAN e 1 display real. Executar após as
fases do `plano-lacunas-2026-08.md` e do `fechamento-redesign-ui-ux-sigilo.md`;
registrar resultado ao final.

## LAN (2 máquinas)

- [ ] Servidor: `uv run codecon-amoung-us-server --port 5555` na máquina A
      (ou "Criar partida" pela UI).
- [ ] Cliente B: "Entrar em partida" com o IP da máquina A → entra no lobby.
- [ ] Lobby atualiza nos dois lados a cada join/leave.
- [ ] Iniciar partida; movimento WASD de B aparece para A e vice-versa.
- [ ] Tarefas completam (E) e o progresso aparece no HUD.
- [ ] Kill funciona (impostor, Espaço) com cooldown visível no HUD.
- [ ] Report de corpo / botão de emergência abre reunião nos dois lados.
- [ ] Votação com 7+ jogadores (bots ou 2 humanos + instâncias extra):
      todos os cards e os botões PULAR/VOTAR visíveis; paginação por setas,
      PgUp/PgDn e roda do mouse; voto por teclado (Enter/Espaço) funciona;
      sem duplo envio (botão entra em "enviando" e trava).
- [ ] **Sigilo pós-votação (contrato):** o ejetado vê a tela privada
      "VOCÊ FOI EJETADO"; os demais veem SOMENTE a transição genérica
      "REUNIÃO ENCERRADA" — idêntica para ejeção, empate e skip, sem nome,
      papel ou contagem. No snapshot seguinte, o ejetado aparece morto
      (alive=false), indistinguível de morte por kill.
- [ ] Game over revela os papéis para todos; desconexão em partida não deixa
      sessão órfã (jogador some/morre e a partida segue).
- [ ] Cancelar "Conectando…" durante o join: sem cliente fantasma no lobby;
      cancelar durante "Criar partida" permite hospedar de novo na mesma
      porta (sem EADDRINUSE).

## Interação e acessibilidade (display real)

- [ ] Botões respondem a hover (realce) e pressed (escurece) e ativam no
      mouse up; mouse up fora do botão não ativa.
- [ ] Navegação por teclado (Tab/Shift+Tab/Enter) persiste entre frames no
      lobby, connecting, game over e error; o anel de foco é perceptível e
      distinto do hover.
- [ ] Menu Configurações → "Reduzir movimento": alternar aplica
      imediatamente (pulsação dos marcadores para/retoma sem reiniciar).

## Display real (1 máquina com monitor)

- [ ] Janela abre em 1280x768 lógico; redimensionar mantém aspecto
      (letterbox) e o mouse mapeia corretamente (cliques nos cards/botões),
      inclusive em 16:9, janela larga e janela pequena; cliques na faixa do
      letterbox não produzem ação.
- [ ] Perda de foco da janela (Alt+Tab) não deixa o jogador andando sozinho.
- [ ] Votação e game over renderizam sem overflow visual em partida real de
      8–10 jogadores.
- [ ] Sem warnings de fonte/glyph no terminal.

## Câmera 2D (mapa 2560x1408)

Cobre o residual não automatizável do plano `lacunas-ressalvas-camera-2d.md`
(A-02/A-03 já cobrem regressão visual e windowing real em CI).

- [ ] Jogador no interior do mapa (hub) permanece centralizado no viewport
      durante o movimento.
- [ ] Nos 4 cantos do mapa a câmera para no limite: nenhuma área além do
      mapa é exibida e o jogador fica visível junto à borda da tela.
- [ ] Suavização sem jitter perceptível em movimento contínuo reto e em
      diagonal; câmera acompanha sem degraus após mudança brusca de direção.
- [ ] Início da partida sem travelling: primeiro frame já na posição do
      jogador (sem varredura desde a origem).
- [ ] HUD (papel, tarefas, vivos, prompt) permanece fixo na faixa inferior
      com a câmera em movimento; nicknames e círculo do jogador local
      alinhados aos sprites.
- [ ] Menu principal sem distorção (crop do hub) e sem barras inesperadas.

## Registro

| Data | Executor | Cenário | Resultado | Observações |
| ---- | -------- | ------- | --------- | ----------- |
|      |          | LAN     |           |             |
|      |          | Display |           |             |
