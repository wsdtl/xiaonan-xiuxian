"""冷机制落地（第六批）：把 ≤30 档再抬一层。

第五批之后的读数：`转移伤害` 19（≤20 只剩它）· `分摊伤害` 21 · `移除战斗对象` 23 ·
`标签条件` 25 · `复活` 26 · `转移资源` 27。本批各补一点，目标是**没有 ≤20 的机制**。

挂载锁照旧（写错只在真实对局里炸）：

- `转移伤害` → 只能挂 `造成伤害前` / `受到致命伤害`
- `分摊伤害` → 只能挂 `造成伤害前`
- `复活` → `死亡后`
- 其余无锁，挂第一条监听

幂等；找不到合法监听就跳过，不硬塞。

    python tools/冷机制落地六.py --试运行
    python tools/冷机制落地六.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
PILLS = ROOT / "data/炼丹/内容/丹药/战丹"
DAMAGE_EVENTS = {"造成伤害前", "受到致命伤害"}
SHARE_EVENTS = {"造成伤害前"}
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


def own(attribute: str, percent: int) -> dict:
    return {"能力": "读取数值", "来源": "自身属性", "属性": attribute,
            "百分比": percent, "最低值": 1}


def listeners(entry: dict) -> list[dict]:
    raw = (entry.get("使用效果") or {}).get("监听")
    return raw if isinstance(raw, list) else []


def has(entry: dict, ability: str) -> bool:
    return any(node.get("能力") == ability for node in nodes(entry.get("使用效果")))


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

    def slot_of(entry: dict, on: set[str] | None = None, event: str | None = None) -> dict | None:
        slots = listeners(entry)
        if on is not None:
            slots = [item for item in slots if str(item.get("事件")) in on]
        if event is not None:
            slots = [item for item in slots if str(item.get("事件")) == event]
            if not slots:
                slot = {"能力": "监听事件", "事件": event, "观察角色": "承受者",
                        "阵营关系": "自身", "效果": [],
                        "每场战斗最多触发": 1}
                if not listeners(entry):
                    return None
                listeners(entry).append(slot)
                return slot
        return slots[0] if slots else None

    def take(mechanism: str, quota: int, themes: tuple[str, ...], build,
             on: set[str] | None = None, event: str | None = None) -> None:
        done = 0
        for path, entry in rows:
            if done >= quota:
                break
            if theme(path) == "基础" or has(entry, mechanism) or theme(path) not in themes:
                continue
            slot = slot_of(entry, on, event)
            if slot is None:
                continue
            text = build(slot)
            if text:
                done += 1
                touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme(path)}) {text}"
                               f"（挂在 {slot.get('事件')}）")

    take("转移伤害", 6, tuple(PARTY), lambda slot: (
        slot["效果"].append({"能力": "转移伤害", "目标": self_target(),
                            "数值": {"能力": "读取数值", "来源": "本次数值",
                                     "百分比": 100}})
        or "补 转移伤害（这一下转到我身上）"), on=DAMAGE_EVENTS)

    take("分摊伤害", 4, tuple(PARTY), lambda slot: (
        slot["效果"].append({"能力": "分摊伤害",
                            "目标": {"能力": "选择目标", "范围": "己方",
                                     "排除自身": True, "选择全部": True},
                            "比例": 40})
        or "补 分摊伤害（全队分摊）"), on=SHARE_EVENTS)

    take("标签条件", 3, ("克制", "天机"), lambda slot: (
        slot.__setitem__("条件", [{"能力": "标签条件", "对象": "事件",
                                 "关系": "包含任一", "标签": ["分摊", "转移"],
                                 "数量": 1}])
        or "补 标签条件（被分摊/转移的伤害才反制）"))

    take("复活", 3, ("劫丹", "绝境"), lambda slot: (
        slot["效果"].append({"能力": "复活",
                            "目标": {"能力": "选择目标", "范围": "事件承受者",
                                     "生存状态": "死亡"},
                            "血气百分比": 18, "精神百分比": 12})
        or "补 复活（死亡后 18% 血气）"), event="死亡后")

    take("转移资源", 3, ("资源", "同契", "援护"), lambda slot: (
        slot["效果"].append({"能力": "转移资源", "来源目标": self_target(),
                            "接收目标": {"能力": "选择目标", "范围": "己方",
                                         "排除自身": True},
                            "来源资源": "精神", "接收资源": "精神",
                            "数值": own("精神上限", 10), "不足时是否失败": False})
        or "补 转移资源（把自己的精神转给同袍）"))

    take("修改归属", 2, ("克制", "天机"), lambda slot: (
        slot["效果"].append({"能力": "修改归属",
                            "目标": {"能力": "选择目标", "范围": "敌方",
                                     "对象类型": "任意"},
                            "字段": "阵营", "阵营": "己方"})
        or "补 修改归属（策反对面的召唤物）"))

    take("修改战术", 3, ("天机", "劫丹"), lambda slot: (
        slot["效果"].append({"能力": "修改战术", "目标": self_target(),
                            "方式": "替换",
                            "战术": [{"行动": "技能",
                                      "目标排序": "血气比例从低到高"}]})
        or "补 修改战术（技能优先打血气最低的）"))

    print(f"落点 {len(touched)} 枚")
    for line in touched[:8]:
        print(line)
    if len(touched) > 8:
        print(f"  …… 其余 {len(touched) - 8} 枚")
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
