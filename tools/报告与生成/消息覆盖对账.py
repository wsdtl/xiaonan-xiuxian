"""消息覆盖对账：哪些二级组件的页面真的被审计过。

零信息判据把所有能找到的页面都扫了一遍，但**它不是每个组件都扫得到**——同一个命令在
不同状态下会得到完全不同的页面，人物没入宗门、没进洞天、没走到丹师那儿，那几处组件就
只剩错误页。所以「判据是绿的」并不等于「每个组件都看过」。

本工具把判据那份语料按二级组件归类，报出：

- 每个组件有多少**真页面**、多少**错误页**；
- 一条真页面都没有的组件——那些就是还没被审计过的地方。

它是报告不是判据：不设通过线，退出码恒为 0。要看的是那张表里「真页面 0」的那几行。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/消息覆盖对账.py

**退出码：0 = 报告已出（不代表覆盖率达标）。**
"""

from __future__ import annotations

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# 判据住在 tools/架构审查/：借它的语料构建与清洗，避免两处各写一份。
if str(ROOT / "tools" / "架构审查") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "架构审查"))

import 检查消息零信息 as judge  # noqa: E402
from game.cmd.command import registered_commands  # noqa: E402

#: 页面里出现这些字样就说明拿到的是错误页，不是这个组件真正的展示。
ERROR_MARKERS = ("失败", "受阻", "尚未加入", "格式：")


def coverage() -> tuple[dict[str, tuple[int, int]], list[str]]:
    """返回（组件 -> (真页面, 错误页), 没有被审计的组件）。"""

    module_of = {
        word: module.replace("game.cmd.", "")
        for word, _scope, module in registered_commands()
    }
    pages, _ = judge._corpus()
    real: collections.Counter[str] = collections.Counter()
    error: collections.Counter[str] = collections.Counter()
    for text, body in pages.items():
        word = text.split(" ")[0]
        # 分支写法的第一个词是 A|B，不是注册过的命令词；它归多分支那一支。
        component = "通用.帮助.branches" if "|" in word else module_of.get(word, "(未知)")
        if any(marker in body for marker in ERROR_MARKERS):
            error[component] += 1
        else:
            real[component] += 1
    components = sorted(set(module_of.values()))
    uncovered = [item for item in components if real[item] == 0]
    return {item: (real[item], error[item]) for item in components}, uncovered


def main() -> int:
    table, uncovered = coverage()
    print("组件页面对账")
    print()
    print("  %-24s %8s %8s" % ("组件", "真页面", "错误页"))
    for component, (real, error) in table.items():
        mark = "  " if real else " <-"
        print("  %-24s %8d %8d%s" % (component, real, error, mark))
    print()
    total = len(table)
    if uncovered:
        print(f"共 {total} 个二级组件，其中 {len(uncovered)} 个一条真页面都没有：")
        for component in uncovered:
            print("  " + component)
        print()
        print("真页面 0 的组件说明它的页面还没被真正看过——要补的是这些组件的状态夹具。")
    else:
        print(f"共 {total} 个二级组件，每个都至少有一条真页面：没有没被看过的组件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
