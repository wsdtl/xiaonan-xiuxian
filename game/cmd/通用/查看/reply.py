"""查看正式编号实体的命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from game.features.chakan_wupin import ItemInspectionResult
from message import M


def missing_query():
    return (
        M.document()
        .section("查看", icon="item")
        .line(M.status("缺少目标", tone="warning"), " 请提供编号或完整名称。")
        .small("例如：查看 100005 · 查看 小还丹")
        .build()
    )


def inspection(result: ItemInspectionResult):
    if result.detail is None and result.candidates:
        reply = (
            M.document()
            .header("查看结果")
            .section("名称不唯一", icon="notice")
            .line(
                M.status("需要选择", tone="warning"),
                _normalize_brackets(
                    f" “{result.query}”对应多项资料，请选择编号查看。"
                ),
            )
            .section("候选")
        )
        for index, candidate in enumerate(result.candidates, start=1):
            reply.item(
                index,
                M.command(
                    M.text(
                        f"{candidate.section} · {candidate.name}",
                        tone=_category_tone(candidate.section),
                    ),
                    f"查看 {candidate.item_id}",
                    submit=False,
                ),
                f" · {candidate.item_id}",
            )
        return reply.build()
    if result.detail is None:
        return (
            M.document()
            .section("查看", icon="notice")
            .line(
                M.status("未找到", tone="danger"),
                _normalize_brackets(f" “{result.query}”没有对应资料。"),
            )
            .small("请检查编号或完整名称是否正确。")
            .build()
        )
    detail = result.detail
    title, icon = _display_title(detail.category)
    related = {item.item_id: item for item in result.related_details}
    lines = (
        _build_description_lines(detail)
        if detail.section in {"功法", "真意", "气机", "器律"}
        else _definition_lines(detail.section, detail.name, detail.fields, related)
    )
    if detail.section == "机制" and detail.name.startswith("构筑计量结算"):
        summary = _mechanism_summary(detail, related)
        lines = (summary,) if summary else lines
    reply = M.document().header(detail.name)
    # 构筑正文统一从说明字段进入详情区；其他实体仍使用短引言加结构化详情。
    description = _player_description(detail)
    if detail.section in {"功法", "真意", "气机", "器律"}:
        # 构筑正文已按说明字段逐行放入详情区，避免引言重复出现。
        description = ""
    if detail.section == "机制" and lines:
        # 机制说明由节点解析成“运转”；避免再把同一段效果重复输出。
        description = ""
    if description:
        reply.section(title, icon=icon).field("编号", detail.item_id)
        reply.line(description)
    else:
        reply.inline_section(
            title,
            f"编号 {detail.item_id}",
            icon=icon,
        )
    if lines:
        reply.section(_detail_title(detail.category), icon=icon)
        for line in lines:
            reply.line(_normalize_brackets(line))
    elif not detail.description:
        reply.section("详情", icon=icon).line(
            M.status("暂无", tone="muted"), " 暂无更多记载。"
        )
    return reply.build()


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
    # 展开了真实机制，因此这里只保留铸法引言，避免同一效果占两遍版面。
    if detail.section == "器律" and "。" in description:
        description = description.split("。", 1)[0].strip() + "。"

    # 主动、被动、常驻和计量结算的完整效果由“法门”结构化展示。
    cut = re.search(r"(?:主动|被动|常驻|闭环结算)(?:[，,:：]|\[)", description)
    if cut:
        description = description[: cut.start()].rstrip("。；： ") + "。"
    return description.strip("。 ") + ("。" if description.strip("。 ") else "")


def _build_description_lines(detail) -> tuple[str, ...]:
    """构筑查看正文直接采用 JSON 说明，避免展示层重写战斗文案。"""

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

    description = _normalize_brackets(detail.description.strip())
    prefix = rf"^(?:功法|真意|气机|器律)\[{re.escape(detail.name)}\][：:]\s*"
    description = re.sub(prefix, "", description, count=1)
    # 元数据已经单独显示；正文中删掉重复的五行卡头，其他说明逐行原样保留。
    description = re.sub(r"^五行根基为[^。；]+。\s*", "", description, count=1)
    body = description.splitlines()
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    lines.extend(body)
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
    entity_name: str,
    fields: Mapping[str, object],
    related: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """把 JSON 结构压成玩家能读懂的定义摘要，禁止泄露 mappingproxy。"""

    if section in {"功法", "真意", "气机", "器律"}:
        lines: list[str] = []
        attributes = fields.get("属性构成")
        if isinstance(attributes, Mapping):
            lines.append(
                "五行根基："
                + " · ".join(f"{key}{value}%" for key, value in attributes.items())
            )
        if section == "器律":
            for key in ("器阶", "铸法"):
                if key in fields:
                    lines.append(f"{key}：{fields[key]}")
        abilities = fields.get("能力")
        if isinstance(abilities, Sequence) and not isinstance(abilities, (str, bytes)):
            labels: list[str] = []
            for ability_index, ability in enumerate(abilities, start=1):
                if isinstance(ability, Mapping):
                    name = str(
                        ability.get("名称") or ability.get("能力") or "未命名能力"
                    )
                    prefix = f"{entity_name}·"
                    name = name.removeprefix(prefix)
                    kind = str(ability.get("能力") or "")
                    if kind == "固定属性加成":
                        attributes = ability.get("属性")
                        if isinstance(attributes, Mapping):
                            labels.append(
                                f"[{ability_index}] 常驻："
                                + "、".join(
                                    f"{key}{_signed('增加', value)}"
                                    for key, value in attributes.items()
                                )
                            )
                        continue
                    kind = {"主动技能": "主动", "被动技能": "被动"}.get(kind, kind)
                    details = [part for part in (kind, name) if part]
                    if "精神消耗" in ability:
                        details.append(f"耗神{ability['精神消耗']}")
                    if "冷却行动" in ability:
                        details.append(f"冷却{ability['冷却行动']}行动")
                    tags = ability.get("标签")
                    if isinstance(tags, Sequence) and not isinstance(
                        tags, (str, bytes)
                    ):
                        details.extend(str(tag) for tag in tags)
                    labels.append(f"[{ability_index}] " + " · ".join(details))
                    effects = ability.get("效果")
                    effect_groups = _ability_effects(effects, related or {})
                    for effect_lines in effect_groups:
                        if not effect_lines:
                            continue
                        labels.append(f"  → {effect_lines[0]}")
                        labels.extend(
                            f"     {'' if line.startswith(('随后', '结算后')) else '• '}{line}"
                            for line in effect_lines[1:]
                        )
            if labels:
                lines.extend(labels)
        return tuple(lines)
    if section == "道侣":
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
    if section == "先天灵宝":
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
    if section == "物品":
        effect = fields.get("使用效果")
        if isinstance(effect, Mapping):
            return _item_effect_lines(effect, related or {})
    if section == "阵法":
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
    if section == "机制":
        node = fields.get("节点")
        return _combat_lines(node, related or {}) if isinstance(node, Mapping) else ()
    if section == "伤势":
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
        return tuple(lines)
    if section == "战场环境":
        lines = []
        for key, value in fields.items():
            if isinstance(value, Mapping):
                if key == "节点":
                    lines.append(
                        f"节点：{value.get('能力', '未说明')} · {value.get('事件', '')}".rstrip(
                            " ·"
                        )
                    )
                elif key == "战斗状态":
                    lines.append(f"战斗状态：{value.get('类别', '未说明')}")
                else:
                    lines.append(f"{key}：" + "、".join(str(item) for item in value))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                lines.append(f"{key}：共{len(value)}项")
            else:
                lines.append(f"{key}：{value}")
        return tuple(lines)
    if section == "丹方":
        lines = []
        for key in ("炼制难度", "炉法"):
            if key in fields:
                lines.append(f"{key}：{fields[key]}")
        product = _related_name(fields.get("成丹"), related or {})
        if product:
            lines.append(f"成丹：{product}")
        return tuple(lines)
    if section == "境界":
        lines = []
        if "等级下限" in fields and "等级上限" in fields:
            lines.append(f"等级：{fields['等级下限']}至{fields['等级上限']}级")
        next_realm = _related_name(fields.get("下一境界"), related or {})
        lines.append(f"下一境界：{next_realm}" if next_realm else "已至当前修行尽头")
        return tuple(lines)
    if section == "人物状态":
        transitions = fields.get("可转入")
        lines = []
        if isinstance(transitions, Sequence) and not isinstance(
            transitions, (str, bytes)
        ):
            names = [_related_name(value, related or {}) for value in transitions]
            lines.append("可转入：" + "、".join(name for name in names if name))
        if "附近公开" in fields:
            lines.append("附近可见：" + ("是" if fields["附近公开"] else "否"))
        return tuple(lines)
    if section in {"炼丹师", "炼器工匠", "阵师"}:
        lines = []
        reference_keys = {"开放丹方", "开放器律", "开放阵法"}
        for key, value in fields.items():
            if (
                key in reference_keys
                and isinstance(value, Sequence)
                and not isinstance(value, (str, bytes))
            ):
                names = [_related_name(item, related or {}) for item in value]
                lines.append(f"{key}：" + "、".join(name for name in names if name))
            else:
                lines.append(f"{key}：{_plain_value(value)}")
        return tuple(lines)
    lines = []
    for key, value in fields.items():
        if isinstance(value, Mapping):
            lines.extend(_effect_lines(value, key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            lines.append(f"{key}：{'、'.join(map(str, value))}")
        else:
            lines.append(f"{key}：{value}")
    return tuple(lines)


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
    mechanisms = effect.get("战斗机制")
    if isinstance(mechanisms, Sequence) and not isinstance(mechanisms, (str, bytes)):
        for mechanism_id in mechanisms:
            mechanism = related.get(str(mechanism_id))
            if mechanism is None:
                continue
            node = mechanism.fields.get("节点")
            summary = (
                "；".join(_combat_lines(node, related))
                if isinstance(node, Mapping)
                else ""
            )
            lines.append(
                f"{mechanism.name}：{summary}" if summary else str(mechanism.name)
            )
    handled = {"类型", "恢复百分比", "目标境界", "永久属性", "战前状态", "战斗机制"}
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


def _related_name(value: object, related: Mapping[str, object]) -> str:
    key = str(value or "").strip()
    if not key:
        return ""
    detail = related.get(key)
    return str(detail.name) if detail is not None else key


def _plain_value(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Mapping):
        return "、".join(f"{key}{_plain_value(child)}" for key, child in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "、".join(_plain_value(child) for child in value)
    return str(value)


def _number(value: object) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )


def _display_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _ability_effects(
    effects: object, related: Mapping[str, object]
) -> tuple[tuple[str, ...], ...]:
    if not isinstance(effects, Sequence) or isinstance(effects, (str, bytes)):
        return ()
    groups: list[tuple[str, ...]] = []
    for effect in effects:
        if not isinstance(effect, Mapping):
            continue
        ability = str(effect.get("能力") or "")
        if ability in {"引用战斗机制", "引用被动机制"}:
            mechanism = related.get(str(effect.get("机制") or ""))
            if mechanism is None:
                continue
            summary = _mechanism_summary(mechanism, related)
            name = str(mechanism.name)
            if name.startswith("构筑计量结算·"):
                # 这是运行时分类名；玩家只需要知道是哪一项计量何时结算。
                label = name.removeprefix("构筑计量结算·")
                groups.append(_mechanism_display_lines(f"结算[{label}]", summary))
            else:
                groups.append(_mechanism_display_lines(name, summary))
        else:
            lines = tuple(line for line in _combat_lines(effect, related) if line)
            if lines:
                groups.append(lines)
    return tuple(groups)


def _mechanism_display_lines(label: str, summary: str) -> tuple[str, ...]:
    """将引用机制的顺序步骤拆成独立行，保留机制名只出现一次。"""

    if not summary:
        return (label,)
    steps: list[str] = []
    random_expanded = False
    for part in summary.split("；"):
        part = part.strip()
        if not part:
            continue
        # 随机备选项是并列内容，单独成行比斜杠串联更易读。
        marker = "随机触发"
        choice_separator = part.find("：", part.find(marker) + len(marker))
        if marker in part and choice_separator >= 0 and " / " in part[choice_separator + 1 :]:
            prefix = (
                part[: choice_separator + 1]
                .replace("造成伤害后：", "造成伤害后，")
                .replace("随机触发一项", "随机执行1项")
            )
            steps.append(prefix)
            steps.extend(
                choice.strip() for choice in part[choice_separator + 1 :].split(" / ")
            )
            random_expanded = True
        else:
            if random_expanded and not part.startswith(("随后", "若", "否则")):
                part = f"随后，自身{part}"
            steps.append(part)
    if len(steps) <= 1:
        return (f"{label}：{summary}",)
    return (f"{label}：{steps[0]}",) + tuple(steps[1:])


def _mechanism_summary(mechanism: object, related: Mapping[str, object]) -> str:
    """把计量监听的内部尝试分支压成玩家可判断的结算语句。"""

    node = getattr(mechanism, "fields", {}).get("节点")
    if not isinstance(node, Mapping):
        return ""
    if not str(getattr(mechanism, "name", "")).startswith("构筑计量结算"):
        return "；".join(_combat_lines(node, related))
    condition_node = next(
        (value for value in _walk_nodes(node.get("效果"))
         if isinstance(value, Mapping) and value.get("能力") == "条件执行"),
        node,
    )
    condition = _conditions(condition_node.get("条件"))
    counter = ""
    # 监听节点把条件放在嵌套的“条件执行”中，不能从外层监听节点读取。
    left = condition_node.get("条件") or ()
    if isinstance(left, Sequence) and left and isinstance(left[0], Mapping):
        value = left[0].get("左值")
        if isinstance(value, Mapping):
            counter = str(value.get("计量") or "")
    body_nodes = condition_node.get("成立效果")
    body = _nodes(_without_counter_reset(body_nodes, counter), related)
    # 成立分支通常先引用真正的消费者机制。按节点能力识别，不能依赖展示文案。
    ref = next(
        (
            str(value.get("机制") or "")
            for value in _walk_nodes(body_nodes)
            if isinstance(value, Mapping)
            and value.get("能力") in {"引用战斗机制", "引用被动机制"}
        ),
        "",
    )
    target = related.get(ref)
    target_node = getattr(target, "fields", {}).get("节点") if target else None
    if isinstance(target_node, Mapping):
        consumer_body = (
            target_node.get("成立效果")
            if target_node.get("能力") == "条件执行"
            else target_node
        )
        body = _nodes(_without_counter_reset(consumer_body, counter), related)
    event = str(node.get("事件") or "行动结束")
    suffix = f"；结算后{counter}清零，需重新积累" if counter else ""
    limits = _trigger_limit_suffix(node)
    return f"{event}时，若{condition}，{'；'.join(body) or '执行结算'}{suffix}{limits}"


def _without_counter_reset(value: object, counter: str) -> object:
    """从消费者正文中移除计量清空节点，避免与外层结算说明重复。"""

    if not counter:
        return value
    if isinstance(value, Mapping):
        if (
            value.get("能力") == "修改机制计量"
            and value.get("方式") == "清空"
            and str(value.get("计量") or "") == counter
        ):
            return None
        return {
            key: _without_counter_reset(child, counter)
            for key, child in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(
            child
            for item in value
            if (child := _without_counter_reset(item, counter)) is not None
        )
    return value


def _walk_nodes(value: object):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk_nodes(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _walk_nodes(child)


def _trigger_limit_suffix(node: Mapping[str, object]) -> str:
    """把节点级触发上限统一写成玩家可判断的限制。"""

    limits: list[str] = []
    per_action = node.get("每次行动最多触发")
    if isinstance(per_action, (int, float)) and not isinstance(per_action, bool) and per_action > 0:
        limits.append(f"每行动限{_display_number(float(per_action))}次")
    per_battle = node.get("每场战斗最多触发")
    if isinstance(per_battle, (int, float)) and not isinstance(per_battle, bool) and per_battle > 0:
        limits.append(f"每战限{_display_number(float(per_battle))}次")
    return f"，{'，'.join(limits)}" if limits else ""


def _combat_lines(
    node: Mapping[str, object], related: Mapping[str, object] | None = None
) -> tuple[str, ...]:
    related = related or {}
    ability = str(node.get("能力") or "")
    if ability == "顺序执行":
        effects = node.get("效果")
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            lines = tuple(
                line
                for effect in effects
                if isinstance(effect, Mapping)
                for line in _combat_lines(effect, related)
            )
            if len(lines) > 1:
                return ("依次处理：" + "；".join(lines),)
            return lines
        return ()
    if ability == "条件执行":
        condition = _conditions(node.get("条件"))
        success = "；".join(_nodes(node.get("成立效果"), related)) or "不产生额外效果"
        failure = "；".join(_nodes(node.get("不成立效果"), related))
        suffix = f"；否则：{failure}" if failure else ""
        return (f"若{condition}：{success}{suffix}",)
    if ability == "随机执行":
        options = node.get("选项")
        summaries = []
        if isinstance(options, Sequence) and not isinstance(options, (str, bytes)):
            for option in options:
                if isinstance(option, Mapping):
                    summaries.extend(_combat_lines(option, related)[:1])
        count = node.get("抽取数量", 1)
        replacement = "，可重复抽取" if node.get("是否放回") else ""
        draw = "随机触发一项" if count == 1 else f"随机触发{count}项"
        return (f"{draw}{replacement}：" + " / ".join(summaries),)
    if ability == "遍历目标":
        target = node.get("目标")
        target_text = "目标"
        if isinstance(target, Mapping):
            target_text = _target(target)
        effects = node.get("效果")
        lines = []
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            for effect in effects:
                if isinstance(effect, Mapping):
                    for line in _combat_lines(effect, related):
                        if line.startswith("对当前目标"):
                            lines.append(
                                f"对{target_text}" + line.removeprefix("对当前目标")
                            )
                        elif line.startswith("当前目标"):
                            lines.append(target_text + line.removeprefix("当前目标"))
                        else:
                            lines.append(f"对{target_text}：{line}")
        return tuple(lines)
    if ability == "重复执行":
        body = "；".join(_nodes(node.get("效果"), related))
        return (f"重复{_value(node.get('次数'))}次：{body}",)
    if ability == "尝试执行":
        attempt = "；".join(_nodes(node.get("尝试效果"), related))
        success = "；".join(_nodes(node.get("成功效果"), related))
        failure = "；".join(_nodes(node.get("失败效果"), related))
        text = f"先处理：{attempt or '指定效果'}"
        if success:
            text += f"；处理成功后：{success}"
        if failure:
            text += f"；处理未成功时：{failure}"
        return (text,)
    if ability == "事务执行":
        body = "；".join(_nodes(node.get("效果"), related))
        failure = "；".join(_nodes(node.get("失败效果"), related))
        text = f"依次处理：{body or '指定效果'}"
        text += "；任一步骤失败，本项不成立并回退已处理的改变"
        if failure:
            text += f"；回退后：{failure}"
        return (text,)
    if ability == "监听事件":
        event = str(node.get("事件") or "对应时机")
        relation = str(node.get("阵营关系") or "")
        subject = {
            "自身": "自身",
            "任意敌方": "任意敌方",
            "任意友方": "任意友方",
        }.get(relation, relation or "相关角色")
        effects = node.get("效果")
        summaries: list[str] = []
        if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes)):
            for effect in effects:
                if isinstance(effect, Mapping):
                    summaries.extend(_combat_lines(effect, related))
        timing = (
            "的召唤物或构造物入场后"
            if event == "战斗对象入场后"
            else event
            if event.endswith(("前", "后", "时"))
            else f"{event}时"
        )
        cap = _trigger_limit_suffix(node)
        condition = _conditions(node.get("条件"))
        requirement = f"，且{condition}" if condition != "条件成立" else ""
        effect_text = "；".join(summaries) or "不产生额外效果"
        return (f"{subject}{timing}{requirement}：{effect_text}{cap}",)
    if ability in {
        "读取数值",
        "计算数值",
        "随机数值",
        "聚合数值",
        "选择目标",
        "选择技能",
        "选择状态",
        "概率条件",
        "数值条件",
        "状态条件",
        "类型条件",
        "组合条件",
        "标签条件",
    }:
        if ability.startswith("选择"):
            return (
                {"选择目标": _target, "选择技能": _skill, "选择状态": _status}[ability](
                    node
                ),
            )
        if ability.endswith("条件"):
            return (_condition(node),)
        return (_value(node),)
    if ability == "造成伤害":
        value = node.get("数值")
        amount = _amount(value)
        target = _target(node.get("目标"))
        elements = node.get("属性构成")
        element_text = ""
        if isinstance(elements, Mapping) and elements:
            element_text = (
                "（"
                + "、".join(f"{key}{value}%" for key, value in elements.items())
                + "）"
            )
        traits = []
        for key, label in (
            ("能否闪避", "可闪避"),
            ("能否暴击", "可暴击"),
            ("能否格挡", "可格挡"),
        ):
            if node.get(key):
                traits.append(label)
        trait_text = f"，{'、'.join(traits)}" if traits else ""
        defense_rule = str(node.get("防御规则") or "")
        damage_type = "真实伤害" if defense_rule == "真实" else "伤害"
        return (f"对{target}造成{amount}{element_text}{damage_type}{trait_text}",)
    if ability == "恢复资源":
        return (
            (
                f"{_target(node.get('目标'))}恢复"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "消耗资源":
        return (
            (
                f"{_target(node.get('目标'))}消耗"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "支付代价":
        kind = str(node.get("代价类型") or "代价")
        failure = "，不足则无法施展" if node.get("不足时是否失败") else ""
        if kind == "资源":
            return (
                (
                    f"消耗{_target(node.get('目标'))}的"
                    f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
                    f"{failure}"
                ),
            )
        if kind == "状态层数":
            return (
                f"消耗{_status(node.get('状态'))}{_value(node.get('数值'))}层{failure}",
            )
        if kind == "行动条":
            return (
                f"令{_target(node.get('目标'))}行动延后{_value(node.get('数值'))}点{failure}",
            )
        if kind == "技能冷却":
            return (
                (
                    f"令{_target(node.get('目标'))}的{_skill(node.get('技能'))}"
                    f"增加{_value(node.get('数值'))}次行动冷却{failure}"
                ),
            )
        return (f"支付{kind}{failure}",)
    if ability == "设置资源":
        return (
            (
                f"将{_target(node.get('目标'))}的{node.get('资源', '资源')}设为"
                f"{_resource_amount(node.get('数值'), node.get('资源', '资源'))}"
            ),
        )
    if ability == "转移资源":
        return (
            (
                f"从{_target(node.get('来源目标'))}向{_target(node.get('接收目标'))}"
                f"转移{_resource_amount(node.get('数值'), node.get('来源资源', '资源'))}"
            ),
        )
    if ability == "添加状态":
        state = node.get("状态")
        if not isinstance(state, Mapping):
            return (f"{_target(node.get('目标'))}获得状态",)
        name = str(state.get("名称") or "未名状态")
        duration = state.get("剩余行动")
        suffix = f"，持续{duration}次行动" if duration is not None else ""
        attributes = state.get("属性")
        if isinstance(attributes, Mapping) and attributes:
            changes = "、".join(
                f"{key}{_signed('增加' if float(value) >= 0 else '减少', abs(value))}"
                for key, value in attributes.items()
                if isinstance(value, (int, float))
            )
            if changes:
                suffix += f"（{changes}）"
        stacks = state.get("层数上限")
        if stacks is not None:
            suffix += f"，最多{stacks}层"
        return (f"{_target(node.get('目标'))}获得“{name}”{suffix}",)
    if ability in {"移除状态", "增加状态层数", "消耗状态层数", "延长状态", "缩短状态"}:
        state = _status(node.get("状态"))
        if ability == "移除状态":
            return (f"移除{state}",)
        if ability == "增加状态层数":
            return (f"令{state}增加{node.get('层数', 1)}层",)
        if ability == "消耗状态层数":
            return (f"消耗{state}{node.get('层数', 1)}层",)
        direction = "延长" if ability == "延长状态" else "缩短"
        return (f"令{state}{direction}{node.get('持续数值', '')}次行动",)
    if ability in {"复制状态", "转移状态"}:
        verb = "复制" if ability == "复制状态" else "转移"
        return (
            f"将{_status(node.get('状态'))}{verb}给{_target(node.get('接收目标'))}",
        )
    if ability == "修改行动条":
        method = "提前" if node.get("方式") == "增加" else "延后"
        return (
            f"令{_target(node.get('目标'))}行动{method}{_value(node.get('数值'))}点",
        )
    if ability == "修改技能冷却":
        method = {"增加": "延长", "减少": "缩短", "设置": "设为"}.get(
            str(node.get("方式") or ""), "改变"
        )
        return (
            f"令{_target(node.get('目标'))}的{_skill(node.get('技能'))}冷却{method}{_value(node.get('数值'))}次行动",
        )
    if ability == "修改机制计量":
        method = str(node.get("方式") or "改变")
        value = _value(node.get("数值", ""))
        raw_counter = _display_name(node.get("计量") or "效果")
        counter = {"分伤": "伤害分担强度"}.get(raw_counter, raw_counter)
        limit = node.get("最高值")
        suffix = (
            f"（上限{limit}）" if isinstance(limit, (int, float)) and limit < 999 else ""
        )
        target = _target(node.get("目标"))
        prefix = "" if target == "自身" else target
        return (f"{prefix}{counter}{_change(method, value)}{suffix}",)
    if ability == "追加攻击":
        return (
            f"对{_target(node.get('目标'))}追加一次{node.get('威力倍率', 1)}倍威力攻击",
        )
    if ability == "分摊伤害":
        return (f"由{_target(node.get('目标'))}分摊{node.get('比例', 0)}%伤害",)
    if ability == "转移伤害":
        return (f"将{_amount(node.get('数值'))}伤害转给{_target(node.get('目标'))}",)
    if ability == "抵挡致命伤害":
        return (f"抵挡一次致命伤害，并至少保留{node.get('保留血气', 1)}点血气",)
    if ability == "复活":
        return (
            f"复活{_target(node.get('目标'))}，恢复{node.get('血气百分比', 10)}%血气与{node.get('精神百分比', 0)}%精神",
        )
    if ability == "修改事件数值":
        return (f"令本次效果数值{_change(node.get('方式'), _value(node.get('数值')))}",)
    if ability == "修改事件目标":
        return (f"令本次效果改为作用于{_target(node.get('目标'))}",)
    if ability == "修改事件标签":
        return (
            f"为本次效果{node.get('方式', '添加')}标签：{'、'.join(map(str, node.get('标签') or ()))}",
        )
    if ability == "取消事件":
        return ("取消本次效果",)
    if ability == "触发技能":
        exemptions = []
        if node.get("忽略代价"):
            exemptions.append("不消耗精神")
        if node.get("忽略冷却"):
            exemptions.append("无视冷却")
        suffix = f"（{'、'.join(exemptions)}）" if exemptions else ""
        return (
            f"立即对{_target(node.get('目标'))}施展{_skill(node.get('技能'))}{suffix}",
        )
    if ability == "记录战斗事实":
        name = str(node.get("名称") or "战斗记录")
        value = node.get("值")
        mode = str(node.get("方式") or "覆盖")
        value_text = _value(value)
        action = {
            "覆盖": "覆盖保存",
            "累加": "累计保存",
        }.get(mode, f"按{mode}保存")
        retained = node.get("保留数量")
        suffix = f"，最多保留{retained}条" if retained is not None else ""
        return (f"将{value_text or '本次事件数值'}{action}为“{name}”{suffix}",)
    if ability == "保存结果":
        name = str(node.get("名称") or "临时结果")
        source = str(node.get("来源") or "上个效果")
        value = node.get("值")
        if value is not None:
            return (f"将{_value(value) or '指定值'}保存为“{name}”",)
        return (f"保存{source}的结果为“{name}”，供后续效果读取",)
    if ability == "修改战斗关联":
        method = "建立" if node.get("方式") == "建立" else "解除"
        left = _target(node.get("一方"))
        right = _target(node.get("另一方"))
        subject = "" if left == "自身" else left
        return (f"{subject}与{right}{method}“{node.get('名称', '战斗')}”关联",)
    if ability == "修改技能":
        field = {"精神消耗": "精神消耗", "冷却行动": "冷却"}.get(
            str(node.get("字段") or ""), str(node.get("字段") or "技能数值")
        )
        skill = _skill(node.get("技能"))
        if node.get("字段") == "禁用" and isinstance(node.get("值"), bool):
            state = "无法施展" if node["值"] else "恢复施展"
            return (f"令{_target(node.get('目标'))}的{skill}{state}",)
        return (
            (
                f"令{_target(node.get('目标'))}{skill}的{field}"
                f"{_signed(node.get('方式'), node.get('值'))}"
            ),
        )
    if ability == "复制技能":
        return (
            (
                f"将{_target(node.get('来源目标'))}的{_skill(node.get('技能'))}"
                f"复制给{_target(node.get('接收目标'))}，"
                f"记作“{node.get('名称', '复制技能')}”"
            ),
        )
    if ability == "修改行动意图":
        if node.get("字段") == "目标":
            return (f"令行动目标改为{_target(node.get('目标'))}",)
        return (f"改变行动意图中的{node.get('字段', '选择')}",)
    if ability == "转化事件":
        return (f"将本次效果转化为“{node.get('事件', '另一效果')}”",)
    if ability == "修改判定":
        return (
            f"令接下来{node.get('次数', 1)}次{node.get('判定', '判定')}{node.get('方式', '生效')}",
        )
    if ability == "修改战场规则":
        name = str(node.get("名称") or "战场规则")
        rule = node.get("规则")
        listeners = rule.get("监听") if isinstance(rule, Mapping) else ()
        detail = "；".join(_nodes(listeners, related))
        suffix = f"：{detail}" if detail else ""
        return (f"{node.get('方式', '添加')}战场规则“{name}”{suffix}",)
    if ability == "切换形态":
        definition = node.get("定义")
        changes = ""
        if isinstance(definition, Mapping):
            attributes = definition.get("属性变化")
            if isinstance(attributes, Mapping):
                changes = (
                    "（"
                    + "、".join(
                        f"{key}{_signed('增加' if value >= 0 else '减少', abs(value))}"
                        for key, value in attributes.items()
                        if isinstance(value, (int, float))
                    )
                    + "）"
                )
        target = _target(node.get("目标"))
        prefix = "进入" if target == "自身" else f"令{target}进入"
        return (f"{prefix}“{node.get('形态', '新形态')}”{changes}",)
    if ability == "创建战斗对象":
        definition = node.get("定义")
        if not isinstance(definition, Mapping):
            return (f"创建一个{node.get('类型', '战斗对象')}",)
        details = []
        if definition.get("耐久") is not None:
            details.append(f"耐久{definition['耐久']}")
        if definition.get("持续行动") is not None:
            details.append(f"持续{definition['持续行动']}次行动")
        listeners = "；".join(_nodes(definition.get("监听"), related))
        if listeners:
            details.append(listeners)
        suffix = f"：{'；'.join(details)}" if details else ""
        return (
            f"召出{node.get('类型', '战斗对象')}“{definition.get('名称', '未名造物')}”{suffix}",
        )
    if ability == "移除战斗对象":
        object_id = _value(node.get("对象ID"))
        return (
            (
                f"移除战斗对象“{object_id}”"
                if object_id
                else "移除自身全部召唤物与构造物"
            ),
        )
    if ability == "修改归属":
        return (
            f"将{_target(node.get('目标'))}的{node.get('字段', '归属')}改为{node.get('阵营') or _target(node.get('归属目标'))}",
        )
    if ability == "回放效果":
        return (f"以{node.get('倍率', 1)}倍强度再次施展{node.get('范围', '上个效果')}",)
    if ability == "修改战术":
        tactics = node.get("战术")
        arrangements: list[str] = []
        if isinstance(tactics, Sequence) and not isinstance(tactics, (str, bytes)):
            for tactic in tactics:
                if isinstance(tactic, Mapping):
                    action = str(tactic.get("行动") or "行动")
                    sorting = str(tactic.get("目标排序") or "默认目标")
                    arrangements.append(f"{action}（{sorting}目标）")
        return (
            f"将{_target(node.get('目标'))}的战术{node.get('方式', '调整')}为"
            + "、".join(arrangements),
        )
    if ability in {"引用战斗机制", "引用被动机制"}:
        mechanism = related.get(str(node.get("机制") or ""))
        if mechanism is None:
            return ()
        definition = mechanism.fields.get("节点")
        detail = (
            "；".join(_combat_lines(definition, related))
            if isinstance(definition, Mapping)
            else ""
        )
        return (f"{mechanism.name}：{detail}" if detail else str(mechanism.name),)
    return ()


def _nodes(
    value: object, related: Mapping[str, object] | None = None
) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        return _combat_lines(value, related)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        line
        for node in value
        if isinstance(node, Mapping)
        for line in _combat_lines(node, related)
        if line
    )


def _conditions(value: object) -> str:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return "条件成立"
    conditions = [_condition(node) for node in value if isinstance(node, Mapping)]
    return "且".join(item for item in conditions if item) or "条件成立"


def _condition(node: Mapping[str, object]) -> str:
    ability = str(node.get("能力") or "")
    if ability == "概率条件":
        return f"有{_value(node.get('概率'))}%概率"
    if ability == "数值条件":
        return f"{_value(node.get('左值'))}{node.get('比较', '等于')}{_value(node.get('右值'))}"
    if ability == "状态条件":
        state = str(node.get("状态") or "指定状态")
        comparison = str(node.get("比较") or "存在")
        stacks = node.get("层数")
        suffix = (
            f"{stacks}层"
            if stacks is not None and comparison not in {"存在", "不存在"}
            else ""
        )
        return f"{_target(node.get('目标'))}的“{state}”{comparison}{suffix}"
    if ability == "类型条件":
        return f"{node.get('对象', '目标')}的{node.get('类型', '类型')}为{node.get('值', '')}"
    if ability == "组合条件":
        children = node.get("条件")
        values = []
        if isinstance(children, Sequence) and not isinstance(children, (str, bytes)):
            values = [
                _condition(value) for value in children if isinstance(value, Mapping)
            ]
        relation = str(node.get("关系") or "全部成立")
        separator = "或" if relation == "任一成立" else "且"
        result = separator.join(values)
        return f"不满足（{result}）" if relation == "全部不成立" else f"（{result}）"
    if ability == "标签条件":
        labels = "、".join(map(str, node.get("标签") or ()))
        relation = str(node.get("关系") or "包含任一")
        if relation == "为空":
            return f"{node.get('对象', '目标')}没有标签"
        if relation == "数量至少":
            return f"{node.get('对象', '目标')}至少有{node.get('数量', 1)}个指定标签"
        return f"{node.get('对象', '目标')}标签{relation}“{labels}”"
    return "条件成立"


def _target(value: object) -> str:
    if not isinstance(value, Mapping):
        return "自身"
    scope = str(value.get("范围") or "目标")
    label = {
        "自身": "自身",
        "当前目标": "当前目标",
        "敌方": "敌方",
        "己方": "己方",
        "全体": "战场全体",
        "效果来源": "效果来源",
        "事件来源": "事件来源",
        "事件承受者": "事件承受者",
        "行动者": "当前行动者",
        "关联对象": "关联对象",
        "主人": "主人",
        "控制者": "控制者",
    }.get(scope, scope)
    if value.get("选择全部"):
        label += "全体"
    else:
        count = value.get("数量")
        if isinstance(count, int) and count > 1:
            label = f"{count}名{label}"
        elif scope in {"敌方", "己方", "全体"}:
            label = f"一名{label}"
    sorting = str(value.get("排序") or "默认")
    sorting_text = {
        "随机": "随机",
        "血气比例从低到高": "血气比例最低",
        "血气比例从高到低": "血气比例最高",
        "速度从高到低": "速度最高",
        "行动条从高到低": "最先行动",
    }.get(sorting, "")
    if sorting_text:
        label += f"（{sorting_text}）"
    if value.get("排除自身"):
        label += "（不含自身）"
    if value.get("生存状态") == "死亡":
        label = "已阵亡的" + label
    return label


def _skill(value: object) -> str:
    if not isinstance(value, Mapping):
        return "技能"
    scope = str(value.get("范围") or "技能")
    name = str(value.get("名称") or "")
    if scope == "指定技能" and name:
        return f"“{name}”"
    label = {
        "全部技能": "技能",
        "当前技能": "当前技能",
        "可用技能": "可用技能",
        "冷却中的技能": "冷却中的技能",
    }.get(scope, scope)
    if scope == "当前技能":
        return label
    if value.get("选择全部"):
        return "全部" + label
    count = value.get("数量")
    prefix = f"{count}门" if isinstance(count, int) and count > 1 else "一门"
    sorting = str(value.get("排序") or "无")
    sorting_text = {
        "随机": "随机",
        "冷却从低到高": "冷却最低的",
        "冷却从高到低": "冷却最高的",
        "释放顺序": "释放顺序最前的",
    }.get(sorting, "")
    return sorting_text + prefix + label


def _status(value: object) -> str:
    if isinstance(value, str):
        return f"“{value}”"
    if not isinstance(value, Mapping):
        return "指定状态"
    target = _target(value.get("目标")) if value.get("目标") is not None else ""
    name = str(value.get("名称") or "")
    category = str(value.get("分类") or "")
    labels = "、".join(map(str, value.get("标签") or ()))
    identity = f"“{name}”" if name else f"{category}状态" if category else "状态"
    if labels:
        identity += f"（{labels}）"
    if value.get("选择全部"):
        identity = "全部" + identity
    return target + identity


def _value(value: object) -> str:
    if isinstance(value, Mapping):
        ability = str(value.get("能力") or "")
        if ability == "读取数值":
            source = str(value.get("来源") or "数值")
            target = _target(value.get("目标")) if value.get("目标") is not None else ""
            label = {
                "自身属性": f"自身{value.get('属性', '属性')}",
                "目标属性": f"目标{value.get('属性', '属性')}",
                "效果来源属性": f"效果来源的{value.get('属性', '属性')}",
                "机制计量": f"{target}{value.get('计量', '机制计量')}",
                "事件事实": f"本次{value.get('事实', '事件数值')}",
                "战斗记录": f"战斗记录“{value.get('名称', '')}”",
                "状态层数": f"{target}“{value.get('状态', '')}”层数",
                "保存结果": f"已保存的“{value.get('名称', '结果')}”",
                "行动条": f"{target}行动进度",
                "自身当前血气": "自身当前血气",
                "自身已损失血气": "自身已损失血气",
                "目标当前血气": "目标当前血气",
                "目标已损失血气": "目标已损失血气",
                "自身当前精神": "自身当前精神",
                "目标当前精神": "目标当前精神",
                "目标已损失精神": "目标已损失精神",
                "自身当前护盾": "自身当前护盾",
                "目标当前护盾": "目标当前护盾",
            }.get(source, source.replace("自身", "自身的").replace("目标", "目标的"))
            percent = value.get("百分比", 100)
            return f"{label}{percent}%" if percent != 100 else label
        if ability == "计算数值":
            operators = {
                "相加": "+",
                "相减": "-",
                "相乘": "×",
                "相除": "÷",
                "取余": "取余",
                "乘方": "的次方",
                "取小": "与二者较小值",
                "取大": "与二者较大值",
            }
            operator = operators.get(
                str(value.get("方式") or ""), str(value.get("方式") or "计算")
            )
            return (
                f"（{_value(value.get('左值'))}{operator}{_value(value.get('右值'))}）"
            )
        if ability == "随机数值":
            return f"{value.get('最低值', 0)}至{value.get('最高值', 0)}之间的随机数"
        if ability == "聚合数值":
            method = str(value.get("方式") or "数量")
            if method == "数量":
                return f"{_target(value.get('目标'))}的数量"
            return (
                f"{_target(value.get('目标'))}中{_value(value.get('数值'))}的{method}"
            )
        attribute = value.get("属性")
        percent = value.get("百分比")
        fixed = value.get("固定值")
        if attribute is not None and percent is not None:
            return f"{attribute}的{percent}%"
        if fixed is not None:
            return str(fixed)
    return str(value if value is not None else "")


def _amount(value: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value}点"
    text = _value(value)
    return f"相当于{text}的" if text else ""


def _resource_amount(value: object, resource: object) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value}点{resource}"
    text = _value(value)
    return f"相当于{text}的{resource}" if text else str(resource)


def _change(method: object, value: object) -> str:
    normalized = str(method or "")
    if normalized == "增加":
        return f"+{value}"
    if normalized == "减少":
        return f"-{value}"
    if normalized == "设置":
        return f"设为{value}"
    if normalized == "清空":
        return "清零"
    if normalized in {"乘算", "乘以百分比"}:
        return f"变为原本的{value}%"
    if normalized:
        return f"{normalized}{value}"
    return str(value)


def _display_name(value: object) -> str:
    text = str(value or "")
    return text[6:] if len(text) > 6 and text[:6].isdigit() else text


def _signed(method: object, value: object) -> str:
    sign = "+" if method == "增加" else "-" if method == "减少" else ""
    return f"{sign}{value if value is not None else ''}"


def _display_title(category: str) -> tuple[str, str]:
    return {
        "功法": ("功法", "skill"),
        "真意": ("真意", "skill"),
        "气机": ("气机", "status"),
        "器律": ("器律", "weapon"),
        "阵法": ("阵法", "skill"),
        "先天灵宝": ("先天灵宝", "item"),
        "丹药": ("丹药", "recovery"),
        "灵植": ("灵植", "recovery"),
        "灵矿": ("灵矿", "material"),
        "兽宝": ("兽宝", "material"),
        "物品": ("物品", "item"),
        "丹方": ("丹方", "recovery"),
        "道侣": ("道侣", "player"),
        "机制": ("战斗机制", "combat"),
        "伤势": ("伤势", "status"),
    }.get(category, (category, "docs"))


def _detail_title(category: str) -> str:
    return {
        "功法": "法门",
        "真意": "真意",
        "气机": "契合",
        "器律": "器纹",
        "丹药": "丹效",
        "丹方": "炼制",
        "阵法": "阵势",
        "先天灵宝": "权柄",
        "道侣": "人物志",
        "伤势": "影响",
        "机制": "运转",
        "境界": "境界",
        "人物状态": "状态流转",
    }.get(category, "记载")


def _category_tone(category: str) -> str:
    return {
        "功法": "mystic",
        "真意": "mystic",
        "气机": "info",
        "器律": "metal",
        "阵法": "mystic",
        "先天灵宝": "cultivation",
        "丹药": "positive",
        "灵植": "wood",
        "灵矿": "metal",
        "道侣": "companion",
        "伤势": "danger",
    }.get(category, "emphasis")


__all__ = ["inspection", "missing_query"]
