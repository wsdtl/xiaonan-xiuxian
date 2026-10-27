"""运行现场监控：进程/端口/锁/三库/WAL/alias 覆盖率/未绑定日志。

只读，不启动、不停止、不写任何库。

    .venv/Scripts/python.exe -X utf8 tools/维护/运行监控.py

**退出码：0 = 采集完成；1 = 采集本身失败。**
"""
from __future__ import annotations

import os
import pathlib
import socket
import sqlite3
import sys
from datetime import datetime

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from assist_router.config import AssistRouterSettings  # noqa: E402
from game.config import game_config  # noqa: E402
from launch import config as launch_config  # noqa: E402

LOCK = ROOT / "launch" / "runtime" / "server.lock"
LOG = ROOT / "log" / "runserver.log"


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


def _pid() -> int | None:
    try:
        raw = LOCK.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw.startswith("pid="):
        return None
    try:
        return int(raw.split("=", 1)[1])
    except ValueError:
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _counts(path: pathlib.Path, query: str) -> int:
    if not path.is_file():
        return -1
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=20)
    try:
        return int(connection.execute(query).fetchone()[0])
    except sqlite3.Error:
        return -1
    finally:
        connection.close()


def _aliases() -> tuple[set[str], set[str]]:
    game = pathlib.Path(game_config.database.path)
    router = pathlib.Path(AssistRouterSettings().db_path)
    users: set[str] = set()
    aliases: set[str] = set()
    if game.is_file():
        connection = sqlite3.connect(f"file:{game}?mode=ro", uri=True, timeout=20)
        try:
            users = {str(row[0]) for row in connection.execute("SELECT user_id FROM player_state")}
        finally:
            connection.close()
    if router.is_file():
        connection = sqlite3.connect(f"file:{router}?mode=ro", uri=True, timeout=20)
        try:
            aliases = {str(row[0]) for row in connection.execute("SELECT qq_uin FROM user_aliases")}
        finally:
            connection.close()
    return users, aliases


def _unbound() -> tuple[int, str]:
    if not LOG.is_file():
        return 0, "无日志"
    count = 0
    last = ""
    with LOG.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "QQ 身份路由尚未建立" in line:
                count += 1
                last = line.strip()
    return count, last or "无"


def main() -> int:
    print("== 运行监控 ==")
    port = int(launch_config.server.port or 8443)
    pid = _pid()
    print(f"  时间        {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  服务锁      {'pid=' + str(pid) if pid else '不存在'} / {'存活' if _alive(pid) else '无进程'}")
    print(f"  端口 {port:<5} {'监听中' if _port_open(port) else '未监听'}")
    for name, path in (
        ("game", pathlib.Path(game_config.database.path)),
        ("runtime_log", pathlib.Path(game_config.runtime_log.path)),
        ("assist_router", pathlib.Path(AssistRouterSettings().db_path)),
    ):
        sizes = []
        for suffix in ("", "-wal", "-shm"):
            file = pathlib.Path(str(path) + suffix) if suffix else path
            sizes.append(f"{suffix or '主库'}={_human_bytes(file.stat().st_size) if file.is_file() else '-'}")
        print(f"  {name:<12} {' '.join(sizes)}")

    users, aliases = _aliases()
    covered = users & aliases
    missing = sorted(users - aliases)
    print(f"  人物 / alias {len(users)} / {len(aliases)}，覆盖 {len(covered)}")
    if missing:
        print(f"  未覆盖       {', '.join(missing)}")
    else:
        print("  未覆盖       无")

    count, last = _unbound()
    print(f"  未绑定日志   {count} 条")
    if last != "无":
        print(f"  最后一条     {last[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
