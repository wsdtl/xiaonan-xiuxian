"""测试进程级隔离。

测试会通过 build_game_services() 装配真实服务链，而它的数据库路径来自 game.config。
不隔离的话：① 并行分片会同时写仓库里的 database/game.db，互相踩；
② 测试状态会落在真实存档上。所以每个 pytest 进程各用一份临时数据库。
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import game.app as app


@pytest.fixture(scope="session", autouse=True)
def _isolated_database(tmp_path_factory):
    """整个会话把游戏数据库指到本进程专属的临时目录。

    用 `tmp_path_factory` 而不是 `mkdtemp`：本环境的 TEMP/TMP 没设，`mkdtemp`
    会回落到当前工作目录，把临时库落在仓库根；pytest 自己会在会话结束时收掉。
    """

    root = tmp_path_factory.mktemp("game-db")
    app.game_config = replace(
        app.game_config,
        database=replace(app.game_config.database, path=root / "game.db"),
    )
    yield
