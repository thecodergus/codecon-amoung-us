"""Configuração central do jogo.

Valores de gameplay e limites de protocolo vivem aqui (e no mapa),
não espalhados pelo código. ``GameConfig`` é imutável e não depende de
pygame, msgspec ou do parser Tiled.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Limites do protocolo (espelhados como constraints no msgspec — protocol.py).
# v3: StartGame carrega ``map_seed`` (mapas procedurais por partida).
PROTOCOL_VERSION: int = 3
NICKNAME_MIN_LENGTH: int = 1
NICKNAME_MAX_LENGTH: int = 12
MAX_PLAYERS: int = 10
MAX_FRAME_BYTES: int = 64 * 1024

# Descoberta de partidas na LAN via UDP broadcast (ver net/discovery.py).
DISCOVERY_PORT: int = 5557
DISCOVERY_MAGIC: str = "codecon-amoung-us/1"
DISCOVERY_BEACON_INTERVAL_SECONDS: float = 1.0
DISCOVERY_LISTEN_SECONDS: float = 2.5
MAX_DISCOVERY_BYTES: int = 512
# Sweep unicast (fallback do broadcast): probe request/response e pacing.
DISCOVERY_PROBE_MAGIC: str = "codecon-amoung-us/1-probe"
DISCOVERY_SWEEP_PPS: int = 20

# Transporte HTTP long polling (net/http_poll.py): espera do long poll no
# servidor e expiração de sessão por inatividade.
HTTP_POLL_HOLD_SECONDS: float = 25.0
HTTP_POLL_SESSION_TIMEOUT_SECONDS: float = 60.0

# Raios de interação (px) — fonte única para servidor e UI.
KILL_RADIUS: float = 40.0
REPORT_RADIUS: float = 50.0

# Nome do mapa padrão, relativo ao diretório de assets.
DEFAULT_MAP_RELPATH = "maps/lab.json"
# Subdiretório dos modelos de personagem (sprites duckee), relativo a models/.
DUCKEE_DIRNAME = "duckee"


def default_assets_dir() -> Path:
    """Resolve o diretório de assets do repositório.

    Suporta override por env var e instalação editável (caminho do módulo
    aponta para o fonte, permitindo subir até a raiz do projeto).
    """
    env_dir = os.environ.get("CODECON_AMONG_US_ASSETS_DIR")
    if env_dir:
        candidate_env = Path(env_dir)
        if candidate_env.is_dir():
            return candidate_env
        raise FileNotFoundError(
            f"CODECON_AMONG_US_ASSETS_DIR aponta para diretório inexistente: {env_dir}"
        )
    module_dir = Path(__file__).resolve().parent
    # src/codecon_amoung_us -> src -> raiz do repo
    repo_root = module_dir.parent.parent
    candidate = repo_root / "assets"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        "Diretório de assets não encontrado. Defina CODECON_AMONG_US_ASSETS_DIR "
        f"ou execute a partir da raiz do projeto (procurou em {candidate})."
    )


def default_models_dir() -> Path:
    """Resolve o diretório de models (sprites de personagem) do repositório."""
    env_dir = os.environ.get("CODECON_AMONG_US_MODELS_DIR")
    if env_dir:
        candidate_env = Path(env_dir)
        if candidate_env.is_dir():
            return candidate_env
        raise FileNotFoundError(
            f"CODECON_AMONG_US_MODELS_DIR aponta para diretório inexistente: {env_dir}"
        )
    module_dir = Path(__file__).resolve().parent
    repo_root = module_dir.parent.parent
    candidate = repo_root / "models"
    if candidate.is_dir():
        return candidate
    raise FileNotFoundError(
        "Diretório de models não encontrado. Defina CODECON_AMONG_US_MODELS_DIR "
        f"ou execute a partir da raiz do projeto (procurou em {candidate})."
    )


def default_map_path() -> Path:
    """Caminho do mapa padrão do projeto."""
    return default_assets_dir() / DEFAULT_MAP_RELPATH


@dataclass(frozen=True)
class GameConfig:
    """Parâmetros de gameplay e de rede do servidor."""

    tick_rate: int = 20
    player_speed: float = 180.0
    kill_radius: float = KILL_RADIUS
    # Raio para reportar corpo (>= kill_radius para o assassino poder reportar).
    report_radius: float = REPORT_RADIUS
    # Passo máximo por subpasso de movimento (menor que a espessura das paredes,
    # 16 px no skeld) — evita tunelamento quando dt é anômalo.
    max_movement_step: float = 8.0
    kill_cooldown_seconds: float = 15.0
    meeting_vote_timeout_seconds: float = 30.0
    max_players: int = MAX_PLAYERS
    # Mínimo para iniciar: 1 (partida solo — host como tripulante, vence por
    # tarefas). Servidores que exigirem mínimo maior sobrescrevem na CLI/API.
    min_players_to_start: int = 1
    impostor_count: int = 1
    map_path: Path | None = None
    # Seed fixa do gerador procedural de mapas (testes/demo reproduzível);
    # None = seed aleatória sorteada a cada partida. Ignorada quando
    # ``map_path`` aponta para um asset Tiled customizado.
    map_seed: int | None = None
    # Timeout do recv loop das threads de conexão (evita bloqueio infinito).
    socket_timeout_seconds: float = 0.2
    # Tempo máximo de shutdown por thread (rede de segurança).
    shutdown_join_timeout_seconds: float = 3.0
    # Anuncia a partida na LAN via UDP broadcast enquanto estiver em lobby
    # (descoberta automática — ver net/discovery.py).
    announce: bool = True
    # Porta do listener WebSocket (transporte alternativo para atravessar
    # firewalls corporativos); None desliga o listener (ver net/ws.py).
    ws_port: int | None = None
    # Porta do listener HTTP long polling (transporte de último degrau para
    # proxies com inspeção — ver net/http_poll.py); None desliga o listener.
    http_port: int | None = None

    def resolve_map_path(self) -> Path:
        """Retorna o mapa configurado ou o padrão do projeto."""
        return self.map_path if self.map_path is not None else default_map_path()
