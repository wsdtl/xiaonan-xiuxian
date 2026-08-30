"""宗门同行命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_tongxing import (
    SectFollowAction,
    SectFollowCopy,
    SectFollowPage,
    SectFollowResult,
)
from message import M

from ...actions import message_actions

_ERROR_KEYS = {
    "not_member": "未加入宗门",
    "not_leader": "不是宗主",
    "follow_not_started": "尚未召集",
    "follow_full": "同行已满",
    "not_following": "尚未同行",
    "target_not_following": "目标不在同行",
    "target_missing": "缺少目标",
    "target_ambiguous": "目标不唯一",
    "follow_leader_cannot_leave": "宗主不能离开",
    "cannot_remove_leader": "不能请离宗主",
    "not_same_location": "不在同处",
    "actor_busy": "当前忙碌",
    "fellowship_conflict": "同行状态冲突",
    "sect_changed": "同行变化",
}


def page(
    copy: SectFollowCopy,
    value: SectFollowPage,
    actions: tuple[SectFollowAction, ...],
    *,
    notice: str = "",
):
    title = f"{value.sect_name} · 同行" if value.sect_name else _text(copy, "查看", "标题")
    builder = M.document().header(title)
    if notice:
        builder.inline_section(
            _text(copy, "查看", "状态"), notice, icon=_text(copy, "图标", "结果")
        )
    builder.inline_section(
        _text(copy, "查看", "当前"),
        _text(copy, "查看", value.page),
        icon=_text(copy, "图标", "同行"),
    )
    if value.members:
        leader = next(
            (member.name for member in value.members if member.role == "宗主"),
            value.leader_name,
        )
        builder.section(
            _text(copy, "查看", "成员"), icon=_text(copy, "图标", "成员")
        ).row(
            (
                _text(copy, "查看", "人数"),
                _text(copy, "格式", "人数").format(
                    当前=len(value.members), 上限=value.maximum_members
                ),
            ),
            ("领队", leader),
        )
        names = tuple(member.name for member in value.members if member.name != leader)
        if names:
            builder.field(f"同行（{len(names)}）", "、".join(names))
    return builder.actions(message_actions(actions)).build()


def operation(
    copy: SectFollowCopy,
    value: SectFollowResult,
    actions: tuple[SectFollowAction, ...],
):
    notice = _text(copy, "结果", value.action).format(姓名=value.target_name)
    return page(copy, value.page, actions, notice=notice)


def error(copy: SectFollowCopy, code: str):
    return (
        M.document()
        .section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "结果"))
        .line(_text(copy, "错误", _ERROR_KEYS.get(code, "同行变化")))
        .build()
    )


def format_error(copy: SectFollowCopy):
    return (
        M.document()
        .section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "结果"))
        .line(_text(copy, "错误", "格式"))
        .build()
    )


def _text(copy: SectFollowCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "format_error", "operation", "page"]
