"""物品资料、定义与使用效果渲染。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from message import M

from .utils import (
    _display_number,
    _number,
    _plain_value,
    _related_name,
    _signed,
)


def _description(detail) -> str:
    """返回实体自己的公开说明；不从说明文本中截断或推断规则。"""

    return detail.description


def _player_description(detail) -> str:
    """返回短引言；构筑的数值与处理顺序统一由下方节点说明。"""

    description = _normalize_brackets(_description(detail).strip())
    if detail.section not in {"功法", "真意", "气机", "器律"}:
        return description
    if not description:
        return ""

    # 内容 JSON 中的说明可能沿用“类别[名称]：五行根基……”的卡头，
    # 查看页已经有实体标题和五行栏，因此只留下真正的引言。
    prefix = rf"^(?:功法|真意|气机|器律)\[{re.escape(detail.name)}\][：:]\s*"
    description = re.sub(prefix, "", description)
    description = re.sub(r"^五行根基为[^。；]+。\s*", "", description)

    # 器律的说明同时承担目录简介和完整规则记录；查看页的器纹区已经
    # 展开了真实能力树，因此这里只保留铸法引言，避免同一效果占两遍版面。
    if detail.section == "器律" and "。" in description:
        description = description.split("。", 1)[0].strip() + "。"

    # 主动、被动、常驻和计量结算的完整效果由“法门”结构化展示。
    cut = re.search(r"(?:主动|被动|常驻|闭环结算)(?:[，,:：]|\[)", description)
    if cut:
        description = description[: cut.start()].rstrip("。；： ") + "。"
    return description.strip("。 ") + ("。" if description.strip("。 ") else "")


def _build_description_lines(detail, rendered: tuple[str, ...] = ()) -> tuple[str, ...]:
    """构筑查看正文 = 卡头（人工写）+ 规则正文（由能力树现算）。

    `说明` 只保存卡头风味简介。规则正文由玩法层从卡片自己的能力树渲染好传进来
    （渲染器是战斗核心的公共能力，命令层不导入核心服务），所以正文和 JSON 不可能
    对不上——以前 `说明` 里另存一份正文，漂移过两次（引用了卡里不存在的专名、
    留下「按 JSON 能力执行」占位残句）。
    """

    fields = detail.fields
    lines: list[str] = []
    attributes = fields.get("属性构成")
    if isinstance(attributes, Mapping):
        lines.append(
            "五行根基："
            + " · ".join(f"{key}{value}%" for key, value in attributes.items())
        )
    if detail.section == "器律":
        for key in ("器阶", "铸法"):
            if key in fields:
                lines.append(f"{key}：{fields[key]}")

    # 卡头里重复了标题与五行；展示层已经单独显示，这里只留风味引言。
    description = _normalize_brackets(detail.description.strip())
    prefix = rf"^(?:功法|真意|气机|器律)\[{re.escape(detail.name)}\][：:]\s*"
    description = re.sub(prefix, "", description, count=1)
    description = re.sub(r"^五行根基为[^。；]+。\s*", "", description, count=1)
    body = description.splitlines()
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    lines.extend(body)

    lines.extend(rendered)
    return tuple(lines)


def _normalize_brackets(value: str) -> str:
    """展示正文统一使用半角方括号；不改动 Markdown 链接语法。"""

    return (
        value.replace("【", "[")
        .replace("】", "]")
        .replace("「", "[")
        .replace("」", "]")
        .replace("『", "[")
        .replace("』", "]")
        .replace("“", "[")
        .replace("”", "]")
    )


def _effect_lines(value: object, prefix: str = "") -> tuple[str, ...]:
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, raw in value.items():
            label = f"{prefix}·{key}" if prefix else str(key)
            if isinstance(raw, Mapping):
                lines.extend(_effect_lines(raw, label))
            elif isinstance(raw, (list, tuple)):
                lines.append(f"{label}：{'、'.join(map(str, raw))}")
            else:
                lines.append(f"{label}：{raw}")
        return tuple(lines)
    return (f"{prefix}：{value}" if prefix else str(value),)


def _definition_lines(
    section: str,
    fields: Mapping[str, object],
    related: Mapping[str, object] | None = None,
    rendered: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """把 JSON 结构压成玩家能读懂的定义摘要，禁止泄露 mappingproxy。

    `rendered` 是玩法层按能力树现算好的规则正文（丹药、战场环境、伤势会用到）；
    命令层不自己渲染，也不导入核心服务。

    每个领域一个构造函数（见 `_SECTION_LINES`），本函数只做派发。此前这里是一条
    130 行、68 个分支的 if 链：分支数看着高，但它们全是各领域的字段解析，彼此
    独立——加一个领域就要在这条链中间插一段。派发表让「一个领域一段」和
    「哪些领域已接管」都直接看得出来。
    """

    handler = _SECTION_LINES.get(section)
    if handler is not None:
        lines = handler(fields, related or {}, rendered)
        if lines is not None:
            return lines
    return _generic_lines(fields)


def _daolv_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """道侣：性别、身份、结交偏好与本命武器。"""

    lines = []
    if "性别" in fields:
        lines.append(f"性别：{fields['性别']}")
    identity = fields.get("身份")
    if isinstance(identity, Mapping):
        title = identity.get("称号")
        if title:
            lines.append(f"身份：{title}")
    relationship = fields.get("结交")
    if isinstance(relationship, Mapping):
        pools = relationship.get("灵植池")
        if isinstance(pools, Sequence) and not isinstance(pools, (str, bytes)):
            lines.append(
                "偏好："
                + "、".join(
                    str(pool).removeprefix("灵植-") + "灵植" for pool in pools
                )
            )
        reward = relationship.get("圆满回礼")
        if isinstance(reward, Mapping):
            lines.append(
                f"圆满回礼：达成圆满后可得专属回礼 × {reward.get('数量', 1)}"
            )
    weapon = fields.get("本命武器")
    if isinstance(weapon, Mapping) and weapon.get("名称"):
        lines.append(f"本命武器：{weapon['名称']}")
    return tuple(lines)


def _innate_treasure_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """先天灵宝：权柄与规则介入的节点。"""

    lines = []
    if "权柄" in fields:
        lines.append(f"权柄：{fields['权柄']}")
    intervention = fields.get("规则介入")
    if isinstance(intervention, Mapping):
        node = intervention.get("节点", "触发时")
        ability = intervention.get("能力", "产生作用")
        quantity = intervention.get("数量")
        suffix = f" · {quantity}份" if quantity is not None else ""
        lines.append(f"作用：{node}时，{ability}{suffix}")
    return tuple(lines)


def _rendered_only(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """正文全部由能力树现算，这里只做转交（丹药、战场环境）。"""

    return rendered


def _base_item_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...] | None:
    """基础物品：有 `使用效果` 就按用途展开；没有则返回 `None` 交回字段平铺。"""

    effect = fields.get("使用效果")
    if isinstance(effect, Mapping):
        return _item_effect_lines(effect, related)
    return None


def _formation_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """阵法：监测项、核心与可炼品级。"""

    lines = []
    if "宏观监测" in fields:
        lines.append("监测：" + "、".join(map(str, fields["宏观监测"])))
    if "阵法核心" in fields:
        lines.append(f"核心：{fields['阵法核心']}")
    grades = fields.get("品级")
    if isinstance(grades, Sequence) and not isinstance(grades, (str, bytes)):
        names = [
            str(grade.get("品级")) for grade in grades if isinstance(grade, Mapping)
        ]
        if names:
            lines.append("可炼品级：" + " · ".join(names))
    return tuple(lines)


def _injury_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """伤势：来源、影响、叠加与疗伤，接上 `战斗状态` 里的时序规则。"""

    lines = []
    if "来源类别" in fields:
        lines.append(f"来源：{fields['来源类别']}")
    state = fields.get("战斗状态")
    if isinstance(state, Mapping):
        details = [str(state.get("类别") or "")]
        remaining = state.get("剩余行动")
        if remaining is not None:
            details.append(f"持续{remaining}次行动")
        limits = state.get("行动限制")
        if (
            isinstance(limits, Sequence)
            and not isinstance(limits, (str, bytes))
            and limits
        ):
            details.append("禁用" + "、".join(map(str, limits)))
        lines.append("影响：" + " · ".join(item for item in details if item))
    stacking = fields.get("叠加")
    if isinstance(stacking, Mapping) and "层数上限" in stacking:
        lines.append(f"叠加：最多{stacking['层数上限']}层")
    treatment = fields.get("治疗")
    if isinstance(treatment, Mapping) and "每层所需轮数" in treatment:
        lines.append(f"疗伤：每层需要闭关{treatment['每层所需轮数']}轮")
    # 战斗状态里的 `监听` 是真正的时序规则，按同一套措辞写出来。
    lines.extend(rendered)
    return tuple(lines)


def _recipe_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """丹方：炼制难度、炉法与成丹。"""

    lines = []
    for key in ("炼制难度", "炉法"):
        if key in fields:
            lines.append(f"{key}：{fields[key]}")
    product = _related_name(fields.get("成丹"), related)
    if product:
        lines.append(f"成丹：{product}")
    return tuple(lines)


def _realm_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """境界：等级区间与下一境界。"""

    lines = []
    if "等级下限" in fields and "等级上限" in fields:
        lines.append(f"等级：{fields['等级下限']}至{fields['等级上限']}级")
    next_realm = _related_name(fields.get("下一境界"), related)
    lines.append(f"下一境界：{next_realm}" if next_realm else "已至当前修行尽头")
    return tuple(lines)


def _person_state_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """人物状态：可转入的相邻状态与附近可见。"""

    transitions = fields.get("可转入")
    lines = []
    if isinstance(transitions, Sequence) and not isinstance(
        transitions, (str, bytes)
    ):
        names = [_related_name(value, related) for value in transitions]
        lines.append("可转入：" + "、".join(name for name in names if name))
    if "附近公开" in fields:
        lines.append("附近可见：" + ("是" if fields["附近公开"] else "否"))
    return tuple(lines)


def _artisan_lines(
    fields: Mapping[str, object],
    related: Mapping[str, object],
    rendered: tuple[str, ...],
) -> tuple[str, ...]:
    """炼丹师 / 炼器工匠 / 阵师：把开放清单解析成名称，其余字段平铺。"""

    lines = []
    reference_keys = {"开放丹方", "开放器律", "开放阵法"}
    for key, value in fields.items():
        if (
            key in reference_keys
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes))
        ):
            names = [_related_name(item, related) for item in value]
            lines.append(f"{key}：" + "、".join(name for name in names if name))
        else:
            lines.append(f"{key}：{_plain_value(value)}")
    return tuple(lines)


def _generic_lines(fields: Mapping[str, object]) -> tuple[str, ...]:
    """没登记领域的兜底：按字段平铺，嵌套对象缩进一层。"""

    lines = []
    for key, value in fields.items():
        if isinstance(value, Mapping):
            lines.extend(_effect_lines(value, key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            lines.append(f"{key}：{'、'.join(map(str, value))}")
        else:
            lines.append(f"{key}：{value}")
    return tuple(lines)


#: 领域 → 自己的详情行构造。返回 `None` 表示不接管，交给 `_generic_lines` 兜底。
_SECTION_LINES = {
    "道侣": _daolv_lines,
    "先天灵宝": _innate_treasure_lines,
    "丹药": _rendered_only,
    "基础物品": _base_item_lines,
    "阵法": _formation_lines,
    "伤势": _injury_lines,
    "战场环境": _rendered_only,
    "丹方": _recipe_lines,
    "境界": _realm_lines,
    "人物状态": _person_state_lines,
    "炼丹师": _artisan_lines,
    "炼器工匠": _artisan_lines,
    "阵师": _artisan_lines,
}
def _item_effect_lines(
    effect: Mapping[str, object], related: Mapping[str, object]
) -> tuple[str, ...]:
    kind = str(effect.get("类型") or "使用后生效")
    purpose = {
        "恢复精神": "服用后恢复精神",
        "恢复血气": "服用后恢复血气",
        "寄存战丹": "服用后备入战丹位，仅下一场正式战斗生效",
        "境界突破": "用于境界突破",
        "构筑重做": "重塑当前同行道侣的修行构筑",
        "突破补正": "补正人物或当前同行道侣的突破所得",
        "护持道契": "在铜雀台夺元时护持道契",
        "转变性别": "改变人物性别",
    }.get(kind, kind)
    lines = [f"用途：{purpose}"]
    if "恢复百分比" in effect:
        lines.append(f"恢复：{effect['恢复百分比']}%")
    target_realm = _related_name(effect.get("目标境界"), related)
    if target_realm:
        lines.append(f"可突破至：{target_realm}")
    permanent = effect.get("永久属性")
    if isinstance(permanent, Mapping) and permanent:
        lines.append(
            "永久增益："
            + "、".join(
                f"{key}{_signed('增加' if _number(value) >= 0 else '减少', _display_number(abs(_number(value))))}"
                for key, value in permanent.items()
            )
        )
    battle_state = effect.get("战前状态")
    if isinstance(battle_state, Mapping):
        state_name = str(battle_state.get("名称") or "战丹药力")
        attributes = battle_state.get("属性")
        changes = ""
        if isinstance(attributes, Mapping) and attributes:
            changes = "：" + "、".join(
                f"{key}{_signed('增加' if _number(value) >= 0 else '减少', _display_number(abs(_number(value))))}"
                for key, value in attributes.items()
            )
        lines.append(f"战前生效：获得“{state_name}”{changes}，持续整场战斗")
    handled = {"类型", "恢复百分比", "目标境界", "永久属性", "战前状态", "监听"}
    labels = {
        "目标角色": "适用对象",
        "目标构筑": "重塑构筑",
        "候选来源": "重塑来源",
        "保持装配数量": "保持原有槽位数量",
        "补正来源": "补正来源",
        "选择数量": "选择数量",
        "只限纯突破节点": "仅限纯属性突破",
        "允许重复补正": "允许重复补正",
    }
    for key, value in effect.items():
        if key in handled:
            continue
        lines.append(f"{labels.get(str(key), str(key))}：{_plain_value(value)}")
    return tuple(lines)
