"""冷机制落地（第二批）：转移伤害 · 分摊伤害 · 聚合数值 · 状态条件。

第一批把 `随机数值`（0 次）· `缩短状态`（5）· `组合条件`（3）用掉了，本批接最冷的四个：

| 机制 | 落点 | 语义 | 事件锁 |
| --- | --- | --- | --- |
| `转移伤害` | 援护 / 同契 里监听 `造成伤害前` 的丹 | 队友这一下，转到我身上 | **只能在伤害事件监听里执行**（`mechanics.py` 只认 `造成伤害前` / `受到致命伤害`） |
| `分摊伤害` | 同上的丹 | 这一下由全队分摊 | 同上（只认 `造成伤害前`） |
| `聚合数值` | 同契 / 援护 | 按队伍人数放大——人多回得多 | 无锁 |
| `状态条件` | 克制 / 天机 | 自己攒的印记够层数才发作 | 只能引用**本卡自己定义**的状态名 |

工具是幂等的：某枚丹已经有这个机制就跳过，重复跑不会叠加。

用法：

    python tools/冷机制落地二.py --试运行
    python tools/冷机制落地二.py
"""

from __future__ import annotations

import argparse
import json
import pathlib

ROOT = pathlib.Path(r"C:\Users\DengXiaonan\Desktop\晓楠修仙")
PILLS = ROOT / "data/炼丹/内容/丹药/战丹"
DAMAGE_EVENTS = {"造成伤害前", "受到致命伤害"}
#: `分摊伤害` 只认 `造成伤害前`（`mechanics.py` 里写死），`转移伤害` 才多认致命伤害。
SHARE_EVENTS = {"造成伤害前"}
PARTY_THEMES = {"援护", "同契", "合炼"}


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
    """返回**实体自己的那个列表**，不是副本。

    这里踩过一次静默失效：`list(...)` 复制之后往上 append 新监听，等于没写，
    而工具照样报"已写入"——只有把覆盖量再量一遍才发现计数没动。
    """

    raw = (entry.get("使用效果") or {}).get("监听")
    return raw if isinstance(raw, list) else []


def has(entry: dict, ability: str) -> bool:
    return any(node.get("能力") == ability for node in nodes(entry.get("使用效果")))


def on_damage(entry: dict) -> bool:
    return any(str(node.get("事件")) in DAMAGE_EVENTS for node in listeners(entry))


def transfer_self() -> dict:
    """这一下打给事件承受者的伤害，转到我身上。"""

    return {"能力": "转移伤害", "目标": self_target(),
            "数值": {"能力": "读取数值", "来源": "本次数值", "百分比": 100}}


def share_team(ratio: int) -> dict:
    return {"能力": "分摊伤害",
            "目标": {"能力": "选择目标", "范围": "己方",
                     "排除自身": True, "选择全部": True},
            "比例": ratio}


def party_scaled(attribute: str, percent: int) -> dict:
    """按己方人数放大的一份恢复/护盾。"""

    return {"能力": "恢复资源", "目标": {"能力": "选择目标", "范围": "己方"},
            "资源": attribute,
            "数值": {"能力": "计算数值", "方式": "相乘",
                     "左值": {"能力": "读取数值", "来源": "自身属性",
                              "属性": "血气上限" if attribute != "精神" else "精神上限",
                              "百分比": percent, "最低值": 1},
                     "右值": {"能力": "聚合数值",
                              "目标": {"能力": "选择目标", "范围": "己方", "选择全部": True},
                              "方式": "数量"}}}


def gate(entry: dict) -> tuple[dict, str] | tuple[None, str]:
    """攒够自己的印记才发作。

    门槛必须读**本卡自己 `添加状态` 定义的状态名**（跨实体引用别人的名字是违规的）。
    也别拿 `战前状态` 当门槛：那东西一开始就在、层数固定 1，`层数至少 2` 永远不成立，
    会变成不报错的哑弹。没有自己定义的标记状态就跳过这枚。
    """

    for node in nodes(entry.get("使用效果")):
        if node.get("能力") == "添加状态" and isinstance(node.get("状态"), dict):
            name = str(node["状态"].get("名称") or "")
            if name:
                return ({"能力": "状态条件", "目标": self_target(), "状态": name,
                         "比较": "存在", "层数": 1}, name)
    return None, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--试运行", action="store_true")
    args = parser.parse_args()

    files = sorted(PILLS.glob("*.json"))
    documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in files}
    rows: list[tuple[pathlib.Path, dict]] = [
        (path, entry) for path in files for entry in documents[path]]

    touched: list[str] = []

    def apply(path, entry, kind: str, node: dict, *, second: bool = False,
              need_event: set[str] | None = None) -> None:
        targets = listeners(entry)
        if not targets:
            return
        if need_event is not None:
            # 分摊/转移伤害只能在伤害事件里执行：必须挂到**那条**监听上。
            # 第一版挂到了第一条监听（`受到伤害后`），真实对局直接抛
            # `ValueError: 当前事件不是造成伤害前`。
            slots = [item for item in targets if str(item.get("事件")) in need_event]
            if not slots:
                return
            slots[0]["效果"].append(node)
            kind = f"{kind}（挂在 {slots[0].get('事件')}）"
        elif second:
            condition, name = gate(entry)
            if condition is None:
                return
            event = "行动结束" if not any(str(n.get("事件")) == "行动结束" for n in targets) else "行动开始"
            targets.append({"能力": "监听事件", "事件": event, "观察角色": "行动者",
                            "阵营关系": "自身",
                            "条件": [condition], "效果": [node],
                            "每次行动最多触发": 1})
            kind = f"{kind}，门槛={name}"
        else:
            targets[0]["效果"].append(node)
        touched.append(f"  {entry['编号']} {entry['名称']:<7}({path.stem[3:]}) 补 {kind}")

    def repair(entry: dict) -> list[str]:
        """摘掉挂错监听的伤害机制（挂在不属于伤害事件的监听里，一跑就抛错）。"""

        fixed: list[str] = []
        for listener in listeners(entry):
            event = str(listener.get("事件"))
            if event == "造成伤害前":
                continue
            # `造成伤害前`：两个都合法；`受到致命伤害`：只有转移合法；其余都不合法。
            if event == "受到致命伤害":
                illegal = {"分摊伤害"}
            else:
                illegal = {"转移伤害", "分摊伤害"}
            before = list(listener.get("效果") or [])
            kept = [node for node in before if node.get("能力") not in illegal]
            if len(kept) != len(before):
                fixed.append(str(listener.get("事件")))
                listener["效果"] = kept
        return fixed

    repaired = 0
    for _path, entry in rows:
        for where in repair(entry):
            repaired += 1
            touched.append(f"  {entry['编号']} {entry['名称']:<7} 摘掉挂在「{where}」上的伤害机制")
    if repaired:
        print(f"修复挂错监听的 {repaired} 处")

    # 转移伤害 / 分摊伤害：只挑监听伤害事件、且属援护·同契·合炼的丹。
    transfer_done = share_done = 0
    for path, entry in rows:
        theme = path.stem.split("-")[1]
        if theme not in PARTY_THEMES or not on_damage(entry):
            continue
        if transfer_done < 3 and not has(entry, "转移伤害"):
            apply(path, entry, "转移伤害（这一下转到我身上）", transfer_self(),
                  need_event=DAMAGE_EVENTS)
            transfer_done += 1
            continue
        if share_done < 3 and not has(entry, "分摊伤害"):
            apply(path, entry, "分摊伤害（全队分摊）", share_team(45),
                  need_event=SHARE_EVENTS)
            share_done += 1

    # 聚合数值：按人数放大的一份群体恢复。
    scaled_done = 0
    for path, entry in rows:
        theme = path.stem.split("-")[1]
        if theme not in PARTY_THEMES or has(entry, "聚合数值"):
            continue
        if scaled_done >= 3:
            break
        apply(path, entry, "聚合数值（按己方人数放大恢复）", party_scaled("血气", 4))
        scaled_done += 1

    # 状态条件：只要这枚丹自己定义过状态名，就能给它加一条"印记到了才发作"的监听。
    gated_done = 0
    for path, entry in rows:
        theme = path.stem.split("-")[1]
        if theme == "基础" or has(entry, "状态条件"):
            continue
        if gate(entry)[0] is None:
            continue
        if gated_done >= 6:
            break
        apply(path, entry, "状态条件（印记到了才发作）",
              {"能力": "恢复资源", "目标": self_target(), "资源": "精神",
               "数值": {"能力": "读取数值", "来源": "自身属性", "属性": "精神上限",
                        "百分比": 6, "最低值": 1}},
              second=True)
        gated_done += 1

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
