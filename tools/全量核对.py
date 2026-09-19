"""全量核对：把这个项目的检查与判据跑一遍，汇总成一行总账。

这个项目有十余支检查与判据，分三类：架构审查、结构测量、语料验收。它们一直是**靠人
记得跑哪几支**——`tools/验证启动顺序.py` 就因此在十几轮改动里一次都没被跑过（它一直
是通的，但没人知道该跑它）。**「全绿」不该是记忆，该是一个脚本。**

    .venv/Scripts/python.exe -X utf8 tools/全量核对.py            # 必过项（实测约 70 秒）
    .venv/Scripts/python.exe -X utf8 tools/全量核对.py --全量      # 必过 + 慢项（实测约 11 分钟，建议后台跑）

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
    ("边界审查（24 项）", ("tools/架构审查/检查边界.py",)),
    ("启动契约", ("tools/架构审查/校验启动契约.py",)),
    ("命令目录", ("tools/架构审查/校验命令目录.py",)),
    ("数据驱动", ("tools/架构审查/检查数据驱动.py",)),
    ("构筑形状", ("tools/架构审查/检查构筑形状.py",)),
    ("词条作用域", ("tools/架构审查/检查词条作用域.py",)),
    ("构筑模板", ("tools/架构审查/检查构筑模板.py",)),
    ("原子能力", ("tools/架构审查/检查原子能力.py",)),
    # 「同一时点不得出现重复动作」是负责人的硬规矩，这一支直接对着可执行结构判。
    ("重复动作", ("tools/架构审查/检查重复动作.py",)),
    # 读了却没人建立 = 条件永远不成立、那段效果从没跑过（第 71 轮清了 44 处）。
    ("悬空引用", ("tools/架构审查/检查悬空引用.py",)),
    # 一个被动只挂一条监听：混装成一个，正文看起来就是「一个被动做了五件事」。
    ("被动形状", ("tools/架构审查/检查被动形状.py",)),
    # 能力名全库唯一（正文显示的是短名，撞名玩家就分不出是哪张卡的技能）。
    ("能力命名", ("tools/架构审查/检查能力命名.py",)),
    # 描述必须与设计一模一样：渲染器不许解释层兜底（未支持 / 兜底 / None 泄漏）。
    ("描述一致", ("tools/架构审查/检查描述一致.py",)),
    # 方法与实体合在一处：丹药自带处方（炼制难度 / 炉法），不再有第二份丹方实体。
    ("炼丹形状", ("tools/架构审查/检查炼丹形状.py",)),
    # 战报展示层要跟战报本身自洽：阵营分组、对阵标题、简要行、内部明细（第 86 轮）。
    ("战报展示", ("tools/架构审查/检查战报展示.py",)),
    ("启动顺序", ("tools/验证启动顺序.py",)),
    ("语法（game/tools/launch/message/tests）", ("-m", "compileall", "-q", "game", "tools", "launch", "message", "tests")),
    ("单元测试", ("-m", "pytest", "-q",)),
    ("数据审查（audit_data）", ("tools/audit_data.py",)),
    ("战斗说明审查", ("tools/audit_combat_descriptions.py",)),
    # 渲染器本身有判据（卡面正文通道），但没有判据管「渲染工具还能不能跑通」：
    # 它曾经绕过模板展开直接读 JSON，整套功法渲染成〈未支持：〉而没人发现。
    ("战斗文本渲染", ("tools/渲染战斗文本.py",)),
    ("协议适配", ("tools/协议适配对照.py",)),
    ("基准文件命名", ("tools/架构审查/检查基准文件.py",)),
    # static/ 一直没人管：手工版本号要同步五处、死样式躺着三处、后台页面一条 CSP 都没有。
    ("静态资源", ("tools/架构审查/检查静态资源.py",)),
    ("机械化棘轮", ("tools/机械化盘点.py",)),
)

#: 慢项：语料通道与历史数据审查。改数据、改渲染、改战斗时必须跑。
#: 名字里**不带条数**——条数写进名字就会漂（基准从 170 条长到 298 条时，名字还挂着 170）。
#: 实际条数由各工具自己那行输出给，单一出处。
SLOW: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("语料通道", ("tools/语料对照.py", "--对照", "tools/基准/语料摘要.sem")),
    ("语料行为通道", ("tools/语料对照.py", "--摘要", "行为",
                      "--对照", "tools/基准/语料行为摘要.sem")),
    ("战前状态通道", ("tools/战前状态对照.py",)),
    ("战场环境通道", ("tools/战场环境对照.py",)),
    ("阵法通道", ("tools/阵法对照.py",)),
    ("卡面正文通道", ("tools/渲染正文对照.py",)),
    ("查看页通道", ("tools/查看结果对照.py",)),
    ("战报通道", ("tools/战报对照.py",)),
    ("装配规划通道", ("tools/装配规划对照.py",)),
    ("交叉对局通道", ("tools/交叉对局对照.py",)),
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
