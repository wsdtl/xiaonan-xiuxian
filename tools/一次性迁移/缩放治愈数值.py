"""把「治愈/护盾数值」按 1/4 写进数据，取消全局总闸后的强度对齐。

## 为什么

原来 `伤害.json` 里有一个全局 `恢复倍率: 25`，只闸**血气与护盾**的恢复量。那一层现在
删了（用户口径：强度由卡面数值自己决定，不要全局常数），于是同一条恢复比改动前强 4 倍。

补法是把这个 1/4 **写进每个数值本身**：

    恢复量 = 数值 × (治疗效果/100=1.0) × (1+治疗加成/100) × (1+受疗加成/100)

只缩「数值」与它同层的「百分比」（那都是量），**不缩** `最高值` / `最低值`（那是封顶与
下限护栏，不是强度）。

## 缩哪些

* `恢复资源` 的 `数值`：资源已知且是 **血气 / 护盾** 才缩。`精神` 不缩（不设闸），
  资源写成参数占位（不知道是什么）也不缩。
* `读取数值` 形态的 `数值`：缩它自己的 `百分比`。
* `转移资源` / `设置资源` 的 `数值`：资源是 血气/护盾 才缩。

## 跑在哪一步

跑在 `重建数据与库.py` 的「展开成原文」之后、`建库` 之前。**库是从数据生成的**，所以
只缩数据一次，库的主体自然也就是缩过的——不必单独去改 `template_data.py`。

不幂等（会一直缩下去），由管线每次从提交原文重跑保证只执行一次。
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

#: 缩放比例：与删掉的全局 `恢复倍率: 25` 一致。
比例 = 0.25

#: 需要缩放的资源。`精神` 不在内——它是出手预算，不设闸。
受闸资源 = ("血气", "护盾")


def _资源名(node: dict):
    资源 = node.get("资源")
    return 资源 if isinstance(资源, str) else None


def 缩节点(node: object) -> int:
    改动 = 0
    if isinstance(node, dict):
        if TEMPLATE_KEY in node:
            return 0
        能力 = node.get("能力")
        if 能力 == "恢复资源" and _资源名(node) in 受闸资源:
            数值 = node.get("数值")
            if isinstance(数值, (int, float)) and not isinstance(数值, bool):
                node["数值"] = 数值 * 比例
                改动 += 1
            elif isinstance(数值, dict) and isinstance(数值.get("百分比"), (int, float)):
                数值["百分比"] = 数值["百分比"] * 比例
                改动 += 1
        elif 能力 in ("转移资源", "设置资源") and _资源名(node) in 受闸资源:
            数值 = node.get("数值")
            if isinstance(数值, (int, float)) and not isinstance(数值, bool):
                node["数值"] = 数值 * 比例
                改动 += 1
        for v in node.values():
            改动 += 缩节点(v)
    elif isinstance(node, list):
        for v in node:
            改动 += 缩节点(v)
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
            改动 = sum(缩节点(e) for e in 条目表 if isinstance(e, dict))
            if not 改动:
                continue
            总 += 改动
            文件数 += 1
            if args.落盘:
                path.write_text(
                    json.dumps(文档, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
    print(f"缩放 {总} 处治愈/护盾数值（×{比例}），涉及 {文件数} 个文件")
    if not args.落盘:
        print("（试运行，未写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
