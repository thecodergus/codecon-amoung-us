"""Integração: servidor + clientes simulados (lobby, início, regras, votação).

Cada teste usa servidor em porta efêmera, shutdown limpo via fixture e
``pytest-timeout`` como rede de segurança.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest

from codecon_amoung_us.config import PROTOCOL_VERSION, GameConfig
from codecon_amoung_us.game.model import Phase, Role, Team
from codecon_amoung_us.map.model import GameMap
from codecon_amoung_us.net.client import SimulatedClient
from codecon_amoung_us.net.server import GameServer
from codecon_amoung_us.protocol import (
    ActionAccepted,
    ActionDenied,
    ActionKind,
    DenialCode,
    Ejected,
    GameOver,
    JoinRequest,
    MeetingEnded,
    MeetingStarted,
    PlayerDisconnected,
    PlayerJoined,
    ProtocolError,
    RoleAssigned,
    StartGame,
)

pytestmark = pytest.mark.integration


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _raw_join(
    port: int, nickname: str = "raw", protocol_version: int = PROTOCOL_VERSION
) -> tuple[ProtocolError | None, bool]:
    """Envia JoinRequest por socket cru e lê a resposta.

    Retorna (ProtocolError recebido, conexão fechada pelo servidor). Usado nos
    caminhos de rejeição do join, onde o cliente não recebe JoinAccepted.
    """
    import time as _time

    from codecon_amoung_us.framing import encode_frame

    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.settimeout(5.0)
        sock.sendall(
            encode_frame(JoinRequest(nickname=nickname, protocol_version=protocol_version))
        )
        buf = b""
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        if b"\n" not in buf:
            return None, False
        from codecon_amoung_us.protocol import decode

        msg = decode(buf.split(b"\n", 1)[0])
        if not isinstance(msg, ProtocolError):
            return None, False
        sock.settimeout(1.0)
        try:
            closed = sock.recv(1) == b""
        except TimeoutError:
            closed = False
        return msg, closed


@pytest.fixture
def server() -> Iterator[GameServer]:
    """Servidor em porta efêmera com shutdown limpo garantido."""
    srv = GameServer(host="127.0.0.1", port=_free_port(), config=GameConfig())
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture
def four_clients(server: GameServer) -> list[SimulatedClient]:
    """Quatro clientes conectados e aceitos no lobby (sincronizado pelo servidor)."""
    import time as _time

    clients = [SimulatedClient() for _ in range(4)]
    for i, client in enumerate(clients):
        client.connect("127.0.0.1", server.port, f"player{i}", timeout=5.0)
    deadline = _time.monotonic() + 5.0
    while _time.monotonic() < deadline and len(server._state.players) < 4:
        _time.sleep(0.01)
    assert len(server._state.players) == 4
    return clients


@pytest.mark.timeout(30)
def test_four_clients_join_lobby(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    for client in four_clients:
        assert client.player_id is not None
        assert client.host_player_id is not None
    # host é o primeiro a entrar
    assert four_clients[0].host_player_id == four_clients[0].player_id
    # distribuição de PlayerJoined: cliente i recebe (3 - i) anúncios
    for i, client in enumerate(four_clients):
        announced = [m for m in client.drain() if isinstance(m, PlayerJoined)]
        assert len(announced) == 3 - i


@pytest.mark.timeout(30)
def test_start_game_assigns_one_impostor(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    host = four_clients[0]
    host.start_game()
    for client in four_clients:
        start = client.wait_for(StartGame, timeout=5.0)
        assert start.map_name == "lab"
        assert len(start.players) == 4
        assigned = client.wait_for(RoleAssigned, timeout=5.0)
        assert assigned.role in (Role.CREW, Role.IMPOSTOR)
        if assigned.role is Role.IMPOSTOR:
            assert assigned.task_ids == []
        else:
            assert len(assigned.task_ids) == 2
    roles = [c.role for c in four_clients]
    assert roles.count(Role.IMPOSTOR) == 1
    assert roles.count(Role.CREW) == 3


@pytest.mark.timeout(30)
def test_non_host_cannot_start(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    four_clients[1].start_game()
    denied = four_clients[1].wait_for(ActionDenied, timeout=5.0)
    assert "host" in denied.reason
    # ainda em lobby
    assert server._state.phase is Phase.LOBBY


@pytest.mark.timeout(40)
def test_solo_host_starts_and_wins_by_tasks(server: GameServer) -> None:
    # Jogador único: o host inicia a partida como tripulante (sem impostor) e
    # vence ao completar as tarefas — não há vitória instantânea no 1º tick.
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    client = SimulatedClient()
    try:
        client.connect("127.0.0.1", server.port, "solo", timeout=5.0)
        client.start_game()
        start = client.wait_for(StartGame, timeout=5.0)
        assert start.map_name == "lab"
        assert len(start.players) == 1
        assigned = client.wait_for(RoleAssigned, timeout=5.0)
        assert assigned.role is Role.CREW
        # sem GameOver imediato: a partida continua até as tarefas
        assert client.peek(GameOver) is None
        assigned_tasks = list(assigned.task_ids)
        assert assigned_tasks, "jogador único deveria ter tarefas atribuídas"
        game_map = load_map(default_map_path())
        for task_id in assigned_tasks:
            point = next(tp for tp in game_map.task_points if tp.task_id == task_id)
            assert _move_to_point(client, point.x, point.y, timeout=20.0)
            client.complete_task(task_id)
        over = client.wait_for(GameOver, timeout=10.0)
        assert over.winner is Team.CREW
        assert server._state.phase is Phase.ENDED
    finally:
        client.close()


@pytest.mark.timeout(30)
def test_snapshots_flow_after_start(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)
    snap = four_clients[0].wait_for_snapshot(timeout=5.0)
    assert len(snap.players) == 4
    assert all(p.alive for p in snap.players)


@pytest.mark.timeout(30)
def test_disconnect_in_lobby_broadcasts(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    leaver = four_clients[2]
    leaver.close()
    # os demais recebem PlayerDisconnected
    for client in four_clients[:2]:
        disc = client.wait_for(PlayerDisconnected, timeout=5.0)
        assert disc.player_id == leaver.player_id


@pytest.mark.timeout(30)
def test_impostor_kill_and_body_in_snapshot(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)
    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    assert _move_next_to(impostor, target.player_id, server.config.kill_radius)
    impostor.kill(target.player_id)
    # corpo aparece no snapshot (algum cliente observa)
    bodies_seen = False
    import time as _time

    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        latest = impostor.snapshot
        if latest and latest.bodies:
            bodies_seen = True
            break
        _time.sleep(0.02)
    assert bodies_seen, "corpo não apareceu no snapshot"


@pytest.mark.timeout(30)
def test_malformed_frame_gets_protocol_error(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    client = four_clients[0]
    # envia payload malformado cru direto no socket
    sock = client._sock
    assert sock is not None
    sock.sendall(b"isto nao eh json\n")
    # servidor deve responder ProtocolError antes de fechar a conexão
    err = client.wait_for(ProtocolError, timeout=5.0)
    assert err.code == "bad_frame"
    # o servidor segue saudável: um novo cliente ainda conecta e é aceito
    extra = SimulatedClient()
    extra.connect("127.0.0.1", server.port, "late", timeout=5.0)
    extra.close()


def _walkable_grid(game_map: GameMap) -> list[list[bool]]:
    """Grade de células (64px) do mapa: célula livre = centro fora de paredes.

    Usada pela navegação BFS dos testes; independe do layout do asset.
    """
    grid: list[list[bool]] = []
    for cy in range(game_map.height):
        row: list[bool] = []
        for cx in range(game_map.width):
            px = cx * game_map.tile_width + game_map.tile_width / 2
            py = cy * game_map.tile_height + game_map.tile_height / 2
            free = not any(
                wall.left < px < wall.right and wall.top < py < wall.bottom
                for wall in game_map.walls
            )
            row.append(free)
        grid.append(row)
    return grid


def _plan_path(
    game_map: GameMap,
    start: tuple[float, float],
    goal: tuple[float, float],
) -> list[tuple[float, float]]:
    """Waypoints em px do caminho BFS (ortogonal) entre pontos, com poda de
    colineares. Válido para qualquer mapa Tiled do projeto."""
    from collections import deque

    grid = _walkable_grid(game_map)
    tw = game_map.tile_width
    th = game_map.tile_height

    def cell_of(px: float, py: float) -> tuple[int, int]:
        return int(px // tw), int(py // th)

    start_cell = cell_of(*start)
    goal_cell = cell_of(*goal)
    if not (0 <= start_cell[0] < game_map.width and 0 <= start_cell[1] < game_map.height):
        return [goal]
    if not grid[start_cell[1]][start_cell[0]]:
        return [goal]
    prev: dict[tuple[int, int], tuple[int, int] | None] = {start_cell: None}
    queue: deque[tuple[int, int]] = deque([start_cell])
    while queue:
        cur = queue.popleft()
        if cur == goal_cell:
            break
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt = (cur[0] + dx, cur[1] + dy)
            if (
                0 <= nxt[0] < game_map.width
                and 0 <= nxt[1] < game_map.height
                and grid[nxt[1]][nxt[0]]
                and nxt not in prev
            ):
                prev[nxt] = cur
                queue.append(nxt)
    if goal_cell not in prev:
        return [goal]
    cells: list[tuple[int, int]] = []
    node: tuple[int, int] | None = goal_cell
    while node is not None:
        cells.append(node)
        node = prev[node]
    cells.reverse()
    pruned: list[tuple[int, int]] = [cells[0]]
    for cell in cells[1:]:
        if len(pruned) >= 2 and (
            pruned[-1][0] == pruned[-2][0] == cell[0] or pruned[-1][1] == pruned[-2][1] == cell[1]
        ):
            pruned[-1] = cell
        else:
            pruned.append(cell)
    return [(cx * tw + tw / 2, cy * th + th / 2) for cx, cy in pruned]


def _move_to_point(client: SimulatedClient, tx: float, ty: float, timeout: float = 20.0) -> bool:
    """Move o cliente até um ponto navegando pelo caminho BFS do mapa.

    Deriva os waypoints do asset carregado (independe do layout); a última
    perna vai direto ao destino.
    """
    import math
    import time as _time

    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    game_map = load_map(default_map_path())
    waypoints: list[tuple[float, float]] = []
    wp_index = 0
    deadline = _time.monotonic() + timeout
    while _time.monotonic() < deadline:
        snap = client.snapshot
        if snap is None:
            _time.sleep(0.02)
            continue
        me = next((p for p in snap.players if p.player_id == client.player_id), None)
        if me is None:
            _time.sleep(0.02)
            continue
        if not waypoints:
            waypoints = _plan_path(game_map, (me.x, me.y), (tx, ty))
        wx, wy = waypoints[wp_index]
        dx, dy = wx - me.x, wy - me.y
        dist = math.hypot(dx, dy)
        # tolerância > 1 passo do servidor (180 px/s @ 20 Hz = 9 px/tick):
        # evita oscilação perto do waypoint sem nunca disparar a chegada
        if dist <= 12.0:
            wp_index += 1
            if wp_index >= len(waypoints):
                return True
            continue
        if dist > 0:
            client.move(dx / dist, dy / dist)
        _time.sleep(0.02)
    return False


def _move_next_to(impostor: SimulatedClient, target_id: int, kill_radius: float) -> bool:
    """Move o impostor até o raio de kill do alvo.

    Rota única via centro da cafeteria + destino (o alvo está parado).
    """
    import math
    import time as _time

    deadline = _time.monotonic() + 8.0
    while _time.monotonic() < deadline:
        snap = impostor.snapshot
        if snap is None:
            _time.sleep(0.02)
            continue
        me = next((p for p in snap.players if p.player_id == impostor.player_id), None)
        tgt = next((p for p in snap.players if p.player_id == target_id), None)
        if me is None or tgt is None:
            _time.sleep(0.02)
            continue
        if math.hypot(tgt.x - me.x, tgt.y - me.y) <= kill_radius:
            return True
        # navega direto ao alvo (waypoint interno do _move_to_point: centro + alvo)
        if _move_to_point(impostor, tgt.x, tgt.y, timeout=20.0):
            return True
    return False


@pytest.mark.timeout(30)
def test_report_triggers_meeting(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)
    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    assert _move_next_to(impostor, target.player_id, server.config.kill_radius)
    impostor.kill(target.player_id)
    # aguarda o corpo no snapshot e reporta
    body_id = None
    import time as _time

    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        latest = impostor.snapshot
        if latest and latest.bodies:
            body_id = latest.bodies[0].body_id
            break
        _time.sleep(0.02)
    assert body_id is not None, "corpo não apareceu"
    impostor.report(body_id)
    meeting = impostor.wait_for(MeetingStarted, timeout=5.0)
    assert meeting.reason.value == "kill_reported"
    assert meeting.meeting_id == 1


@pytest.mark.timeout(30)
def test_emergency_meeting_requires_proximity(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    import math

    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)
    # o spawn do host fica longe do botão (build_lab_map garante >= 2 células)
    game_map = load_map(default_map_path())
    spawn = game_map.spawn_points[0]
    emergency = game_map.emergency_meeting
    assert emergency is not None
    assert (
        math.hypot(emergency[0] - spawn.x, emergency[1] - spawn.y)
        > game_map.emergency_meeting_radius
    )
    four_clients[0].emergency()
    denied = four_clients[0].wait_for(ActionDenied, timeout=5.0)
    assert "alcance" in denied.reason


# ---------------------------------------------------------------------------
# Etapa 12: regras integradas + votação secreta na rede
# ---------------------------------------------------------------------------


def _start_game(four_clients: list[SimulatedClient]) -> None:
    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)


def _impostor_kills_and_reports(
    server: GameServer, four_clients: list[SimulatedClient]
) -> tuple[SimulatedClient, int, int]:
    """Mata um alvo e abre reunião por kill report. Retorna (impostor, alvo, meeting_id)."""
    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    assert _move_next_to(impostor, target.player_id, server.config.kill_radius)
    impostor.kill(target.player_id)
    import time as _time

    body_id = None
    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        latest = impostor.snapshot
        if latest and latest.bodies:
            body_id = latest.bodies[0].body_id
            break
        _time.sleep(0.02)
    assert body_id is not None, "corpo não apareceu"
    impostor.report(body_id)
    meeting = impostor.wait_for(MeetingStarted, timeout=5.0)
    return impostor, target.player_id, meeting.meeting_id


def _all_alive_voters(impostor: SimulatedClient) -> list[int]:
    """ids dos votantes elegíveis (vivos) no snapshot mais recente."""
    snap = impostor.snapshot
    assert snap is not None
    return [p.player_id for p in snap.players if p.alive]


@pytest.mark.timeout(40)
def test_voting_majority_ejection_is_secret_over_the_wire(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, killed_id, meeting_id = _impostor_kills_and_reports(server, four_clients)
    voters = _all_alive_voters(impostor)
    assert killed_id not in voters and len(voters) == 3
    # alvo do voto: um tripulante vivo (que não seja o impostor)
    victim = next(pid for pid in voters if pid != impostor.player_id)

    for client in four_clients:
        if client.player_id in voters:
            client.vote(meeting_id, victim)

    # O ejetado recebe Ejected (identidade + papel) + MeetingEnded
    ejected_client = next(c for c in four_clients if c.player_id == victim)
    msgs = ejected_client.wait_for_any((Ejected, MeetingEnded), timeout=5.0)
    assert isinstance(msgs, Ejected)
    assert msgs.player_id == victim
    ejected_client.wait_for(MeetingEnded, timeout=5.0)

    # Demais clientes: NUNCA Ejected; somente MeetingEnded, serializado com
    # exatamente os campos {type, meeting_id} (protocolo v2, sem booleano)
    import json

    for client in four_clients:
        if client.player_id == victim:
            continue
        m = client.wait_for(MeetingEnded, timeout=5.0)
        assert client.peek(Ejected) is None
        # verificação sobre o frame serializado efetivamente recebido
        from codecon_amoung_us.framing import encode_frame

        serialized = json.loads(encode_frame(m).rstrip(b"\n"))
        assert set(serialized.keys()) == {"type", "meeting_id"}


@pytest.mark.timeout(40)
def test_voting_tie_does_not_eject(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    _start_game(four_clients)
    impostor, _killed, meeting_id = _impostor_kills_and_reports(server, four_clients)
    voters = _all_alive_voters(impostor)
    others = [pid for pid in voters if pid != impostor.player_id]
    assert len(others) == 2
    # empate: impostor vota em A; A vota em B; B pula (skip) -> A:1, B:1
    a, b = others
    impostor.vote(meeting_id, a)
    next(c for c in four_clients if c.player_id == a).vote(meeting_id, b)
    next(c for c in four_clients if c.player_id == b).vote(meeting_id, None)

    for client in four_clients:
        client.wait_for(MeetingEnded, timeout=5.0)
        assert client.peek(Ejected) is None


@pytest.mark.timeout(40)
def test_game_over_when_impostor_ejected(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, _killed, meeting_id = _impostor_kills_and_reports(server, four_clients)
    assert impostor.player_id is not None
    imp_id = impostor.player_id
    voters = _all_alive_voters(impostor)
    crew_voters = [pid for pid in voters if pid != imp_id]
    # impostor pula; 2 tripulantes votam no impostor -> impostor ejetado
    impostor.vote(meeting_id, None)
    for pid in crew_voters:
        next(c for c in four_clients if c.player_id == pid).vote(meeting_id, imp_id)

    # impostor recebe Ejected + MeetingEnded; todos recebem GameOver (papéis revelados)
    imp_client = next(c for c in four_clients if c.player_id == imp_id)
    e = imp_client.wait_for(Ejected, timeout=5.0)
    assert e.role is Role.IMPOSTOR
    imp_client.wait_for(MeetingEnded, timeout=5.0)
    for client in four_clients:
        over = client.wait_for(GameOver, timeout=5.0)
        assert over.winner is Team.CREW
        assert over.roles[imp_id] is Role.IMPOSTOR


@pytest.mark.timeout(40)
def test_kill_out_of_range_is_denied(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    far = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    # sem se aproximar, o kill deve ser negado
    impostor.kill(far.player_id)
    denied = impostor.wait_for(ActionDenied, timeout=5.0)
    assert "kill" in denied.reason
    # nenhum corpo aparece
    import time as _time

    start = _time.monotonic()
    body_seen = False
    while _time.monotonic() - start < 1.0:
        latest = impostor.snapshot
        if latest and latest.bodies:
            body_seen = True
            break
        _time.sleep(0.02)
    assert not body_seen


@pytest.mark.timeout(40)
def test_crew_completes_task_and_sees_task_state(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    crew = next(c for c in four_clients if c.role is Role.CREW)
    assigned = [t for t in crew.tasks.tasks if not t.done] if crew.tasks else []
    assert assigned, "tripulante deveria ter tarefas atribuídas"
    task = assigned[0]
    # localiza o ponto da tarefa no mapa (task_id -> posição)
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    game_map = load_map(default_map_path())
    point = next(tp for tp in game_map.task_points if tp.task_id == task.task_id)
    assert _move_to_point(crew, point.x, point.y, timeout=20.0)
    crew.complete_task(task.task_id)
    # aguarda TaskState atualizado com a tarefa concluída
    import time as _time

    done = False
    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        ts = crew.tasks
        if ts and any(t.task_id == task.task_id and t.done for t in ts.tasks):
            done = True
            break
        _time.sleep(0.02)
    assert done, "TaskState não refletiu a conclusão"


# ---------------------------------------------------------------------------
# Endurecimento pós-auditoria: validação server-side e robustez de reunião
# ---------------------------------------------------------------------------


def _impostor_kills_only(
    server: GameServer, four_clients: list[SimulatedClient]
) -> tuple[SimulatedClient, int]:
    """Mata um alvo sem abrir reunião. Retorna (impostor, id do morto)."""
    import time as _time

    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    assert _move_next_to(impostor, target.player_id, server.config.kill_radius)
    impostor.kill(target.player_id)
    body_id = None
    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        latest = impostor.snapshot
        if latest and latest.bodies:
            body_id = latest.bodies[0].body_id
            break
        _time.sleep(0.02)
    assert body_id is not None, "corpo não apareceu"
    return impostor, target.player_id


@pytest.mark.timeout(40)
def test_report_out_of_range_is_denied(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, killed_id = _impostor_kills_only(server, four_clients)
    assert impostor.player_id is not None
    # outro tripulante vivo está no spawn (longe do corpo) -> report negado
    far = next(
        c for c in four_clients if c.player_id != impostor.player_id and c.player_id != killed_id
    )
    body_id = impostor.snapshot.bodies[0].body_id if impostor.snapshot else None
    assert body_id is not None
    far.report(body_id)
    denied = far.wait_for(ActionDenied, timeout=5.0)
    assert "alcance" in denied.reason
    assert far.peek(MeetingStarted) is None
    assert impostor.peek(MeetingStarted) is None


@pytest.mark.timeout(40)
def test_dead_player_cannot_report(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    _start_game(four_clients)
    impostor, killed_id = _impostor_kills_only(server, four_clients)
    body_id = impostor.snapshot.bodies[0].body_id if impostor.snapshot else None
    assert body_id is not None
    dead = next(c for c in four_clients if c.player_id == killed_id)
    dead.report(body_id)
    denied = dead.wait_for(ActionDenied, timeout=5.0)
    assert "morto" in denied.reason
    assert dead.peek(MeetingStarted) is None


@pytest.mark.timeout(30)
def test_duplicate_join_rejected(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    dup = four_clients[0]
    dup.send(JoinRequest(nickname="dup", protocol_version=PROTOCOL_VERSION))
    err = dup.wait_for(ProtocolError, timeout=5.0)
    assert err.code == "already_joined"
    # nenhum jogador fantasma foi criado
    assert len(server._state.players) == 4


@pytest.mark.timeout(30)
def test_lobby_full_rejected_with_protocol_error() -> None:
    srv = GameServer(host="127.0.0.1", port=_free_port(), config=GameConfig(max_players=1))
    srv.start()
    first = SimulatedClient()
    try:
        first.connect("127.0.0.1", srv.port, "one", timeout=5.0)
        err, closed = _raw_join(srv.port, "two")
        assert err is not None and err.code == "lobby_full"
        assert closed
        assert len(srv._state.players) == 1
    finally:
        first.close()
        srv.stop()


@pytest.mark.timeout(30)
def test_join_during_game_rejected(server: GameServer, four_clients: list[SimulatedClient]) -> None:
    four_clients[0].start_game()
    for client in four_clients:
        client.wait_for(StartGame, timeout=5.0)
        client.wait_for(RoleAssigned, timeout=5.0)
    err, closed = _raw_join(server.port, "late")
    assert err is not None and err.code == "game_in_progress"
    assert closed
    assert len(server._state.players) == 4


@pytest.mark.timeout(30)
def test_bad_version_rejected_direct(server: GameServer) -> None:
    # v0 é rejeitado pela constraint (ge=1) no decode; o handler permanece
    # como defesa em profundidade (testado por chamada direta).
    import socket as _socket

    from codecon_amoung_us.framing import FrameDecoder
    from codecon_amoung_us.net.server import ClientConnection
    from codecon_amoung_us.protocol import Message

    sock_a, sock_b = _socket.socketpair(_socket.AF_INET, _socket.SOCK_STREAM)
    conn = ClientConnection(server, sock_a)
    outbox: list[tuple[ClientConnection | None, Message]] = []
    server._on_join(conn, JoinRequest(nickname="x", protocol_version=0), outbox)
    sock_b.settimeout(2.0)
    data = sock_b.recv(4096)
    messages = FrameDecoder().feed(data)
    assert len(messages) == 1
    assert isinstance(messages[0], ProtocolError)
    assert messages[0].code == "bad_version"
    sock_a.close()
    sock_b.close()


@pytest.mark.timeout(40)
def test_vote_on_dead_target_denied(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, killed_id, meeting_id = _impostor_kills_and_reports(server, four_clients)
    impostor.vote(meeting_id, killed_id)
    denied = impostor.wait_for(ActionDenied, timeout=5.0)
    assert "morto" in denied.reason
    assert server._state.meeting is not None
    assert impostor.player_id not in server._state.meeting.votes


@pytest.mark.timeout(40)
def test_disconnect_during_meeting_finishes_immediately(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, _killed, meeting_id = _impostor_kills_and_reports(server, four_clients)
    assert impostor.player_id is not None
    imp_id = impostor.player_id
    voters = _all_alive_voters(impostor)
    others = [pid for pid in voters if pid != imp_id]
    assert len(others) == 2
    a, leaver_id = others
    # todos votam exceto o leaver, que desconecta sem votar
    impostor.vote(meeting_id, a)
    next(c for c in four_clients if c.player_id == a).vote(meeting_id, None)
    next(c for c in four_clients if c.player_id == leaver_id).close()
    # a reunião encerra imediatamente para os demais
    for client in four_clients:
        if client.player_id == leaver_id:
            continue
        m = client.wait_for_any((Ejected, MeetingEnded), timeout=5.0)
        if isinstance(m, Ejected):
            m = client.wait_for(MeetingEnded, timeout=5.0)
        else:
            assert isinstance(m, MeetingEnded)


@pytest.mark.timeout(40)
def test_meeting_timeout_finishes_without_votes() -> None:
    import time as _time

    srv = GameServer(
        host="127.0.0.1",
        port=_free_port(),
        config=GameConfig(meeting_vote_timeout_seconds=1.0),
    )
    srv.start()
    clients = [SimulatedClient() for _ in range(4)]
    try:
        for i, client in enumerate(clients):
            client.connect("127.0.0.1", srv.port, f"player{i}", timeout=5.0)
        deadline = _time.monotonic() + 5.0
        while _time.monotonic() < deadline and len(srv._state.players) < 4:
            _time.sleep(0.01)
        assert len(srv._state.players) == 4
        _start_game(clients)
        _impostor_kills_and_reports(srv, clients)
        # ninguém vota: a reunião deve terminar pelo timeout de 1s
        for client in clients:
            client.wait_for(MeetingEnded, timeout=10.0)
    finally:
        for client in clients:
            client.close()
        srv.stop()


# ---------------------------------------------------------------------------
# Protocolo v2: confirmações privadas (ActionAccepted), denials tipadas e
# rejeição de clientes v1 no wire
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_join_v1_rejected_with_bad_version(server: GameServer) -> None:
    # v1 decodifica (constraint ge=1, le=2), mas o servidor rejeita o join
    # com bad_version — clientes v1 não conhecem o schema v2.
    err, closed = _raw_join(server.port, "oldclient", protocol_version=1)
    assert err is not None
    assert err.code == "bad_version"
    assert closed
    assert len(server._state.players) == 0


@pytest.mark.timeout(40)
def test_vote_accepted_confirms_privately(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, _killed, meeting_id = _impostor_kills_and_reports(server, four_clients)
    impostor.vote(meeting_id, None)
    # o impostor ainda tem na fila o ActionAccepted(KILL) do kill — consome
    # confirmações até achar a do voto
    accepted = impostor.wait_for(ActionAccepted, timeout=5.0)
    if accepted.action is ActionKind.KILL:
        accepted = impostor.wait_for(ActionAccepted, timeout=5.0)
    assert accepted.action is ActionKind.VOTE
    assert accepted.cooldown_seconds is None


@pytest.mark.timeout(40)
def test_kill_accepted_confirms_cooldown(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor = next(c for c in four_clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=5.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    assert _move_next_to(impostor, target.player_id, server.config.kill_radius)
    impostor.kill(target.player_id)
    accepted = impostor.wait_for(ActionAccepted, timeout=5.0)
    assert accepted.action is ActionKind.KILL
    assert accepted.cooldown_seconds == server.config.kill_cooldown_seconds


@pytest.mark.timeout(40)
def test_kill_in_cooldown_denied_with_retry_after(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, killed_id = _impostor_kills_only(server, four_clients)
    impostor.wait_for(ActionAccepted, timeout=5.0)
    # outro tripulante vivo: aproxima e tenta matar durante o cooldown
    snap = impostor.wait_for_snapshot(timeout=5.0)
    other = next(
        p for p in snap.players if p.alive and p.player_id not in (impostor.player_id, killed_id)
    )
    assert _move_next_to(impostor, other.player_id, server.config.kill_radius)
    impostor.kill(other.player_id)
    denied = impostor.wait_for(ActionDenied, timeout=5.0)
    assert denied.action is ActionKind.KILL
    assert denied.code is DenialCode.COOLDOWN
    assert denied.retry_after_seconds is not None and denied.retry_after_seconds > 0
    # nenhum corpo novo apareceu
    import time as _time

    start = _time.monotonic()
    bodies_seen = len(impostor.snapshot.bodies) if impostor.snapshot else 0
    while _time.monotonic() - start < 1.0:
        latest = impostor.snapshot
        if latest and len(latest.bodies) > bodies_seen:
            break
        _time.sleep(0.02)
    assert len(impostor.snapshot.bodies) == bodies_seen if impostor.snapshot else True


@pytest.mark.timeout(40)
def test_task_out_of_range_denied_with_code(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    import math

    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    _start_game(four_clients)
    crew = next(c for c in four_clients if c.role is Role.CREW)
    assigned = [t for t in crew.tasks.tasks if not t.done] if crew.tasks else []
    assert assigned
    game_map = load_map(default_map_path())
    point = next(tp for tp in game_map.task_points if tp.task_id == assigned[0].task_id)
    snap = crew.wait_for_snapshot(timeout=5.0)
    me = next(p for p in snap.players if p.player_id == crew.player_id)
    # garante que o jogador está fora do raio antes de tentar
    if math.hypot(point.x - me.x, point.y - me.y) <= point.interaction_radius:
        return  # spawn anômalo; nada a negar
    crew.complete_task(assigned[0].task_id)
    denied = crew.wait_for(ActionDenied, timeout=5.0)
    assert denied.action is ActionKind.TASK
    assert denied.code is DenialCode.OUT_OF_RANGE


@pytest.mark.timeout(40)
def test_task_already_done_denied_with_code(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    import time as _time

    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    _start_game(four_clients)
    crew = next(c for c in four_clients if c.role is Role.CREW)
    assigned = [t for t in crew.tasks.tasks if not t.done] if crew.tasks else []
    assert assigned
    game_map = load_map(default_map_path())
    point = next(tp for tp in game_map.task_points if tp.task_id == assigned[0].task_id)
    assert _move_to_point(crew, point.x, point.y, timeout=20.0)
    crew.complete_task(assigned[0].task_id)
    # aguarda a confirmação (TaskState com done) antes de tentar de novo
    done = False
    start = _time.monotonic()
    while _time.monotonic() - start < 5.0:
        ts = crew.tasks
        if ts and any(t.task_id == assigned[0].task_id and t.done for t in ts.tasks):
            done = True
            break
        _time.sleep(0.02)
    assert done, "TaskState não refletiu a conclusão"
    crew.complete_task(assigned[0].task_id)
    denied = crew.wait_for(ActionDenied, timeout=5.0)
    assert denied.action is ActionKind.TASK
    assert denied.code is DenialCode.ALREADY_DONE


@pytest.mark.timeout(40)
def test_tie_meeting_ends_without_ejection_and_game_continues(
    server: GameServer, four_clients: list[SimulatedClient]
) -> None:
    _start_game(four_clients)
    impostor, _killed, meeting_id = _impostor_kills_and_reports(server, four_clients)
    voters = _all_alive_voters(impostor)
    others = [pid for pid in voters if pid != impostor.player_id]
    assert len(others) == 2
    a, b = others
    impostor.vote(meeting_id, a)
    next(c for c in four_clients if c.player_id == a).vote(meeting_id, b)
    next(c for c in four_clients if c.player_id == b).vote(meeting_id, None)

    for client in four_clients:
        m = client.wait_for(MeetingEnded, timeout=5.0)
        # contrato v2: exatamente {type, meeting_id}, sem resultado
        import json

        from codecon_amoung_us.framing import encode_frame

        serialized = json.loads(encode_frame(m).rstrip(b"\n"))
        assert set(serialized.keys()) == {"type", "meeting_id"}
        assert client.peek(Ejected) is None
    # sem game over: a partida continua (snapshots fluem de novo)
    snap = four_clients[0].wait_for_snapshot(timeout=5.0)
    assert server._state.phase is Phase.PLAYING
    assert all(any(p.player_id == pid for p in snap.players) for pid in range(4))
