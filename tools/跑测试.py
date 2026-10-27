"""跑 tests/：按实测耗时把测试文件分到 4 片并发跑，缩短墙钟。

分片按文件做 LPT（大文件先放），不拆单个文件；每片一个 pytest 进程，
各自用 _输出/临时/测试片N 做 TEMP/TMP，互不共享数据库。

    .venv/Scripts/python.exe -X utf8 tools/跑测试.py

**退出码：0 = 全部通过，1 = 有失败。**
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
TESTS = ROOT / "tests"
SHARDS = max(1, min(4, (os.cpu_count() or 4) - 1))

#: 逐文件实测墙钟（秒，含 pytest 启动；2026-10-27）。新增/删除测试文件后刷新。
WEIGHTS: dict[str, float] = {
    "test_component_loading.py": 2.8,
    "test_crafting_facilities.py": 11.2,
    "test_combat_entry_surfaces.py": 8.4,
    "test_prepared_status.py": 8.0,
    "test_generic_shop.py": 6.8,
    "test_battle_report.py": 6.5,
    "test_data_contract.py": 5.5,
    "test_access_guard.py": 5.2,
    "test_assist_router.py": 2.9,
    "test_branch_commands.py": 2.5,
    "test_identity_bridge.py": 2.5,
    "test_qq_ws_runtime.py": 2.4,
}
DEFAULT_WEIGHT = 3.0


def _shards() -> list[list[str]]:
    files = sorted(TESTS.glob("test_*.py"))
    weighted = sorted(
        ((WEIGHTS.get(path.name, DEFAULT_WEIGHT), "tests/" + path.name) for path in files),
        key=lambda row: -row[0],
    )
    groups: list[list[str]] = [[] for _ in range(SHARDS)]
    load = [0.0] * SHARDS
    for weight, relative in weighted:
        slot = load.index(min(load))
        groups[slot].append(relative)
        load[slot] += weight
    return [group for group in groups if group]


def _run(index: int, files: list[str]) -> tuple[bool, str, float]:
    started = time.perf_counter()
    scratch = ROOT / "_输出" / "临时" / ("测试片" + str(index))
    scratch.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "TEMP": str(scratch), "TMP": str(scratch)}
    done = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            str(scratch),
            *files,
        ],
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
    if done.returncode != 0:
        failed = [
            line.strip()
            for line in (done.stdout or "").splitlines()
            if line.strip().startswith(("FAILED", "ERROR"))
        ]
        if failed:
            tail += " ｜ " + "；".join(failed[:3])
        errors = [line.strip() for line in (done.stderr or "").splitlines() if line.strip()]
        if errors:
            tail += " ｜ stderr: " + errors[-1]
    # 测试会往 basetemp 里复制数据树（一个片可到上万文件）；跑完就地清掉，
    # 别让下一次全量核对的 rmtree 在 Windows 上删几分钟。
    shutil.rmtree(scratch, ignore_errors=True)
    return done.returncode == 0, tail[:500], time.perf_counter() - started


def main() -> int:
    groups = _shards()
    started = time.perf_counter()
    failures: list[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(groups)) as pool:
        futures = [pool.submit(_run, index, group) for index, group in enumerate(groups, start=1)]
        for index, future in enumerate(futures, start=1):
            ok, tail, seconds = future.result()
            mark = "通过" if ok else "失败"
            print(f"  [{mark}] 第 {index} 组 {seconds:>6.1f}s  {tail}")
            if not ok:
                failures.append(index)
    wall = time.perf_counter() - started
    if failures:
        print(f"单元测试：{len(groups)} 组，失败 {len(failures)} 组 —— 第 {'、'.join(map(str, failures))} 组（墙钟 {wall:.1f}s）")
        return 1
    print(f"单元测试：{len(groups)} 组全部通过（墙钟 {wall:.1f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
