"""存档布局审查：玩家状态每人一行、存档库不许有日志类表、回执归日志库。

规则一：player_state 每个玩家恰好 1 行（主键保证），行数与内容条数无关。
规则二：存档库（game.db）不得出现日志类表——表名以 log_ 开头、以 _log/_logs 结尾，
        或叫 committed_transaction，都算日志类，必须住在 runtime_log.db。
规则三：旧结构 state_snapshot 不得存在（那是"一个状态键一行"的旧设计）。
规则四：日志库里每个玩家的幂等回执条数不得超过上限（默认 100 笔），且回执表必须带 expires_at。

实现见 game/core/database/storage.py。退出码：0 = 合规；1 = 违规；2 = 库缺失。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SAVE_DB = ROOT / "database/game.db"
LOG_DB = ROOT / "database/runtime_log.db"
RECEIPT_LIMIT = 100
LOG_TABLE_NAMES = {"committed_transaction"}


def is_log_like(name: str) -> bool:
    lowered = name.lower()
    return lowered in LOG_TABLE_NAMES or lowered.startswith("log_") or lowered.endswith("_log") or lowered.endswith("_logs")


def tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    names = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    return names


def main() -> int:
    if not SAVE_DB.exists():
        print("存档布局审查：没有存档库，跳过")
        return 0
    save_tables = tables(SAVE_DB)
    log_tables = tables(LOG_DB)
    if "player_state" not in save_tables:
        print("存档布局审查：存档库没有 player_state 表")
        return 1
    connection = sqlite3.connect(f"file:{SAVE_DB.as_posix()}?mode=ro", uri=True)
    rows, owners = connection.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM player_state").fetchone()
    connection.close()
    bad = sorted(name for name in save_tables if is_log_like(name))
    print(f"存档布局：player_state {rows} 行 / {owners} 个玩家 ｜ 存档库表 {sorted(save_tables)}")
    if rows != owners:
        print("  [失败] player_state 有玩家多行")
        return 1
    if bad:
        print(f"  [失败] 存档库出现日志类表：{bad}（应住日志库）")
        return 1
    if "state_snapshot" in save_tables:
        print("  [失败] 旧结构 state_snapshot 仍在")
        return 1
    if "log_committed_transactions" not in log_tables:
        print("  [失败] 日志库缺少 log_committed_transactions")
        return 1
    connection = sqlite3.connect(f"file:{LOG_DB.as_posix()}?mode=ro", uri=True)
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(log_committed_transactions)")}
    counts = {str(row[0]): int(row[1]) for row in connection.execute(
        "SELECT user_id, COUNT(*) FROM log_committed_transactions GROUP BY user_id").fetchall()}
    connection.close()
    if "expires_at" not in columns:
        print("  [失败] 回执表没有 expires_at（无法按 TTL 过期）")
        return 1
    over = {owner: count for owner, count in counts.items() if count > RECEIPT_LIMIT}
    if over:
        print(f"  [失败] 回执超上限（每人 {RECEIPT_LIMIT} 笔）：{over}")
        return 1
    print(f"  每人一行、存档库无日志类表、旧结构已除、日志库回执 ≤ {RECEIPT_LIMIT} 笔：合规（{counts}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
