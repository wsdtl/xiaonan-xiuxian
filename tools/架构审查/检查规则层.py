"""规则层审查：效果之外的规则必须「登记得下、条件站得住、渲染得出来、内容只用登记过的」。

规则层是 `data/战斗/定义/规则层.json`，代码侧是 `game/core/combat/rules.py` 的
**拦截点表** `INTERCEPTION_POINTS`。这一层的设计目标是**加一条规则和加一张功法一样简单**：
一条规则 = 一个拦截点 + 一组条件 + 一个处置，条件用已登记的条件原子写，参数用 `$字段`
占位。于是判据也必须是通用的——**不为任何具体规则写一条判据**，只核七件事：

1. **登记表自洽**：直接跑启动期那份校验（归属 / 拦截点 / 处置 / 优先级 / 可改写 / 卡面 /
   条件真的按原子能力契约校验 / 参数不许有死项 / **条件不许为空** / 行级载体必须真有
   技能行读它），两处同一个函数，不留缝。
2. **拦截点在实现表里，且方向一致**：`INTERCEPTION_POINTS` 里每个拦截点都要有规则用它
   （没人用的拦截点是死代码），每条规则的载体必须是该拦截点认的载体。
3. **能被标准探针覆盖**：规则条件匹配的标签必须落在该拦截点的「探针标签」里，
   否则「加规则自动获得行为验证」不成立——这时要么改条件，要么扩探针场景（那是代码）。
4. **渲染路径**：每条规则都渲染得出来（拿探针卡跑一遍真渲染器）。
5. **内容只用登记过的**：六面卡片与战场环境里出现的规则名必须是登记过的，且载体写对。
6. **种族登记表**：种族的天生锁定技（第四种载体）登记过、**有负面必配强正面**、
   基准族人族为空、**两个种族不许长成同一副样子**。
7. **名额**：一条锁定技最多让几个载体（卡 / 种族）带，用量每轮打出来，超一个就红。

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
#: 基准族：它的天生规则必须是空的（所有种族的强弱都以它为参照）。
BASE_RACE = "人族"


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
    """每条规则都渲染得出来，而且卡面口径成立：整段在主动技能之前，**一条一个 `•`**。

    探针把单位级规则分给三种写法（根能力 / 被动行 / 状态定义）各带一部分，这样三处的
    尾注都真的出现过——同名规则写两处时只印一次（以先出现的载体为准）。**参战者固有规则
    不在这里**：它不挂在卡上，没有卡面可印（由 `tests/test_inherent_rules.py` 从服务入口验）。
    """

    from game.core.combat.card_text import render_body
    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY, rule_card_text

    unit = [name for name, definition in layer.items() if str(definition.get("归属")) == "单位"]
    line = [name for name, definition in layer.items() if str(definition.get("归属")) == "行"]
    切 = max(1, len(unit) // 3)
    根上 = [{"名称": name} for name in unit[:切]]
    被动上 = [{"名称": name} for name in unit[切:切 * 2]] or 根上
    状态上 = [{"名称": name} for name in unit[切 * 2:]] or 根上
    probe = {
        "能力": [
            {"能力": RULE_TEXT_ABILITY, RULE_FIELD: 根上},
            # 单位级规则的第二种写法：被动技能行自己的 `规则[]`。
            {
                "能力": "被动技能",
                "名称": "探针载规则",
                "结算顺序": 1,
                "规则": 被动上,
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
                                    RULE_FIELD: 状态上,
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
    # 卡面口径（负责人定）：锁定技整段排在**主动技能之前**，**一条一个 `•` 开头的行**；
    # 不是写在根能力上的那一份要带尾注，说清它跟谁生灭。
    规则行 = [行 for 行 in lines if 行.startswith("•")]
    规则段位置 = next((i for i, 行 in enumerate(lines) if 行 == "规则："), -1)
    主动位置 = next((i for i, 行 in enumerate(lines) if 行 == "主动："), len(lines))
    if 规则段位置 < 0:
        problems.append("卡面上没有「规则：」段")
    elif 规则段位置 > 主动位置:
        problems.append("「规则：」段没有排在主动技能之前")
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
        elif not any(expected in 行 for 行 in 规则行):
            problems.append(f"规则 {name} 没有单独成行（一条要一个 `•` 开头）")
    if "〔随[探针锁势]〕" not in text:
        problems.append("状态带来的规则没有尾注（应出现〔随[状态名]〕）")
    return problems


def check_content_uses(layer: dict[str, dict]) -> list[str]:
    """两个方向：内容用的规则要登记过、写法要落在引擎真的会读的地方。

    单位级规则在**内容里**有三种写法：根能力 `规则文本`、被动技能行、状态定义（第四种
    `固有规则` 不在内容里，由生成敌人的那一侧直接挂）。**状态定义里那一份
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
    """名额：**一条锁定技最多让几张卡带**，种族另有一本账（`种族名额`），默认与卡同额。

    锁定技不是靠稀有保值的（它是结构性文本），这个数防的是**一条闸门被抄到所有卡上**
    （二十张卡都「不可被指定」，选目标这件事本身就没意义了）。种族是**天生层**，所以
    它的发行量单独算：卡的闸门不被种族撑宽，反过来种族也不受卡的额度限制。判据把两笔
    用量都数出来，**超一个就红**：想多发就得先在登记表里抬对应的那个数。

    行级规则（技能行）不给种族用，所以行级只看卡这一本账。
    """

    from game.core.combat.rules import RULE_FIELD, RULE_TEXT_ABILITY

    problems: list[str] = []
    卡用量: dict[str, set[str]] = {name: set() for name in layer}
    族用量: dict[str, set[str]] = {name: set() for name in layer}

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
                            名 = str(item.get("名称") or "")
                            if 名 in 卡用量:
                                卡用量[名].add(卡)
            for key, value in node.items():
                walk(value, 卡, 状态定义=(key == "状态" and isinstance(value, Mapping)))
        elif isinstance(node, Sequence) and not isinstance(node, (str, bytes)):
            for item in node:
                walk(item, 卡)

    for filename, entry in _cards():
        卡 = str(entry.get("编号") or entry.get("名称") or filename)
        for node in entry.get("能力") or ():
            walk(node, 卡)
    for entry in _race_entries():
        种族 = str(entry.get("种族") or "")
        for item in entry.get("天生规则") or ():
            if isinstance(item, Mapping):
                名 = str(item.get("名称") or "")
                if 名 in 族用量:
                    族用量[名].add(f"种族:{种族}")
    print("  名额用量：" + " · ".join(
        f"{name} 卡{len(卡用量[name])}/{int(dict(layer[name]).get('名额') or 0)}"
        f"·族{len(族用量[name])}/{race_quota(layer[name])}"
        for name in sorted(layer)
    ))
    for name, definition in sorted(layer.items()):
        quota = int(dict(definition).get("名额") or 0)
        used = len(卡用量.get(name) or ())
        if used > quota:
            problems.append(
                f"{name} 已有 {used} 张卡带着它，卡名额只有 {quota}："
                "要么改内容，要么在登记表里显式抬名额"
            )
        race_used = len(族用量.get(name) or ())
        race_limit = race_quota(definition)
        if race_used > race_limit:
            problems.append(
                f"{name} 已有 {race_used} 个种族带着它，种族名额只有 {race_limit}："
                "要么改内容，要么在登记表里显式抬种族名额"
            )
        # **卡与种族不共用同一条闸门**：敌人的构筑里随时可能抽到带规则的那几张卡，
        # 同一张脸上写两条同名规则是启动期错误（「同一条单位级规则在一个参战者身上
        # 写了两遍」），所以两条发行渠道的名字不许重叠。
        if used and race_used:
            problems.append(
                f"{name} 同时被 {used} 张卡和 {race_used} 个种族带着："
                "卡与种族不许共用闸门（敌人生成时会撞「同一条规则写了两遍」）"
            )
    return problems


def race_quota(definition: Mapping) -> int:
    """这条规则的**种族名额**：不写就与卡同额（只有单位级规则该有它）。"""

    value = dict(definition).get("种族名额")
    if value is None:
        value = dict(definition).get("名额") or 1
    return int(value)


def _enemy_tiers() -> tuple[str, ...]:
    """敌方修士的六档阶梯名（种族的 `出现档次` 只能写这些）。"""

    path = ROOT / "data" / "角色" / "规则" / "主体" / "敌方修士.json"
    if not path.exists():
        return ()
    value = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        str(item.get("阶梯") or "")
        for item in value.get("阶梯") or []
        if isinstance(item, Mapping)
    )


def _attributes() -> set[str]:
    """登记过的战斗属性名（种族 `成长修正` 只能写这些键）。"""

    path = ROOT / "data" / "战斗" / "定义" / "属性.json"
    if not path.exists():
        return set()
    return {str(key) for key in json.loads(path.read_text(encoding="utf-8"))}


def _race_extra_fields(name: str, entry: Mapping) -> list[str]:
    """种族另外三样（非锁定技）：成长修正 / 寿元系数 / 卡池来源。

    它们不进效果管线，也不挂规则，但都是**会被引擎读**的字段，所以照样进判据：
    成长修正的键必须是登记过的属性、倍率是正数；寿元系数是正数；卡池来源只有两种。

    基准族人族不许写这三样——它是「什么都不天生」的那把尺子。
    """

    problems: list[str] = []
    if name == BASE_RACE:
        for key in ("成长修正", "寿元系数", "卡池来源"):
            if entry.get(key) not in (None, {}):
                problems.append(f"{BASE_RACE} 是基准族，不该写 {key}")
        return problems
    成长 = entry.get("成长修正")
    if 成长 not in (None, {}):
        if not isinstance(成长, Mapping):
            problems.append(f"{name}.成长修正必须是对象")
        else:
            属性 = _attributes()
            for 键, 倍率 in 成长.items():
                if 属性 and str(键) not in 属性:
                    problems.append(f"{name}.成长修正用了没登记的属性：{键}")
                try:
                    数值 = float(倍率)
                except (TypeError, ValueError):
                    problems.append(f"{name}.成长修正.{键}不是数字：{倍率}")
                    continue
                if 数值 <= 0:
                    problems.append(f"{name}.成长修正.{键}必须大于 0：{数值}")
    寿元 = entry.get("寿元系数")
    if 寿元 is not None:
        try:
            系数 = float(寿元)
        except (TypeError, ValueError):
            problems.append(f"{name}.寿元系数不是数字：{寿元}")
        else:
            if 系数 <= 0:
                problems.append(f"{name}.寿元系数必须大于 0：{系数}")
    卡池 = entry.get("卡池来源")
    if 卡池 is not None and str(卡池) not in {"敌方修士", "灵兽"}:
        problems.append(f"{name}.卡池来源只能是敌方修士或灵兽：{卡池}")
    return problems


def _race_entries() -> list[dict]:
    """`角色/规则/种族/种族.json`：种族的天生锁定技登记表。"""

    path = ROOT / "data" / "角色" / "规则" / "种族" / "种族.json"
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def check_race_registry(layer: dict[str, dict]) -> list[str]:
    """种族的天生锁定技：登记过、载体对、**有负面必配强正面**、每个种族形状不同。

    种族是锁定技的第四种载体（见 `data/战斗/说明.md` 第 67 条），不挂卡、没有卡面，
    所以它的规则只进这个判据与启动期校验。五条口径：

    - **挡同伴 / 挡自己算负面**（条件里带 `来源关系:己方` 或 `来源关系:自身`），
      挡敌方或不设限算正面；
    - **有负面就必须配至少一条强正面**——种族的天生规则是「一正一负」的代价结构，
      只给负面就是纯惩罚，只给正面就是白送；
    - **基准族人族不许有任何天生规则**，而且**两个种族不许长成同一副样子**
      （组合完全一样就报，逼着每个种族有自己的形状）；
    - **每个种族都要在敌方档次里出得来**（`出现档次` 非空、档名是真的档），否则这条
      种族是躺着没人读的死数据；
    - **基准族六档全出现**（谁都得能跟人族比），**每档至少三个族**（不然一档就一张脸）。
    """

    from game.core.combat.rules import parse_rule_entries, probe_tags

    problems: list[str] = []
    组合: dict[str, str] = {}
    负面标签 = {"来源关系:己方", "来源关系:自身"}
    档位 = _enemy_tiers()
    档内: dict[str, list[str]] = {tier: [] for tier in 档位}
    for entry in _race_entries():
        name = str(entry.get("种族") or "").strip()
        if not name:
            problems.append("种族登记表有一条没写 `种族`")
            continue
        if not str(entry.get("族系") or "").strip():
            problems.append(f"{name} 没有写 `族系`")
        档 = [str(item) for item in entry.get("出现档次") or ()]
        if not 档:
            problems.append(f"{name} 没写 `出现档次`：生成侧抽不到它，等于躺着的死数据")
        for tier in 档:
            if tier not in 档内:
                problems.append(f"{name} 的 `出现档次` 不是敌方档次：{tier}")
            else:
                档内[tier].append(name)
        try:
            rules = parse_rule_entries(
                entry.get("天生规则") or [],
                layer,
                carrier="单位",
                path=f"{name}.天生规则",
            )
        except (TypeError, ValueError) as exc:
            problems.append(f"{name} 的天生规则不成立：{exc}")
            continue
        problems.extend(_race_extra_fields(name, entry))
        if name == BASE_RACE:
            if rules:
                problems.append(
                    f"{BASE_RACE} 是基准族，不许有天生规则（现在有 {'、'.join(sorted(rules))}）"
                )
            continue
        if not rules:
            problems.append(f"{name} 一条天生规则都没有：只有基准族允许空")
            continue
        负面 = sorted(n for n, rule in rules.items() if 负面标签 & probe_tags(rule))
        正面 = sorted(n for n in rules if n not in 负面)
        if 负面 and not 正面:
            problems.append(
                f"{name} 只有负面（{'、'.join(负面)}）：有负面就必须配至少一条强正面"
            )
        签名 = "|".join(
            f"{n}:{'/'.join(sorted(probe_tags(rule)))}" for n, rule in sorted(rules.items())
        )
        if 签名 in 组合:
            problems.append(
                f"{name} 与 {组合[签名]} 的天生规则组合完全一样：每个种族要有自己的形状"
            )
        else:
            组合[签名] = name
    for tier, names in sorted(档内.items()):
        if len(names) < 3:
            problems.append(f"敌方档次 {tier} 只有 {len(names)} 个种族：每档至少三个")
        if BASE_RACE not in names:
            problems.append(f"基准族 {BASE_RACE} 必须出现在 {tier} 档：谁都得能跟人族比")
    return problems


CHECKS = (
    ("登记表自洽", check_registry),
    ("拦截点与实现", check_interception_points),
    ("标准探针覆盖", check_probe_coverage),
    ("渲染路径", check_render_path),
    ("内容只用登记过的", check_content_uses),
    ("种族登记表", check_race_registry),
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
