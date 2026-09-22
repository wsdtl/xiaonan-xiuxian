"""道侣结交命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from decimal import Decimal

from game.features.daolv_jiejiao import (
    CompanionConversation,
    CompanionCopy,
    CompanionFarewellResult,
    CompanionGiftResult,
    CompanionInvitationResult,
    CompanionView,
)
from message import M

from ...actions import CommandAction, message_actions


def text(copy: CompanionCopy, section: str, key: str, values: Mapping[str, object] | None = None) -> str:
    return copy.text[section][key].format_map(values or {})


def error(copy: CompanionCopy, message: str):
    return (
        M.document()
        .section(text(copy, "错误", "标题"), icon=copy.icons["错误"])
        .line(M.status("交互失败", tone="danger"), " ", message)
        .build()
    )


def view(copy: CompanionCopy, value: CompanionView, actions: tuple[CommandAction, ...]):
    definition = value.definition
    relation_text = (
        text(copy, "查看", "尚未结交")
        if not value.has_relation
        else _affection(value.relation.current_affection)
    )
    return (
        M.document()
        .header(text(copy, "查看", "标题", {"名称": definition.name}))
        .section(text(copy, "查看", "身份"), icon=copy.icons["身份"])
        .row(
            (text(copy, "查看", "称号"), definition.title),
            (text(copy, "查看", "性别"), definition.gender),
        )
        .row(
            (text(copy, "查看", "境界"), definition.realm_name),
            (text(copy, "查看", "等级"), definition.level),
        )
        .line(definition.description)
        .section(text(copy, "查看", "喜好"), icon=copy.icons["喜好"])
        .line(
            "、".join(
                name.removeprefix("灵植-") + "灵植"
                for name in definition.favorite_pool_names
            )
        )
        .small(definition.dialogue.preference)
        .section(text(copy, "查看", "关系"), icon=copy.icons["关系"])
        .field(
            text(copy, "查看", "当前好感"),
            M.progress(
                float(value.relation.current_affection),
                100,
                tone="companion",
                display="value",
            )
            if value.has_relation
            else M.status(relation_text, tone="muted"),
        )
        .line(
            M.status(
                "同行中" if value.is_active else "未同行",
                tone="positive" if value.is_active else "muted",
            ),
            " ",
            text(copy, "查看", "同行中")
            if value.is_active
            else text(copy, "查看", "未同行"),
        )
        .actions(message_actions(actions))
        .build()
    )


def conversation(
    copy: CompanionCopy,
    result: CompanionConversation,
    actions: tuple[CommandAction, ...],
):
    definition = result.view.definition
    return (
        M.document()
        .header(text(copy, "交谈", "标题", {"名称": definition.name}))
        .section(definition.title, icon=copy.icons["交谈"])
        .small(f"“{result.line}”")
        .small(definition.dialogue.preference)
        .actions(message_actions(actions))
        .build()
    )


def gift(
    copy: CompanionCopy,
    result: CompanionGiftResult,
    actions: tuple[CommandAction, ...],
):
    definition = result.view.definition
    builder = M.document().header(text(copy, "赠礼", "标题", {"名称": definition.name}))
    if not result.accepted:
        return (
            builder.section(definition.title, icon=copy.icons["赠礼"])
            .line(M.status("婉拒", tone="warning"))
            .line(
                text(copy, "赠礼", "婉拒", {"名称": definition.name, "物品": result.item.name})
            )
            .small(f"“{result.dialogue}”")
            .small(text(copy, "赠礼", "物品未消耗"))
            .actions(message_actions(actions))
            .build()
        )
    if result.grade is None:
        raise RuntimeError("已接受的道侣赠礼缺少品级结果")
    if result.replayed:
        builder.section(definition.title, icon=copy.icons["赠礼"]).line(
            M.status("已处理", tone="info"), " ", text(copy, "赠礼", "已处理")
        )
    else:
        builder.section(definition.title, icon=copy.icons["赠礼"]).line(
            M.status("已收下", tone="positive"),
            " ",
            text(
                copy,
                "赠礼",
                "收下", {"名称": definition.name, "数量": result.quantity, "品级": result.grade.name, "物品": result.item.name},
            ),
        ).small(f"“{result.dialogue}”").row(
            (
                text(copy, "赠礼", "基础好感"),
                M.text(_affection(result.base_affection), tone="companion"),
            ),
            (
                text(copy, "赠礼", "品级倍率", {"品级": result.grade.name}),
                result.grade.ability_multiplier,
            ),
        ).row(
            (text(copy, "赠礼", "喜好程度"), result.preference),
            (
                text(copy, "赠礼", "喜好倍率"),
                result.preference_multiplier,
            ),
        ).row(
            (
                text(copy, "赠礼", "实际好感"),
                M.text(f"+{_affection(result.affection_gain)}", tone="positive"),
            ),
            (
                text(copy, "赠礼", "当前好感"),
                M.progress(
                    float(result.affection_after),
                    100,
                    tone="companion",
                    display="value",
                ),
            ),
        )
    if result.first_full:
        builder.line(
            M.status("好感圆满", tone="positive"), " ", text(copy, "赠礼", "首次圆满")
        ).small(f"“{definition.dialogue.full_affection}”")
        if result.reward_item is None or result.reward_grade is None:
            raise RuntimeError("道侣首次圆满结果缺少回礼")
        builder.field(
            text(copy, "赠礼", "获得回礼"),
            (
                M.command(
                    M.text(result.reward_item.name, tone="companion"),
                    f"查看 {result.reward_item.item_id}",
                ),
                *M.text(f" × {result.reward_quantity}"),
            ),
        )
    if result.treasure_activation is not None:
        activation = result.treasure_activation
        builder.section("先天灵宝", icon="item").field(
            activation.name, activation.summary
        )
    builder.small("就近寻访道侣、投其所好赠礼；好感达到 100 才能邀约同行")
    return builder.actions(message_actions(actions)).build()


def invitation(
    copy: CompanionCopy,
    result: CompanionInvitationResult,
    actions: tuple[CommandAction, ...],
):
    definition = result.view.definition
    builder = (
        M.document()
        .header(text(copy, "邀约", "标题", {"名称": definition.name}))
        .section(definition.title, icon=copy.icons["邀约"])
        .small(f"“{result.dialogue}”")
    )
    if result.already_active:
        builder.line(
            M.status("同行中", tone="info"),
            " ",
            text(copy, "邀约", "已经同行", {"名称": definition.name}),
        )
    elif result.first_invitation:
        builder.line(
            M.status("邀约成功", tone="positive"), " ", text(copy, "邀约", "首次同行")
        ).row(("资质", result.instance.qualification), ("同行", definition.name))
    else:
        builder.line(
            M.status("邀约成功", tone="positive"),
            " ",
            text(copy, "邀约", "再次同行", {"名称": definition.name}),
        )
    return builder.actions(message_actions(actions)).build()


def farewell(
    copy: CompanionCopy,
    result: CompanionFarewellResult,
    actions: tuple[CommandAction, ...],
):
    definition = result.definition
    return (
        M.document()
        .header(text(copy, "暂别", "标题", {"名称": definition.name}))
        .section(definition.title, icon=copy.icons["暂别"])
        .line(M.status("已经暂别", tone="muted"))
        .small(f"“{result.dialogue}”")
        .small(
            text(
                copy,
                "暂别",
                "返回故地", {"名称": definition.name, "地点": definition.location_name},
            )
        )
        .actions(message_actions(actions))
        .build()
    )


def _affection(value: Decimal) -> str:
    return format(value, "f").rstrip("0").rstrip(".") or "0"


__all__ = ["conversation", "error", "farewell", "gift", "invitation", "text", "view"]
