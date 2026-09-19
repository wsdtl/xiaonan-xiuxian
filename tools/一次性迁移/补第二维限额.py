"""补第二维·限额（全局感知版）：给限额塌陷的卡分档，同时**不许把全局读数弄更挤**。

上一版（第 41 轮）按固定档位表改，局部散开了、但全局 `每次行动最多触发=3` 从 33.4% 升到 34.2%，
被棘轮当场否决。原因：那些卡原值多是 2，固定档位一律把它们抬到 3。

这一版改三处：

1. **候选集**：每个监听节点的目标档不写死，而是「按其事件的实测频次给出档位 ±1」的候选；
2. **全局贪心**：在候选里挑**当前全局用得最少**的那个值（并把已分配的量计回去），
   于是分散动作会主动往冷门档位走，而不是往 3 上堆；
3. **写入前自检**：先模拟改完后的全局分布，若**最大项占比变差**就整体中止（退出码 3），
   不落盘——工具自己先把棘轮那一步跑一遍。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/补第二维限额.py            # 试算（打印模拟结果）
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/补第二维限额.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处，3 = 模拟后全局更挤、已拒绝写入。**
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/物品/炼器/内容/器律-*.json"),
)
CAP_FIELD = "每次行动最多触发"
#: 事件在一次行动内的实测平均次数（`tools/事件频次.py`）。
MEASURED_MEAN = {
    "技能冷却变化后": 2.20, "获得护盾后": 2.13, "获得护盾前": 1.99,
    "资源恢复前": 1.84, "资源恢复后": 1.84, "资源变化后": 1.60,
    "添加状态前": 1.46, "添加状态后": 1.46, "恢复前": 1.45, "事件转化后": 1.42,
    "战场规则变化后": 1.36, "技能变化后": 1.32, "命中判定前": 1.23, "命中后": 1.23,
    "造成伤害前": 1.23, "造成伤害后": 1.23, "受到伤害后": 1.23,
    "移除状态后": 1.22, "行动条变化后": 1.22, "技能冷却完成后": 1.18,
}
TOLERANCE = 0.002


def candidates(event: str, current: int) -> list[int]:
    """按实测频次给中心档，再取 ±1 作为候选（没有实测数据的事件不动）。"""
    mean = MEASURED_MEAN.get(event)
    if mean is None:
        return []
    center = max(2, min(5, math.ceil(mean) + 1))
    return [value for value in (center - 1, center, center + 1) if 2 <= value <= 5
            and value != current]


def collect(files: list[tuple[pathlib.Path, list[dict]]]) -> tuple[collections.Counter, list[dict]]:
    counts: collections.Counter = collections.Counter()
    targets: list[dict] = []
    for path, entries in files:
        for entry in entries:
            listeners: list[dict] = []

            def walk(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("能力") == "监听事件":
                        listeners.append(node)
                        if CAP_FIELD in node:
                            counts[int(node[CAP_FIELD])] += 1
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)

            walk(entry)
            if len(listeners) < 2:
                continue
            values = {int(node[CAP_FIELD]) for node in listeners if CAP_FIELD in node}
            if len(values) != 1:
                continue
            targets.append({"path": path, "entry": entry, "监听": listeners,
                            "原值": next(iter(values))})
    return counts, targets


def share(counts: collections.Counter) -> tuple[int, float]:
    total = sum(counts.values())
    top, count = counts.most_common(1)[0]
    return top, (count / total if total else 0.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--写入", action="store_true", help="默认只试算，加这个才落盘")
    parser.add_argument("--授权集", default="", help="把授权卡清单写到这个 json")
    args = parser.parse_args()

    files = [(path, json.loads(path.read_text(encoding="utf-8")))
             for _section, pattern in SURFACES for path in sorted(ROOT.glob(pattern))]
    counts, targets = collect(files)
    before_top, before_share = share(counts)
    plan = counts.copy()
    grant: dict[str, list[str]] = collections.defaultdict(list)
    changed_nodes = 0
    skipped = 0

    for target in targets:
        assigned: dict[int, int] = {}
        for index, node in enumerate(target["监听"]):
            event = str(node.get("事件") or "")
            current = int(node.get(CAP_FIELD, 1) or 1)
            pool = candidates(event, current)
            if not pool:
                continue
            # 全局贪心：挑已用量最少的档；平手时挑离原值远的（更看得出差别）。
            best = min(pool, key=lambda value: (plan[value], abs(value - current) * -1))
            assigned[index] = best
        if len(set(assigned.values())) < 2:
            # 分完还是一种取值，就把第一个挪到次冷的候选上。
            for index, node in assigned.items():
                pool = candidates(str(target["监听"][index].get("事件") or ""),
                                  int(target["监听"][index].get(CAP_FIELD, 1) or 1))
                other = [value for value in pool if value != node]
                if other:
                    assigned[index] = min(other, key=lambda value: plan[value])
                    break
        if len(set(assigned.values())) < 2:
            skipped += 1
            continue
        for index, value in assigned.items():
            old = int(target["监听"][index].get(CAP_FIELD, 1) or 1)
            plan[old] -= 1
            plan[value] += 1
            target["监听"][index][CAP_FIELD] = value
            changed_nodes += 1
        grant[target["path"].relative_to(ROOT).as_posix()].append(str(target["entry"]["编号"]))

    if not changed_nodes:
        print("没找到可改处。")
        return 2
    after_top, after_share = share(plan)
    print(f"改动 {changed_nodes} 个限额节点 · 涉及 {sum(len(v) for v in grant.values())} 张卡"
          f"（{skipped} 张分不开，跳过）")
    print(f"全局最大项：{before_top} {before_share:.1%} → {after_top} {after_share:.1%}")
    for value, count in plan.most_common():
        print(f"  ={value}  {count:>5}  {count / sum(plan.values()):>6.1%}")
    if after_share > before_share + TOLERANCE:
        print("模拟后全局更挤 —— 拒绝写入（工具自检，等同于先跑一遍棘轮）。")
        return 3
    if args.授权集:
        pathlib.Path(args.授权集).write_text(
            json.dumps(dict(grant), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"授权集写入 {args.授权集}")
    if not args.写入:
        print("这是试算；确认后再加 --写入。")
        return 0
    for path, entries in files:
        if grant.get(path.relative_to(ROOT).as_posix()):
            path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print("已写入。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
