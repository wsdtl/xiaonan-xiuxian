"""存档键名审查：玩家状态里记的是新版键名还是旧版中文键名。

玩家状态是一人一行的 JSON，每个状态键下记着「值 / 版本 / 时间」三项：

    { "角色/main": { "value": ..., "version": 3, "updated_at": "..." } }

而更早的版本用的是中文键名 **值 / 版本 / 时间**。代码只认新键名，并且
`game/core/database/说明.md` 明确写着「**不保留兼容读取**」——所以一旦库里还是旧键名，
不会报「存档太旧」，而是每条命令都在读存档时抛异常：

- 直接命令会在组件里炸出原文（例如 `KeyError: 'value'`）；
- 带状态守卫的命令更彻底：守卫读不到状态就**失败即拒绝**，一律回一句
  「不可执行 · 状态检查失败，请稍后重试」（见 `game/cmd/access_guard.py`），
  连「帮助」这种「始终可用」的命令也过不去——守卫先读存档，再看规则。

本工具默认只读，逐个人物报出旧键名条目数；加 `--迁移` 就地把键名换成新的
（只改这三个键，不动任何业务数据）：

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查存档键名.py
    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查存档键名.py --迁移

**退出码：0 = 全是新键名，1 = 发现旧键名（或迁移后仍有残留）。**
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 旧键名 -> 新键名。只动这三项。
RENAMES = {"值": "value", "版本": "version", "时间": "updated_at"}
NEW_KEYS = tuple(RENAMES.values())


def database_path() -> pathlib.Path:
    from game.config import game_config

    return pathlib.Path(game_config.database.path)


def inspect(path: pathlib.Path) -> tuple[list[tuple[str, int, int]], bool]:
    """返回（每个人物的（user_id, 条目数, 旧键名条目数）, 有没有新旧混用）。"""

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
        legacy = 0
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            old = any(key in entry for key in RENAMES)
            new = any(key in entry for key in NEW_KEYS)
            if old:
                legacy += 1
            if old and new:
                mixed = True
        report.append((str(user_id), len(data), legacy))
    return report, mixed


def migrate(path: pathlib.Path) -> int:
    connection = sqlite3.connect(str(path), timeout=25)
    try:
        rows = connection.execute("SELECT user_id, state_json FROM player_state").fetchall()
        changed = 0
        for user_id, blob in rows:
            data = json.loads(blob)
            for key, entry in list(data.items()):
                if not isinstance(entry, dict):
                    raise SystemExit(f"意外形态：{user_id} 的 {key} 不是对象")
                for old, new in RENAMES.items():
                    if old not in entry:
                        continue
                    if new in entry:
                        raise SystemExit(f"新旧键同时存在：{user_id} 的 {key}")
                    entry[new] = entry.pop(old)
                    changed += 1
            connection.execute(
                "UPDATE player_state SET state_json = ? WHERE user_id = ?",
                (json.dumps(data, ensure_ascii=False, sort_keys=True), user_id),
            )
        connection.commit()
    finally:
        connection.close()
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--迁移", action="store_true", help="把旧键名就地换成新键名")
    args = parser.parse_args()

    path = database_path()
    if not path.is_file():
        print(f"存档键名审查跳过：没有找到 {path}")
        return 0

    if args.迁移:
        changed = migrate(path)
        print(f"已替换键名 {changed} 处（值→value、版本→version、时间→updated_at）")

    report, mixed = inspect(path)
    legacy_total = sum(item[2] for item in report)
    for user_id, entries, legacy in report:
        mark = "旧键名" if legacy else "新键名"
        print(f"  {mark}  {user_id}  条目 {entries}  待迁移 {legacy}")
    if mixed:
        print("发现新旧键混在同一份存档里：这不该出现，先人工看清楚再迁移")
        return 1
    if legacy_total:
        print(f"存档键名漂移：{len(report)} 个人物里有 {legacy_total} 条状态还是旧版中文键名")
        print("跑一次 tools/架构审查/检查存档键名.py --迁移 即可修好（只改这三个键）")
        return 1
    print(f"存档键名审查通过：{len(report)} 个人物、{sum(item[1] for item in report)} 条状态都是新键名")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
