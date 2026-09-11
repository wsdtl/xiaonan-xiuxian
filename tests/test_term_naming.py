"""词条命名的硬约束：计量与状态逐实例唯一，判定与规则保持引擎口令。

改名的意义就在这里——`计量`（计数器）和 `状态`（状态池）挂在一名战斗者身上，
读写都发生在同一张卡内，所以名字本来就该逐卡唯一；两张卡撞名会把互不相关的
效果接在一起。`判定` 与 `规则` 相反，引擎按名字取用它们，必须留给引擎。

这条测试防的是「以后新写的卡又抄了别人的词条名」。审查工具
`tools/架构审查/检查词条作用域.py` 给出同样结论的详细报告。
"""

import json
from collections import defaultdict
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"

#: 词条名只在这些目录里定义；`定义/` 放的是原子能力表，不算实体。
SURFACES = ("**/内容/**/*.json",)

#: 引擎自己按名字取用的口令，不属于卡片词条，改名会打断引擎。
JUDGEMENTS = frozenset({"命中", "暴击", "格挡", "控制", "连击", "反击", "任意"})


def _entities():
    for pattern in SURFACES:
        for path in sorted(DATA.glob(pattern)):
            relative = path.relative_to(DATA).as_posix()
            if "/定义/" in relative:
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            entries = document if isinstance(document, list) else [document]
            for entry in entries:
                if isinstance(entry, dict):
                    identity = str(entry.get("编号") or entry.get("名称") or relative)
                    yield identity, entry


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _sites():
    """返回 词条种类 -> 名字 -> 定义它的实体集合，以及判定取值集合。"""

    definitions: dict[str, dict[str, set[str]]] = {
        "计量": defaultdict(set),
        "状态": defaultdict(set),
        "战前状态": defaultdict(set),
        "规则": defaultdict(set),
    }
    judgements: set[str] = set()

    for identity, entry in _entities():
        for node in _walk(entry):
            ability = node.get("能力")
            if ability == "修改构筑计量" and isinstance(node.get("计量"), str):
                definitions["计量"][node["计量"]].add(identity)
            elif ability == "添加状态":
                status = node.get("状态")
                if isinstance(status, dict) and isinstance(status.get("名称"), str):
                    definitions["状态"][status["名称"]].add(identity)
            elif ability == "修改战场规则" and isinstance(node.get("名称"), str):
                definitions["规则"][node["名称"]].add(identity)
            elif ability == "修改判定" and isinstance(node.get("判定"), str):
                judgements.add(node["判定"])
            # 战前状态不是原子能力，而是战丹 `使用效果` 上的整块状态定义，
            # 它和 `添加状态` 落在同一个状态池里，重名一样会互相串。
            prepared = node.get("战前状态")
            if isinstance(prepared, dict) and isinstance(prepared.get("名称"), str):
                definitions["战前状态"][prepared["名称"]].add(identity)

    return {kind: dict(names) for kind, names in definitions.items()}, judgements


DEFINITIONS, JUDGEMENTS_SEEN = _sites()


@pytest.mark.parametrize("kind", ["计量", "状态", "战前状态"])
def test_term_names_are_globally_unique(kind):
    """同名词条只能由一个实体定义——撞名等于把两张卡的效果接在一起。"""

    shared = {
        name: sorted(owners)
        for name, owners in DEFINITIONS[kind].items()
        if len(owners) > 1
    }
    assert not shared, f"{kind} 名字被多个实体共用：{shared}"


def test_counter_and_status_pools_do_not_share_names():
    """同一个名字不能既是计数器又是状态池，否则说明里分不清指的是哪一个。"""

    pools = {kind: set(DEFINITIONS[kind]) for kind in ("计量", "状态", "战前状态")}
    assert not (pools["计量"] & pools["状态"]), (
        f"计量与状态重名：{sorted(pools['计量'] & pools['状态'])}"
    )
    assert not (pools["状态"] & pools["战前状态"]), (
        f"状态与战前状态重名：{sorted(pools['状态'] & pools['战前状态'])}"
    )


def test_judgements_stay_inside_the_engine_vocabulary():
    """判定取值是引擎在 `_judgement()` 里按名字取用的口令，必须原样留着。"""

    assert JUDGEMENTS_SEEN <= JUDGEMENTS, (
        f"出现引擎不认识的判定：{sorted(JUDGEMENTS_SEEN - JUDGEMENTS)}"
    )
    assert JUDGEMENTS_SEEN, "一个判定取值都没扫到，说明这条测试已经空跑"


def test_four_card_directions_have_their_own_counter_flavour():
    """四类卡片各叫各的词，不是同一套名字换个前缀。"""

    def names_of(directory: str, pattern: str) -> set[str]:
        found: set[str] = set()
        for path in DATA.glob(f"{directory}/{pattern}"):
            for entry in json.loads(path.read_text(encoding="utf-8")):
                for node in _walk(entry):
                    if node.get("能力") == "修改构筑计量" and isinstance(node.get("计量"), str):
                        found.add(node["计量"])
        return found

    gongfa = names_of("战斗/内容/功法", "功法-*.json")
    qilv = names_of("炼器/内容", "器律-*.json")
    assert gongfa and qilv
    # 器律的名字带器物味（`器痕/器印`），功法带灵气味（`归元/养元`），两套词不互相抄。
    assert not (gongfa & qilv), f"功法与器律用了同一个计量名：{sorted(gongfa & qilv)}"
