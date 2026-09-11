"""收掉最后 8 个悬空引用：在「引用它的效果列表」前面插一个建立节点。

三类形状同一个病灶——**只读不建**：

    状态  状态条件(目标=自身/当前目标)   ← 查有没有这个状态，全库没一处施加
    事实  读取数值(来源=战斗记录)        ← 按记录的数值造成伤害，全库没一处记录
    关联  选择目标(关联=X)               ← 挑建立了该关联的目标，全库没一处建立

统一补法：找到引用它的那个节点，在**它所在的那个效果列表最前面**插一个建立节点，
让引用之前先有东西可引。目标跟着引用的目标走。

- 状态 → `添加状态`，目标取 `状态条件` 的目标；名字按现行规范新取，全局唯一
- 事实 → `记录战斗事实`（归属=自身，方式=累加，值=1），于是「按记录数值造成伤害」有意义
- 关联 → `修改战斗关联`（方式=建立，一方=自身，另一方=当前目标）

**这是补内容、会改平衡**，判据是「差异必须全部落在授权卡里，外部 0 处」。

    python tools/一次性迁移/补最后引用.py            # 预演
    python tools/一次性迁移/补最后引用.py --apply
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

CATEGORY = "中性"
DURATION_UNIT = "状态承受者行动"
REMAINING = 3
REPEAT = "增加层数"
STACK_CAP = 5
LADDER = (2, 4, 6, 8, 10)

#: 可以插建立节点的列表：这些才装效果。`条件` 列表只许放条件节点。
#: 战前装配的实体：监听由 prepared_statuses 承载，不走构筑那套装配。
SKIP_KINDS: frozenset[str] = frozenset()

EFFECT_KEYS = frozenset({
    "效果", "成立效果", "不成立效果", "选项", "尝试效果", "成功效果", "失败效果",
})


def status_word(entity: rename.Entity) -> tuple[str, ...]:
    table = rename.STATUS_WORDS.get(entity.kind) or rename.DEFAULT_STATUS_WORDS
    return tuple(table.get(CATEGORY) or rename.DEFAULT_STATUS_WORDS[CATEGORY])


def pick_name(entity: rename.Entity, taken: set[str]) -> str | None:
    for length in LADDER:
        if length >= len(entity.name):
            break
        for word in status_word(entity):
            candidate = entity.name[:length] + word
            if candidate not in taken:
                return candidate
    for word in status_word(entity):
        candidate = entity.name + word
        if candidate not in taken:
            return candidate
    return None


def refers(node, kind: str, name: str) -> bool:
    """这个节点是不是在引用（而不是建立）那个名字。"""

    if not isinstance(node, dict):
        return False
    ability = node.get("能力")
    if not isinstance(ability, str):
        return False
    if kind == "状态":
        return ability == "状态条件" and node.get("状态") == name
    if kind == "事实":
        return (
            ability == "读取数值"
            and node.get("来源") == "战斗记录"
            and node.get("名称") == name
        )
    if kind == "关联":
        return ability == "选择目标" and node.get("关联") == name
    return False


def establish(kind: str, name: str, target) -> dict:
    if kind == "状态":
        return {
            "能力": "添加状态",
            "目标": target or {"能力": "选择目标", "范围": "自身"},
            "状态": {
                "名称": name,
                "类别": CATEGORY,
                "持续单位": DURATION_UNIT,
                "剩余行动": REMAINING,
                "重复方式": REPEAT,
                "层数上限": STACK_CAP,
            },
        }
    if kind == "事实":
        return {
            "能力": "记录战斗事实",
            "归属": {"能力": "选择目标", "范围": "自身"},
            "名称": name,
            "值": 1,
            "方式": "累加",
        }
    return {
        "能力": "修改战斗关联",
        "名称": name,
        "方式": "建立",
        "一方": {"能力": "选择目标", "范围": "自身"},
        "另一方": {"能力": "选择目标", "范围": "当前目标"},
    }


def collect(entity: rename.Entity, dead: dict[str, str]) -> dict[str, str]:
    """这张卡引用了哪些悬空名字；状态类返回旧名，另两类返回原名。"""

    found: dict[str, str] = {}
    for node in rename.walk(entity.payload):
        for kind, names in dead.items():
            for name in names:
                if refers(node, kind, name):
                    found[name] = kind
    return found


def patch(entity: rename.Entity, dead, taken: set[str], stats, rows) -> None:
    # 战前装配的实体（战丹 / 长期伤势）一起处理：它们的引用在**监听节点的 `条件`** 里，
    # 靠 `监听条件` 规则下钻到该监听自己的 `效果` 列表，不碰 `监听` 列表本身
    # —— 那里只许放监听事件节点。
    if entity.kind in SKIP_KINDS:
        return
    used = collect(entity, dead)
    if not used:
        return

    mapping: dict[str, str] = {}
    for name, kind in used.items():
        if kind != "状态":
            mapping[name] = name
            continue
        new = pick_name(entity, taken)
        if new is None:
            stats["取名失败"] += 1
            continue
        taken.add(new)
        mapping[name] = new

    pending = dict(used)

    def rebuild(node, key=None, ability=None):
        if isinstance(node, list):
            kept = []
            # 只往**效果列表**里插：`条件` 列表只许放条件节点。
            # `被动技能.效果` 也不行——那里只许放监听节点，要下钻到监听节点内部再插。
            effect_list = key in EFFECT_KEYS and ability != "被动技能"
            for item in node:
                if effect_list:
                    for name, kind in list(pending.items()):
                        if any(refers(child, kind, name) for child in rename.walk(item)):
                            target = None
                            if kind == "状态":
                                for child in rename.walk(item):
                                    if refers(child, kind, name):
                                        target = child.get("目标")
                                        break
                            kept.append(establish(kind, mapping[name], target))
                            stats[f"插入建立点（{kind}）"] += 1
                            del pending[name]
                kept.append(rebuild(item))
            return kept
        if isinstance(node, dict):
            out = {}
            child_ability = node.get("能力") if isinstance(node.get("能力"), str) else None
            # 监听节点的 `条件` 里引用待补名字时，`条件` 列表插不进去（只许放条件节点），
            # 要把建立节点插到**这个监听节点自己的 `效果` 列表**最前面。
            prepend = []
            if child_ability == "监听事件":
                gate = node.get("条件") or ()
                for name, kind in list(pending.items()):
                    if not any(refers(child, kind, name) for child in rename.walk(gate)):
                        continue
                    target = None
                    if kind == "状态":
                        for child in rename.walk(gate):
                            if refers(child, kind, name):
                                target = child.get("目标")
                                break
                    prepend.append(establish(kind, mapping[name], target))
                    stats[f"插入建立点（{kind}·监听条件）"] += 1
                    del pending[name]
            for child_key, value in node.items():
                if (
                    isinstance(value, str)
                    and used.get(value) == "状态"
                    and child_key in ("状态", "名称")
                ):
                    stats["改指状态引用"] += 1
                    out[child_key] = mapping[value]
                else:
                    out[child_key] = rebuild(value, child_key, child_ability)
            if prepend and isinstance(out.get("效果"), list):
                out["效果"] = prepend + out["效果"]
            return out
        return node

    rebuilt = rebuild(entity.payload)
    entity.payload.clear()
    entity.payload.update(rebuilt)
    for name, kind in sorted(used.items()):
        rows.append(
            f"{entity.identity}\t{entity.name}\t{kind}\t{name}\t{mapping[name]}\t"
            f"{'未插入' if name in pending else '已插建立点'}"
        )
    if pending:
        stats["没能插入建立点"] += len(pending)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="写回数据文件")
    parser.add_argument("--报告", dest="report", default="_补最后引用.txt")
    args = parser.parse_args()

    found = audit.collect()
    dead: dict[str, set[str]] = {}
    for kind in ("状态", "事实", "关联"):
        dead[kind] = {n for n, r in found[kind].items() if not r["定义"] and r["读取"]}

    entities = rename.load_entities()
    taken: set[str] = set()
    for entity in entities:
        taken |= set(entity.counters) | set(entity.statuses)

    stats: collections.Counter = collections.Counter()
    rows: list[str] = []
    for entity in entities:
        patch(entity, dead, taken, stats, rows)

    changed = rename.write_back(entities) if args.apply else []

    out = io.TextIOWrapper(open(ROOT / args.report, "wb"), encoding="utf-8")
    out.write("悬空：" + "，".join(f"{k} {len(v)}" for k, v in dead.items()) + "\n")
    for key, count in stats.most_common():
        out.write(f"  {count:>4}  {key}\n")
    out.write(f"\n改动文件 {len(changed)}\n")
    out.write("模式: " + ("已写回" if args.apply else "预演") + "\n\n")
    out.write("卡号\t卡名\t类\t原名\t新名\t结果\n")
    for line in rows:
        out.write(line + "\n")
    out.flush()

    print(f"处理 {len(rows)} 处；"
          + "，".join(f"{k} {v}" for k, v in stats.most_common())
          + f"；改动文件 {len(changed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
