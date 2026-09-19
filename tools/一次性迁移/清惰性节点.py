"""删掉生成器留下的惰性节点：没人读、也没人泛选碰得到的占位。

两类：

* `添加状态`：状态名没人按名字读、定义体里没有任何有效载荷（属性/标签/控制/免疫/监听），
  并且**本卡没有任何泛选状态**（不带名称的 `选择状态`）会扫到它。
* `修改构筑计量`：计量名没有任何 `读取数值` 读它。

**这不是纯等价改写**：删掉一个状态会顺手删掉它派发的 `添加状态前/后` 事件，别人的监听
可能正盯着那个事件；删掉一个计量会改父节点的短路结果（顶到上限时返回 `False`）。
所以改完必须跑 `tools/语料对照.py` 比行为——差异落在哪张卡，就是那些节点原来在干什么。

用法::

    python tools/一次性迁移/清惰性节点.py            # 预演
    python tools/一次性迁移/清惰性节点.py --apply
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import io
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rename = _load("词条改名", "tools/一次性迁移/重命名词条.py")
audit = _load("词条作用域", "tools/架构审查/检查词条作用域.py")

#: 原子能力注册表：字段的 `最少项` 决定摘空之后父节点还能不能留。
REGISTRY: dict = __import__("json").loads(
    (ROOT / "data" / "战斗" / "定义" / "原子能力.json").read_text(encoding="utf-8")
)


#: 豁免名单：这两个状态虽然自身没有载荷、也没人按名字读，却是所在卡里
#: `添加状态后` 监听的**唯一**触发源——删掉它们就少派发一次事件，卡里的监听
#: 不再运行，终局资源跟着变。用语料跑出来的，不是猜的。
EXEMPT = {
    "400550": {"日月灵印"},
    "400378": {"业火灵契"},
}


def prune(node, state, stats, removed):
    """递归重建能力树，顺手摘掉惰性节点；返回 None 表示这个节点被删了。"""

    if isinstance(node, list):
        kept = []
        for item in node:
            result = prune(item, state, stats, removed)
            if result is not None:
                kept.append(result)
        return kept
    if not isinstance(node, dict):
        return node

    ability = node.get("能力") if isinstance(node.get("能力"), str) else ""

    if ability == "添加状态":
        holder = node.get("状态")
        if isinstance(holder, dict):
            name = holder.get("名称")
            if (
                isinstance(name, str)
                and name in state["unread_status"]
                and not any(holder.get(key) for key in audit.STATUS_PAYLOAD)
                and not state["generic"]
                and name not in EXEMPT.get(state["identity"], ())
            ):
                stats["删惰性状态"] += 1
                removed.append(f"{state['identity']} 状态 {name}")
                return None
    if ability == "修改构筑计量" and node.get("计量") in state["unread_counter"]:
        stats["删死计量"] += 1
        removed.append(f"{state['identity']} 计量 {node.get('计量')}")
        return None

    rebuilt = {key: prune(value, state, stats, removed) for key, value in node.items()}

    # 摘空之后父节点可能就不合法了：注册表说 `效果` 至少要 1 项，那就连父节点一起摘。
    # 这一步会自下而上级联——空监听摘掉后，外层技能的效果数组也可能跟着空。
    if ability:
        for key, field in (REGISTRY.get(ability, {}).get("字段") or {}).items():
            floor = field.get("最少项")
            value = rebuilt.get(key)
            if floor and isinstance(value, list) and len(value) < floor:
                stats["级联摘掉空壳"] += 1
                removed.append(f"{state['identity']} 级联摘掉 {ability}.{key} 已空")
                return None
    return rebuilt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_输出/清惰性节点.txt")
    args = parser.parse_args()

    found = audit.collect()
    unread_status = {name for name, record in found["状态"].items() if not record["读取"]}
    unread_counter = {name for name, record in found["计量"].items() if not record["读取"]}

    entities = rename.load_entities()
    stats: collections.Counter = collections.Counter()
    emptied: list[str] = []
    removed: list[str] = []

    for entity in entities:
        generic = any(
            node.get("能力") == "选择状态" and not node.get("名称")
            for node in audit._walk_all(entity.payload)
        )
        state = {
            "unread_status": unread_status,
            "unread_counter": unread_counter,
            "generic": generic,
            "identity": entity.identity,
        }
        pruned = prune(entity.payload, state, stats, removed)
        if not isinstance(pruned, dict):
            continue
        if entity.payload.get("能力") and not pruned.get("能力"):
            emptied.append(f"{entity.identity} {entity.name}：能力 被摘空")
        entity.payload.clear()
        entity.payload.update(pruned)

    changed = rename.write_back(entities) if args.apply else []

    (ROOT / "_输出").mkdir(exist_ok=True)
    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write(f"合计摘掉 {sum(stats.values())} 个节点\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>6}  {key}\n")
    out.write(f"\n被摘空根能力的实体 {len(emptied)} 张\n")
    for line in emptied[:30]:
        out.write(f"  {line}\n")
    out.write(f"\n改动文件: {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n")
    out.flush()

    # 完整清单落在迁移目录里，不截断：以后要回查「这张卡原来挂过什么钩子」靠它。
    ledger = ROOT / "tools" / "一次性迁移" / "清惰性节点清单.txt"
    with ledger.open("w", encoding="utf-8") as handle:
        handle.write(
            f"# `清惰性节点.py` 摘掉的 {len(removed)} 个节点\n"
            "# 原子能力注册表（`战斗/定义/原子能力.json`）一条没动——词汇表是设计余量。\n"
            "# 以后印卡补内容，就从这份清单看哪张卡空着哪些格子。\n\n"
        )
        for line in removed:
            handle.write(f"{line}\n")

    print(
        f"摘掉 {sum(stats.values())} 个节点（"
        + "，".join(f"{key} {count}" for key, count in stats.most_common())
        + f"）；摘空 {len(emptied)} 张；改动文件 {len(changed)}；"
        + f"完整清单 {ledger.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
