"""描述一致判据：渲染器**不许解释层兜底**。

渲染器（`game/core/combat/card_text.py`）是卡面正文的唯一来源。凡是**数据里没写、
渲染器自己补一个说法**的地方，都是「描述 ≠ 设计」：

| 种类 | 长什么样 | 数据那边该怎么补 |
| --- | --- | --- |
| `未支持` | `〈未支持：…〉` | 渲染器认不出的节点/字段，要么补渲染，要么改数据 |
| `兜底` | 正文照常读，但渲染器记了一笔（如 `兜底：裁定缺阈值`） | 回数据里把缺的那一段写出来 |
| `None` 泄漏 | 正文里出现 `None` | 缺字段，补上 |

引擎自己的**缺省**不算兜底——比如 `目标` 省略 = 当前目标、`方式` 省略 = 增加、
`技能.范围` 省略 = 全部技能。这些渲染器直接读引擎的同一份常量（`DEFAULT_TARGET_SCOPE`
这类），写出来的就是引擎会做的事。

**退出码：0 = 一个字都没兜底，1 = 有。**
"""

from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

# 共用库住在 tools/库/：脚本按文件运行时 sys.path[0] 是自己的目录，得手动加。
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[1] / "库"))

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from 全库扫描 import 全库文档  # noqa: E402
from game.core.combat.card_text import render_body, render_listeners  # noqa: E402
from 规则层 import load_rule_layer  # noqa: E402


def main() -> int:
    层 = load_rule_layer()
    实体数 = 0
    问题: list[tuple[str, str, str]] = []
    分类: collections.Counter = collections.Counter()
    for 相对, 文档 in 全库文档():
        条目 = 文档 if isinstance(文档, list) else [文档]
        for 实体 in 条目:
            if not isinstance(实体, dict) or not 实体.get("编号"):
                continue
            实体数 += 1
            行, 缺失 = render_body(实体, 层)
            if not 行:
                行, 缺失2 = render_listeners(实体, 层)
                缺失 = tuple(缺失) + tuple(缺失2)
            for 项 in 缺失:
                文本 = str(项)
                分类[文本.split("：", 1)[0]] += 1
                问题.append((相对, str(实体.get("编号")), 文本))
            for 行文 in 行:
                if "None" in 行文:
                    分类["None 泄漏"] += 1
                    问题.append((相对, str(实体.get("编号")), 行文[:80]))

    print(f"实体 {实体数} 个")
    print(f"描述与设计不一致 {len(问题)} 处")
    for 类, 次 in 分类.most_common():
        print(f"    {类} × {次}")
    for 相对, 编号, 文本 in 问题[:30]:
        print(f"    {相对} {编号} {文本}")
    return 1 if 问题 else 0


if __name__ == "__main__":
    raise SystemExit(main())
