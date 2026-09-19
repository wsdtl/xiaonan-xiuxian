"""队伍命令回复构造。"""

from __future__ import annotations

from game.features.duiwu import TeamAction, TeamCopy, TeamOperationResult, TeamPage
from message import M

from ...actions import message_actions

_ERROR_KEYS = {
    "target_missing": "缺少目标",
    "target_not_found": "目标不存在",
    "target_ambiguous": "目标不唯一",
    "cannot_invite_self": "不能邀请自己",
    "not_same_location": "不在同处",
    "target_busy": "目标忙碌",
    "actor_busy": "当前忙碌",
    "not_grouped": "未组队",
    "already_grouped": "已经组队",
    "target_grouped": "目标已经组队",
    "not_leader": "不是队长",
    "target_not_member": "目标不是成员",
    "cannot_remove_leader": "不能操作队长",
    "cannot_transfer_self": "不能移交自己",
    "team_full": "队伍已满",
    "pending_invitation_exists": "已有邀请",
    "invitation_missing": "没有邀请",
    "invitation_expired": "邀请失效",
    "team_changed": "队伍变化",
    "team_state_invalid": "队伍变化",
    "team_state_incomplete": "队伍变化",
    "team_role_inconsistent": "队伍变化",
    "team_snapshot_invalid": "队伍变化",
    "team_snapshot_overflow": "队伍变化",
    "member_cannot_start": "队员不能发起",
}


def page(
    copy: TeamCopy,
    value: TeamPage,
    actions: tuple[TeamAction, ...],
    *,
    notice: str = "",
):
    builder = M.document().header(_text(copy, "查看", "标题"))
    if notice:
        builder.inline_section(
            _text(copy, "查看", "状态"),
            (M.status("完成", tone="positive"), *M.text(f" {notice}")),
            icon=_text(copy, "图标", "结果"),
        )
    if not value.members:
        builder.section(
            _text(copy, "查看", "状态"), icon=_text(copy, "图标", "队伍")
        ).line(M.status("独行", tone="muted"), " ", _text(copy, "查看", "未组队"))
    else:
        builder.section(
            _text(copy, "查看", "状态"), icon=_text(copy, "图标", "队伍")
        ).field(
            _text(copy, "查看", "人数"),
            _text(copy, "格式", "人数").format_map(
                {"当前": len(value.members), "上限": value.maximum_players}
            ),
        )
        if len(value.members) == 1:
            builder.line(_text(copy, "查看", "单人队伍"))
        builder.section(_text(copy, "查看", "成员"), icon=_text(copy, "图标", "成员"))
        template = _text(copy, "格式", "成员")
        for index, member in enumerate(value.members, start=1):
            builder.item(index, template.format_map({"姓名": member.name, "身份": member.role}))
    if value.invitation is not None:
        builder.section(
            _text(copy, "查看", "待处理邀请"),
            icon=_text(copy, "图标", "邀请"),
        ).line(
            _text(copy, "格式", "邀请来源").format_map({"姓名": value.invitation.inviter_name})
        ).small(
            _text(copy, "格式", "邀请时限").format_map(
                {"分钟": value.invitation.remaining_minutes}
            )
        )
    return builder.actions(message_actions(actions)).build()


def operation(
    copy: TeamCopy,
    value: TeamOperationResult,
    actions: tuple[TeamAction, ...],
):
    notice = _text(copy, "结果", value.action).format_map({"姓名": value.target_name})
    return page(copy, value.page, actions, notice=notice)


def error(copy: TeamCopy, code: str):
    key = _ERROR_KEYS.get(code, "队伍变化")
    return (
        M.document()
        .section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "邀请"))
        .line(M.status("操作失败", tone="danger"), " ", _text(copy, "错误", key))
        .build()
    )


def format_error(copy: TeamCopy):
    return (
        M.document()
        .section(_text(copy, "查看", "标题"), icon=_text(copy, "图标", "邀请"))
        .line(M.status("格式有误", tone="warning"), " ", _text(copy, "错误", "格式"))
        .build()
    )


def _text(copy: TeamCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "format_error", "operation", "page"]
