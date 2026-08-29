# Checklist de verificação em ambiente real (G-13)

Bloqueio: exige 2 máquinas na mesma LAN e 1 display real. Executar após as
fases do `plano-lacunas-2026-08.md` e registrar resultado ao final.

## LAN (2 máquinas)

- [ ] Servidor: `uv run codecon-amoung-us-server --port 5555` na máquina A
      (ou "Criar partida" pela UI).
- [ ] Cliente B: "Entrar em partida" com o IP da máquina A → entra no lobby.
- [ ] Iniciar partida; movimento WASD de B aparece para A e vice-versa.
- [ ] Report de corpo / botão de emergência abre reunião nos dois lados.
- [ ] Votação com 7+ jogadores (bots ou 2 humanos + instâncias extra):
      todos os cards e os botões PULAR/VOTAR visíveis; paginação por setas,
      PgUp/PgDn e roda do mouse; voto por teclado (Enter/Espaço) funciona.
- [ ] Cancelar "Conectando…" durante o join: sem cliente fantasma no lobby;
      cancelar durante "Criar partida" permite hospedar de novo na mesma
      porta (sem EADDRINUSE).

## Display real (1 máquina com monitor)

- [ ] Janela abre em 1280x768 lógico; redimensionar mantém aspecto
      (letterbox) e o mouse mapeia corretamente (cliques nos cards/botões).
- [ ] Perda de foco da janela (Alt+Tab) não deixa o jogador andando sozinho.
- [ ] Votação e game over renderizam sem overflow visual em partida real de
      8–10 jogadores.
- [ ] Sem warnings de fonte/glyph no terminal.

## Registro

| Data | Executor | Cenário | Resultado | Observações |
| ---- | -------- | ------- | --------- | ----------- |
|      |          | LAN     |           |             |
|      |          | Display |           |             |
