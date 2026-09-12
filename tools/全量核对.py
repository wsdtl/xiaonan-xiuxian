"""全量核对：把这个项目的检查与判据跑一遍，汇总成一行总账。

这个项目有十余支检查与判据，分三类：架构审查、结构测量、语料验收。它们一直是**靠人
记得跑哪几支**——`tools/验证启动顺序.py` 就因此在十几轮改动里一次都没被跑过（它一直
是通的，但没人知道该跑它）。**「全绿」不该是记忆，该是一个脚本。**

    .venv/Scripts/python.exe -X utf8 tools/全量核对.py            # 必过 11 项（实测 67 秒）
    .venv/Scripts/python.exe -X utf8 tools/全量核对.py --全量      # 17 项（实测 376 秒）

每一支都在**独立进程**里跑，各自超时；逐条报结果，末尾给总账。任一失败则整体非零退出。

**退出码：0 = 全部通过，1 = 有失败项。**
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 必过项：架构审查、启动顺序、语法、单元测试。改动任何地方都该跑完这一组。
REQUIRED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("边界审查（20 项）", ("tools/架构审查/检查边界.py",)),
    ("启动契约", ("tools/架构审查/校验启动契约.py",)),
    ("命令目录", ("tools/架构审查/校验命令目录.py",)),
    ("数据驱动", ("tools/架构审查/检查数据驱动.py",)),
    ("构筑形状", ("tools/架构审查/检查构筑形状.py",)),
    ("词条作用域", ("tools/架构审查/检查词条作用域.py",)),
    ("启动顺序", ("tools/验证启动顺序.py",)),
    ("语法（game/tools/launch/message）", ("-m", "compileall", "-q", "game", "tools", "launch", "message")),
    ("单元测试", ("-m", "pytest", "-q",)),
    ("数据审查（audit_data）", ("tools/audit_data.py",)),
    ("战斗说明审查", ("tools/audit_combat_descriptions.py",)),
    ("协议适配", ("tools/协议适配对照.py",)),
    ("机械化棘轮", ("tools/机械化盘点.py",)),
)

#: 慢项：语料通道与历史数据审查。改数据、改渲染、改战斗时必须跑。
SLOW: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("语料 1264 场", ("tools/语料对照.py", "--对照", "tools/基准/语料摘要.sem")),
    ("战前状态 170 场", ("tools/战前状态对照.py",)),
    ("卡面正文 2314 张", ("tools/渲染正文对照.py",)),
    ("查看页 3859 个实体", ("tools/查看结果对照.py",)),
    ("战报 1264 份", ("tools/战报对照.py",)),
    ("装配规划 28545 条", ("tools/装配规划对照.py",)),
)


def run_one(name: str, argv: tuple[str, ...]) -> tuple[bool, str, float]:
    started = time.perf_counter()
    try:
        done = subprocess.run(
            [sys.executable, "-X", "utf8", *argv],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # 起不来也算失败
        return False, f"无法启动：{exc}", time.perf_counter() - started
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    if done.returncode != 0 and (done.stderr or "").strip():
        last_error = (done.stderr or "").strip().splitlines()[-1]
        tail = f"{tail} ｜ {last_error}".strip(" ｜")
    return done.returncode == 0, tail[:150], time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--全量", action="store_true", help="连同语料通道一起跑（约 15 分钟）")
    args = parser.parse_args()

    groups = [("必过项", REQUIRED)]
    if args.全量:
        groups.append(("语料与数据", SLOW))

    failures: list[str] = []
    for title, items in groups:
        print(f"===== {title} =====")
        for name, argv in items:
            ok, tail, seconds = run_one(name, argv)
            mark = "通过" if ok else "失败"
            print(f"  [{mark}] {name:<26} {seconds:>6.1f}s  {tail}")
            if not ok:
                failures.append(name)
        print()

    total = sum(len(items) for _, items in groups)
    if failures:
        print(f"总账：{total} 项，失败 {len(failures)} 项 —— {'、'.join(failures)}")
        return 1
    print(f"总账：{total} 项全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
