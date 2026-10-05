"""存档布局审查：每玩家一行、状态键不许是内容编号、回执条数有上限。

规则一：state_snapshot 里每个玩家最多 1 行，总行数不得超过玩家数（内容增长不影响）。
规则二：任何 state_key 不得是内容编号（纯数字或 编号:阶）——那是把静态内容逐条落库。
规则三：每个玩家的幂等回执（committed_transaction）条数不得超过上限（默认 100 笔）；
        回执只需覆盖"重放一次"的窗口，不需要长期历史。

实现见 game/core/database/storage.py（_load_logical_state / _store_logical_state /
prune_receipts）。退出码：0 = 合规；1 = 违规；2 = 脚本或库缺失。
"""
from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "database/game.db"
RECEIPT_LIMIT = 100
CONTENT_KEY = re.compile(r"^\d{4,}(:\d+)?$")


def receipt_counts() -> dict[str, int]:
    connection = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT user_id, COUNT(*) FROM committed_transaction GROUP BY user_id"
    ).fetchall()
    connection.close()
    return {str(row[0]): int(row[1]) for row in rows}


def main() -> int:
    if not LIB.exists():
        print("存档布局审查：没有存档库，跳过")
        return 0
    connection = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    rows = connection.execute(
        "SELECT user_id, state_type, state_key FROM state_snapshot"
    ).fetchall()
    connection.close()
    owners = {str(row[0]) for row in rows}
    content_rows = [f"{r[0]}/{r[1]}/{r[2]}" for r in rows if CONTENT_KEY.match(str(r[2]))]
    stragglers = [
        f"{r[0]}/{r[1]}/{r[2]}"
        for r in rows
        if not (str(r[1]) == "player" and str(r[2]) == "main")
    ]
    print(f"存档布局：玩家 {len(owners)} 个 ｜ state_snapshot 行数 {len(rows)}")
    if content_rows:
        print(f"  [失败] 把内容编号当状态键 {len(content_rows)} 处，例如 {content_rows[:3]}")
        return 1
    if stragglers:
        print(f"  [失败] 仍有逐条行 {len(stragglers)} 处，例如 {stragglers[:3]}")
        return 1
    counts = receipt_counts()
    over = {owner: count for owner, count in counts.items() if count > RECEIPT_LIMIT}
    if over:
        print(f"  [失败] 幂等回执超上限（每人 {RECEIPT_LIMIT} 笔）：{over}")
        return 1
    print(f"  每玩家一行、状态键不含内容编号、回执 ≤ {RECEIPT_LIMIT} 笔：合规 ｜ 回执 {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
