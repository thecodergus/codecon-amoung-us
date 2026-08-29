"""Smoke multiplayer (Etapa 14): servidor standalone + 4 clientes simulados.

Roteiro executado contra o servidor CLI real (subprocesso no mesmo venv):

  1. sobe o servidor standalone em porta efêmera;
  2. 4 clientes conectam no lobby (JoinAccepted + PlayerJoined);
  3. o host inicia a partida (StartGame + RoleAssigned, exatamente 1 impostor);
  4. o impostor se aproxima de um tripulante e mata (corpo no snapshot);
  5. o impostor reporta o corpo -> MeetingStarted (kill_reported);
  6. votação: impostor pula, os 2 tripulantes vivos votam no impostor
     (o voto do morto é ignorado por inelegibilidade) -> ejetado;
  7. verificação: Ejected (com papel) só ao ejetado; MeetingEnded para todos
     com exatamente {type, meeting_id} (sem booleano de ejeção — v2);
     GameOver com papéis revelados (tripulantes vencem).

Uso:
    uv run python scripts/smoke_multiplayer.py

Exit code 0 = sucesso; 1 = falha de verificação ou de infraestrutura
(a saída do servidor é impressa no stderr em caso de falha).
"""

from __future__ import annotations

import math
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from codecon_amoung_us.framing import encode_frame
from codecon_amoung_us.game.model import Role, Team
from codecon_amoung_us.net.client import SimulatedClient
from codecon_amoung_us.protocol import (
    Ejected,
    GameOver,
    MeetingEnded,
    MeetingStarted,
    RoleAssigned,
    StartGame,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_MODULE = "codecon_amoung_us.net.server"
HOST = "127.0.0.1"


def _assert_meeting_ended_v2(message: MeetingEnded) -> None:
    """Contrato v2: MeetingEnded serializa exatamente {type, meeting_id}."""
    import json

    payload = json.loads(encode_frame(message).rstrip(b"\n"))
    if set(payload.keys()) != {"type", "meeting_id"}:
        raise RuntimeError(f"MeetingEnded com campos inesperados: {sorted(payload.keys())}")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"servidor não aceitou conexão em {timeout}s")


def _start_game(clients: list[SimulatedClient]) -> None:
    clients[0].start_game()
    for client in clients:
        client.wait_for(StartGame, timeout=10.0)
        client.wait_for(RoleAssigned, timeout=10.0)


def _move_to_point(client: SimulatedClient, tx: float, ty: float, timeout: float = 25.0) -> bool:
    """Move o cliente até um ponto navegando pelo caminho BFS do mapa (lab).

    Deriva os waypoints do asset carregado (independe do layout); a última
    perna vai direto ao destino.
    """
    from codecon_amoung_us.config import default_map_path
    from codecon_amoung_us.map.loader import load_map

    game_map = load_map(default_map_path())

    def walkable_grid() -> list[list[bool]]:
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

    def plan_path(
        start: tuple[float, float], goal: tuple[float, float]
    ) -> list[tuple[float, float]]:
        from collections import deque

        grid = walkable_grid()
        tw, th = game_map.tile_width, game_map.tile_height
        sc = (int(start[0] // tw), int(start[1] // th))
        gc = (int(goal[0] // tw), int(goal[1] // th))
        if (
            not (0 <= sc[0] < game_map.width and 0 <= sc[1] < game_map.height)
            or not grid[sc[1]][sc[0]]
        ):
            return [goal]
        prev: dict[tuple[int, int], tuple[int, int] | None] = {sc: None}
        queue: deque[tuple[int, int]] = deque([sc])
        while queue:
            cur = queue.popleft()
            if cur == gc:
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
        if gc not in prev:
            return [goal]
        cells: list[tuple[int, int]] = []
        node: tuple[int, int] | None = gc
        while node is not None:
            cells.append(node)
            node = prev[node]
        cells.reverse()
        pruned: list[tuple[int, int]] = [cells[0]]
        for cell in cells[1:]:
            if len(pruned) >= 2 and (
                pruned[-1][0] == pruned[-2][0] == cell[0]
                or pruned[-1][1] == pruned[-2][1] == cell[1]
            ):
                pruned[-1] = cell
            else:
                pruned.append(cell)
        return [(cx * tw + tw / 2, cy * th + th / 2) for cx, cy in pruned]

    waypoints: list[tuple[float, float]] = []
    wp_index = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.snapshot
        if snap is None:
            time.sleep(0.02)
            continue
        me = next((p for p in snap.players if p.player_id == client.player_id), None)
        if me is None:
            time.sleep(0.02)
            continue
        if not waypoints:
            waypoints = plan_path((me.x, me.y), (tx, ty))
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
        time.sleep(0.02)
    return False


def _move_next_to(
    impostor: SimulatedClient, target_id: int, kill_radius: float, timeout: float = 25.0
) -> bool:
    """Move o impostor até o raio de kill do alvo (alvo parado)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = impostor.snapshot
        if snap is None:
            time.sleep(0.02)
            continue
        me = next((p for p in snap.players if p.player_id == impostor.player_id), None)
        tgt = next((p for p in snap.players if p.player_id == target_id), None)
        if me is None or tgt is None:
            time.sleep(0.02)
            continue
        if math.hypot(tgt.x - me.x, tgt.y - me.y) <= kill_radius:
            return True
        # navega até o alvo; o loop externo revalida o raio de kill (o alvo
        # está parado, então chegar perto dele garante estar dentro do raio)
        _move_to_point(impostor, tgt.x, tgt.y, timeout=timeout)
    return False


def _wait_for_body(client: SimulatedClient, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.snapshot
        if snap is not None and snap.bodies:
            return snap.bodies[0].body_id
        time.sleep(0.02)
    raise RuntimeError("corpo não apareceu no snapshot")


def _impostor_kills_and_reports(clients: list[SimulatedClient], kill_radius: float) -> int:
    """Mata um tripulante e reporta; retorna o meeting_id."""
    impostor = next(c for c in clients if c.role is Role.IMPOSTOR)
    snap = impostor.wait_for_snapshot(timeout=10.0)
    target = next(p for p in snap.players if p.player_id != impostor.player_id and p.alive)
    if not _move_next_to(impostor, target.player_id, kill_radius):
        raise RuntimeError("impostor não alcançou o alvo para o kill")
    impostor.kill(target.player_id)
    body_id = _wait_for_body(impostor)
    impostor.report(body_id)
    meeting = impostor.wait_for(MeetingStarted, timeout=10.0)
    if meeting.reason.value != "kill_reported":
        raise RuntimeError(f"razão de reunião inesperada: {meeting.reason.value}")
    return meeting.meeting_id


def _run() -> int:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", SERVER_MODULE, "--host", HOST, "--port", str(port)],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    server_lines: list[str] = []

    def _read_server_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            server_lines.append(line.rstrip())

    threading.Thread(target=_read_server_output, daemon=True).start()
    try:
        print(f"[1/6] servidor standalone em {HOST}:{port} (pid {proc.pid})")
        _wait_for_server(port)

        clients = [SimulatedClient() for _ in range(4)]
        try:
            print("[2/6] conectando 4 clientes no lobby")
            for i, client in enumerate(clients):
                client.connect(HOST, port, f"smoke{i}", timeout=10.0)
                if client.player_id is None:
                    raise RuntimeError(f"cliente {i} não recebeu JoinAccepted")

            print("[3/6] host inicia a partida")
            _start_game(clients)
            roles = [c.role for c in clients]
            if roles.count(Role.IMPOSTOR) != 1 or roles.count(Role.CREW) != 3:
                raise RuntimeError(f"distribuição de papéis inesperada: {roles}")

            impostor = next(c for c in clients if c.role is Role.IMPOSTOR)
            snap = impostor.wait_for_snapshot(timeout=10.0)
            if len(snap.players) != 4:
                raise RuntimeError(f"snapshot com {len(snap.players)} jogadores, esperado 4")

            print("[4/6] impostor mata um tripulante e reporta")
            meeting_id = _impostor_kills_and_reports(clients, 40.0)

            print("[5/6] votação: tripulantes ejetam o impostor")
            imp_id = impostor.player_id
            assert imp_id is not None
            impostor.vote(meeting_id, None)
            for client in clients:
                if client.player_id != imp_id:
                    client.vote(meeting_id, imp_id)

            print("[6/6] verificando ejeção secreta + game over")
            # ejetado: Ejected (identidade+papel) -> MeetingEnded -> GameOver
            ejected = impostor.wait_for(Ejected, timeout=10.0)
            if ejected.role is not Role.IMPOSTOR or ejected.player_id != imp_id:
                raise RuntimeError(f"Ejected inesperado: {ejected}")
            ended = impostor.wait_for(MeetingEnded, timeout=10.0)
            _assert_meeting_ended_v2(ended)
            over = impostor.wait_for(GameOver, timeout=10.0)
            if over.winner is not Team.CREW:
                raise RuntimeError(f"vencedor inesperado: {over.winner}")
            if over.roles.get(imp_id) is not Role.IMPOSTOR:
                raise RuntimeError("papel do impostor não revelado no GameOver")
            # demais: MeetingEnded (nunca Ejected) + GameOver
            for client in clients:
                if client is impostor:
                    continue
                ended = client.wait_for(MeetingEnded, timeout=10.0)
                _assert_meeting_ended_v2(ended)
                if client.peek(Ejected) is not None:
                    raise RuntimeError("jogador não-ejetado recebeu Ejected")
                over = client.wait_for(GameOver, timeout=10.0)
                if over.winner is not Team.CREW:
                    raise RuntimeError(f"vencedor inesperado: {over.winner}")
                if over.roles.get(imp_id) is not Role.IMPOSTOR:
                    raise RuntimeError("papel do impostor não revelado no GameOver")
        finally:
            for client in clients:
                client.close()
        print("SMOKE MULTIPLAYER OK: 4 clientes, kill, reunião, ejeção secreta e game over.")
        return 0
    except (RuntimeError, TimeoutError, AssertionError) as exc:
        print(f"SMOKE MULTIPLAYER FALHOU: {exc}", file=sys.stderr)
        if server_lines:
            print("--- saída do servidor ---", file=sys.stderr)
            for line in server_lines:
                print(line, file=sys.stderr)
        return 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main() -> None:
    sys.exit(_run())


if __name__ == "__main__":
    main()
