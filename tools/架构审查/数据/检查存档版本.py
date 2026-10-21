"""存档版本审查：任何用户「被读到的那一刻」，拿到的状态必须是当前版语义。

读路径 `game/core/database/storage.py::_load_logical_state` 会在读到落后行时就地补齐
（**只在内存**，不写库）；真落盘由下一次写事务的 `_store_logical_state` 完成。
所以本判据的做法是**真走一次读路径**，再断言读到的每个条目都合规：

- 结构：`player_state` 必须有 `schema_version` 列（缺了说明结构没对齐）；
- 语义：每个状态键下必须齐备 **值 / 版本 / 时间** 三件。

本工具**默认只读**（不含任何写库路径），可直接对着 `database/game.db` 跑：

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查存档版本.py

**退出码：0 = 所有人物读出来都合规；1 = 有不合规，或读路径本身抛错。**
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


def database_path() -> pathlib.Path:
    from game.config import game_config

    return pathlib.Path(game_config.database.path)


def inspect(path: pathlib.Path) -> tuple[list[tuple[str, int, int]], bool]:
    """返回（每个人物的（user_id, 条目数, 不合规条目数）, 结构是否缺列）。"""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(player_state)")}
        if "schema_version" not in columns:
            return [], True
        owners = [row[0] for row in connection.execute("SELECT user_id FROM player_state ORDER BY user_id")]
        report = []
        for owner in owners:
            entries = _load_logical_state(connection, str(owner))   # ★ 真走读路径（含内存补齐）
            bad = 0
            for key, entry in entries.items():
                if not isinstance(entry, dict):
                    bad += 1
                    continue
                if not all(name in entry for name in (_ENTRY_VALUE, _ENTRY_VERSION, _ENTRY_UPDATED)):
                    bad += 1
            report.append((str(owner), len(entries), bad))
        return report, False
    finally:
        connection.close()


def main() -> int:
    path = database_path()
    if not path.is_file():
        print(f"存档版本审查跳过：没有找到 {path}")
        return 0

    try:
        report, missing = inspect(path)
    except Exception as error:  # 读路径本身抛错也是红——这正是要拦的
        print(f"存档版本审查失败：读路径抛错 {type(error).__name__}: {error}")
        return 1

    if missing:
        print("存档结构没对齐：player_state 缺 schema_version 列（跑一次启动即可补上）")
        return 1

    bad_total = sum(item[2] for item in report)
    for user_id, entries, bad in report:
        mark = "不合规" if bad else "合规"
        print(f"  {mark}  {user_id}  条目 {entries}  不合规 {bad}")
    if bad_total:
        print(f"存档版本漂移：{len(report)} 个人物里有 {bad_total} 条状态读出来不成形")
        return 1
    print(
        f"存档版本审查通过：{len(report)} 个人物、"
        f"{sum(item[1] for item in report)} 条状态读出来都是当前版语义"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())