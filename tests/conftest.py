"""测试进程级隔离。

测试会通过 build_game_services() 装配真实服务链，而它的数据库路径来自 game.config。
不隔离的话：① 并行分片会同时写仓库里的 database/game.db，互相踩；
② 测试状态会落在真实存档上。所以每个 pytest 进程各用一份临时数据库。
"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

import game.app as app


@pytest.fixture(scope="session", autouse=True)
def _isolated_database():
    """整个会话把游戏数据库指到本进程专属的临时目录。"""

    root = Path(tempfile.mkdtemp(prefix="xiaonan-test-db-"))
    app.game_config = replace(
        app.game_config,
        database=replace(app.game_config.database, path=root / "game.db"),
    )
    yield
