"""三库一致性备份 + 恢复演练。

源库只读；备份写到 .runtime/backups/<时间戳>/；演练恢复到 _输出/临时/恢复演练-<时间戳>/。
不写 database/。

    .venv/Scripts/python.exe -X utf8 tools/维护/存档备份.py

**退出码：0 = 三库备份与演练均通过；1 = 有失败。**
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sqlite3
import sys
import time
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assist_router.config import AssistRouterSettings  # noqa: E402
from game.config import game_config  # noqa: E402

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")
BACKUP_ROOT = ROOT / ".runtime" / "backups" / f"三库-{STAMP}"
DRILL_ROOT = ROOT / "_输出" / "验收" / f"恢复演练-{STAMP}"

#: 每张表在备份与恢复演练后必须一致的行数。
TABLE_COUNTS = {
    "runtime_log": ("log_battle_reports", "log_message_flows", "log_committed_transactions"),
    "assist_router": ("users", "user_aliases", "groups", "group_aliases", "events"),
}


def _databases() -> dict[str, pathlib.Path]:
    return {
        "game": pathlib.Path(game_config.database.path),
        "runtime_log": pathlib.Path(game_config.runtime_log.path),
        "assist_router": pathlib.Path(AssistRouterSettings().db_path),
    }


def _open_readonly(path: pathlib.Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)


def _table_counts(path: pathlib.Path, tables: tuple[str, ...]) -> dict[str, int]:
    connection = _open_readonly(path)
    try:
        present = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
            if table in present
        }
    finally:
        connection.close()


def _player_counts(path: pathlib.Path) -> dict[str, int]:
    connection = _open_readonly(path)
    try:
        players = int(connection.execute("SELECT COUNT(*) FROM player_state").fetchone()[0])
        entries = 0
        for (raw,) in connection.execute("SELECT state_json FROM player_state"):
            try:
                value = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                entries += len(value)
        return {"player_state": players, "state_entries": entries}
    finally:
        connection.close()


def _backup(source: pathlib.Path, target: pathlib.Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"源库不存在：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = _open_readonly(source)
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
        integrity = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"{source.name} 备份完整性检查失败：{integrity}")
    finally:
        dst.close()
        src.close()


def _drill(backup: pathlib.Path, source_name: str) -> dict[str, object]:
    target = DRILL_ROOT / source_name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, target)
    connection = sqlite3.connect(f"file:{target}?mode=ro", uri=True, timeout=30)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok":
        raise RuntimeError(f"{source_name} 恢复后完整性检查失败：{integrity}")
    return {"integrity": integrity, "bytes": target.stat().st_size}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--不演练", action="store_true", help="只备份，不恢复演练")
    args = parser.parse_args()
    started = time.perf_counter()
    databases = _databases()
    receipt: dict[str, object] = {}
    failures: list[str] = []
    print("== 三库备份 ==")
    for name, source in databases.items():
        try:
            target = BACKUP_ROOT / source.name
            _backup(source, target)
            receipt[name] = {
                "源": str(source),
                "备份": str(target),
                "字节": target.stat().st_size,
                "行数": _player_counts(source) if name == "game" else _table_counts(source, TABLE_COUNTS.get(name, ())),
            }
            print(f"  [通过] {name:<12} {source.stat().st_size:>12,} -> {target}")
        except Exception as error:  # noqa: BLE001 - 汇总所有失败
            failures.append(name)
            print(f"  [失败] {name:<12} {type(error).__name__}: {error}")
    if args.不演练:
        receipt["演练"] = "跳过"
    else:
        print("== 恢复演练 ==")
        for name, source in databases.items():
            if name in failures:
                continue
            try:
                backup = BACKUP_ROOT / source.name
                drill = _drill(backup, source.name)
                expected = receipt[name]["行数"]  # type: ignore[index]
                actual = (
                    _player_counts(DRILL_ROOT / source.name)
                    if name == "game"
                    else _table_counts(DRILL_ROOT / source.name, TABLE_COUNTS.get(name, ()))
                )
                if expected != actual:
                    raise RuntimeError(f"恢复后行数不一致：{expected} != {actual}")
                receipt[name]["演练"] = {**drill, "行数": actual}  # type: ignore[index]
                print(f"  [通过] {name:<12} integrity=ok 行数={actual}")
            except Exception as error:  # noqa: BLE001
                failures.append(name)
                print(f"  [失败] {name:<12} {type(error).__name__}: {error}")
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    (BACKUP_ROOT / "回执.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    wall = time.perf_counter() - started
    if failures:
        print(f"总账：失败 {len(failures)} 项 —— {'、'.join(failures)}（墙钟 {wall:.1f}s）")
        return 1
    print(f"总账：三库备份与演练通过（墙钟 {wall:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
