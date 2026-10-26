"""辅助路由的本地配置；数据库和 NapCat 连接从环境读取。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from launch.config import config

#: 固定匹配参数；唯一候选自动建立路由。
MATCH_WINDOW_SECONDS = 3.0
CONFIRM_SCORE = 80
AUTO_CONFIRM_USER = True
AUTO_CONFIRM_GROUP = True
EVENT_RETENTION_SECONDS = 600
MAX_EVENTS = 20000


def _setting(name: str) -> str:
    return config.get(name, "") or os.getenv(name, "")


@dataclass(frozen=True)
class AssistRouterSettings:
    db_path: Path = Path(
        _setting("ASSIST_ROUTER_DB") or "database/assist_router.db"
    )
    napcat_url: str = _setting("ASSIST_ROUTER_NAPCAT_URL")
    napcat_token: str = _setting("ASSIST_ROUTER_NAPCAT_TOKEN")
