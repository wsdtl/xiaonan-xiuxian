"""查看正式编号实体的命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from game.features.chakan_wupin import ItemInspectionResult
from message import M


def missing_query():
    return (
        M.document().section("查看", icon="item")
        .line("请提供正式编号或完整名称。")
        .line("例如：查看 100005")
        .line("例如：查看 小还丹")
        .build()
    )


def inspection(result: ItemInspectionResult):
    if result.detail is None and result.candidates:
        reply = (
            M.document()
            .header("实体查询")
            .section("名称不唯一", icon="notice")
            .line(f"“{result.query}”对应多个实体，请选择唯一编号查看。")
            .section("候选")
        )
        for index, candidate in enumerate(result.candidates, start=1):
            reply.item(
                index,
                M.command(
                    f"{candidate.section} · {candidate.name}",
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
            .line(f"未找到正式编号实体：{result.query}")
            .line("请使用 JSON 中的正式编号或完整名称。")
            .build()
        )
    detail = result.detail
    reply = (
        M.document()
        .header(detail.name)
        .section("实体", icon="item")
        .row(("类别", detail.category), ("编号", detail.item_id))
    )
    if detail.description:
        reply.section("说明", icon="docs").line(detail.description)
    if detail.fields:
        reply.section("定义", icon="skill")
        for line in _definition_lines(detail.section, detail.fields):
            reply.line(line)
    else:
        reply.section("定义", icon="notice").line("当前实体未声明可展示的补充字段。")
    return reply.build()


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


def _definition_lines(section: str, fields: Mapping[str, object]) -> tuple[str, ...]:
    """把 JSON 结构压成玩家能读懂的定义摘要，禁止泄露 mappingproxy。"""

    if section in {"功法", "真意", "气机", "器律"}:
        lines: list[str] = []
        attributes = fields.get("属性构成")
        if isinstance(attributes, Mapping):
            lines.append("五行：" + "、".join(f"{key}{value}" for key, value in attributes.items()))
        if section == "器律":
            for key in ("器阶", "铸法"):
                if key in fields:
                    lines.append(f"{key}：{fields[key]}")
        abilities = fields.get("能力")
        if isinstance(abilities, Sequence) and not isinstance(abilities, (str, bytes)):
            labels = []
            for ability in abilities:
                if isinstance(ability, Mapping):
                    labels.append(str(ability.get("名称") or ability.get("能力") or "未命名能力"))
            if labels:
                lines.append("能力：" + "、".join(labels))
        return tuple(lines)
    if section == "阵法":
        lines = []
        if "宏观监测" in fields:
            lines.append("监测：" + "、".join(map(str, fields["宏观监测"])))
        if "阵法核心" in fields:
            lines.append(f"核心：{fields['阵法核心']}")
        grades = fields.get("品级")
        if isinstance(grades, Mapping):
            lines.append("品级：" + "、".join(str(key) for key in grades))
        return tuple(lines)
    if section in {"机制", "伤势", "战场环境"}:
        lines = []
        for key, value in fields.items():
            if isinstance(value, Mapping):
                if key == "节点":
                    lines.append(f"节点：{value.get('能力', '未说明')} · {value.get('事件', '')}".rstrip(" ·"))
                elif key == "战斗状态":
                    lines.append(f"战斗状态：{value.get('类别', '未说明')}")
                else:
                    lines.append(f"{key}：" + "、".join(str(item) for item in value))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                lines.append(f"{key}：共{len(value)}项")
            else:
                lines.append(f"{key}：{value}")
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


__all__ = ["inspection", "missing_query"]
