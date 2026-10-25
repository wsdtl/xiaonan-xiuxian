"""存档结构审查：列、条目、以及当前领域能否真正读出来。

前半段查键名/结构；后半段用当前服务逐域读，补上旧字段、失效引用、孤儿关系。

**退出码：0 = 所有人物和当前领域都读得出来；1 = 结构或语义不合规。**
"""

from __future__ import annotations

import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.core.database.storage import _ENTRY_UPDATED, _ENTRY_VALUE, _ENTRY_VERSION  # noqa: E402
from game.core.database.storage import _load_logical_state  # noqa: E402
from 存档语义 import audit_saves  # noqa: E402

EXPECTED_COLUMNS = frozenset({"user_id", "state_json", "version", "updated_at"})


def database_path() -> pathlib.Path:
    from game.config import game_config

    return pathlib.Path(game_config.database.path)


def inspect(path: pathlib.Path) -> tuple[list[tuple[str, int, int]], list[str]]:
    """返回（每个人物的（user_id, 条目数, 不合规条目数）, 结构问题）。"""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(player_state)")}
        problems = []
        if columns != EXPECTED_COLUMNS:
            problems.append(f"player_state 列不是当前结构：{sorted(columns)}")
        owners = [row[0] for row in connection.execute("SELECT user_id FROM player_state ORDER BY user_id")]
        report = []
        for owner in owners:
            entries = _load_logical_state(connection, str(owner))
            bad = 0
            for entry in entries.values():
                if not isinstance(entry, dict):
                    bad += 1
                    continue
                if set(entry) != {_ENTRY_VALUE, _ENTRY_VERSION, _ENTRY_UPDATED}:
                    bad += 1
            report.append((str(owner), len(entries), bad))
        return report, problems
    finally:
        connection.close()


def main() -> int:
    path = database_path()
    if not path.is_file():
        print(f"存档结构审查跳过：没有找到 {path}")
        return 0

    try:
        report, problems = inspect(path)
    except Exception as error:
        print(f"存档结构审查失败：读路径抛错 {type(error).__name__}: {error}")
        return 1

    if problems:
        for item in problems:
            print(f"  {item}")
        return 1

    bad_total = sum(item[2] for item in report)
    for user_id, entries, bad in report:
        mark = "不合规" if bad else "合规"
        print(f"  {mark}  {user_id}  条目 {entries}  不合规 {bad}")
    if bad_total:
        print(f"存档结构漂移：{len(report)} 个人物里有 {bad_total} 条状态不成形")
        return 1
    print(
        f"存档结构审查通过：{len(report)} 个人物、"
        f"{sum(item[1] for item in report)} 条状态都是当前结构"
    )

    try:
        checks, semantic = audit_saves(path)
    except Exception as error:  # noqa: BLE001 - 审计失败要带原异常
        print(f"存档语义审查失败：{type(error).__name__}: {error}")
        return 1
    if semantic:
        for item in semantic:
            print(f"  {item}")
        print(f"存档语义审查失败：{len(semantic)} 处当前服务读不出来")
        return 1
    print(f"存档语义审查通过：{checks} 项领域读取全部成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
