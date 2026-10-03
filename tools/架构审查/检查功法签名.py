"""功法签名判据：反对"同一张卡换数字"。

病根不是数值不平衡，而是**大量卡共用同一个效果骨架**——把层数、百分比、冷却三件套
排列组合一遍就算一张新卡。这条判据把"骨架"抽出来（**忽略所有数值参数**），
指纹相同的卡就是"同一张卡换数字"，一律点出来。

指纹怎么算：把效果树归一化成模板调用的**嵌套结构**，丢掉参数里的数字与文案，
只保留：模板编号 + 嵌套形状（顺序执行 / 条件执行 / 遍历目标 之类）。

跑法：`python -X utf8 tools/架构审查/检查功法签名.py`
输出：同形组清单（重组在前）+ 每族指纹数与族配额。
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARTS = ROOT / "data" / "战斗" / "内容" / "功法"

#: 单族占比上限（防止换个名字又变成一窝蜂）。
FAMILY_QUOTA = 0.20


def fingerprint(node: object) -> str:
    """效果树的骨架指纹：模板编号 + 嵌套形状，**不含任何数值**。"""

    if isinstance(node, dict):
        if isinstance(node.get("模板"), str):
            inner = [fingerprint(v) for k, v in sorted(node.items()) if k not in ("模板", "参数")]
            return f"T({node['模板']})[{'+'.join(x for x in inner if x)}]"
        parts = [f"{k}={fingerprint(v)}" for k, v in sorted(node.items()) if v is not None]
        return "{" + ",".join(x for x in parts if not x.endswith("=None")) + "}"
    if isinstance(node, list):
        return "[" + ",".join(fingerprint(v) for v in node) + "]"
    if isinstance(node, (int, float, bool)) or node is None:
        return ""
    return ""     # 文案与数字一律不进指纹


def cards() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for path in sorted(ARTS.rglob("*.json")):
        family = path.stem.replace("功法-", "")
        value = json.loads(path.read_text(encoding="utf-8"))
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, dict):
                found.append((family, item))
    return found


def main() -> int:
    组 = collections.defaultdict(list)
    for family, card in cards():
        组[fingerprint(card.get("能力"))].append((family, str(card.get("名称"))))
    总 = sum(len(v) for v in 组.values())
    同形 = {k: v for k, v in 组.items() if len(v) > 1}
    同形卡数 = sum(len(v) for v in 同形.values())
    print(f"功法 {总} 张 ｜ 不同骨架 {len(组)} 种 ｜ 同形组 {len(同形)} 组、涉及 {同形卡数} 张")
    print("=== 最大的同形组（前 12 组：同一张卡换数字）")
    for names in sorted(同形.values(), key=len, reverse=True)[:12]:
        print(f"   {len(names)} 张：{'、'.join(n for _, n in names[:5])}")
    族 = collections.Counter(f for f, _ in cards())
    print("=== 各族规模与骨架多样性")
    for name, count in 族.most_common():
        该族 = [k for k, v in 组.items() if any(f == name for f, _ in v)]
        print(f"   {name:<8} 卡 {count:>3}（{count / 总 * 100:>4.1f}%）｜ 骨架 {len(该族):>3} 种")
    最大 = 族.most_common(1)[0]
    ok = 最大[1] / 总 <= FAMILY_QUOTA
    print(
        f"[{'通过' if ok else '失败'}] 族配额：最大族 {最大[0]} {最大[1]} 张"
        f"（{最大[1] / 总 * 100:.1f}%，上限 {FAMILY_QUOTA * 100:.0f}%）"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

