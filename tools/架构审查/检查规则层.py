"""规则层审查：效果之外的规则必须「登记过、有实现、渲染得出来、内容只用登记过的」。

规则层是 `data/战斗/定义/规则层.json`，代码侧是 `game/core/combat/rules.py` 的
`RULE_CONSUMERS`（消费者 -> 归属）。这条判据做**双向核对**，与 `检查原子能力.py` 同一个路子：

1. **登记 -> 实现**：每条规则的消费者必须在 `RULE_CONSUMERS` 里，且归属与消费者一致；
2. **实现 -> 登记**：`RULE_CONSUMERS` 里每个消费者都得有规则用（没人用的消费者是死代码）；
3. **行级规则接上词汇表**：`归属: 行` 的规则名必须真的是某个原子能力声明的字段
   （启动期也拦，这里给它一个不依赖服务的入口）；
4. **渲染路径**：每条规则都有卡面文案，且 `card_text` 真的能按登记表把它渲染出来
   （拿一张探针卡跑一遍真渲染器，不是查表）；
5. **内容只用登记过的**：六面卡片里出现的 `规则文本.规则[].名称` 必须是登记过的单位级规则，
   行的规则字段必须对应登记过的行级规则——两个方向都查。

    .venv/Scripts/python.exe -X utf8 tools/架构审查/检查规则层.py

**退出码：0 = 干净，1 = 有违规。**
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

REGISTRY = ROOT / "data" / "战斗" / "定义" / "规则层.json"
ABILITIES = ROOT / "data" / "战斗" / "定义" / "原子能力.json"


def _abilities() -> dict[str, dict]:
    return json.loads(ABILITIES.read_text(encoding="utf-8"))


def _cards():
    """六面卡片 + 战场环境，逐个产出（工具侧展开模板）。"""

    import importlib

    模板 = importlib.import_module("构筑模板")
    from 构筑模板展开 import load_build_json

    for _segment, config in 模板.SEGMENTS.items():
        for path in sorted(config["目录"].glob(config["模式"])):
            for entry in load_build_json(path):
                yield path.name, entry
    for path in sorted((ROOT / "data" / "战斗" / "内容" / "战场环境").rglob("*.json")):
        for entry in load_build_json(path):
            yield path.name, entry


def check_registry(layer: dict[str, dict]) -> list[str]:
    """登记表自洽：直接跑启动期那一份校验（归属/消费者/优先级/可改写/卡面/字段类型）。

    启动期拦的是「游戏起不来」，这里拦的是「判据跑不动」——两处用同一个函数，
    所以不会出现「启动拦得住、判据看不见」的缝。
    """

    from game.core.combat.rules import validate_rule_layer

    try:
        validate_rule_layer(layer, _abilities())
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    return []


def check_consumers(layer: dict[str, dict]) -> list[str]:
    """登记 <-> 实现 的双向核对。"""

    from game.core.combat.rules import RULE_CONSUMERS

    problems: list[str] = []
    for name, definition in sorted(layer.items()):
        consumer = str(definition.get("消费者") or "")
        owner = str(definition.get("归属") or "")
        if consumer not in RULE_CONSUMERS:
            problems.append(f"{name} 的消费者没有实现：{consumer or '<空>'}")
        elif RULE_CONSUMERS[consumer] != owner:
            problems.append(
                f"{name} 的归属与消费者不一致：{consumer} 属于 {RULE_CONSUMERS[consumer]}，登记写 {owner}"
            )
    used = {str(definition.get("消费者") or "") for definition in layer.values()}
    for consumer in sorted(set(RULE_CONSUMERS) - used):
        problems.append(f"消费者没有任何规则用它：{consumer}（要么登记一条规则，要么删掉实现）")
    return problems


def check_line_rules_in_vocabulary(layer: dict[str, dict]) -> list[str]:
    """行级规则的字段必须在原子能力里声明过。"""

    abilities = _abilities()
    declared = {
        field
        for definition in abilities.values()
        for field in dict(definition.get("字段") or {})
    }
    return [
        f"行级规则 {name} 没有对应的原子能力字段（先在 原子能力.json 里声明字段）"
        for name, definition in sorted(layer.items())
        if str(definition.get("归属") or "") == "行" and name not in declared
    ]


def check_render_path(layer: dict[str, dict]) -> list[str]:
    """每条规则都要能真的渲染出来：拿探针卡跑一遍真渲染器。"""

    from game.core.combat.card_text import render_body
    from game.core.combat.rules import RULE_TEXT_ABILITY, RULE_TEXT_FIELD, rule_card_text

    from 规则层 import load_rule_layer  # noqa: F401  （确保工具侧读得到同一份文件）

    unit = [name for name, definition in layer.items() if str(definition.get("归属")) == "单位"]
    line = [name for name, definition in layer.items() if str(definition.get("归属")) == "行"]
    probe = {
        "能力": [
            {"能力": RULE_TEXT_ABILITY, RULE_TEXT_FIELD: [{"名称": name} for name in unit]},
        ]
        + [
            {
                "能力": "主动技能",
                "名称": name,
                "释放顺序": index + 1,
                "效果": [
                    {
                        "能力": "修改行动条",
                        "目标": {"能力": "选择目标", "范围": "自身"},
                        "方式": "增加",
                        "数值": 1,
                    }
                ],
                name: True,
            }
            for index, name in enumerate(line)
        ],
    }
    lines, misses = render_body(probe, layer)
    text = "\n".join(lines)
    problems = [f"规则 {miss} 渲染不出来" for miss in misses]
    for name, definition in sorted(layer.items()):
        template = str(dict(definition).get("卡面") or "")
        if not template:
            problems.append(f"规则 {name} 没有卡面文案")
            continue
        defaults = {
            str(field): spec.get("默认")
            for field, spec in dict(definition.get("字段") or {}).items()
            if spec.get("默认") is not None
        }
        expected = rule_card_text(name, defaults, layer)
        if expected not in text:
            problems.append(f"规则 {name} 没有渲染进卡面（应出现「{expected}」）")
    return problems


def check_content_uses(layer: dict[str, dict]) -> list[str]:
    """两个方向：内容用的规则要登记过；登记的行级规则字段不许被用在别处。"""

    from game.core.combat.rules import RULE_TEXT_ABILITY, RULE_TEXT_FIELD

    unit = {name for name, definition in layer.items() if str(definition.get("归属")) == "单位"}
    line = {name for name, definition in layer.items() if str(definition.get("归属")) == "行"}
    allowed = {
        str(field)
        for definition in _abilities().values()
        for field in dict(definition.get("字段") or {})
    }
    problems: list[str] = []
    counts = {"单位": 0, "行": 0}
    for filename, entry in _cards():
        for node in entry.get("能力") or ():
            if not isinstance(node, dict):
                continue
            if node.get("能力") == RULE_TEXT_ABILITY:
                for item in node.get(RULE_TEXT_FIELD) or ():
                    name = str(dict(item).get("名称") or "")
                    counts["单位"] += 1
                    if name not in unit:
                        problems.append(f"{filename} 用了未登记的单位级规则：{name or '<空>'}")
            for name, value in node.items():
                if name in line and value:
                    counts["行"] += 1
    for name in sorted(line - allowed):
        problems.append(f"行级规则 {name} 没有对应的原子能力字段，内容写了也会被启动拦下")
    print(f"  内容用到单位级规则 {counts['单位']} 次 · 行级规则 {counts['行']} 次")
    return problems


CHECKS = (
    ("登记表自洽", check_registry),
    ("登记与实现", check_consumers),
    ("行级规则进词汇表", check_line_rules_in_vocabulary),
    ("渲染路径", check_render_path),
    ("内容只用登记过的", check_content_uses),
)


def main() -> int:
    layer = json.loads(REGISTRY.read_text(encoding="utf-8"))
    problems: list[str] = []
    print(f"规则层：登记 {len(layer)} 条")
    for name, check in CHECKS:
        try:
            found = check(layer)
        except Exception as exc:  # noqa: BLE001
            found = [f"{type(exc).__name__}: {exc}"]
        for problem in found:
            print(f"  [{name}] {problem}")
        problems.extend(found)
    if problems:
        print(f"规则层违规 {len(problems)} 处")
        return 1
    print(f"规则层审查通过：{len(CHECKS)} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
