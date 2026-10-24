"""存档键名审查：玩家状态只认当前键名。

玩家状态是一人一行的 JSON，每个状态键下只许有「值 / 版本 / 时间」三项：

    { "角色/main": { "value": ..., "version": 3, "updated_at": "..." } }

这里逐个人物核对键名，发现非法键名或混用即报错。
本工具只读。

**退出码：0 = 全是当前键名；1 = 发现非法键名或混用。**
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

NEW_KEYS = frozenset({"value", "version", "updated_at"})


def database_path() -> pathlib.Path:
    from game.config import game_config

    return pathlib.Path(game_config.database.path)


def inspect(path: pathlib.Path) -> tuple[list[tuple[str, int, int]], bool]:
    """返回（每个人物的（user_id, 条目数, 非法条目数）, 是否混用键名）。"""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        rows = connection.execute(
            "SELECT user_id, state_json FROM player_state ORDER BY user_id"
        ).fetchall()
    finally:
        connection.close()
    report: list[tuple[str, int, int]] = []
    mixed = False
    for user_id, blob in rows:
        data = json.loads(blob)
        bad = 0
        for entry in data.values():
            if not isinstance(entry, dict):
                bad += 1
                continue
            keys = set(entry)
            if keys != NEW_KEYS:
                bad += 1
                if keys & NEW_KEYS:
                    mixed = True
        report.append((str(user_id), len(data), bad))
    return report, mixed


def main() -> int:
    path = database_path()
    if not path.is_file():
        print(f"存档键名审查跳过：没有找到 {path}")
        return 0

    report, mixed = inspect(path)
    bad_total = sum(item[2] for item in report)
    for user_id, entries, bad in report:
        mark = "不合规" if bad else "当前键名"
        print(f"  {mark}  {user_id}  条目 {entries}  不合规 {bad}")
    if mixed:
        print("发现当前键名与非法键名混用：直接修数据。")
        return 1
    if bad_total:
        print(f"存档键名不合规：{len(report)} 个人物里有 {bad_total} 条状态不是当前键名")
        return 1
    print(f"存档键名审查通过：{len(report)} 个人物、{sum(item[1] for item in report)} 条状态都是当前键名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
