"""补第二维·来源（全局感知版）：给来源塌陷的卡换掉**一处**读数的来源。

「两面同模」里塌了**来源**那一维的卡，同卡有 ≥2 个 `读取数值` 但来源全同。
只动语义成立的一类换法（第 26/27 轮已验证）：

    读 `自身属性(血气上限/精神上限/护盾上限)` → 读 `自身当前X` 或 `自身已损失X`

即「按上限缩放」→「按当前值 / 按缺口缩放」，玩家看到的读法从"看我的天花板"变成
"看我现在的状态"，是真实的机制差别。

与第 42 轮同一套防身措施：候选集 + **全局贪心**（挑全局用得最少的来源）+
**写入前模拟**（全局最大项一变差就中止）。

    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/补第二维来源.py            # 试算
    .venv/Scripts/python.exe -X utf8 tools/一次性迁移/补第二维来源.py --写入 --授权集 _授权.json

**退出码：0 = 正常，2 = 没找到可改处，3 = 模拟后全局更挤、已拒绝写入。**
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
SURFACES = (
    ("功法", "data/战斗/内容/功法/功法-*.json"),
    ("真意", "data/战斗/内容/真意/真意-*.json"),
    ("气机", "data/战斗/内容/气机/气机-*.json"),
    ("器律", "data/物品/炼器/内容/器律-*.json"),
)
CAP_RESOURCE = {"血气上限": "血气", "精神上限": "精神", "护盾上限": "护盾"}
TOLERANCE = 0.002


def alternatives(node: dict) -> list[str]:
    """某个读数节点可以换到哪些来源（语义成立的那几类）。"""
    if node.get("来源") != "自身属性":
        return []
    resource = CAP_RESOURCE.get(str(node.get("属性") or ""))
    if resource is None:
        return []
    return [f"自身当前{resource}", f"自身已损失{resource}"]


def share(counts: collections.Counter) -> tuple[str, float]:
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

    counts: collections.Counter = collections.Counter()
    targets: list[dict] = []
    for path, entries in files:
        for entry in entries:
            reads: list[dict] = []

            def walk(node: object) -> None:
                if isinstance(node, dict):
                    if node.get("能力") == "读取数值":
                        reads.append(node)
                        counts[str(node.get("来源") or "固定值")] += 1
                    for value in node.values():
                        walk(value)
                elif isinstance(node, list):
                    for value in node:
                        walk(value)

            walk(entry)
            if len(reads) < 2 or len({str(n.get("来源")) for n in reads}) > 1:
                continue
            targets.append({"path": path, "entry": entry, "读数": reads})

    before_top, before_share = share(counts)
    plan = counts.copy()
    grant: dict[str, list[str]] = collections.defaultdict(list)
    changed = 0

    for target in targets:
        options: list[tuple[dict, str]] = []
        for node in target["读数"]:
            for origin in alternatives(node):
                options.append((node, origin))
        if not options:
            continue
        # 全局贪心：挑「换过去之后全局最冷」的来源。
        node, origin = min(options, key=lambda item: plan[item[1]])
        current = str(node.get("来源"))
        if plan[origin] >= plan[current]:
            continue  # 换了不会更均摊，不动
        plan[current] -= 1
        plan[origin] += 1
        node["来源"] = origin
        node.pop("属性", None)
        changed += 1
        grant[target["path"].relative_to(ROOT).as_posix()].append(str(target["entry"]["编号"]))

    if not changed:
        print("没找到可改处。")
        return 2
    after_top, after_share = share(plan)
    print(f"改动 {changed} 处来源 · 涉及 {sum(len(v) for v in grant.values())} 张卡")
    print(f"全局最大项：{before_top} {before_share:.1%} → {after_top} {after_share:.1%}")
    for name, count in plan.most_common(8):
        print(f"  {name:<14}{count:>5}  {count / sum(plan.values()):>6.1%}")
    if after_share > before_share + TOLERANCE:
        print("模拟后全局更挤 —— 拒绝写入。")
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
