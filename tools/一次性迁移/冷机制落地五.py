"""冷机制落地（第五批）：把四个最冷的推到 20 档。

审计读数（第四批之后）：`随机数值` 6 · `组合条件` 7 · `缩短状态` 11 · `转移伤害` 19。
本批各补一段，目标是都进 20~25 档。

| 机制 | 补法 | 挂载锁 |
| --- | --- | --- |
| `随机数值` | 天机 / 劫丹 / 应变：回一口是多是少掷出来（血气 5~20、精神 4~14、行动条 6~18） | 无锁，挂第一条监听 |
| `组合条件` | 各药性：把单条件升成双门槛（本次数值 >0 **且** 自身血气已损失 ≥30%） | 无锁，写进监听的 `条件` |
| `缩短状态` | 克制 / 控制 / 天机：缩短当前目标的正面状态；克制药性再补一条缩短自身负面 | 无锁 |
| `转移伤害` | 剩下的援护 / 同契 / 合炼：队友这一下转到我身上 | **只能在 `造成伤害前` / `受到致命伤害`** |

幂等：已经有这个机制就跳过；`转移伤害` 找不到合法监听也跳过（不硬塞）。

    python tools/一次性迁移/冷机制落地五.py --试运行
    python tools/一次性迁移/冷机制落地五.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"
DAMAGE_EVENTS = {"造成伤害前", "受到致命伤害"}
PARTY = {"援护", "同契", "合炼"}


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


def listeners(entry: dict) -> list[dict]:
    raw = (entry.get("使用效果") or {}).get("监听")
    return raw if isinstance(raw, list) else []


def has(entry: dict, ability: str) -> bool:
    return any(node.get("能力") == ability for node in nodes(entry.get("使用效果")))


def chance_gain(resource: str, low: int, high: int) -> dict:
    # `修改行动条.数值` 是**纯数字**字段，不接数值节点（塞进去真实对局抛
    # `TypeError: float() argument must be ... not 'dict'`），所以行动条不做随机版。
    attribute = "血气上限" if resource == "血气" else "精神上限"
    base = {"能力": "读取数值", "来源": "自身属性", "属性": attribute}
    return {"能力": "恢复资源", "目标": self_target(), "资源": resource,
            "数值": {"能力": "计算数值", "方式": "相乘", "左值": base,
                     "右值": {"能力": "计算数值", "方式": "相除",
                              "左值": {"能力": "随机数值", "最低值": low,
                                       "最高值": high, "取整": True},
                              "右值": 100}}}


def shorten(category: str) -> dict:
    scope = "当前目标" if category == "正面" else "自身"
    return {"能力": "缩短状态",
            "状态": {"能力": "选择状态",
                     "目标": {"能力": "选择目标", "范围": scope},
                     "分类": category, "排序": "剩余行动从多到少"},
            "持续数值": 2, "方式": "减少"}


def double_gate() -> list[dict]:
    return [{"能力": "组合条件", "关系": "全部成立",
             "条件": [{"能力": "数值条件",
                       "左值": {"能力": "读取数值", "来源": "本次数值"},
                       "比较": "大于", "右值": 0},
                      {"能力": "数值条件",
                       "左值": {"能力": "读取数值", "来源": "自身已损失血气"},
                       "比较": "大于等于",
                       "右值": {"能力": "读取数值", "来源": "自身属性",
                                "属性": "血气上限", "百分比": 30}}]}]


def primary_attack() -> dict:
    """这一下打给队友的伤害，转到我身上。"""

    return {"能力": "转移伤害", "目标": self_target(),
            "数值": {"能力": "读取数值", "来源": "本次数值", "百分比": 100}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    rows = [(path, entry) for path in files for entry in documents[path]]
    touched: list[str] = []

    def theme(path: pathlib.Path) -> str:
        return path.stem.split("-")[1]

    def first_slot(entry: dict, on: set[str] | None = None) -> dict | None:
        slots = listeners(entry)
        if on is not None:
            slots = [item for item in slots if str(item.get("事件")) in on]
        return slots[0] if slots else None

    def repair() -> int:
        """摘掉 `修改行动条` 里塞了数值节点的写法（纯数字字段，塞节点会抛错）。"""

        fixed = 0
        for _path, entry in rows:
            for node in nodes(entry.get("使用效果")):
                if node.get("能力") == "修改行动条" and isinstance(node.get("数值"), dict):
                    node["数值"] = 12
                    fixed += 1
        return fixed

    fixed = repair()
    if fixed:
        print(f"修复 修改行动条 的非法数值 {fixed} 处")

    def take(mechanism: str, quota: int, build, themes: tuple[str, ...] = (),
             on: set[str] | None = None) -> None:
        done = 0
        for path, entry in rows:
            if done >= quota:
                break
            if theme(path) == "基础" or has(entry, mechanism):
                continue
            if themes and theme(path) not in themes:
                continue
            slot = first_slot(entry, on)
            if slot is None:
                continue
            if build(path, entry, slot):
                done += 1

    def note(path, entry, slot, text: str) -> bool:
        touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme(path)}) {text}"
                       f"（挂在 {slot.get('事件')}）")
        return True

    # 随机数值：三种资源各来几枚。
    plan = [("血气", 5, 20), ("精神", 4, 14), ("血气", 8, 16)]
    counters = {"随机数值": 0}
    for path, entry in rows:
        if counters["随机数值"] >= 9:
            break
        if theme(path) in {"基础"} or has(entry, "随机数值"):
            continue
        if theme(path) not in {"天机", "劫丹", "应变", "绝境"}:
            continue
        resource, low, high = plan[counters["随机数值"] % len(plan)]
        slot = first_slot(entry)
        if slot is None:
            continue
        slot["效果"].append(chance_gain(resource, low, high))
        counters["随机数值"] += 1
        note(path, entry, slot, f"补 随机数值（{resource} {low}~{high}）")

    # 组合条件：单条件升成双门槛。
    take("组合条件", 8, lambda path, entry, slot: (
        slot.__setitem__("条件", double_gate())
        or note(path, entry, slot, "补 组合条件（本次数值 >0 且已损失 ≥30%）")))

    # 缩短状态：目标正面 + 自身负面。
    shorten_done = 0
    for path, entry in rows:
        if shorten_done >= 8 or has(entry, "缩短状态") or theme(path) == "基础":
            continue
        slot = first_slot(entry)
        if slot is None:
            continue
        if theme(path) in {"克制", "控制"}:
            slot["效果"].append(shorten("负面"))
            note(path, entry, slot, "补 缩短状态（缩短自身负面）")
        elif theme(path) in {"天机", "攻伐", "阵势"}:
            slot["效果"].append(shorten("正面"))
            note(path, entry, slot, "补 缩短状态（缩短目标正面）")
        else:
            continue
        shorten_done += 1

    # 转移伤害：只挂伤害事件监听。
    take("转移伤害", 5, lambda path, entry, slot: (
        slot["效果"].append(primary_attack())
        or note(path, entry, slot, "补 转移伤害（这一下转到我身上）")),
        themes=tuple(PARTY), on=DAMAGE_EVENTS)

    print(f"落点 {len(touched)} 枚")
    for line in touched:
        print(line)
    if args.试运行:
        print("\n（试运行，未落盘）")
        return 0

    for path, document in documents.items():
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\n已写入 {len(documents)} 个战丹文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
