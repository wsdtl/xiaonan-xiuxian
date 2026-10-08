"""锁定技可达性模型：一条登记规则在**真实内容**下还能不能被触发。

`tools/行为验证/验证规则层.py` 用合成探针证明「引擎机能逐条成立」；它不走 `data/` 里的内容，
所以抓不到「内容根本不会发出这类请求」。这个模型补那一格，供盘点与判据共用。

口径（刻意保守）：

1. **拦截点 → 发出能力**取 `game/core/combat/rules.py` 的 `INTERCEPTION_POINTS` 注释所指的那次操作；
2. **请求发给了谁**只看目标范围：`自身` 只可能构成 `来源关系:自身`；`己方` 可构成 `己方/自身`；
   其余（`当前目标`/`敌方`/`事件来源`/无目标）一律算**三个方向都可能**——所以判定结果是**下界**；
3. **判定按「规则 × 载体实际填的方向」**：规则条件里写 `来源关系:$来源` 的是占位符，参数由载体自己填。
"""

from __future__ import annotations

import collections
import json
import pathlib

from 构筑模板展开 import load_build_json

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SECTIONS = (
    ("功法", DATA / "战斗" / "内容" / "功法"),
    ("真意", DATA / "战斗" / "内容" / "真意"),
    ("气机", DATA / "战斗" / "内容" / "气机"),
    ("器律", DATA / "物品" / "炼器" / "内容"),
    ("战场环境", DATA / "战斗" / "内容" / "战场环境"),
)
#: 拦截点 -> 内容侧发出这类请求的原子能力。
EMITTERS = {
    "被选为目标": ("选择目标",),
    "行动条被改写": ("修改行动条",),
    "事件被改写": ("取消事件", "转化事件", "修改事件数值"),
    "技能被改写": ("修改技能", "修改技能冷却"),
    "状态被添加": ("添加状态",),
    "状态被移除": ("移除状态",),
    "资源被消耗": ("消耗资源", "支付代价", "转移资源"),
    "行动被限制": ("添加状态",),
    "归属被修改": ("修改归属", "转移状态"),
    "形态被切换": ("切换形态",),
    "计量被修改": ("修改构筑计量",),
    "造物被召唤": ("创建战斗对象",),
}
ALL_RELATIONS = ("自身", "己方", "敌方")


def scope_of(node: dict) -> str:
    """这次请求打到了谁身上：选择目标看顶层，状态类看 状态.目标，其余看 目标。"""

    if node.get("能力") == "选择目标":
        return str(node.get("范围") or "缺范围")
    inner = node.get("状态")
    if isinstance(inner, dict) and isinstance(inner.get("目标"), dict):
        return str(inner["目标"].get("范围") or "缺范围")
    target = node.get("目标")
    if isinstance(target, dict):
        return str(target.get("范围") or "缺范围")
    return "（无目标）"


def relations(scope: str) -> set[str]:
    """这个范围可能构成哪些 `来源关系`。拿不准就算三个方向都可能。"""

    if scope == "自身":
        return {"自身"}
    if scope == "己方":
        return {"己方", "自身"}
    return set(ALL_RELATIONS)


def nodes() -> dict[str, list[dict]]:
    """全库内容里按原子能力名分组的节点。"""

    found: dict[str, list[dict]] = collections.defaultdict(list)
    for _, folder in SECTIONS:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                rows = load_build_json(path)
            except Exception:
                continue
            for row in rows:
                def walk(node: object) -> None:
                    if isinstance(node, dict):
                        ability = node.get("能力")
                        if isinstance(ability, str):
                            found[ability].append(node)
                        for value in node.values():
                            walk(value)
                    elif isinstance(node, list):
                        for value in node:
                            walk(value)
                walk(row.get("能力"))
    return found


def reachable(ability_nodes: dict[str, list[dict]]) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """返回（拦截点 -> 可达的来源关系, 拦截点 -> 目标范围分布）。"""

    got: dict[str, set[str]] = {}
    scopes: dict[str, dict] = {}
    for point, abilities in EMITTERS.items():
        found: set[str] = set()
        counter: collections.Counter = collections.Counter()
        for ability in abilities:
            for node in ability_nodes.get(ability, []):
                scope = scope_of(node)
                counter[scope] += 1
                found |= relations(scope)
        got[point] = found
        scopes[point] = dict(counter.most_common(6))
    return got, scopes


def rule_direction(rule: dict, used: object = None) -> str:
    """这条规则实际生效的方向：载体填的优先，其次规则条件里的字面量，最后「不限」。"""

    text = str(used or "")
    if text:
        return text
    tags = [str(t) for c in (rule.get("条件") or []) for t in (c.get("标签") or [])]
    for tag in tags:
        if tag.startswith("来源关系:") and "$" not in tag:
            return tag.split(":")[1]
    return "不限"


def rules() -> dict:
    return json.loads((DATA / "战斗" / "定义" / "规则层.json").read_text(encoding="utf-8"))


def races() -> list:
    return json.loads((DATA / "角色" / "规则" / "种族" / "种族.json").read_text(encoding="utf-8"))
#: 载具自查：库只依赖 tools/库/ 与 data/，不 import 具体工具。

