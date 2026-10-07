"""跑单元测试：把 tests/ 的文件分成若干组并发跑，缩短墙钟。

测试文件彼此独立，但都要装一遍数据快照（每次约 1.4 秒），串行跑是纯浪费。
这里按文件轮转分组、并发执行，任一组的 pytest 非零退出即整体非零退出。

    .venv/Scripts/python.exe -X utf8 tools/跑测试.py

**退出码：0 = 全部通过，1 = 有失败。**
"""
from __future__ import annotations

import concurrent.futures
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
#: 并发组数：测试本身几乎不占 CPU，瓶颈是各自装数据；给足并发就能摊平。
GROUPS = max(1, min(8, os.cpu_count() or 4))


def _shards() -> list[list[str]]:
    """按文件体积做 LPT 平衡分组——体积是耗时最好的现成代理。"""

    files = sorted(TESTS.glob("test_*.py"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        return []
    groups: list[list[str]] = [[] for _ in range(GROUPS)]
    load = [0] * GROUPS
    for path in files:
        slot = load.index(min(load))
        groups[slot].append(path.name)
        load[slot] += path.stat().st_size
    return [group for group in groups if group]


def _run(job: tuple[int, list[str]]) -> tuple[bool, str, float]:
    index, group = job
    started = time.perf_counter()
    # 本环境的 TEMP/TMP 没设，pytest 与 tempfile 会回落到当前工作目录，把
    # pytest-of-* 与临时库落在仓库根。显式指到 _输出/ 下（已被 .gitignore 忽略）。
    basetemp = ROOT / "_输出" / "测试临时" / f"片{index}"
    basetemp.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(basetemp), "TMP": str(basetemp)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "--basetemp", str(basetemp), *[f"tests/{name}" for name in group]],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    return done.returncode == 0, tail[:120], time.perf_counter() - started


def main() -> int:
    groups = _shards()
    started = time.perf_counter()
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
        for index, (ok, tail, seconds) in enumerate(pool.map(_run, enumerate(groups, start=1)), start=1):
            print(f"  [{'通过' if ok else '失败'}] 第 {index} 组（{len(groups[index - 1])} 个文件） {seconds:>6.1f}s  {tail}")
            if not ok:
                failures.append(str(index))
    wall = time.perf_counter() - started
    if failures:
        print(f"单元测试：{len(groups)} 组，失败 {len(failures)} 组 —— 第 {'、'.join(failures)} 组（墙钟 {wall:.1f}s）")
        return 1
    print(f"单元测试：{len(groups)} 组全部通过（墙钟 {wall:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
