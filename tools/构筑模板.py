"""构筑模板原型：把重复的「语义块」参数化，用一份模板展开成多张卡的效果。

## 为什么做这个

实测：功法 600 门共 244224 个效果节点，但效果只有 **627 个动作序列原型**；前 20 个原型
覆盖约 **47%** 节点。其中最大的一个原型（``监听事件 > 条件执行 > 尝试执行 > 消耗状态层数``）
在库里被**抄了 392 遍**，每次 108 行，合计 42336 行——就是「蓄元 → 满层 → 引爆」这条机制。

而且那 392 个实例里，50 个叶子位置有 **38 个逐字节相同**，真正变化的只有 9 个位置，
其中 5 个位置写的是**同一个状态名**。也就是说：一条效果里同一个名字写了 5 遍，
改一处漏一处就会变成「消耗 A、读 B」——`tools/架构审查/检查词条作用域.py` 正是为这类
问题存在的。

本工具把「模板 + 参数」这套机制做出来并**自我验证**：从实例反推出该参数化的叶子位置，
正向用参数展开回一棵完整树，再和原实例**逐字节比对**。对不上就说明模板机制不成立。

## 用法

```powershell
# 列出现有原型（按节点权重排序）
.venv/Scripts/python.exe -X utf8 tools/构筑模板.py --列表

# 拿排名第 1 的原型跑回环验证：反推参数 → 展开 → 与原实例逐字节比对
.venv/Scripts/python.exe -X utf8 tools/构筑模板.py --原型 1

# 看某个实例展开前后的样子
.venv/Scripts/python.exe -X utf8 tools/构筑模板.py --原型 1 --展示 3
```

**本工具只读 `data/`，不写任何数据文件。** 迁移到「卡里存引用」是后续阶段的事，
需要先改引擎让加载期认识模板（见文末「未做」）。

## 未做（需要设计决定）

1. 模板还没有正式编号、没有进 `构筑契约.json`——它目前只是本工具内部的对象。
2. 引擎还不认识「模板引用」；现在展开出来的树必须写回 `data/` 才生效。
3. 参数名是我按语义起的；`读值上限` 与 `阈值` 在数据里高度相关（上限 12 ↔ 阈值 2），
   是否要做成联动，等有需求再定。
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 折叠口径只有一份，在引擎侧的数据层模块：生成器与迁移共用它，避免「生成折、迁移不折」。
from game.core.combat.fold import (  # noqa: E402
    fold_repeats,
)

#: 一个面的配置：目录、文件名模式，以及**哪些位置算匹配单位**。
#:
#: `根列表`：条目里这个键是「根节点数组」，每个根的 `效果` 数组都是匹配单位。
#:   构筑三段用它（`能力[i].效果`）。
#: `位置`：路径模式，`*` 匹配任意一层（用于跨过列表下标）。战场环境 / 伤势 / 战丹
#:   的效果挂在别处，用这个指明。
#:
#: 匹配单位始终是「某个效果数组里的一项」——不是固定路径，所以换一个面只要加配置。
#:
#: **六个面共用一份库。** 但排名必须**按面归一**（见 `_ranked_units`）：新面的效果多是
#: 片段级（挂在 `阶段.常驻能力`、`战斗状态.监听`、`使用效果.监听` 上），同一动作序列下
#: 会分出远超三段的簇；共用一份绝对收益排名时，靠前的名额会被片段占走，三段里本来
#: 成簇的大效果反而凑不成模板（实测三段覆盖率从 6,405 条掉到 3,605 条）。
#:
#: 三段的序列重叠很高（真意 209 个序列里 123 个功法已有、器律 59 个里 39 个已有），
#: 所以**必须联合生成一份库**，否则同一段机制会在两份库里各存一份，改一处漏一处。
SEGMENTS: dict[str, dict] = {
    "功法": {
        "目录": ROOT / "data" / "战斗" / "内容" / "功法",
        "模式": "功法-*.json",
        "根列表": "能力",
    },
    "真意": {
        "目录": ROOT / "data" / "战斗" / "内容" / "真意",
        "模式": "真意-*.json",
        "根列表": "能力",
    },
    "器律": {
        "目录": ROOT / "data" / "物品" / "炼器" / "内容",
        "模式": "器律*.json",
        "根列表": "能力",
    },
    "战场环境": {
        "目录": ROOT / "data" / "战斗" / "内容" / "战场环境",
        "模式": "*.json",
        "位置": ("阶段/*/常驻能力", "阶段/*/入阶能力"),
    },
    "伤势": {
        "目录": ROOT / "data" / "角色" / "内容",
        "模式": "伤势.json",
        "位置": ("战斗状态/监听",),
    },
    "战丹": {
        "目录": ROOT / "data" / "物品" / "炼丹" / "内容" / "丹药" / "战丹",
        "模式": "*.json",
        "位置": ("使用效果/监听",),
    },
}

ABILITY = "能力"
EFFECT = "效果"

#: 模板引用节点里标记模板编号的键。与 `game.core.combat.templates.TEMPLATE_KEY` 同值；
#: 这里单独写一份是为了让本工具在没有引擎上下文时也能认引用项（见 `_is_effect_array`）。
TEMPLATE_KEY = "模板"


#: 可选参数缺失时的实参值。用普通字符串，保证能进 JSON 与集合运算。
_ABSENT = "<缺省>"

#: 可选：把稳定编号 `p1`…`pN` 换成可读标签。**只影响显示，不参与任何匹配**。
#:
#: 实测「状态载体名」（4 处）与「读取来源名」（1 处）在某张卡上恰好同值，
#: 但向量不同，必须保持两个参数，否则别的卡会还原不出来。
ARCHETYPE_1_LABELS: dict[str, str] = {
    "p1": "触发事件",
    "p2": "消耗层数",
    "p3": "状态载体名",
    "p4": "引爆效果名",
    "p5": "读值上限",
    "p6": "读取来源名",
    "p7": "伤害百分比",
    "p8": "触发阈值",
    "p9": "条件上限",
    "p10": "每轮触发上限",
}


def _position_label(path: str) -> str:
    """按位置路径自动起一个可读名字：取末尾两段，去掉索引段。

    `/效果/[0]/条件/[0]/左值/状态` -> `左值·状态`
    `/效果/[0]/成立效果/[0]/成功效果/[0]/状态/名称` -> `状态·名称`
    """

    parts = [part for part in path.split("/") if part and not part.startswith("[")]
    tail = parts[-2:] if len(parts) >= 2 else parts
    return "·".join(tail) or path


def _walk_leaves(node: Any, path: str, out: dict[str, Any]) -> None:
    """收集所有标量叶子：路径 -> 值。

    列表带真实下标（`[0]`、`[1]`），因为同一原型里 `尝试效果` 这类数组可能有多项，
    参数化的位置未必在第 0 项。
    """

    if isinstance(node, dict):
        for key, value in node.items():
            _walk_leaves(value, f"{path}/{key}", out)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk_leaves(item, f"{path}/[{index}]", out)
    else:
        out[path] = node


def _node_cost(node: Any) -> int:
    if isinstance(node, dict):
        return 1 + sum(_node_cost(value) for value in node.values())
    if isinstance(node, list):
        return sum(_node_cost(item) for item in node)
    return 1


def _ability_sequence(node: Any, out: list[str]) -> list[str]:
    if isinstance(node, dict):
        ability = node.get(ABILITY)
        if isinstance(ability, str):
            out.append(ability)
        for key in sorted(node):
            if isinstance(node[key], (dict, list)):
                _ability_sequence(node[key], out)
    elif isinstance(node, list):
        for item in node:
            _ability_sequence(item, out)
    return out


def _set_leaf(node: Any, path: str, value: Any) -> None:
    """按叶子路径写回占位符。路径形如 `/效果/[0]/成立效果/[0]/层数`。"""

    def visit(current: Any, parts: list[str]) -> None:
        if not parts:
            return
        head, rest = parts[0], parts[1:]
        if head.startswith("[") and head.endswith("]"):
            visit(current[int(head[1:-1])], rest)
            return
        if not rest:
            current[head] = value
            return
        visit(current[head], rest)

    visit(node, [part for part in path.split("/") if part])


def _is_effect_array(value: Any) -> bool:
    """这个值是不是「效果数组」：非空，且每一项都是带 `能力` **或**模板引用的字典。

    必须同时认模板引用：迁移落盘之后引用项没有 `能力` 键，只认 `能力` 会让迁移在
    **已迁移数据**上认不出这些数组，幂等复核读不出真相。
    """

    return (
        isinstance(value, list)
        and bool(value)
        and all(
            isinstance(item, dict)
            and (isinstance(item.get(ABILITY), str) or TEMPLATE_KEY in item)
            for item in value
        )
    )


def _is_unit_item(value: Any) -> bool:
    """这一项是不是**待模板化的**效果节点（带 `能力`）。

    与 `_is_effect_array` 的区别：已被换成模板引用的项**不算**。迁移会钻进已模板化的
    内层数组（`监听事件.效果` 里的项现在也满足 `_is_effect_array`），把那些引用当成
    「保留」重复计数——实测把 219 条报成 17,265 条，幂等复核与覆盖率都读不出真相。
    """

    return isinstance(value, dict) and isinstance(value.get(ABILITY), str)


def _collect_from_entry(entry: dict, where: str, config: dict) -> list[tuple[str, dict]]:
    """从一个条目里取出该面**待模板化的效果数组项**。

    匹配单位是「某个效果数组里的一项」，位置由面的配置指明（`根列表` 或 `位置`）。
    **不往更深处收集**：效果树里还有 `监听事件.效果`、`尝试执行.效果` 等内层数组，
    那些是模板主体的一部分，由展开还原；把它们也当独立候选会让片段挤占排名名额，
    实测把覆盖率从 6,405 条压到 2,614 条。

    取出的项先过一遍 `_fold_repeats`——见那里的说明，这是消除「同一条 `•` 写两遍」
    的**唯一正确位置**。折叠必须作用在**整个数组**上，不能逐项折：相邻的两项要互相比
    才能判出重复（实测 `周天潮生` 里 `[430254, 430254]` 逐项折叠永远发现不了，卡面上
    就出现两段一模一样的「对己方全体逐个结算」）。
    """

    out: list[tuple[str, dict]] = []
    已产出: dict[int, set[int]] = {}
    for label, _root_index, _item_index, array in unit_arrays(entry, config):
        folded = _fold_repeats(array)
        # 折叠后**按下标重取**。`unit_arrays` 的下标是按**未折叠**数组算出来的，折叠
        # 之后同一个位置会被反复产出，所以要按下标去重；被折掉的尾项直接跳过。
        # 去重按 `id(array)` 分桶——不同数组的下标会撞（每个数组都从 0 开始）。
        已见 = 已产出.setdefault(id(array), set())
        if _item_index >= len(folded) or _item_index in 已见:
            continue
        已见.add(_item_index)
        item = folded[_item_index]
        if not _is_unit_item(item):
            continue
        out.append((f"{where}:{label}", item))
    return out


def _fold_repeats(node: Any) -> Any:
    """`game.core.combat.fold.fold_repeats` 的别名。

    实现只有一份（在数据层）：生成器挖模板前折一遍、迁移找原型前折一遍，同一份函数，
    两处各写一份就会脱节——实测漏掉 1,669 条顶层效果。
    """

    return fold_repeats(node)


def _roots(entry: dict) -> list[dict]:
    """构筑三段的根能力列表（`条目.能力[]`）。"""

    roots = entry.get(ABILITY)
    if not isinstance(roots, list):
        return []
    return [item for item in roots if isinstance(item, dict)]


def _matches(pattern: str, path: str) -> bool:
    """路径模式匹配：`*` 匹配一层（用来跨过列表下标）。"""

    want = pattern.split("/")
    have = [part for part in path.split("/") if part]
    if len(want) != len(have):
        return False
    return all(w == "*" or w == h for w, h in zip(want, have))


def unit_arrays(entry: dict, config: dict):
    """遍历一个条目里**配置指定的**效果数组：产出 `(位置, 根下标, 项下标, 数组)`。

    收集与迁移共用这一个遍历，两处不会各写一套「哪里算匹配单位」而慢慢分叉。
    `数组` 是**数组对象本身**（迁移要就地改写）；`项下标` 是该位置内第几项。
    根下标为 None 表示这一项来自 `位置` 配置而不是 `根列表`。
    """

    roots_key = config.get("根列表")
    if roots_key:
        for root_index, root in enumerate(_roots(entry)):
            effects = root.get(EFFECT)
            if not _is_effect_array(effects):
                continue
            for item_index in range(len(effects)):
                yield (f"{roots_key}[{root_index}]/{EFFECT}[{item_index}]",
                       root_index, item_index, effects)

    patterns = config.get("位置") or ()
    if not patterns:
        return

    def visit(node: Any, path: str):
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}/{key}"
                if _is_effect_array(value) and any(_matches(p, child) for p in patterns):
                    yield child, value
                    # **不再往里递归**：效果项里的 `监听事件.效果`、`尝试执行.效果`
                    # 是模板主体的一部分，由展开还原。曾经漏了这个 `continue`，
                    # 内层片段被当成独立候选，排名会被它们占满。
                    continue
                yield from visit(value, child)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                yield from visit(item, f"{path}/[{index}]")

    for path, array in visit(entry, ""):
        for item_index in range(len(array)):
            yield f"{path}[{item_index}]", None, item_index, array


def _collect_effects() -> dict[tuple[str, ...], dict]:
    """收集全部面的效果数组项，按动作序列分桶。

    实例是 `(标识, 效果, 面)` 三元组。面是分簇与排名归一用的——同名效果在不同面上
    必须分开成模板，否则模板库会把「同一机制的两份」混成一份。

    实例标识保留来源（`面:编号:位置`）：同一条目编号只保证面内唯一，跨面会撞
    （功法与真意都有 `41xxxx` 段号）。

    **不剔除键序与多数序不同的实例**：它们的差异由引用自己的 `顺序` 键兜住
    （见 `templates.restore_reference`）。曾经在这里剔过一次，结果是白白丢掉约
    四分之一的可覆盖实例。
    """

    groups: dict[tuple[str, ...], dict] = {}
    for segment, config in SEGMENTS.items():
        for path in sorted(config["目录"].glob(config["模式"])):
            document = json.loads(path.read_text(encoding="utf-8"))
            entries = document if isinstance(document, list) else [document]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                identity = str(entry.get("编号") or entry.get("名称") or path.stem)
                where = f"{segment}:{identity}"
                for card_id, effect in _collect_from_entry(entry, where, config):
                    key = tuple(_ability_sequence(effect, []))
                    bucket = groups.setdefault(key, {"实例": []})
                    bucket["实例"].append((card_id, effect, segment))
    return groups


def _shape(node: Any) -> tuple[str, ...]:
    """结构签名：全部**标量叶子位置**的路径。

    为什么用叶子路径而不是动作序列：动作序列只说「装配了哪些原子能力」，说不清
    「哪个位置有没有那个键」。实测一个动作序列下的实例会分成几种字段集合
    （某条有 `数值/最高值`、另一条没有），`_build_template` 要求**某个实例能承载
    全部参数位置**，一种形态的实例承载不了另一种，整个动作序列就被放弃了。
    按结构签名先分簇，每簇各自成模板，这类实例就救得回来。

    口径必须与 `_derive_params` 的路径**完全一致**（只到标量为止，不进标量内部），
    否则「结构相同的两条实例」会被算成不同簇，簇被切碎、覆盖率反而下降
    （实测：用「含列表下标的全路径」会把 6,405 条切到只剩 2,614 条）。
    """

    out: set[str] = set()

    def walk(current: Any, path: str) -> None:
        if isinstance(current, dict):
            # **占位符本身不是结构**：`{"$参数": "p1"}` 只是「这里会填东西」的标记。
            # 记它自己的路径、不带额外后缀——占位符叫什么名不该影响签名（实测两处
            # 口径不一会让同一簇在生成器与迁移两边算出不同签名）。
            if set(current) == {"$参数"}:
                out.add(path)
                return
            for key, value in current.items():
                walk(value, f"{path}/{key}")
        elif isinstance(current, list):
            for index, item in enumerate(current):
                walk(item, f"{path}/[{index}]")
        else:
            out.add(path)

    walk(node, "")
    return tuple(sorted(out))


def _clusters(instances: list[tuple[str, dict, str]]) -> list[list[tuple[str, dict, str]]]:
    """把同一动作序列的实例按**面 + 结构签名**分簇，顺序稳定。

    面必须进簇的标识：不同面的同名效果必须分开管——否则「面」只能记成簇里第一条实例
    的来源，排名归一和迁移核对全错位（实测把 功法 5,188/真意 1,295/器律 141 算成
    6,511/272/7，总数还多了 166）。
    """

    buckets: dict[tuple[str, tuple[str, ...]], list[tuple[str, dict, str]]] = (
        collections.defaultdict(list)
    )
    for instance in instances:
        buckets[(instance[2], _shape(instance[1]))].append(instance)
    return [buckets[sig] for sig in sorted(buckets)]


def _collect_units() -> list[dict]:
    """模板的**生成单元**：`{"序列", "签名", "面", "实例"}`。

    `(面, 结构签名)` 是簇的标识；生成器与迁移都用它，所以重跑得到同一份库。
    """

    units: list[dict] = []
    for key, bucket in _collect_effects().items():
        for cluster in _clusters(bucket["实例"]):
            units.append({
                "序列": key,
                "签名": _shape(cluster[0][1]),
                "面": cluster[0][2],
                "实例": cluster,
            })
    return units


def _ranked_units(units: list[dict]) -> list:
    """按「**本面内**省下的节点数」排序，同分时按内容排序，保证与输入顺序无关。

    归一化的意义：新面的效果多是片段级（挂在 `阶段.常驻能力`、`战斗状态.监听` 上），
    簇多而小。若按绝对收益排名，靠前的名额会被大量小片段占走，三段里本来成簇的大效果
    反而凑不成模板——实测三段覆盖率因此从 6,405 条掉到 3,605 条。

    做法：先算每个面「簇的平均节点成本」，排名分 = 本簇收益 ÷ 该面平均值。这样
    「本面内偏大的簇」优先，各面互不挤占；归一只是排序口径，不影响生成的模板内容。
    """

    totals: dict[str, list[float]] = {}
    for unit in units:
        totals.setdefault(unit["面"], []).append(_node_cost(unit["实例"][0][1]))
    scale = {face: (sum(costs) / len(costs) if costs else 1.0)
             for face, costs in totals.items()}

    def score(unit: dict) -> float:
        cost = _node_cost(unit["实例"][0][1])
        return -len(unit["实例"]) * cost / max(scale.get(unit["面"], 1.0), 1.0)

    return sorted(units, key=lambda unit: (score(unit), unit["序列"], unit["签名"]))


def _list_archetypes(units: list[dict]) -> None:
    ranked = _ranked_units(units)
    total_nodes = 0
    for unit in ranked:
        total_nodes += len(unit["实例"]) * _node_cost(unit["实例"][0][1])
    total = sum(len(unit["实例"]) for unit in ranked)
    print(f"效果数组项 {total} 条，结构簇 {len(ranked)} 个（按面归一排名）")
    print(f"{'排名':<4}{'次数':>5}{'节点':>6}{'合计':>9}  {'面':<8}动作序列")
    for index, unit in enumerate(ranked[:20], 1):
        instances = unit["实例"]
        cost = _node_cost(instances[0][1])
        share = len(instances) * cost * 100.0 / max(total_nodes, 1)
        print(f"{index:<4}{len(instances):>5}{cost:>6}{len(instances)*cost:>9}"
              f"  {unit['面']:<8}{' > '.join(unit['序列'][:4])}  ({share:>4.1f}%)")


def _derive_params(instances) -> tuple[dict[str, str], list[str]]:
    """从实例数据机械推导参数分组。

    规则：把每个「取值会变」的位置写成一个**向量**（在每个实例里的取值），向量相同
    的位置归为同一个参数。这样同一张卡里始终同值的东西会被合并成一个参数
    （原型 1 里状态名有 4 处、层数有 3 处，各自合并成 1 个），而恰好取过相同值的
    不同参数不会被误并。

    返回的**参数标识是稳定编号 `p1`…`pN`**，不带语义——语义标签会撞名（不同参数
    可能落在同名位置，如两处 `效果·名称`），一旦按标签合并实参就会误判成
    「同一个参数取值不同」。要显示用 `_param_labels`。
    """

    per_instance: list[dict[str, Any]] = []
    all_paths: set[str] = set()
    for _card_id, effect, _face in instances:
        leaves: dict[str, Any] = {}
        _walk_leaves(effect, "", leaves)
        per_instance.append(leaves)
        all_paths |= set(leaves)

    def vector(path: str) -> tuple[str, ...]:
        return tuple(
            json.dumps(item.get(path, _ABSENT), ensure_ascii=False, sort_keys=True)
            for item in per_instance
        )

    varying = [path for path in sorted(all_paths) if len(set(vector(path))) > 1]

    order: list[tuple[str, ...]] = []
    mapping: dict[str, str] = {}
    for path in varying:
        signature = vector(path)
        if signature not in order:
            order.append(signature)
        mapping[path] = f"p{order.index(signature) + 1}"
    names = [f"p{index}" for index in range(1, len(order) + 1)]
    return mapping, names


def _param_labels(mapping: dict[str, str], labels: dict[str, str] | None = None) -> dict[str, str]:
    """参数标识 -> 显示用标签。标签不参与任何匹配，只影响打印与文档。"""

    if labels:
        return {owner: labels.get(owner, owner) for owner in set(mapping.values())}
    by_param: dict[str, list[str]] = {}
    for path, owner in mapping.items():
        by_param.setdefault(owner, []).append(path)
    result: dict[str, str] = {}
    used: dict[str, int] = {}
    for owner, paths in by_param.items():
        base = _position_label(sorted(paths)[0])
        seen = used.get(base, 0)
        used[base] = seen + 1
        result[owner] = base if seen == 0 else f"{base}#{seen + 1}"
    return result


def _union_order(nodes: list[Any]) -> Any:
    """把若干同构节点的键序合成一个**超序列**。

    为什么需要：模板主体的键序就是**展开结果的键序**，而展开不重排；所以模板一旦定序，
    所有实例都以它为准。

    定序规则是**多数序**，不是「第一个实例的序」：实测原文自身的键序并非处处自洽
    （同一原型里同一位置的键序有 2 种写法，散在 257 个位置上），取第一个实例会跟着
    输入文件的排序走，既不确定，也会把多数实例判成「还原不了」。

    做法：先按出现次数选出该位置的主序（票数相同取字典序靠前者，保证确定性），再按
    「遇到新键就插到当前键之后」把主序之外的键合进来，于是每个实例的键序都是结果的
    子序列——除了那些本身与多数序冲突的少数实例，它们由回环判据拒绝迁移。
    """

    if not nodes:
        return None
    first = next((node for node in nodes if node is not None), None)
    if first is None:
        return None
    if isinstance(first, dict):
        dicts = [node for node in nodes if isinstance(node, dict)]
        ordered = _majority_order(dicts)
        for key in list(ordered):
            ordered[key] = _union_order([node[key] for node in dicts if key in node])
        return ordered
    if isinstance(first, list):
        length = max((len(node) for node in nodes if isinstance(node, list)), default=0)
        return [
            _union_order(
                [node[index] for node in nodes
                 if isinstance(node, list) and index < len(node)]
            )
            for index in range(length)
        ]
    return first


def _majority_order(nodes: list[dict]) -> dict[str, Any]:
    """按多数序定一个字典的键序；票数相同取字典序靠前者，保证结果与输入顺序无关。"""

    votes: collections.Counter = collections.Counter(tuple(node) for node in nodes)
    winner = max(sorted(votes), key=lambda order: votes[order])
    ordered: dict[str, Any] = {key: None for key in winner}
    for node in nodes:
        previous: str | None = None
        for key in node:
            if key not in ordered:
                ordered[key] = None
                if previous is not None:
                    ordered = _move_after(ordered, key, previous)
            previous = key
    return ordered


def _move_after(ordered: dict[str, Any], key: str, after: str) -> dict[str, Any]:
    """把刚插入的 `key` 移到 `after` 之后，保持「新键紧跟其首见位置」的语义。"""

    items = [(k, v) for k, v in ordered.items() if k != key]
    index = next((i for i, (k, _) in enumerate(items) if k == after), len(items) - 1)
    items.insert(index + 1, (key, ordered[key]))
    return dict(items)


def _merge_instance(instances) -> dict:
    """把一簇实例的**键与值合成一份基座**：后写的覆盖先写的。

    用于「没有任何单条实例写全全部参数位置」的簇。基座里因此会出现该条实例原本没有
    的键——那些键对应的位置在它那里是「缺省」，由 `_bind` 记成 `_ABSENT`、展开时删掉，
    所以不影响它的还原。
    """

    def merge(nodes: list[Any]) -> Any:
        first = nodes[0]
        if isinstance(first, dict):
            merged: dict[str, Any] = {}
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                for key, value in node.items():
                    if key in merged:
                        merged[key] = merge([merged[key], value])
                    else:
                        merged[key] = value
            return merged
        if isinstance(first, list):
            length = max((len(node) for node in nodes if isinstance(node, list)), default=0)
            return [
                merge([node[index] for node in nodes
                       if isinstance(node, list) and index < len(node)])
                for index in range(length)
            ]
        return first

    return merge([effect for _cid, effect, _face in instances])


def _build_template(instances, params: dict[str, str]):
    """取一个实例做形状，按参数表把位置标成占位符。

    有些参数只在部分实例里出现（原型 1 的 21 个实例没有 `数值/最高值`），所以**逐个
    实例**尝试写占位符：哪个实例有这条路径就在它身上标，标不到就跳过。带占位符的那份
    实例成为模板基底，再由 `_expand` 展开——有该参数的实例会填回值，没有的实例删掉
    那个键。

    一簇里若**没有任何单条实例写全**全部参数位置（实测 318 条效果栽在这里，整簇被
    放弃），就退而用 `_merge_instance` 合成的基座；它对每条实例都成立，因为缺的键在
    各自那里本来就记作「缺省」。
    """

    template: dict | None = None
    for _card_id, effect, _face in instances:
        try:
            candidate = json.loads(json.dumps(effect, ensure_ascii=False))
            for path, name in params.items():
                _set_leaf(candidate, path, {"$参数": name})
        except (KeyError, IndexError):
            continue
        template = candidate
        break
    if template is None:
        try:
            candidate = _merge_instance(instances)
            for path, name in params.items():
                _set_leaf(candidate, path, {"$参数": name})
        except (KeyError, IndexError) as exc:
            raise KeyError("没有任何实例能承载全部参数位置") from exc
        template = candidate
    return _apply_order(
        template, _union_order([effect for _cid, effect, _face in instances])
    )


def _apply_order(node: Any, order: Any) -> Any:
    """把 `order`（键序超序列）施加到 `node` 上，返回键序一致的副本。"""

    if isinstance(node, dict) and isinstance(order, dict):
        ordered: dict[str, Any] = {}
        for key in order:
            if key in node:
                ordered[key] = _apply_order(node[key], order[key])
        for key, value in node.items():
            if key not in ordered:
                ordered[key] = value
        return ordered
    if isinstance(node, list) and isinstance(order, list):
        return [
            _apply_order(item, order[index] if index < len(order) else None)
            for index, item in enumerate(node)
        ]
    return node


def _bind(instance: dict, params: dict[str, str]) -> dict[str, Any]:
    """从一个真实实例里读出参数值。

    实测同一原型内部并非完全同构：原型 1 的 392 个实例有 4 种字段集合，
    21 个实例没有 `数值/最高值`，12 个没有 `每次行动最多触发`。所以参数分两种：

    - 实例里有该路径 -> 记为实参
    - 实例里没有该路径 -> 记为 `_ABSENT`，展开时把那个键**删掉**，而不是填个值
    """

    leaves: dict[str, Any] = {}
    _walk_leaves(instance, "", leaves)
    bound: dict[str, Any] = {}
    for path, name in params.items():
        value = leaves.get(path, _ABSENT)
        if name in bound and bound[name] is not _ABSENT and value is not _ABSENT \
                and bound[name] != value:
            raise ValueError(f"同名参数 {name} 在不同位置取值不同：{bound[name]!r} vs {value!r}")
        if name not in bound or bound[name] is _ABSENT:
            bound[name] = value
    return bound


def _expand(node: Any, bound: dict[str, Any]) -> Any:
    """按实参展开模板；实参为 `_ABSENT` 的键从结果里删掉。"""

    if isinstance(node, dict):
        if set(node) == {"$参数"}:
            name = node["$参数"]
            if name not in bound:
                raise KeyError(f"展开缺少参数：{name}")
            return bound[name]
        result: dict[str, Any] = {}
        for key, value in node.items():
            expanded = _expand(value, bound)
            if expanded is _ABSENT:
                continue
            result[key] = expanded
        return result
    if isinstance(node, list):
        return [_expand(item, bound) for item in node]
    return node


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _roundtrip(rank: int, units: list[dict], show: int) -> int:
    unit = _ranked_units(units)[rank - 1]
    key, instances = unit["序列"], unit["实例"]
    print(f"排名 {rank}（面：{unit['面']}）：{len(instances)} 个实例，动作序列")
    print(f"  {' > '.join(key)}")
    print()

    params, names = _derive_params(instances)
    labels = _param_labels(params, ARCHETYPE_1_LABELS if rank == 1 else None)
    counts: dict[str, int] = collections.Counter(params.values())
    print(f"机械推出的参数：{len(names)} 个，覆盖 {len(params)} 个变化位置")
    for name in names:
        paths = [path for path, owner in params.items() if owner == name]
        print(f"  {name}（{labels[name]}）：{counts[name]} 处  {paths[0]}")
    print()

    template = _build_template(instances, params)
    print(f"模板：{_node_cost(template)} 个节点（原实例 {_node_cost(instances[0][1])} 个）")
    print()

    mismatches: list[str] = []
    for card_id, effect, _face in instances:
        bound = _bind(effect, params)
        rebuilt = _expand(template, bound)
        if _dumps(rebuilt) != _dumps(effect):
            mismatches.append(card_id)
        if show and card_id == instances[min(show, len(instances)) - 1][0]:
            print(f"--- 实例 {card_id} 的参数 ---")
            for name in names:
                paths = [path for path, owner in params.items() if owner == name]
                print(f"  {name} = {json.dumps(bound.get(name), ensure_ascii=False)}")
            print("  展开结果与原实例逐字节一致：", _dumps(rebuilt) == _dumps(effect))
            print()

    ok = len(instances) - len(mismatches)
    print(f"回环验证：{ok}/{len(instances)} 一致")
    if mismatches:
        print(f"  不一致：{'、'.join(mismatches[:10])}")
        return 1
    print("  模板机制成立：全部实例都能由「模板 + 参数」无损还原")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--列表", action="store_true", help="列出现有结构簇（按面归一排名）")
    parser.add_argument("--原型", type=int, default=0, help="对第 N 个排名做回环验证")
    parser.add_argument("--展示", type=int, default=0, help="展示第 N 个实例的参数")
    args = parser.parse_args()

    units = _collect_units()
    if args.列表:
        _list_archetypes(units)
        return 0
    if args.原型:
        return _roundtrip(args.原型, units, args.展示)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
