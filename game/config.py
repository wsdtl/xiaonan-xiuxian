"""从框架自定义项中解释游戏自身配置。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from launch import config as framework_config


class CustomConfigSource(Protocol):
    """游戏配置只依赖框架公开的自定义项读取能力。"""

    base_dir: Path

    def get(self, name: str, default: str = "") -> str: ...


@dataclass(frozen=True)
class GameDatabaseConfig:
    """游戏**资产库**配置（玩家事实：纳戒、道藏、资粮、阵藏…）。"""

    path: Path
    busy_timeout_ms: int


@dataclass(frozen=True)
class GameRuntimeLogConfig:
    """游戏**非资产库**配置（观测数据：事务流水、消息流水、战报），与资产库对称。

    非资产库同样属于游戏，所以路径进游戏配置面；维护者入口（`game/cmd/后台入口`）按它自己的
    规范从框架自定义项读取同名键、同默认值，**不读**游戏配置——那是一处已注明的例外。
    """

    path: Path
    busy_timeout_ms: int


@dataclass(frozen=True)
class GameConsoleConfig:
    """天道后台（一个二级组件）自己的配置：密码、非资产库路径、媒体目录。

    后台是普通二级组件，配置**同样走这一处游戏配置面**；密码不再散在 env 里各自解释。
    """

    password: str
    runtime_log_path: Path
    runtime_log_busy_timeout_ms: int
    media_dir: Path


@dataclass(frozen=True)
class GameConfig:
    database: GameDatabaseConfig
    runtime_log: GameRuntimeLogConfig
    console: GameConsoleConfig


def load_game_config(source: CustomConfigSource = framework_config) -> GameConfig:
    """读取并校验游戏自定义配置，不向框架注册业务字段。"""

    database = GameDatabaseConfig(
        path=_custom_path(source, "DATABASE_PATH", "database/game.db"),
        busy_timeout_ms=_positive_int(source, "DATABASE_BUSY_TIMEOUT_MS", 5000),
    )
    runtime_log = GameRuntimeLogConfig(
        path=_custom_path(source, "RUNTIME_LOG_DATABASE_PATH", "database/runtime_log.db"),
        busy_timeout_ms=_positive_int(source, "RUNTIME_LOG_BUSY_TIMEOUT_MS", 5000),
    )
    console = GameConsoleConfig(
        password=(source.get("WEB_CONSOLE_PASSWORD", "") or "").strip(),
        # 与游戏侧同源，不再各写默认值。
        runtime_log_path=runtime_log.path,
        runtime_log_busy_timeout_ms=runtime_log.busy_timeout_ms,
        media_dir=_custom_path(source, "RUNTIME_LOG_MEDIA_DIR", ".runtime/runtime_log_media"),
    )
    return GameConfig(database=database, runtime_log=runtime_log, console=console)


def _custom_path(source: CustomConfigSource, name: str, default: str) -> Path:
    raw = (source.get(name, default) or default).strip()
    path = Path(raw).expanduser()
    return path if path.is_absolute() else source.base_dir / path


def _positive_int(source: CustomConfigSource, name: str, default: int) -> int:
    raw = (source.get(name, str(default)) or str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc
    if value < 1:
        raise ValueError(f"{name} 必须大于 0")
    return value


game_config = load_game_config()


__all__ = [
    "GameConfig",
    "GameConsoleConfig",
    "GameDatabaseConfig",
    "GameRuntimeLogConfig",
    "game_config",
    "load_game_config",
]
