# Plano — Início de partida no lobby com jogador único + lobby fiel

Data: 2026-08-29
Status: aprovado para execução
Origem: bug reportado pelo usuário — clicar em "Iniciar (host)" com
"Jogadores: (vazio)(host)" não produzia nenhum efeito visível.

## 1. Síntese do diagnóstico

1. **Clique sem efeito = `ActionDenied` engolido pela UI.** O botão "Iniciar
   (host)" chama `_start_game` (ui/app.py:212-214) → `StartGameRequest`. O
   servidor rejeita quando `len(players) < min_players_to_start` (server.py:392-
   394) — `min_players_to_start = 2` (config.py:75). Com apenas o host (1
   jogador) o servidor responde `ActionDenied("jogadores insuficientes")`, e o
   ramo `ActionDenied` da UI é silencioso (app.py:283-284).
2. **Lobby mostra "(vazio)" mesmo com o host conectado.** `SimulatedClient.connect`
   consome o `JoinAccepted` via `wait_for` (net/client.py:64); o
   `App._handle_message(JoinAccepted)` (app.py:253-256) que popularia
   `lobby_players` nunca roda para o próprio join. O recv loop seta `player_id`/
   `host_player_id` (client.py:106-108), mas `lobby_players` fica `[]` →
   `_refresh_lobby` (app.py:326-331) renderiza "(vazio)".
3. **Armadilha da partida solo:** `check_win` (game/rules.py:142-143) retorna
   vitória dos tripulantes quando `alive_impostors == 0`; com 1 jogador,
   `_start_game` (server.py:399) atribui `impostor_count = min(1, 0) = 0`, o host
   seria tripulante e a partida encerraria instantaneamente no primeiro tick.

## 2. Decisão (usuário)

Permitir iniciar partida **sozinho** (Ramo A): `min_players_to_start = 1`. O host
entra como tripulante e vence ao completar as tarefas; a regra de vitória é
ajustada para não decretar vitória instantânea em partida sem impostor.

## 3. Mudanças

### 3.1 Lobby fiel (sempre)

- `net/client.py`: guardar o último `JoinAccepted` recebido no recv loop
  (`self._join`), expor propriedade `join_accepted`. Sem alterar `wait_for`/
  `drain` (nenhum teste consome `JoinAccepted` após `connect` — verificado).
- `ui/app.py::_enter_lobby`: popular `my_id`, `host_id` e `lobby_players` a
  partir de `client.join_accepted` antes do `_refresh_lobby` (vale para host e
  joiner).

### 3.2 Feedback visível de `ActionDenied` no lobby (sempre)

- `ui/app.py`: adicionar label de aviso ao `lobby_menu` (mesmo padrão de
  `lobby_list_label`, app.py:139). No ramo `ActionDenied` (app.py:283-284): se
  `screen_name == "lobby"`, exibir `message.reason` no label; limpar o aviso ao
  entrar no lobby e ao clicar em "Iniciar". Não usar `_show_error` (o "Voltar"
  dela vai ao menu sem derrubar a conexão — gap G-22 conhecido).

### 3.3 Início solo (Ramo A)

- `config.py:75`: `min_players_to_start: int = 1`.
- `game/rules.py::check_win`: quando `alive_impostors == 0`, vencer só se houve
  papel IMPOSTOR na partida (impostor eliminado) **ou** todas as tarefas
  concluídas; caso contrário `None` (partida sem impostor continua até as
  tarefas). Preserva o invariante de `test_win_crew_when_no_impostors` (o
  impostor morto ainda possui o papel).

## 4. Testes

- `tests/test_rules.py`: partida sem papel IMPOSTOR + tarefas pendentes →
  `check_win is None`; com tarefas concluídas → `Team.CREW`.
- `tests/test_integration.py`: 1 cliente → `start_game` → `StartGame` +
  `RoleAssigned(CREW)`, sem `GameOver` imediato; completar as 2 tarefas →
  `GameOver(CREW)`.
- `tests/test_ui_events.py`: com servidor real — `_create_game` popula
  `lobby_players` com o host e o label do lobby mostra o nickname; `_start_game`
  transiciona para `screen_name == "game"`.

## 5. Verificação

- `uv run pytest -v` verde (suíte atual 129 testes + novos).
- `uv run ruff format --check . && uv run ruff check .` e `uv run mypy .` limpos.
- Manual: `uv run codecon-amoung-us` → Host → lobby mostra "Jogadores: host
  (host)" → "Iniciar (host)" inicia a partida.

## 6. Riscos

- Partida solo é degenerada por natureza (sem impostor, apenas tarefas); o
  ajuste de `check_win` é mínimo e preserva todos os invariantes testados.
- Fora de escopo: gap G-22 (conexão órfã no `_back_to_main`) não é tocado; a
  Etapa 3.2 evita navegar por essa tela.
