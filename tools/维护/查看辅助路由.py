"""只读查看辅助路由数据；不写 database/assist_router.db。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database" / "assist_router.db"


def _time(value: object) -> str:
    try:
        return datetime.fromtimestamp(float(value)).strftime("%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "-"


def main() -> int:
    if not DB.is_file():
        print(f"辅助路由库还不存在：{DB}")
        print("先重启主服务，让 assist_router 初始化。")
        return 0

    connection = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=20)
    connection.row_factory = sqlite3.Row
    try:
        print("== 辅助路由状态 ==")
        for table in (
            "events",
            "users",
            "user_aliases",
            "groups",
            "group_aliases",
        ):
            count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table}: {count}")

        print()
        print("== 最近事件 ==")
        for row in connection.execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT 30"
        ):
            print(
                f"{row['id']:>4} {row['source']:<6} {row['scene']:<7} "
                f"{row['sender_name'] or '-':<12} {row['sender_id']:<24} "
                f"{_time(row['occurred_at'])}  {row['text'][:80]}"
            )

        print()
        print("== 用户别名 ==")
        user_rows = connection.execute(
            "SELECT * FROM user_aliases ORDER BY last_seen DESC LIMIT 50"
        ).fetchall()
        if not user_rows:
            print("（暂无）")
        for row in user_rows:
            print(
                f"- bot={row['official_bot_key']} openid={row['openid']} "
                f"-> qq={row['qq_uin']} conf={row['confidence']} "
                f"status={row['status']} last={_time(row['last_seen'])}"
            )

        print()
        print("== 群别名 ==")
        group_rows = connection.execute(
            "SELECT * FROM group_aliases ORDER BY last_seen DESC LIMIT 50"
        ).fetchall()
        if not group_rows:
            print("（暂无）")
        for row in group_rows:
            print(
                f"- bot={row['official_bot_key']} group_openid={row['group_openid']} "
                f"-> qq_group={row['qq_group_id']} conf={row['confidence']} "
                f"status={row['status']} last={_time(row['last_seen'])}"
            )

    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
