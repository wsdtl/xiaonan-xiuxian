"""验证字段契约引擎的行为契约。

`game/core/data/schema.py` 是通用校验引擎，`game/core/combat/schema.py` 是它的
战斗适配，`game/core/combat/builds.py` 是四类构筑各自形状的执行者。引擎决定
"数据不合契约即阻止启动"，因此它的判定必须稳定：合法数据必须通过，各类非法
数据必须**被拒绝且给出可定位的路径**。

本脚本用真实数据与定向破坏做断言，不依赖任何基准文件：

- 真实数据整体校验必须通过；
- 每类破坏必须被拒绝，且错误信息包含预期路径片段与关键词；
- 破坏样本必须与原始数据不相等（防止探针自己失效）。

用法：

```powershell
.venv/Scripts/python.exe -X utf8 tools/验证契约引擎.py
```

退出码 0 表示全部通过。
"""

from __future__ import annotations

import copy
import pathlib
import sys
from collections.abc import Callable, Mapping
from typing import Any

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.core.combat.builds import (  # noqa: E402
    BUILD_SECTIONS,
    load_build_contracts,
    validate_builds,
)
from game.core.combat.foundation import (  # noqa: E402
    EXECUTOR_CATEGORIES,
    rule_validator,
)
from game.core.combat.schema import RuleSchemaValidator  # noqa: E402
from game.core.data import JsonDataService  # noqa: E402


def _plain(value: object) -> object:
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(k): _plain(v) for k, v in value.items()}  # type: ignore[union-attr]
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _validator(definition: dict) -> RuleSchemaValidator:
    return RuleSchemaValidator(
        abilities=definition["原子能力"],
        executor_categories=EXECUTOR_CATEGORIES,
        attributes=definition["属性"],
        resources=definition["资源"],
        events=definition["事件"],
    )


#: schema 自身不合法的破坏：`validate_definitions` 校验的是契约写对没有。
#: 注意「删掉某字段规格」「把字段类型换成对象」都仍是合法契约，不属于此类——
#: 它们只改变约束，数据侧才会因此失败（见下方 DATUM_MUTATIONS）。
SCHEMA_MUTATIONS: dict[str, tuple[Callable[[dict], None], str]] = {
    "未知顶层字段": (
        lambda node: node.__setitem__("额外字段", 1),
        "规则不认识字段",
    ),
    "未知字段规格键": (
        lambda node: node["字段"].__setitem__(
            "名称", {"类型": "字符串", "必填": True, "不存在的键": 1}
        ),
        "规则不认识字段",
    ),
    "未知字段类型": (
        lambda node: node["字段"].__setitem__("名称", {"类型": "不存在的类型"}),
        "未知字段类型",
    ),
    "数值上下界倒置": (
        lambda node: node["字段"].__setitem__("释放顺序", {"类型": "整数", "最小": 5, "最大": 1}),
        "最小值不能大于最大值",
    ),
    "非对象类型声明子字段": (
        lambda node: node["字段"].__setitem__("名称", {"类型": "字符串", "字段": {}}),
        "只有对象类型可以声明子字段",
    ),
    "引用不存在的原子能力": (
        lambda node: node["字段"].__setitem__(
            "额外代价", {"类型": "能力数组", "允许能力": ["不存在的原子能力"]}
        ),
        "未知原子能力",
    ),
    "非法类别": (lambda node: node.__setitem__("类别", "不存在的类别"), "未知类别"),
    "非法执行器": (
        lambda node: node.__setitem__("执行器", "不存在的执行器"),
        "战斗核心没有执行器",
    ),
    "默认值本身不合法": (
        lambda node: node["字段"].__setitem__("精神消耗", {"类型": "整数", "默认": "不是数字"}),
        "必须是整数",
    ),
}

EXPECT_UNKNOWN_FIELD = "规则不认识字段"
EXPECT_NOT_STRING = "必须"


class _CardSource:
    """只提供 `entities()` 的最小数据源，供构筑契约断言使用。"""

    def __init__(self, cards: Mapping[str, Mapping[str, Any]]) -> None:
        self._cards = cards

    def entities(self, section: str) -> Mapping[str, Any]:
        return self._cards.get(section, {})


def _first_card(data: JsonDataService, section: str) -> dict:
    entities = data.entities(section)
    content_id = next(iter(entities))
    return dict(_plain(entities[content_id]))  # type: ignore[arg-type]


def _first_ability_node(card: dict) -> dict | None:
    """挑一个真实的、带 `能力` 的深层节点作为破坏样本。"""

    def walk(node: object) -> dict | None:
        if isinstance(node, dict):
            if isinstance(node.get("能力"), str) and len(node) > 2:
                return node
            for value in node.values():
                found = walk(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = walk(value)
                if found is not None:
                    return found
        return None

    return walk(card.get("能力"))


def check_datum_constraints(definition: dict, failures: list[str]) -> None:
    """证明 schema 真的在约束数据，而不只是被声明。"""

    data = JsonDataService("data")
    data.initialize()
    sample = _first_ability_node(_first_card(data, "功法"))
    if sample is None:
        failures.append("没有可直接破坏的功法节点，无法验证数据侧约束")
        return

    cases: dict[str, tuple[Callable[[dict], None], str]] = {
        "节点多写未声明字段": (
            lambda target: target.__setitem__("契约未声明的字段", 1),
            EXPECT_UNKNOWN_FIELD,
        ),
        "节点换成未登记的原子能力": (
            lambda target: target.__setitem__("能力", "不存在的原子能力"),
            "未知原子能力",
        ),
    }
    numeric_key = next(
        (
            key
            for key, value in sample.items()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ),
        None,
    )
    if numeric_key is not None:
        cases["数值字段给文本"] = (
            lambda target, key=numeric_key: target.__setitem__(key, "不是数字"),
            EXPECT_NOT_STRING,
        )
    for label, (mutate, expected) in cases.items():
        broken = copy.deepcopy(sample)
        mutate(broken)
        if broken == sample:
            failures.append(f"{label}：破坏未生效，探针失效")
            continue
        try:
            _validator(definition).validate_node(broken, "功法.能力")
        except Exception as exc:
            if expected not in str(exc):
                failures.append(f"{label}：错误信息缺少 {expected!r}，实际 {exc}")
        else:
            failures.append(f"{label}：违反契约的数据未被拒绝")
    print(f"数据侧约束：{len(cases)} 类破坏，逐类断言完成")


BUILD_MUTATIONS: dict[str, tuple[str, Callable[[dict], None], str]] = {
    "真意换成主动技能": (
        "真意",
        lambda card: card["能力"][0].__setitem__("能力", "主动技能"),
        "只允许 被动技能",
    ),
    "气机多出第二项能力": (
        "气机",
        lambda card: card["能力"].append(copy.deepcopy(card["能力"][0])),
        "必须正好有1项根能力",
    ),
    "器律丢掉器阶": (
        "器律",
        lambda card: card.pop("器阶"),
        "字段不符合器律契约",
    ),
    "功法多出词条表": (
        "功法",
        lambda card: card.__setitem__("词条", {}),
        "字段不符合功法契约",
    ),
    "属性构成不合计一百": (
        "功法",
        lambda card: card.__setitem__("属性构成", {"火": 80, "木": 40}),
        "必须合计 100",
    ),
    "权重与另一张卡重复": (
        "功法",
        lambda card: card.__setitem__("权重", None),
        "权重与",
    ),
}


def check_build_contracts(data: JsonDataService, failures: list[str]) -> None:
    """四类构筑各自的形状必须被严格执行，不能互相借用。"""

    definition = dict(_plain(data.dataset("战斗定义")))  # type: ignore[arg-type]
    validator = rule_validator(definition)
    contracts = load_build_contracts(data)
    base: dict[str, dict[str, dict]] = {}
    for section in BUILD_SECTIONS:
        entities = data.entities(section)
        ids = list(entities)[:2]
        base[section] = {
            str(content_id): dict(_plain(entities[content_id]))  # type: ignore[arg-type]
            for content_id in ids
        }
    if not validate_builds(_CardSource(base), contracts, validator):
        failures.append("真实构筑未能通过契约校验")
        return
    # 让「权重重复」有第二个真实权重可用。
    own_id = next(iter(base["功法"]))
    keys = list(base["功法"])
    duplicate = base["功法"][keys[1]].get("权重")

    for label, (section, mutate, expected) in BUILD_MUTATIONS.items():
        cards = {
            name: {cid: copy.deepcopy(card) for cid, card in entries.items()}
            for name, entries in base.items()
        }
        target = cards[section][next(iter(cards[section]))]
        if label == "权重与另一张卡重复":
            target["权重"] = duplicate
        else:
            mutate(target)
        if target == base[section][own_id if section == "功法" else next(iter(base[section]))]:
            failures.append(f"{label}：破坏未生效，探针失效")
            continue
        try:
            validate_builds(_CardSource(cards), contracts, validator)
        except Exception as exc:
            if expected not in str(exc):
                failures.append(f"{label}：错误信息缺少 {expected!r}，实际 {exc}")
        else:
            failures.append(f"{label}：跨方向的形状未被拒绝")
    print(f"构筑契约：{len(BUILD_MUTATIONS)} 类破坏，逐类断言完成")


def main() -> int:
    data = JsonDataService("data")
    data.initialize()
    definition = dict(_plain(data.dataset("战斗定义")))  # type: ignore[arg-type]

    failures: list[str] = []

    # 1. 真实数据必须整体通过。
    try:
        _validator(definition).validate_definitions()
    except Exception as exc:
        failures.append(f"真实数据未通过校验：{type(exc).__name__}: {exc}")
    abilities = len(definition["原子能力"])
    print(f"真实数据通过：{abilities} 个原子能力")

    # 2. 每类 schema 破坏必须被拒绝，并给出可定位的信息。
    target = "主动技能"
    if target not in definition["原子能力"]:
        failures.append(f"缺少探针所需的定义：{target}")
    else:
        for label, (mutate, expected) in SCHEMA_MUTATIONS.items():
            table = dict(definition)
            mutated = copy.deepcopy(definition["原子能力"])
            mutate(mutated[target])
            if mutated == definition["原子能力"]:
                failures.append(f"{label}：破坏未生效，探针失效")
                continue
            table["原子能力"] = mutated
            try:
                _validator(table).validate_definitions()
            except Exception as exc:
                if expected not in str(exc):
                    failures.append(f"{label}：错误信息缺少 {expected!r}，实际 {exc}")
            else:
                failures.append(f"{label}：契约破坏未被拒绝")
        print(f"契约自校验：{len(SCHEMA_MUTATIONS)} 类破坏，逐类断言完成")

    # 3. 数据侧破坏必须被拒绝。
    check_datum_constraints(definition, failures)

    # 4. 四类构筑各自的形状必须被拒绝跨方向借用。
    check_build_contracts(data, failures)

    print()
    if failures:
        print(f"契约引擎行为不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  {item}")
        return 1
    print("契约引擎行为验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
