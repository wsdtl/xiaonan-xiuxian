"""全量核对：9 项必过判据，并发跑，任一失败整体非零退出。

    .venv/Scripts/python.exe -X utf8 tools/全量核对.py

**退出码：0 = 全部通过，1 = 有失败项。**
"""
from __future__ import annotations

import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 本环境只允许写工作区内：TEMP/TMP 指到 _输出/临时（已忽略），子进程一并继承。
_SCRATCH = ROOT / "_输出" / "临时"
_SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(_SCRATCH)

#: 必过项：只留挡住启动失败、存档损坏、边界穿透、正式数据被写回的那几条。
REQUIRED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("边界审查", ("tools/架构审查/结构/检查边界.py",)),
    ("启动契约", ("tools/架构审查/命令/检查启动契约.py",)),
    ("数据驱动", ("tools/架构审查/数据/检查数据驱动.py",)),
    ("存档键名", ("tools/架构审查/数据/检查存档键名.py",)),
    ("存档结构", ("tools/架构审查/数据/检查存档版本.py",)),
    ("数据不被写回", ("tools/架构审查/数据/检查数据不被写回.py",)),
    ("启动顺序", ("tools/行为验证/驱动/验证启动顺序.py",)),
    ("语法", ("-m", "compileall", "-q", "game", "tools", "launch", "message", "tests")),
    ("单元测试", ("tools/跑测试.py",)),
)


def run_one(item: tuple[str, tuple[str, ...]]) -> tuple[str, bool, str, float]:
    name, argv = item
    started = time.perf_counter()
    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", *argv],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        return name, False, "超时（900 秒）", time.perf_counter() - started
    except OSError as exc:
        return name, False, f"无法启动：{exc}", time.perf_counter() - started
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    if done.returncode != 0:
        markers = [
            line.strip()
            for line in (done.stdout or "").splitlines()
            if line.strip().startswith(("FAILED", "ERROR")) or "FAILED " in line
        ]
        if markers:
            tail = " ｜ ".join([tail, *markers[:3]])
        if (done.stderr or "").strip():
            last_error = (done.stderr or "").strip().splitlines()[-1]
            tail = f"{tail} ｜ stderr: {last_error}".strip(" ｜")
    return name, done.returncode == 0, tail[:320], time.perf_counter() - started


def main() -> int:
    started = time.perf_counter()
    failures: list[str] = []
    shutil.rmtree(_SCRATCH, ignore_errors=True)
    _SCRATCH.mkdir(parents=True, exist_ok=True)
    cores = os.cpu_count() or 4
    workers = max(1, min(cores - 1, 4))
    # 单元测试自己开 4 片；核多的机器上让它与其它项同时跑，墙钟从「两段相加」变成
    # 「取最长的一段」。核少时仍让测试独占，避免 7 个进程抢 4 个核反而更慢。
    measured: dict[str, tuple[str, bool, str, float]] = {}
    if cores >= 8:
        ordered = tuple(sorted(REQUIRED, key=lambda item: "单元测试" not in item[0]))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for item, result in zip(ordered, pool.map(run_one, ordered)):
                measured[item[0]] = result
    else:
        heavies = tuple(item for item in REQUIRED if "单元测试" in item[0])
        others = tuple(item for item in REQUIRED if item not in heavies)
        measured.update({item[0]: run_one(item) for item in heavies})
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            for item, result in zip(others, pool.map(run_one, others)):
                measured[item[0]] = result
    for item in REQUIRED:
        name, ok, tail, seconds = measured[item[0]]
        print(f"  [{'通过' if ok else '失败'}] {name:<14} {seconds:>6.1f}s  {tail}")
        if not ok:
            failures.append(name)
    wall = time.perf_counter() - started
    if failures:
        print(f"总账：{len(REQUIRED)} 项，失败 {len(failures)} 项 —— {'、'.join(failures)}（墙钟 {wall:.1f}s）")
        return 1
    print(f"总账：{len(REQUIRED)} 项全部通过（墙钟 {wall:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
