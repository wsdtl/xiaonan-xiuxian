"""卡形判据总入口：一次并发跑完全部卡形检查。

卡形（功法 / 真意 / 气机 / 器律 / 丹药）的判据彼此独立、都要读同一份数据快照，
所以它们合成一个入口并发执行：进度按支报，任一支非零退出即整体非零退出。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查卡形.py

**退出码：0 = 全部通过，1 = 有失败支。**
"""
from __future__ import annotations

import concurrent.futures
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]

MEMBER: tuple[str, ...] = (
    "检查构筑形状.py",
    "检查三件套边界.py",
    "检查词条作用域.py",
    "检查构筑模板.py",
    "检查原子能力.py",
    "检查重复动作.py",
    "检查悬空引用.py",
    "检查被动形状.py",
    "检查能力命名.py",
    "检查描述一致.py",
    "检查炼丹形状.py",
    "检查功法冷却.py",
    "检查监听位置.py",
    "检查结构唯一性.py",
)


def run_one(name: str) -> tuple[str, bool, str, float]:
    started = time.perf_counter()
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(ROOT / "tools" / "架构审查" / name)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
    )
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    return name, done.returncode == 0, tail[:120], time.perf_counter() - started


def main() -> int:
    failed: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(MEMBER)) as pool:
        for name, ok, tail, seconds in pool.map(run_one, MEMBER):
            print(f"  [{'通过' if ok else '失败'}] {name:<22} {seconds:>6.1f}s  {tail}")
            if not ok:
                failed.append(name)
    if failed:
        print(f"卡形判据：{len(MEMBER)} 支，失败 {len(failed)} 支 —— {'、'.join(failed)}")
        return 1
    print(f"卡形判据：{len(MEMBER)} 支全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
