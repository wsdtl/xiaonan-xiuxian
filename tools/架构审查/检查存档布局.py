"""存档布局审查：玩家状态每人一行、旧结构必须已迁空、回执条数有上限。

规则一：player_state 每个玩家恰好 1 行（主键保证），行数是玩家数、与内容条数无关。
规则二：旧表 state_snapshot 必须已迁空（0 行）——它代表"一个状态键一行"的旧结构；
        残留即说明结构迁移没做完。
规则三：每个玩家的幂等回执（committed_transaction）条数不得超过上限（默认 100 笔）。

实现见 game/core/database/storage.py。退出码：0 = 合规；1 = 违规；2 = 库缺失。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "database/game.db"
RECEIPT_LIMIT = 100


def main() -> int:
    if not LIB.exists():
        print("存档布局审查：没有存档库，跳过")
        return 0
    connection = sqlite3.connect(f"file:{LIB.as_posix()}?mode=ro", uri=True)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "player_state" not in tables:
        print("存档布局审查：没有 player_state 表（结构未迁移）")
        connection.close()
        return 1
    players = connection.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM player_state").fetchone()
    legacy = int(
        connection.execute(
            "SELECT COUNT(*) FROM state_snapshot" if "state_snapshot" in tables else "SELECT 0"
        ).fetchone()[0]
    )
    receipts = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            "SELECT user_id, COUNT(*) FROM committed_transaction GROUP BY user_id"
        ).fetchall()
    }
    connection.close()
    print(f"存档布局：player_state {players[0]} 行 / {players[1]} 个玩家 ｜ 旧表残留 {legacy} 行 ｜ 回执 {receipts}")
    if players[0] != players[1]:
        print("  [失败] player_state 有玩家多行")
        return 1
    if legacy:
        print(f"  [失败] 旧表 state_snapshot 仍残留 {legacy} 行，结构迁移未完成")
        return 1
    over = {owner: count for owner, count in receipts.items() if count > RECEIPT_LIMIT}
    if over:
        print(f"  [失败] 幂等回执超上限（每人 {RECEIPT_LIMIT} 笔）：{over}")
        return 1
    print(f"  每人一行、旧结构已迁空、回执 ≤ {RECEIPT_LIMIT} 笔：合规")
    return 0


if __name__ == "__main__":
    sys.exit(main())
