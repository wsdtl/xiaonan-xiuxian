"""游戏运行前必须成立的跨服务契约。"""

from .contracts import (
    StartupContractError,
    validate_command_uniqueness,
    validate_startup_contracts,
)

__all__ = [
    "StartupContractError",
    "validate_command_uniqueness",
    "validate_startup_contracts",
]
