"""把 `增加状态层数` / `消耗状态层数` / `延长状态` / `缩短状态` 并成两个能力。

> **已被 `合并原子能力.py` 取代，只作留档，别再跑。** 这里是最早那一版：只改数据里
> 的节点，碰到带模板编号的引用节点就绕开（`if TEMPLATE_KEY in node: return 0`），
> 所以模板主体里那约 5,600 处旧名要靠 `清旧能力名.py` 迭代展开补齐；也不写原子能力
> 定义、不同步生成模块。`合并原子能力.py` 把这些一并做完了。

## 为什么并

一个动作被拆成两个能力名，执行器再靠**自己的名字**去猜方向：

    增加状态层数  ->  执行器 修改状态层数
    消耗状态层数  ->  执行器 修改状态层数     ← 同一个执行器
    延长状态      ->  执行器 修改状态持续
    缩短状态      ->  执行器 修改状态持续     ← 同一个执行器

于是运行时要三套机制表达「加还是减」：`方式` 字段、`consume=` 开关、`effect.get("数值")`
字段名兜底。合并之后一个动作一个名字、一个执行器、一个方向来源（`方式` 字段）。

## 约定

* `增加状态层数` → `修改状态层数`，`方式: "增加"`
* `消耗状态层数` → `修改状态层数`，`方式: "减少"`
* `延长状态`     → `修改状态持续`，`方式: "增加"`
* `缩短状态`     → `修改状态持续`，`方式: "减少"`

`方式` 写在**能力名之后**的位置，保持原有键序（渲染按插入顺序输出）。原数据里没有
`方式` 的节点（实测 `增加状态层数` 2069 处全都没有、`消耗状态层数` 有 11 处没有）
由本工具补上，方向按原能力名决定。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/合并状态能力.py --落盘
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402
from game.core.combat.fold import TEMPLATE_KEY  # noqa: E402

#: 旧能力名 -> (新能力名, 方式)
改名 = {
    "增加状态层数": ("修改状态层数", "增加"),
    "消耗状态层数": ("修改状态层数", "减少"),
    "延长状态": ("修改状态持续", "增加"),
    "缩短状态": ("修改状态持续", "减少"),
}


def 改节点(node: object) -> int:
    """递归改名。返回改动的节点数。"""

    改动 = 0
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return 0
        旧 = node.get("能力")
        if isinstance(旧, str) and 旧 in 改名:
            新, 方式 = 改名[旧]
            # 保持键序：把 `能力` 的值换掉，`方式` 紧跟其后插入（原数据里 `方式`
            # 在 `层数` 之后，这里统一到 `能力` 之后，渲染时方向先读）。
            重建: dict = {}
            for 键, 值 in node.items():
                if 键 == "能力":
                    重建["能力"] = 新
                    重建.setdefault("方式", node.get("方式", 方式))
                    continue
                if 键 == "方式":
                    continue
                重建[键] = 值
            node.clear()
            node.update(重建)
            改动 += 1
        改动 += sum(改节点(v) for v in node.values())
    elif isinstance(node, list):
        改动 += sum(改节点(v) for v in node)
    return 改动


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--落盘", action="store_true")
    args = parser.parse_args()

    总 = 0
    文件数 = 0
    for 面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            条目表 = 文档 if isinstance(文档, list) else [文档]
            改动 = sum(改节点(e) for e in 条目表 if isinstance(e, dict))
            if not 改动:
                continue
            总 += 改动
            文件数 += 1
            if args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
    print(f"改名 {总} 个节点，涉及 {文件数} 个文件")
    if not args.落盘:
        print("（试运行，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
