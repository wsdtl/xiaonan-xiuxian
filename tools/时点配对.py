"""时点配对：给「只有一个触发时点」的卡补一条**配对时点的回响**。

完成度指标里最差的一档是「三面同模」——触发时点 / 缩放来源 / 限额取值各只有一种。
其中最容易补、也最有设计含义的是**触发时点**：引擎的事件本来就是成对的
（`X前`/`X后`），卡只听一半，等于只写了半个反应。

规则：卡只有一个时点 E、且 E 有配对 P 时，把它的**第一个监听节点**复制一份挂到 P 上，
数值减半（`数值`/`层数` ×0.5，最小 1）——**次要时点给一半**，主次分明；
新监听节点单独给 `每次行动最多触发=1`，免得与主时点的额度互相吃。

    .venv/Scripts/python.exe -X utf8 tools/时点配对.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/时点配对.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处。**
"""

from __future__ import annotations

import argparse
import collections
import copy
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/炼器/内容/器律-*.json"),
)
CAP_FIELD = "每次行动最多触发"

#: 事件配对（只列语义上真的成对的）。值是回响挂到的事件。
PARTNER = {
    "恢复后": "恢复前",
    "资源恢复后": "资源恢复前",
    "造成伤害后": "造成伤害前",
    "命中后": "命中判定前",
    "暴击后": "暴击判定前",
    "格挡后": "格挡判定前",
    "技能施放后": "技能施放前",
    "添加状态后": "添加状态前",
    "获得护盾后": "获得护盾前",
    "技能冷却完成后": "技能冷却变化后",
    "击杀后": "死亡后",
    "受到致命伤害": "受到伤害后",
    "护盾破碎后": "获得护盾后",
    "战斗对象退场后": "战斗对象入场后",
    "闪避后": "命中判定前",
    "移除状态后": "添加状态后",
    # 反向：卡只听「前」侧时，配对到「后」侧（不然只听前半步的卡照样是半个反应）。
    "造成伤害前": "造成伤害后",
    "恢复前": "恢复后",
    "资源恢复前": "资源恢复后",
    "资源消耗后": "资源消耗前",
    "命中判定前": "命中后",
    "暴击判定前": "暴击后",
    "格挡判定前": "格挡后",
    "获得护盾前": "获得护盾后",
    "技能施放前": "技能施放后",
    "添加状态前": "添加状态后",
    "战斗对象入场后": "战斗对象退场后",
    "死亡后": "击杀后",
    "技能冷却变化后": "技能冷却完成后",
    "状态层数变化后": "移除状态后",
}
#: 回响里要减半的数值字段。
HALVE_FIELDS = ("数值", "层数")
#: `转移伤害` 只允许挂在这两个事件的监听里（`game/core/combat/builds.py` 的 `_validate_event_binding`）。
#: 复制监听时必须照这条契约拦一道：不然「造成伤害前 → 造成伤害后」这种配对会直接违约。
TRANSFER_EVENTS = {"造成伤害前", "受到致命伤害"}

#: **事件锁定的能力**：只能在特定事件的监听里执行，否则引擎运行时直接抛错
#: （`mechanics.py` 的 `_current_event(context, expected)`）。第 40 轮踩过：
#: `受到致命伤害 → 受到伤害后` 的配对让 3 张卡在语料里抛 `当前事件不是受到致命伤害`。
#: 这类锁**不在构筑契约里**，`builds.py` 拦不到，只能自己按引擎的 `_current_event` 调用点维护。
EVENT_LOCKED = {
    "转移伤害": TRANSFER_EVENTS,
    "抵挡致命伤害": {"受到致命伤害"},
}

#: **事件字段可修改性**：这几条能力要求当前事件的 `可修改` 里含对应字段
#: （`mechanics.py` 的 `_require_event_mutation`），字段白名单写在
#: `data/战斗/定义/事件.json` 的每个事件上。第 40 轮踩过：`恢复前 → 恢复后` 的配对让
#: `真意:410398` 在交叉对局里抛 `事件 恢复后 不允许修改取消`（`恢复后` 的 `可修改` 是空的）。
MUTATION_FIELDS = {
    "修改事件数值": "当前数值",
    "修改事件目标": "目标",
    "修改事件标签": "标签",
    "取消事件": "取消",
    "转化事件": "类型",
}
EVENT_DEFINITION = "data/战斗/定义/事件.json"


def mutations_in(node: object, found: set[str] | None = None) -> set[str]:
    """收集子树里出现的「要求事件字段可修改」的能力名。"""
    found = set() if found is None else found
    if isinstance(node, dict):
        name = str(node.get("能力") or "")
        if name in MUTATION_FIELDS:
            found.add(name)
        for value in node.values():
            mutations_in(value, found)
    elif isinstance(node, list):
        for value in node:
            mutations_in(value, found)
    return found


def load_mutable_events() -> dict[str, set[str]]:
    """每个事件允许修改哪些字段（`可修改`）。事件定义是「事件名 → 定义」的字典。"""
    raw = json.loads((ROOT / EVENT_DEFINITION).read_text(encoding="utf-8"))
    table: dict[str, set[str]] = {}
    for name, entry in raw.items():
        if isinstance(entry, dict):
            table[str(name)] = {str(item) for item in entry.get("可修改") or ()}
    return table


def locked_in(node: object) -> str | None:
    """返回子树里第一个「事件锁定」的能力名；没有则 None。"""
    if isinstance(node, dict):
        name = str(node.get("能力") or "")
        if name in EVENT_LOCKED:
            return name
        for value in node.values():
            found = locked_in(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = locked_in(value)
            if found:
                return found
    return None


def halve(node: object) -> None:
    if isinstance(node, dict):
        for key in HALVE_FIELDS:
            value = node.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                node[key] = max(1, int(value * 0.5))
        for value in node.values():
            halve(value)
    elif isinstance(node, list):
        for value in node:
            halve(value)


def profile(entry: dict) -> dict[str, object]:
    events: set[str] = set()
    sources: set[str] = set()
    caps: set[str] = set()
    first: dict | None = None

    def walk(node: object) -> None:
        nonlocal first
        if isinstance(node, dict):
            ability = str(node.get("能力") or "")
            if ability == "监听事件":
                events.add(str(node.get("事件") or ""))
                if CAP_FIELD in node:
                    caps.add(str(node[CAP_FIELD]))
                if first is None:
                    first = node
            elif ability == "读取数值":
                sources.add(str(node.get("来源") or "固定值"))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(entry)
    return {"事件": events, "来源": sources, "限额": caps, "首个监听": first}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    mutable = load_mutable_events()
    grant: dict[str, list[str]] = {}
    pairs: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()
    for _section, pattern in SURFACES:
        for path in sorted(ROOT.glob(pattern)):
            entries = json.loads(path.read_text(encoding="utf-8"))
            cards: list[str] = []
            for entry in entries:
                info = profile(entry)
                if not info["首个监听"]:
                    continue
                if not (len(info["事件"]) <= 1 and len(info["来源"]) <= 1 and len(info["限额"]) <= 1):
                    continue
                event = next(iter(info["事件"]))
                partner = PARTNER.get(event)
                if partner is None:
                    skipped[f"{event}（无配对）"] += 1
                    continue
                echo = copy.deepcopy(info["首个监听"])
                echo["事件"] = partner
                echo[CAP_FIELD] = 1
                halve(echo.get("效果") or [])
                locked = locked_in(echo.get("效果") or [])
                if locked and partner not in EVENT_LOCKED[locked]:
                    skipped[f"含{locked}、配对事件不合法"] += 1
                    continue
                blocked = [
                    name for name in mutations_in(echo.get("效果") or [])
                    if MUTATION_FIELDS[name] not in mutable.get(partner, set())
                ]
                if blocked:
                    skipped[f"含{blocked[0]}、{partner} 不可修改该字段"] += 1
                    continue
                # 挂到该卡第一个「被动技能」的效果列表末尾（监听节点都住在那里；
                # `能力[].效果[0]` 必须是监听节点，所以只能**追加**、不能插到最前）。
                def first_ability(node: object) -> bool:
                    if isinstance(node, dict):
                        if node.get("能力") == "被动技能" and isinstance(node.get("效果"), list):
                            node["效果"].append(echo)
                            return True
                        for value in node.values():
                            if first_ability(value):
                                return True
                    elif isinstance(node, list):
                        for value in node:
                            if first_ability(value):
                                return True
                    return False

                planted = first_ability(entry)
                if not planted:
                    skipped["找不到挂点"] += 1
                    continue
                pairs[f"{event}→{partner}"] += 1
                cards.append(str(entry["编号"]))
            if cards:
                grant[path.relative_to(ROOT).as_posix()] = sorted(cards)
                if args.写入:
                    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")

    if not pairs:
        print("没找到可改处。")
        print("跳过：" + " · ".join(f"{k} {v}" for k, v in skipped.most_common()))
        return 2
    print("配对落点：")
    for key, count in pairs.most_common():
        print(f"  {key:<22}{count:>3} 张")
    print(f"\n合计 {sum(pairs.values())} 张卡补上第二时点"
          f"（涉及 {sum(len(v) for v in grant.values())} 张）")
    if skipped:
        print("跳过：" + " · ".join(f"{k} {v}" for k, v in skipped.most_common()))
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(grant, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
