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
from collections.abc import Mapping, Sequence

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
    """每条规则在三处写法上都渲染得出来：根能力 `规则文本`、被动技能行、状态定义。"""

    from game.core.combat.card_text import render_body
    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY, rule_card_text

    unit = [name for name, definition in layer.items() if str(definition.get("归属")) == "单位"]
    line = [name for name, definition in layer.items() if str(definition.get("归属")) == "行"]
    unit_entries = [{"名称": name} for name in unit]
    line_entries = [{"名称": name} for name in line]
    probe = {
        "能力": [
            {"能力": RULE_TEXT_ABILITY, RULE_FIELD: unit_entries},
            # 单位级规则的第二种写法：被动技能行自己的 `规则[]`。
            {
                "能力": "被动技能",
                "名称": "探针载规则",
                "结算顺序": 1,
                "规则": unit_entries,
                "效果": [
                    {
                        "能力": "监听事件",
                        "事件": "战斗开始",
                        "阵营关系": "自身",
                        "效果": [
                            {
                                "能力": "记录战斗事实",
                                "归属": {"能力": "选择目标", "范围": "自身"},
                                "名称": "探针",
                                "值": 1,
                                "方式": "追加",
                                "保留数量": 1,
                            },
                            # 第三种写法：状态定义里的 `规则[]`（跟状态一起生灭）。
                            {
                                "能力": "添加状态",
                                "目标": {"能力": "选择目标", "范围": "自身"},
                                "状态": {
                                    "名称": "探针锁势",
                                    "类别": "正面",
                                    "持续单位": "整场战斗",
                                    RULE_FIELD: unit_entries,
                                },
                            },
                        ],
                    }
                ],
            },
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
    """两个方向：内容用的规则要登记过、写法要落在引擎真的会读的地方。

    单位级规则有三种写法：根能力 `规则文本`、被动技能行、状态定义。**状态定义里那一份
    由引擎在「添加状态」与「状态反应生成状态」两处解析**，所以判据也要走遍整棵能力树，
    不能只看根上的那几个节点。
    """

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

    def walk(node, source: str, where: str, *, 状态定义: bool = False) -> None:
        if isinstance(node, Mapping):
            ability = str(node.get("能力") or "")
            entries = node.get(RULE_FIELD) if RULE_FIELD in node else None
            # `修改战场规则` 的 `规则` 是**战场规则本体**（带监听的那个对象），
            # 不是规则层的一份规则引用——同名不同物，这里不能按载体算。
            if ability == "修改战场规则":
                entries = None
            if entries is not None or 状态定义:
                if 状态定义 or ability in {RULE_TEXT_ABILITY, "被动技能"}:
                    read(f"{where}.规则", entries, "单位", source)
                elif ability == "主动技能":
                    read(f"{where}.规则", entries, "行", source)
                elif entries:
                    problems.append(
                        f"{source} 的 {where}（{ability or '<无能力>'}）写了规则，"
                        "但引擎不读这个位置的规则：单位级写 `规则文本` / 被动技能 / 状态定义，行级写主动技能"
                    )
            for key, value in node.items():
                walk(value, source, f"{where}.{key}", 状态定义=(key == "状态" and isinstance(value, Mapping)))
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for index, item in enumerate(node):
                walk(item, source, f"{where}[{index}]")

    for filename, entry in _cards():
        for index, node in enumerate(entry.get("能力") or ()):
            walk(node, filename, f"能力[{index}]")
    for index, reaction in enumerate(_status_reactions()):
        for key in ("生成状态",):
            value = reaction.get(key)
            if isinstance(value, Mapping):
                read(f"状态反应[{index}].{key}.规则", value.get(RULE_FIELD), "单位", "状态反应.json")
    print(f"  内容用到单位级规则 {counts['单位']} 次 · 行级规则 {counts['行']} 次")
    return problems


def _status_reactions() -> list[dict]:
    """`规则/状态反应.json`：状态反应的 `生成状态` 也可能带规则。"""

    path = ROOT / "data" / "战斗" / "规则" / "状态反应.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, Mapping):
        value = value.get("状态反应") or []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def check_rule_quota(layer: dict[str, dict]) -> list[str]:
    """名额：**一条锁定技全库最多让几张卡带**，默认 1。

    锁定技不是靠稀有保值的（它是结构性文本），这个数防的是**一条闸门被抄到所有卡上**
    （二十张卡都「不可被指定」，选目标这件事本身就没意义了）。判据把用量数出来，
    **超一张就红**：想多发就得先在登记表里抬 `名额`，那是一次显式的设计决定。
    """

    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY

    problems: list[str] = []
    用量: dict[str, set[str]] = {name: set() for name in layer}

    def 计(名字: object, 卡: str) -> None:
        name = str(名字 or "")
        if name in 用量:
            用量[name].add(卡)

    def walk(node, 卡: str, *, 状态定义: bool = False) -> None:
        if isinstance(node, Mapping):
            ability = str(node.get("能力") or "")
            entries = node.get(RULE_FIELD) if RULE_FIELD in node else None
            if ability == "修改战场规则":
                entries = None
            if entries is not None or 状态定义:
                if 状态定义 or ability in {RULE_TEXT_ABILITY, "被动技能"} or ability == "主动技能":
                    for item in entries or ():
                        if isinstance(item, Mapping):
                            计(item.get("名称"), 卡)
            for key, value in node.items():
                walk(value, 卡, 状态定义=(key == "状态" and isinstance(value, Mapping)))
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for item in node:
                walk(item, 卡)

    for filename, entry in _cards():
        卡 = str(entry.get("编号") or entry.get("名称") or filename)
        for node in entry.get("能力") or ():
            walk(node, 卡)
    print("  名额用量：" + " · ".join(
        f"{name} {len(用量[name])}/{int(dict(layer[name]).get('名额') or 0)}"
        for name in sorted(layer)
    ))
    for name, definition in sorted(layer.items()):
        quota = int(dict(definition).get("名额") or 0)
        used = len(用量.get(name) or ())
        if used > quota:
            problems.append(
                f"{name} 已有 {used} 张卡带着它，名额只有 {quota}："
                "要么改内容，要么在登记表里显式抬名额"
            )
    return problems


CHECKS = (
    ("登记表自洽", check_registry),
    ("拦截点与实现", check_interception_points),
    ("标准探针覆盖", check_probe_coverage),
    ("渲染路径", check_render_path),
    ("内容只用登记过的", check_content_uses),
    ("名额", check_rule_quota),
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
