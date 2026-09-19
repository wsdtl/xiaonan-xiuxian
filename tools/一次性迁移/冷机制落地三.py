"""冷机制落地（第三批）：复活 · 转移资源 · 重复执行 · 标签条件 · 移除战斗对象。

| 机制 | 落点 | 语义 |
| --- | --- | --- |
| `复活` | 劫丹 / 绝境 | 死里逃生：`死亡后` 把自己拉起来（血气 20%、精神 15%） |
| `转移资源` | 资源 / 同契 | 把自己的精神转给同袍 |
| `重复执行` | 合炼 | 多段炉火：把已有的一条小效果重复 3 次 |
| `标签条件` | 克制 | 只有这一下是**被分摊/被转移**的伤害时才反制（读事件标签） |
| `移除战斗对象` | 阵势（召唤丹） | 召回自己召来的灵体，换成一口治疗 |

`移除战斗对象` 的语义在 `mechanics.py:_ability_remove_object` 里：空 `对象ID` 时移除的是
**来源自己召来的**对象（`owner_id == source.id`），不是驱散对手的召唤物——所以只能配在
自带召唤的那枚丹上。

幂等：已经有这个机制就跳过。

    python tools/一次性迁移/冷机制落地三.py --试运行
    python tools/一次性迁移/冷机制落地三.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
PILLS = ROOT / "data/物品/炼丹/内容/丹药/战丹"


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


def has(entry: dict, ability: str) -> bool:
    return any(node.get("能力") == ability for node in nodes(entry.get("使用效果")))


def listeners(entry: dict) -> list[dict]:
    """返回**实体自己的那个列表**，不是副本。

    这里踩过一次静默失效：`list(...)` 复制之后往上 append 新监听，等于没写，
    而工具照样报"已写入"——只有把覆盖量再量一遍才发现计数没动。
    """

    raw = (entry.get("使用效果") or {}).get("监听")
    return raw if isinstance(raw, list) else []


def add_listener(entry: dict, event: str, effects: list[dict], **extra) -> bool:
    targets = listeners(entry)
    if not targets:
        return False
    node = {"能力": "监听事件", "事件": event, "观察角色": "承受者",
            "阵营关系": "自身", "效果": effects}
    node.update(extra)
    targets.append(node)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    rows = [(path, entry) for path in files for entry in documents[path]]
    touched: list[str] = []

    def theme_of(path: pathlib.Path) -> str:
        return path.stem.split("-")[1]

    def take(mechanism: str, wanted: tuple[str, ...], quota: int, build) -> None:
        done = 0
        for path, entry in rows:
            if done >= quota:
                break
            if theme_of(path) not in wanted or has(entry, mechanism):
                continue
            note = build(path, entry)
            if note:
                done += 1
                touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme_of(path)}) {note}")

    # 复活：死亡后把自己拉起来。
    take("复活", ("劫丹", "绝境"), 2,
         lambda path, entry: add_listener(
             entry, "死亡后",
             [{"能力": "复活",
               "目标": {"能力": "选择目标", "范围": "事件承受者", "生存状态": "死亡"},
               "血气百分比": 20, "精神百分比": 15}],
             **{"每场战斗最多触发": 1})
         and "补 复活（死亡后 20% 血气）")

    # 转移资源：把自己的精神转给同袍。
    take("转移资源", ("资源", "同契", "援护"), 2,
         lambda path, entry: add_listener(
             entry, "行动结束",
             [{"能力": "转移资源",
               "来源目标": self_target(),
               "接收目标": {"能力": "选择目标", "范围": "己方", "排除自身": True},
               "来源资源": "精神", "接收资源": "精神",
               "数值": own("精神上限", 12), "不足时是否失败": False}],
             **{"每次行动最多触发": 1})
         and "补 转移资源（把自己的精神转给同袍）")

    # 重复执行：把已有的一条小效果重复 3 次。
    take("重复执行", ("合炼",), 3,
         lambda path, entry: add_listener(
             entry, "行动结束",
             [{"能力": "重复执行", "次数": 3, "失败时停止": False,
               "效果": [{"能力": "恢复资源", "目标": self_target(), "资源": "血气",
                        "数值": own("血气上限", 3)}]}],
             **{"每次行动最多触发": 1})
         and "补 重复执行（三段炉火：3% 血气 ×3）")

    # 标签条件：只有这一下是被分摊/被转移的伤害时才反制。
    take("标签条件", ("克制",), 2,
         lambda path, entry: add_listener(
             entry, "受到伤害后",
             [{"能力": "恢复资源", "目标": self_target(), "资源": "血气",
               "数值": own("血气上限", 5)}],
             条件=[{"能力": "标签条件", "对象": "事件", "关系": "包含任一",
                  "标签": ["分摊", "转移"], "数量": 1}],
             **{"每场战斗最多触发": 2})
         and "补 标签条件（被分摊/转移的伤害才反制）")

    # 移除战斗对象：召回自己召来的灵体，换一口治疗（只配自带召唤的丹）。
    for path, entry in rows:
        if has(entry, "移除战斗对象") or not has(entry, "创建战斗对象"):
            continue
        if add_listener(entry, "行动结束",
                        [{"能力": "移除战斗对象"},
                         {"能力": "恢复资源", "目标": self_target(), "资源": "血气",
                          "数值": own("血气上限", 10)}],
                        **{"每次行动最多触发": 1}):
            touched.append(f"  {entry['编号']} {entry['名称']:<7}({theme_of(path)}) "
                           f"补 移除战斗对象（召回灵体换 10% 血气）")
            break

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
