"""升阶命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from message import DocumentMessage, M

from game.features.shengjie import CraftingPlan, MaterialPlanView, ShengjieResult


def _text(copy: Mapping[str, str], key: str) -> str:
    return str(copy.get(key) or key)


def upgraded(copy: Mapping[str, str], value: ShengjieResult) -> DocumentMessage:
    builder = (
        M.document()
        .section(_text(copy, "标题"), icon="game.box")
        .row(
            (_text(copy, "物品"), M.text(value.item_name)),
            (_text(copy, "数量"), str(value.quantity)),
        )
        .row(
            (_text(copy, "来源"), f"{value.source_grade_name}"),
            (_text(copy, "目标"), M.text(value.target_grade_name, tone="positive")),
        )
        .section(_text(copy, "消耗"), icon="game.herb")
        .line(f"{value.total_cost} 黄品灵石（单件 {value.unit_cost}）")
        .field(
            _text(copy, "灵石"),
            f"{value.spirit_stone_after}（原 {value.spirit_stone_before}）",
        )
        .small(_text(copy, "成功"))
    )
    return builder.build()


def plan(
    copy: Mapping[str, str],
    value: CraftingPlan | MaterialPlanView,
) -> DocumentMessage:
    plan_value = value.plan
    title = _text(copy, "方案")
    if isinstance(value, CraftingPlan):
        subtitle = f"{value.kind} · {value.name}"
    else:
        subtitle = f"{value.category} · {value.target_grade_name}"
    builder = (
        M.document()
        .section(title, icon="game.spark")
        .line(subtitle)
    )
    if not plan_value.lines:
        builder.line(_text(copy, "无需"))
    else:
        builder.section(_text(copy, "执行"), icon="game.bag")
        for index, line in enumerate(plan_value.lines, start=1):
            command = (
                f"升阶 {line.source_grade_name}{line.item_name} "
                f"{line.target_grade_name} {line.quantity}"
            )
            builder.item(
                index,
                M.command(command, command),
                f" × {line.quantity} · {line.total_cost} 黄品",
            )
    builder.field(
        _text(copy, "合计"),
        f"{plan_value.total_cost} 黄品（余额 {plan_value.spirit_stone_before} → "
        f"{plan_value.spirit_stone_after}）",
    )
    if plan_value.missing:
        builder.section(_text(copy, "缺料"), icon="game.pin_doc")
        for index, missing in enumerate(plan_value.missing, start=1):
            builder.item(
                index,
                f"{missing.category} · {missing.item_id or '任意'} · "
                f"{missing.quantity} 件",
            )
    if isinstance(value, CraftingPlan) and plan_value.satisfiable:
        builder.small(f"{_text(copy, '然后')}：{value.craft_command}")
    builder.small(_text(copy, "页脚"))
    return builder.build()


def error(copy: Mapping[str, str], message: str, command: str) -> DocumentMessage:
    return (
        M.document()
        .section(_text(copy, "标题"), icon="game.pin_doc")
        .line(M.text(message, tone="danger"))
        .small(f"写法：{command}")
        .build()
    )


__all__ = ["error", "plan", "upgraded"]
