"""冷机制落地（第四批）：修改战术 · 修改归属 · 复制技能 · 转化事件。

| 机制 | 落点 | 语义 |
| --- | --- | --- |
| `修改战术` | 天机 | 改出手选择：技能优先打血气比例最低的 |
| `修改归属` | 克制 | 策反：把对面的召唤物改成己方阵营 |
| `复制技能` | 天机 | 偷学：把事件来源正在施放的技能抄给自己 |
| `转化事件` | 克制 / 天机 | 只在**当前事件允许改写**时才挂——白名单在 `战斗/定义/事件.json` 的 `可修改` 里，工具自己查，不在名单里就跳过 |

幂等：已经有这个机制就跳过。挂载点按机制挑监听（`复制技能` 要挂在技能事件上）。

    python tools/冷机制落地四.py --试运行
    python tools/冷机制落地四.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
PILLS = ROOT / "data/炼丹/内容/丹药/战丹"
EVENTS = ROOT / "data/战斗/定义/事件.json"
SKILL_EVENTS = {"技能施放前", "技能施放后", "技能变化后", "技能冷却变化后"}


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


def writable_events() -> dict[str, set[str]]:
    raw = json.loads(EVENTS.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for name, spec in raw.items():
        if isinstance(spec, dict):
            out[str(name)] = {str(item) for item in (spec.get("可修改") or ())}
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    rows = [(path, entry) for path in files for entry in documents[path]]
    writable = writable_events()
    touched: list[str] = []

    def theme(path: pathlib.Path) -> str:
        return path.stem.split("-")[1]

    def attach(path, entry, kind: str, node: dict, *, on: set[str] | None = None) -> bool:
        slots = listeners(entry)
        if on is not None:
            slots = [item for item in slots if str(item.get("事件")) in on]
        if not slots:
            return False
        slots[0]["效果"].append(node)
        touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme(path)}) {kind}"
                       f"（挂在 {slots[0].get('事件')}）")
        return True

    def take(mechanism: str, themes: tuple[str, ...], quota: int, build,
             on: set[str] | None = None) -> None:
        done = 0
        for path, entry in rows:
            if done >= quota:
                break
            if theme(path) not in themes or has(entry, mechanism):
                continue
            if build(path, entry, on):
                done += 1

    # 修改战术：技能优先打血气比例最低的。
    take("修改战术", ("天机",), 2, lambda path, entry, on: attach(
        path, entry, "补 修改战术（技能优先打血气最低的）",
        {"能力": "修改战术", "目标": self_target(), "方式": "替换",
         "战术": [{"行动": "技能", "目标排序": "血气比例从低到高"}]}))

    # 修改归属：把对面的召唤物改成己方阵营。
    take("修改归属", ("克制", "天机"), 2, lambda path, entry, on: attach(
        path, entry, "补 修改归属（策反对面的召唤物）",
        {"能力": "修改归属",
         "目标": {"能力": "选择目标", "范围": "敌方", "对象类型": "任意"},
         "字段": "阵营", "阵营": "己方"},
        on={"造成伤害前", "受到伤害后", "行动结束", "击杀后", "添加状态后"}))

    # 复制技能：抄下事件来源正在施放的那一招。
    take("复制技能", ("天机", "合炼"), 2, lambda path, entry, on: attach(
        path, entry, "补 复制技能（抄下对手这一招）",
        {"能力": "复制技能",
         "来源目标": {"能力": "选择目标", "范围": "事件来源"},
         "接收目标": self_target(),
         "技能": {"能力": "选择技能", "范围": "当前技能"},
         "名称": f"{str(entry['名称'])[:2]}习诀"},
        on=SKILL_EVENTS))

    # 转化事件：只在当前事件允许改写时才挂。
    done = 0
    for path, entry in rows:
        if done >= 3 or has(entry, "转化事件"):
            continue
        slot = next((item for item in listeners(entry)
                     if "转化事件" in writable.get(str(item.get("事件")), set())), None)
        if slot is None:
            continue
        target = "恢复前" if "恢复" in str(slot.get("事件")) else next(
            iter(sorted(writable[str(slot.get("事件"))])), "")
        if not target:
            continue
        slot["效果"].append({"能力": "转化事件", "事件": target})
        touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme(path)}) "
                       f"补 转化事件（{slot.get('事件')} → {target}）")
        done += 1

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
