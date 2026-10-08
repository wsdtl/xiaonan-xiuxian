"""锁定技盘点：每条登记规则在**真实内容**下还能不能被触发。

仓库已有的 `tools/行为验证/验证规则层.py` 用**合成探针**证明「引擎机能逐条成立」；
但它故意不走 `data/` 里的内容，所以抓不到另一类问题——**内容根本不会发出这类请求**。
本脚本补的正是这一格：把每个拦截点的内容侧发出者扫一遍，看它们把请求发给了谁，
再拿种族实际填的方向去对。

口径（可判、且刻意偏保守）：

1. **拦截点 → 发出能力**取代码侧权威表 `game/core/combat/rules.py` 的 `INTERCEPTION_POINTS`
   注释所指的那次操作，落到具体原子能力名上；
2. **请求发给了谁**只看目标范围：`自身` 只可能构成 `来源关系:自身`；`己方` 可构成 `己方/自身`；
   其余（`当前目标`/`敌方`/`事件来源`/无目标）一律算**三个方向都可能**——所以这里报出的
   「不可达」是**下界**：真到战斗里只会更不可达，不会更可达；
3. **判定按「规则 × 种族实际填的方向」**：规则定义里写 `来源关系:$来源` 的，参数由种族自己填，
   所以必须看数据里填了什么，不能只看规则定义。

    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点锁定技.py
    .venv/Scripts/python.exe -X utf8 tools/报告与生成/盘点锁定技.py --输出 _输出/锁定技可达性.md

**退出码恒为 0**：这是盘点报告，判定归 `工具/架构审查` 那边的判据。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys as _sys

# 共用库住在 tools/库/：脚本按文件运行时 sys.path[0] 是自己的目录，得手动加。
_sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "库"))

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
#: 拦截点 -> 内容侧发出这类请求的原子能力。取自 rules.INTERCEPTION_POINTS 的 note 所指的那次操作。
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


def _scope(node: dict) -> str:
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


def _relations(scope: str) -> set[str]:
    """这个范围可能构成哪些 `来源关系`。保守：拿不准就算三个方向都可能。"""

    if scope == "自身":
        return {"自身"}
    if scope == "己方":
        return {"己方", "自身"}
    return {"敌方", "己方", "自身"}


def _nodes() -> dict[str, list[dict]]:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--输出", default="", help="写进文件；默认打到标准输出")
    args = parser.parse_args()

    nodes = _nodes()
    reachable: dict[str, set[str]] = {}
    scopes: dict[str, dict] = {}
    for point, abilities in EMITTERS.items():
        found: set[str] = set()
        counter: collections.Counter = collections.Counter()
        for ability in abilities:
            for node in nodes.get(ability, []):
                scope = _scope(node)
                counter[scope] += 1
                found |= _relations(scope)
        reachable[point] = found
        scopes[point] = dict(counter.most_common(5))

    layer = json.loads((DATA / "战斗" / "定义" / "规则层.json").read_text(encoding="utf-8"))
    races = json.loads((DATA / "角色" / "规则" / "种族" / "种族.json").read_text(encoding="utf-8"))

    out: list[str] = ["# 锁定技可达性盘点", "", "## 各拦截点的内容侧发出者", "",
                      "| 拦截点 | 可达来源关系 | 发出范围分布 |", "| --- | --- | --- |"]
    for point in EMITTERS:
        out.append("| %s | %s | %s |" % (point, "/".join(sorted(reachable[point])),
                                          str(scopes[point])))

    usage: collections.Counter = collections.Counter()
    dead: collections.Counter = collections.Counter()
    affected: set[str] = set()
    total = 0
    for race in races:
        for entry in (race.get("天生规则") or []):
            name = str(entry.get("名称"))
            total += 1
            row = layer.get(name) or {}
            point = str(row.get("拦截点") or "?")
            tags = [str(t) for c in (row.get("条件") or []) for t in (c.get("标签") or [])]
            rel = str(entry.get("来源") or "") or next(
                (t.split(":")[1] for t in tags if t.startswith("来源关系:") and "$" not in t), "不限")
            usage[(point, name, rel)] += 1
            if rel != "不限" and rel not in reachable.get(point, set()):
                dead[(point, name, rel)] += 1
                affected.add(str(race.get("编号")))

    out += ["", "## 不可达组合", "",
            "| 拦截点 | 规则 | 种族填的方向 | 被几个种族使用 |", "| --- | --- | --- | --- |"]
    for (point, name, rel), count in sorted(dead.items(), key=lambda kv: -kv[1]):
        out.append("| %s | %s | %s | %d |" % (point, name, rel, count))
    out += ["", "## 汇总", "",
            "- 种族 %d 个；天生规则条目 %d 条；涉及 (拦截点,规则,方向) 组合 %d 个"
              % (len(races), total, len(usage)),
            "- 不可达组合 %d 个；受影响种族 %d 个；空转条目 %d 条（%.0f%%）"
              % (len(dead), len(affected), sum(dead.values()),
                 100 * sum(dead.values()) / total if total else 0),
            "- 口径：拿不准的方向一律算可达，所以上面这张表是**下界**。"]

    text = chr(10).join(out) + chr(10)
    if args.输出:
        target = pathlib.Path(args.输出)
        if not target.is_absolute():
            target = ROOT / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print("已写入 %s" % target)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
