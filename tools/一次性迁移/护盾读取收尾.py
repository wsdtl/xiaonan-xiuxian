"""护盾读取收尾：把两个空位来源 `自身当前护盾` / `目标当前护盾` 用起来。

审计里最后两块真空白：`读取数值.来源` 的选项表里有、但全库 0 次的两个来源——
`自身当前护盾` 与 `目标当前护盾`（"护盾还在时"这类判断一直没人写过，只写过"已损失护盾"）。

落点选本来就管护盾的两处：

- **器律-守御**（器物本体反应，护盾是它的本职）
- **战丹-阵势**（触发面就是 `护盾吸收后` / `护盾破碎后`）

写法：在已有监听的效果末尾追加一条**带条件的**效果——

    条件：数值条件  读取数值(来源=自身当前护盾 或 目标当前护盾)  大于 0
    效果：回一口精神 / 补一层护盾（`恢复资源` + `资源: 护盾`）

**哑弹风险**：条件读错来源不会报错、只会永不触发。所以挑的对象都要求监听时点本身与护盾相关
（`获得护盾前` / `获得护盾后` / `护盾吸收后` / `护盾破碎后`），这样"此刻有没有盾"是真变量；
跑完用 `语料对照.py` 看这些卡的摘要**有没有变化**——没变化说明这条效果一次都没触发。

    python tools/一次性迁移/护盾读取收尾.py --试运行
    python tools/一次性迁移/护盾读取收尾.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"
LAWS = ROOT / "data/物品/炼器/内容"
#: 门槛是"此刻还有盾"，所以只能在**盾还在**的时点挂：`护盾破碎后` 挂上去必然永远不成立
#: （盾都破了），那是哑弹。破碎时点要用反向条件，本工具不做。
SHIELD_EVENTS = {"获得护盾前", "获得护盾后", "护盾吸收后"}


def nodes(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from nodes(value)
    elif isinstance(node, list):
        for value in node:
            yield from nodes(value)


def self_target() -> dict:
    return {"能力": "选择目标", "范围": "自身"}


def own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def shield_gate(origin: str) -> dict:
    """此刻还有盾（`自身当前护盾` / `目标当前护盾` > 0）。"""

    return {"能力": "数值条件",
            "左值": {"能力": "读取数值", "来源": origin},
            "比较": "大于", "右值": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    touched: list[str] = []

    # 一、器律-守御：器物自己身上还有盾时，多回一口精神。
    path = LAWS / "器律-守御.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    done = 0
    for entry in document:
        if done >= 4:
            break
        raw = (entry.get("能力") or [{}])[0]
        slots = [node for node in nodes(raw) if node.get("能力") == "监听事件"]
        slot = next((node for node in slots if str(node.get("事件")) in SHIELD_EVENTS), None)
        if slot is None:
            continue
        slot["效果"].append({"能力": "恢复资源", "目标": self_target(), "资源": "精神",
                            "数值": own("精神上限", 5)})
        slot.setdefault("条件", []).append(shield_gate("自身当前护盾"))
        done += 1
        touched.append(f"  {entry['编号']} {entry['名称']:<7}(器律-守御) 护盾还在时多回 5% 精神"
                       f"（读 自身当前护盾，挂在 {slot.get('事件')}）")
    if not args.试运行:
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    # 二、战丹-阵势：对面还有盾时，这一下额外补自己一层盾（读 目标当前护盾）。
    path = PILLS / "战丹-阵势.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    done = 0
    for entry in document:
        if done >= 4:
            break
        slot = next((node for node in nodes(entry.get("使用效果"))
                     if node.get("能力") == "监听事件"
                     and str(node.get("事件")) in SHIELD_EVENTS), None)
        if slot is None:
            continue
        slot["效果"].append({"能力": "恢复资源", "目标": self_target(), "资源": "护盾",
                            "数值": own("血气上限", 8)})
        slot.setdefault("条件", []).append(shield_gate("目标当前护盾"))
        done += 1
        touched.append(f"  {entry['编号']} {entry['名称']:<7}(战丹-阵势) 对面还有盾时额外补 8% 护盾"
                       f"（读 目标当前护盾，挂在 {slot.get('事件')}）")
    if not args.试运行:
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")

    print(f"落点 {len(touched)} 处")
    for line in touched:
        print(line)
    if args.试运行:
        print("\n（试运行，未落盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
