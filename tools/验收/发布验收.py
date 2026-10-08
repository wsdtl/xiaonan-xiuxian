"""发布验收：慢通道整组跑一遍。

这些通道各读一层（语料 / 战前状态 / 战场环境 / 阵法 / 卡面正文 / 查看页 /
战报 / 战报记录 / 装配规划 / 交叉对局），合计十几分钟，所以**不进必过项**——
它们是发布前的手动验收，不是改动之后随手跑的那一组。

    .venv/Scripts/python.exe -X utf8 tools/验收/发布验收.py

每一支独立进程、各自计时、末尾给一行总账。退出码：0 = 全部一致，1 = 有差异。

重新取基准：在各通道脚本上加 --写基准（见 tools/说明.md）。
"""
from __future__ import annotations

import os

import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]

# 本环境（DSH 沙箱）只允许写工作区内：%TEMP% 对 Python 一律 PermissionError，
# tempfile 于是回落到当前目录，把 pip-*/pytest-of-* 这类临时件丢在仓库根。
# 把 TEMP/TMP 指到 _输出/临时（已被 .gitignore 忽略），子进程一并继承。
_SCRATCH = ROOT / "_输出" / "临时"
_SCRATCH.mkdir(parents=True, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = str(_SCRATCH)


CHANNELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("语料通道", ("tools/验收/语料对照.py", "--对照", "tools/基准/语料摘要.sem")),
    ("监听收窄对照", ("tools/验收/监听收窄对照.py",)),
    ("语料行为通道", ("tools/验收/语料对照.py", "--摘要", "行为", "--对照", "tools/基准/语料行为摘要.sem")),
    ("战前状态通道", ("tools/验收/战前状态对照.py",)),
    ("战场环境通道", ("tools/验收/战场环境对照.py",)),
    ("阵法通道", ("tools/验收/阵法对照.py",)),
    ("卡面正文通道", ("tools/验收/渲染正文对照.py",)),
    ("查看页通道", ("tools/验收/查看结果对照.py",)),
("零信息复核", ("tools/验收/复核零信息判据.py",)),
    ("战报通道", ("tools/验收/战报对照.py",)),
    ("战报记录通道", ("tools/验收/战报记录对照.py",)),
    ("装配规划通道", ("tools/验收/装配规划对照.py",)),
    ("交叉对局通道", ("tools/验收/交叉对局对照.py",)),
)


def main() -> int:
    started = time.perf_counter()
    failures: list[str] = []
    for name, argv in CHANNELS:
        one = time.perf_counter()
        done = subprocess.run(
            [sys.executable, "-X", "utf8", *argv],
            cwd=ROOT,
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
        mark = "通过" if done.returncode == 0 else "失败"
        print(f"  [{mark}] {name:<14} {time.perf_counter() - one:>7.1f}s  {tail[:120]}")
        if done.returncode != 0:
            failures.append(name)
    wall = time.perf_counter() - started
    if failures:
        print(f"验收总账：{len(CHANNELS)} 条通道，失败 {len(failures)} 条 —— {'、'.join(failures)}（墙钟 {wall:.0f}s）")
        return 1
    print(f"验收总账：{len(CHANNELS)} 条通道全部一致（墙钟 {wall:.0f}s）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
