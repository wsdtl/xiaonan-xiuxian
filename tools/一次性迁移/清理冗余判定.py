"""清掉生成器给条件结算套的三层废壳。

几乎所有 `条件执行` 都长这样：

    条件执行(X)                       ← 外层，真正干活的判定
      └ 成立效果[0] = 尝试执行
            ├ 尝试效果[0] = 条件执行(X)     ← 又判一次 X，冗余
            │     └ 成立效果 = E
            ├ 成功效果 = B
            └ 失败效果 = B                  ← 两个分支同内容，冗余

外层判过 X 之后、到内层再判之前没有任何节点会改动 X 读的东西（内层在外层成立效果的
第 0 位），所以内层判定恒为真；`尝试执行` 的返回值和内层一致，分支又两边相同。
于是整段等价于：

    条件执行(X)
      └ 成立效果 = E [+ B，当 B 不是已经做过的清零时]

**不动** `尝试执行` 本身。它的返回值会传给上层（`事务执行` 回滚、`重复执行.失败时停止`
都看返回值），拆掉就改了行为。只有整个「尝试执行只拿来套一层同条件判定」的壳才拆。

用法::

    python tools/一次性迁移/清理冗余判定.py            # 预演
    python tools/一次性迁移/清理冗余判定.py --apply
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
SIBLING = ROOT / "tools" / "一次性迁移" / "重命名词条.py"

_spec = importlib.util.spec_from_file_location("词条改名", SIBLING)
rename = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rename)


def fingerprint(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def simplify(node: object, stats: collections.Counter) -> object:
    """就地化简；返回（可能是新的）节点。"""

    if isinstance(node, list):
        return [simplify(item, stats) for item in node]
    if not isinstance(node, dict):
        return node

    node = {key: simplify(value, stats) for key, value in node.items()}

    if node.get("能力") == "条件执行":
        branch = node.get("成立效果")
        if isinstance(branch, list) and branch:
            head = branch[0]
            if isinstance(head, dict) and head.get("能力") == "尝试执行":
                trial = head.get("尝试效果")
                if (
                    isinstance(trial, list)
                    and len(trial) == 1
                    and isinstance(trial[0], dict)
                    and trial[0].get("能力") == "条件执行"
                    and fingerprint(trial[0].get("条件")) == fingerprint(node.get("条件"))
                    and fingerprint(head.get("成功效果")) == fingerprint(head.get("失败效果"))
                ):
                    # 只把内层那次重复判定换成 `顺序执行`，**保留 `尝试执行` 外壳与两条分支**。
                    #
                    # 分支看着冗余（成功失败同内容），其实不是：`_run_effects` 是短路返回，
                    # 内层任一效果失败就不会再跑后面的清零；而 `尝试执行` 的分支无论成败都跑。
                    # 少了它，「施展技能」失败时计量不会被清零，下一回合会再触发一次。
                    stats["去掉重复判定"] += 1
                    effects = list(trial[0].get("成立效果") or [])
                    node = dict(node)
                    node["成立效果"] = [
                        {**head, "尝试效果": [{"能力": "顺序执行", "效果": effects}]}
                    ] + list(branch[1:])
                    return node

    return node


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/清理冗余判定.txt")
    args = parser.parse_args()

    entities = rename.load_entities()
    stats: collections.Counter = collections.Counter()
    changed_files: list[str] = []
    untouched = 0

    for entity in entities:
        before = fingerprint(entity.payload)
        payload = simplify(entity.payload, stats)
        if fingerprint(payload) == before:
            untouched += 1
            continue
        entity.payload.clear()
        entity.payload.update(payload)

    if args.apply:
        changed_files = rename.write_back(entities)

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"化简 {sum(stats.values())} 处；未改动的实体 {untouched}\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>6}  {key}\n")
    out.write(f"\n改动文件: {len(changed_files)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()

    print(
        f"化简 {sum(stats.values())} 处（"
        + "，".join(f"{key} {count}" for key, count in stats.most_common())
        + f"）；改动文件 {len(changed_files)}；详见 {args.report}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
