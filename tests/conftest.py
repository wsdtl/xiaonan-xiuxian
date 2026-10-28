"""测试进程级隔离。

测试会通过 build_game_services() 装配真实服务链，而它的数据库路径来自 game.config。
不隔离的话：① 并行分片会同时写仓库里的 database/game.db，互相踩；
② 测试状态会落在真实存档上。所以每个 pytest 进程各用一份临时数据库。
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

import game.core.database.battle_report_store as battle_log
from game import app
from launch.config import config as framework_config
from launch.log import FILE_FORMAT, local_logger_id, logger


def _redirect_file_logs() -> None:
    """把 pytest 的文件日志挪到 _输出，别污染线上 runserver.log。"""

    root = Path(__file__).resolve().parents[1] / "_输出" / "测试日志"
    root.mkdir(parents=True, exist_ok=True)
    try:
        logger.remove(local_logger_id)
    except ValueError:
        pass
    logger.add(
        root / f"runserver-{os.getpid()}.log",
        level=framework_config.log.level,
        format=FILE_FORMAT,
        encoding="utf-8",
        colorize=False,
        backtrace=True,
        diagnose=False,
        enqueue=True,
    )


_redirect_file_logs()


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
    # 运行期观察库（消息流水与战报）走游戏配置；战报仓储在核心数据库模块里
    # 按需导入路径函数，所以在这里替换函数即可隔离。
    original = battle_log.runtime_log_database_path
    battle_log.runtime_log_database_path = lambda: root / "runtime_log.db"
    yield
    battle_log.runtime_log_database_path = original

@pytest.fixture
def services():
    """装配一次真实服务链；用完关掉数据库。"""

    value = app.build_game_services()
    try:
        yield value
    finally:
        value.core.database.close()
