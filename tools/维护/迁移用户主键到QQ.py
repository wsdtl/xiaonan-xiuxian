"""把 game.db / runtime_log.db 里的旧 openid 用户主键迁到 QQ 号。

必须先备份，再在 --apply 下执行。只做文本替换和主键更新，不删除数据。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _text_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    result = []
    for row in connection.execute(f'PRAGMA table_info("{table}")'):
        declared = str(row[2] or "").upper()
        if declared in {"", "TEXT", "CHAR", "CLOB", "VARCHAR"} or "CHAR" in declared:
            result.append(str(row[1]))
    return result


def _tables(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in _tables(connection)
    }


def _migrate_database(path: Path, mapping: dict[str, str]) -> None:
    connection = sqlite3.connect(path)
    try:
        before = _counts(connection)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("PRAGMA temp_store=MEMORY")
        for table in _tables(connection):
            for column in _text_columns(connection, table):
                print(f"  迁移 {path.name}.{table}.{column}", flush=True)
                for old, new in mapping.items():
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}" = '
                        f'REPLACE("{column}", ?, ?) WHERE "{column}" LIKE ?',
                        (old, new, f"%{old}%"),
                    )
                    # Windows/SQLite 对连续主键更新会在一个长事务里触发
                    # 临时文件问题；逐条提交，失败由外层备份回滚。
                    connection.commit()

        after = _counts(connection)
        if before != after:
            raise RuntimeError(f"迁移前后行数变化：{before} -> {after}")

        for table in _tables(connection):
            for column in _text_columns(connection, table):
                for old in mapping:
                    remaining = connection.execute(
                        f'SELECT COUNT(*) FROM "{table}" '
                        f'WHERE "{column}" LIKE ?',
                        (f"%{old}%",),
                    ).fetchone()[0]
                    if remaining:
                        raise RuntimeError(
                            f"残留旧用户ID：{path.name}.{table}.{column} = {old}"
                        )
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"数据库完整性检查失败：{path}：{integrity}")
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mapping",
        nargs="?",
        default="_输出/辅助路由用户映射.json",
        help="openid -> QQ 映射 JSON",
    )
    parser.add_argument("--game-db", default="database/game.db")
    parser.add_argument("--log-db", default="database/runtime_log.db")
    parser.add_argument("--no-logs", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    items = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    mapping: dict[str, str] = {}
    for item in items:
        old = str(item.get("openid") or "").strip()
        new = str(item.get("qq_uin") or "").strip()
        if not old or not new:
            raise ValueError(f"映射缺少 openid/qq_uin：{item}")
        if old in mapping:
            raise ValueError(f"重复 openid：{old}")
        mapping[old] = new
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("同一个 QQ 号对应了多个 openid，需先确定合并策略")

    game_db = Path(args.game_db)
    log_db = Path(args.log_db)
    targets = [game_db]
    if not args.no_logs and log_db.is_file():
        targets.append(log_db)

    print(f"目标映射 {len(mapping)} 条")
    print("数据库", ", ".join(str(path) for path in targets))
    for path in targets:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            print(path.name, _counts(connection))
        finally:
            connection.close()

    if not args.apply:
        print("dry-run：未修改。确认后加 --apply。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = ROOT / "_输出" / "迁移备份" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    backups: list[tuple[Path, Path]] = []
    for path in targets:
        backup = backup_dir / path.name
        shutil.copy2(path, backup)
        if backup.stat().st_size != path.stat().st_size:
            raise RuntimeError(f"备份大小不一致：{backup}")
        backups.append((path, backup))
        print(f"已备份 {path} -> {backup}")

    try:
        for path in targets:
            _migrate_database(path, mapping)
            print(f"已迁移 {path}")
    except Exception:
        for path, backup in backups:
            shutil.copy2(backup, path)
            print(f"已回滚 {path}")
        raise
    print(f"完成；备份目录：{backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
