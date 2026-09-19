"""把 `data/` 里的引用与旧能力名一并清干净（定点迭代）。

## 为什么要迭代

能力改名（`增加状态层数` → `修改状态层数` 等）落在**数据**里只有 341 处，另外约 5,600
处藏在**模板主体的字符串**里。展开一次只会把外层引用换掉，模板主体里若还引用了别的
模板、或主体本身带着旧能力名，就得再展开再改一遍——所以要迭代到不动点：

    展开 → 改名 → 再展开 → 再改名 → … 直到两件事都不再发生

顺序不能颠倒成「先改名再展开」：改名只认 `能力` 字段，而引用节点没有 `能力` 键，
藏在未展开引用背后的旧名永远露不出来。

用法：

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/清旧能力名.py --落盘
"""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

import 构筑模板 as 模板  # noqa: E402
from game.core.combat import templates as 引擎  # noqa: E402
from game.core.combat.fold import TEMPLATE_KEY  # noqa: E402

#: 旧能力名 -> (新能力名, 方式)
改名 = {
    "增加状态层数": ("修改状态层数", "增加"),
    "消耗状态层数": ("修改状态层数", "减少"),
    "延长状态": ("修改状态持续", "增加"),
    "缩短状态": ("修改状态持续", "减少"),
}

最大轮数 = 12


def 改节点(node: object) -> int:
    改动 = 0
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return 0
        旧 = node.get("能力")
        if isinstance(旧, str) and 旧 in 改名:
            新, 方式 = 改名[旧]
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


def 还有旧名(node: object) -> bool:
    if isinstance(node, dict):
        值 = node.get("能力")
        if isinstance(值, str) and 值 in 改名:
            return True
        return any(还有旧名(v) for v in node.values())
    if isinstance(node, list):
        return any(还有旧名(v) for v in node)
    return False


def 引用数(node: object) -> int:
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return 1
        return sum(引用数(v) for v in node.values())
    if isinstance(node, list):
        return sum(引用数(v) for v in node)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--落盘", action="store_true")
    args = parser.parse_args()

    库 = importlib.import_module("game.core.combat.template_data").library()

    for 轮 in range(1, 最大轮数 + 1):
        改了 = 0
        展开了 = 0
        for 面, 配置 in 模板.SEGMENTS.items():
            for path in sorted(配置["目录"].glob(配置["模式"])):
                文档 = json.loads(path.read_text(encoding="utf-8"))
                条目表 = 文档 if isinstance(文档, list) else [文档]
                for 实体 in 条目表:
                    if not isinstance(实体, dict):
                        continue
                    if 引用数(实体):
                        引擎.expand_in_place(实体, 库)
                        展开了 += 1
                    改了 += 改节点(实体)
                if args.落盘 and (展开了 or 改了):
                    path.write_text(
                        json.dumps(文档, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        print(f"第 {轮} 轮：展开 {展开了} 条，改名 {改了} 处")
        if not 改了:
            break

    残留 = 0
    for 面, 配置 in 模板.SEGMENTS.items():
        for path in sorted(配置["目录"].glob(配置["模式"])):
            文档 = json.loads(path.read_text(encoding="utf-8"))
            for 实体 in (文档 if isinstance(文档, list) else [文档]):
                if isinstance(实体, dict) and 还有旧名(实体):
                    残留 += 1
    print(f"仍含旧能力名的实体：{残留}")
    if not args.落盘:
        print("（试运行，未写盘）")
    return 1 if 残留 else 0


if __name__ == "__main__":
    raise SystemExit(main())
