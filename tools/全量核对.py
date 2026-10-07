"""全量核对：把必过判据并发跑一遍，汇总成一行总账。

必过项是**改动任何地方都该跑完**的那一组：架构判据、行为验证、语法与单元测试。
每一支在独立进程里跑、并发执行、各自计时，末尾给一行总账；任一失败则整体非零退出。

慢通道（语料 / 对照 / 基准回归）不在本入口：它们属于发布验收，见
`tools/验收/发布验收.py`。

    .venv/Scripts/python.exe -X utf8 tools/全量核对.py

**退出码：0 = 全部通过，1 = 有失败项。**
"""
from __future__ import annotations

import concurrent.futures
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 必过项。每项一个名字 + 一组 argv（相对项目根）。
REQUIRED: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("边界审查（25 项）", ("tools/架构审查/检查边界.py",)),
    ("启动契约", ("tools/架构审查/校验启动契约.py",)),
    ("命令目录", ("tools/架构审查/校验命令目录.py",)),
    ("数据驱动", ("tools/架构审查/检查数据驱动.py",)),
    ("卡形判据（14 支）", ("tools/架构审查/检查卡形.py",)),
    ("战报展示", ("tools/架构审查/检查战报展示.py",)),
    ("启动顺序", ("tools/验证启动顺序.py",)),
    ("语法（game/tools/launch/message/tests）", ("-m", "compileall", "-q", "game", "tools", "launch", "message", "tests")),
    ("单元测试", ("-m", "pytest", "-q",)),
    ("战斗说明审查", ("tools/audit_combat_descriptions.py",)),
    ("战斗文本渲染", ("tools/渲染战斗文本.py",)),
    ("协议适配", ("tools/协议适配对照.py",)),
    ("基准文件命名", ("tools/架构审查/检查基准文件.py",)),
    ("静态资源", ("tools/架构审查/检查静态资源.py",)),
    ("文档计数", ("tools/架构审查/检查文档计数.py",)),
    ("规则层", ("tools/架构审查/检查规则层.py",)),
    ("规则层行为", ("tools/验证规则层.py",)),
    ("机械化棘轮", ("tools/机械化盘点.py",)),
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
    except OSError as exc:  # 起不来也算失败
        return name, False, f"无法启动：{exc}", time.perf_counter() - started
    tail = ""
    for line in reversed((done.stdout or "").splitlines()):
        if line.strip():
            tail = line.strip()
            break
    if done.returncode != 0 and (done.stderr or "").strip():
        last_error = (done.stderr or "").strip().splitlines()[-1]
        tail = f"{tail} ｜ {last_error}".strip(" ｜")
    return name, done.returncode == 0, tail[:150], time.perf_counter() - started


def main() -> int:
    started = time.perf_counter()
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(REQUIRED)) as pool:
        for name, ok, tail, seconds in pool.map(run_one, REQUIRED):
            print(f"  [{'通过' if ok else '失败'}] {name:<28} {seconds:>6.1f}s  {tail}")
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
