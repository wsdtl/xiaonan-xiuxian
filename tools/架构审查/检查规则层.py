"""规则层审查：效果之外的规则必须「登记得下、条件站得住、渲染得出来、内容只用登记过的」。

规则层是 `data/战斗/定义/规则层.json`，代码侧是 `game/core/combat/rules.py` 的
**拦截点表** `INTERCEPTION_POINTS`。这一层的设计目标是**加一条规则和加一张功法一样简单**：
一条规则 = 一个拦截点 + 一组条件 + 一个处置，条件用已登记的条件原子写，参数用 `$字段`
占位。于是判据也必须是通用的——**不为任何具体规则写一条判据**，只核五件事：

1. **登记表自洽**：直接跑启动期那份校验（归属 / 拦截点 / 处置 / 优先级 / 可改写 / 卡面 /
   条件真的按原子能力契约校验 / 参数不许有死项 / **条件不许为空** / 行级载体必须真有
   技能行读它），两处同一个函数，不留缝。
2. **拦截点在实现表里，且方向一致**：`INTERCEPTION_POINTS` 里每个拦截点都要有规则用它
   （没人用的拦截点是死代码），每条规则的载体必须是该拦截点认的载体。
3. **能被标准探针覆盖**：规则条件匹配的标签必须落在该拦截点的「探针标签」里，
   否则「加规则自动获得行为验证」不成立——这时要么改条件，要么扩探针场景（那是代码）。
4. **渲染路径**：每条规则都渲染得出来（拿探针卡跑一遍真渲染器）。
5. **内容只用登记过的**：六面卡片与战场环境里出现的规则名必须是登记过的，且载体写对。

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
    """登记表自洽：跑启动期那份校验（含条件的原子能力契约校验）。"""

    from game.core.combat.foundation import rule_validator
    from game.core.combat.rules import validate_rule_layer

    validator = rule_validator(
        {
            "原子能力": _abilities(),
            "属性": json.loads((ROOT / "data" / "战斗" / "定义" / "属性.json").read_text(encoding="utf-8")),
            "资源": json.loads((ROOT / "data" / "战斗" / "定义" / "资源.json").read_text(encoding="utf-8")),
            "事件": json.loads((ROOT / "data" / "战斗" / "定义" / "事件.json").read_text(encoding="utf-8")),
        }
    )
    try:
        validate_rule_layer(layer, _abilities(), validator)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    return []


def check_interception_points(layer: dict[str, dict]) -> list[str]:
    """拦截点与实现表双向核对：没人用的拦截点是死代码。"""

    from game.core.combat.rules import INTERCEPTION_POINTS

    problems: list[str] = []
    used = {str(definition.get("拦截点") or "") for definition in layer.values()}
    for name in sorted(set(INTERCEPTION_POINTS) - used):
        problems.append(f"拦截点没有任何规则用它：{name}（要么登记一条规则，要么删掉实现）")
    for name, definition in sorted(layer.items()):
        point = INTERCEPTION_POINTS.get(str(definition.get("拦截点") or ""))
        if point is None:
            continue  # 登记表自洽那一项已经报过
        if str(definition.get("归属") or "") not in point.carriers:
            problems.append(f"{name} 的载体与拦截点不符：{definition.get('拦截点')}")
    return problems


def check_probe_coverage(layer: dict[str, dict]) -> list[str]:
    """标准探针必须覆盖每条规则的条件标签，否则「加规则自动获得行为验证」不成立。

    两种载体一视同仁：行级规则也要能落进行为判据的场景里（`不可禁用` 的条件就是
    `字段:禁用` + `值:真`），否则一条行级规则可以带着没人验的条件进库。
    """

    from game.core.combat.rules import INTERCEPTION_POINTS, expand_rule, probe_tags

    problems: list[str] = []
    for name, definition in sorted(layer.items()):
        point = INTERCEPTION_POINTS.get(str(definition.get("拦截点") or ""))
        if point is None:
            continue  # 登记表自洽那一项已经报过
        defaults = {
            str(field): spec.get("默认")
            for field, spec in dict(definition.get("字段") or {}).items()
        }
        # 挑一个能让条件全部成立的取值：选项里第一个非空值
        for field, spec in dict(definition.get("字段") or {}).items():
            options = [str(item) for item in spec.get("选项") or []]
            if options:
                defaults[field] = options[0]
        rule = expand_rule(name, defaults, layer)
        missing = probe_tags(rule) - set(point.probe_tags)
        if missing:
            problems.append(
                f"{name} 的条件标签超出标准探针场景：{'、'.join(sorted(missing))}"
                f"（拦截点 {definition.get('拦截点')} 的探针标签：{'、'.join(point.probe_tags)}）"
            )
    return problems


def check_render_path(layer: dict[str, dict]) -> list[str]:
    """每条规则都渲染得出来：拿一张探针卡跑真渲染器。"""

    from game.core.combat.card_text import render_body
    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY, rule_card_text

    unit = [name for name, definition in layer.items() if str(definition.get("归属")) == "单位"]
    line = [name for name, definition in layer.items() if str(definition.get("归属")) == "行"]
    probe = {
        "能力": [
            {
                "能力": RULE_TEXT_ABILITY,
                RULE_FIELD: [{"名称": name} for name in unit],
            }
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
                RULE_FIELD: [{"名称": name}],
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
            if spec.get("默认") not in (None, "")
        }
        expected = rule_card_text(name, defaults, layer)
        if expected not in text:
            problems.append(f"规则 {name} 没有渲染进卡面（应出现「{expected}」）")
    return problems


def check_content_uses(layer: dict[str, dict]) -> list[str]:
    """两个方向：内容用的规则要登记过、载体要写对。"""

    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY

    unit = {name for name, definition in layer.items() if str(definition.get("归属")) == "单位"}
    line = {name for name, definition in layer.items() if str(definition.get("归属")) == "行"}
    problems: list[str] = []
    counts = {"单位": 0, "行": 0}

    def read(where: str, entries, expected: str, source: str) -> None:
        for item in entries or ():
            name = str(dict(item).get("名称") or "")
            allowed = unit if expected == "单位" else line
            counts[expected] += 1
            if name not in allowed:
                problems.append(f"{source} 的 {where} 用了未登记的{expected}级规则：{name or '<空>'}")

    for filename, entry in _cards():
        for node in entry.get("能力") or ():
            if not isinstance(node, dict):
                continue
            if node.get("能力") == RULE_TEXT_ABILITY:
                read("规则文本", node.get(RULE_FIELD), "单位", filename)
            elif node.get(RULE_FIELD):
                read(str(node.get("能力")), node.get(RULE_FIELD), "行", filename)
    print(f"  内容用到单位级规则 {counts['单位']} 次 · 行级规则 {counts['行']} 次")
    return problems


CHECKS = (
    ("登记表自洽", check_registry),
    ("拦截点与实现", check_interception_points),
    ("标准探针覆盖", check_probe_coverage),
    ("渲染路径", check_render_path),
    ("内容只用登记过的", check_content_uses),
)


def main() -> int:
    layer = json.loads(REGISTRY.read_text(encoding="utf-8"))
    print(f"规则层：登记 {len(layer)} 条")
    problems: list[str] = []
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
