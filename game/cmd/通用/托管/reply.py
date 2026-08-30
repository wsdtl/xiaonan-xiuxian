"""托管命令回复构造。"""

from __future__ import annotations

from datetime import datetime

from game.features.tuoguan import HostingCopy, HostingResult
from message import M

_MODE_KEYS = {"personal": "独行", "team": "队伍", "sect": "宗门"}
_PHASE_KEYS = {
    "待开始": "等待开始",
    "待结束": "等待结束",
    "执行开始": "执行开始",
    "执行结束": "执行结束",
}
_ERROR_KEYS = {
    "member_cannot_start": "不是领队",
    "member_cannot_cancel": "跟随者不能取消",
    "member_cannot_resume": "不是领队恢复",
    "already_hosting": "已经托管",
    "not_hosting": "尚未托管",
    "not_paused": "无需恢复",
    "participant_busy": "参与者忙碌",
    "fellowship_conflict": "同行冲突",
    "group_changed": "同行变化",
    "state_incomplete": "同行变化",
    "session_invalid": "同行变化",
    "transaction_invalid": "同行变化",
    "request_conflict": "执行冲突",
    "cancel_conflict": "取消冲突",
    "unknown_activity": "活动未知",
    "too_few_activities": "活动过少",
    "too_many_activities": "活动过多",
}


def result(copy: HostingCopy, value: HostingResult):
    session = value.session
    document = M.document().header(_text(copy, "结果", "标题"))
    if session is None:
        return (
            document.section(
                _text(copy, "结果", "标题"), icon=_text(copy, "图标", "状态")
            )
            .line(_text(copy, "结果", "无当前托管"))
            .build()
        )
    mode_key = _MODE_KEYS[session.mode]
    document.inline_section(
        _text(copy, "结果", "标题"),
        (
            _text(copy, "结果", "最近托管")
            if value.action == "查看" and not value.active
            else _text(copy, "结果", value.action)
        ),
        icon=_text(copy, "图标", "结果"),
    )
    document.section(_text(copy, "结果", mode_key), icon=_text(copy, "图标", "状态"))
    document.field(_text(copy, "结果", "人数"), len(session.participant_user_ids))
    document.field(_text(copy, "结果", "计划"), " → ".join(session.activities))
    activity_label = (
        "最后活动"
        if session.status in {"已取消", "已到期"}
        else _text(copy, "结果", "当前活动")
    )
    document.field(activity_label, session.current_activity)
    if session.status in {"已取消", "已到期"}:
        document.field(_text(copy, "结果", "当前阶段"), session.status)
    else:
        phase_key = _PHASE_KEYS.get(session.phase, "等待开始")
        document.field(
            _text(copy, "结果", "当前阶段"),
            f"{session.status} · {_text(copy, '结果', phase_key)}",
        )
    if session.next_trigger_at is not None:
        document.field(_text(copy, "结果", "下次触发"), _time(session.next_trigger_at))
    if session.expires_at is not None:
        document.field(_text(copy, "结果", "到期时间"), _time(session.expires_at))
    document.field(
        _text(copy, "结果", "完成循环"),
        f"{session.cycle_count}{_text(copy, '结果', '循环单位')}",
    )
    if session.last_error:
        document.section(_text(copy, "结果", "暂停原因")).line(session.last_error)
    elif session.last_message:
        document.section(_text(copy, "结果", "最近提示")).line(session.last_message)
    return document.build()


def error(copy: HostingCopy, code: str):
    return (
        M.document()
        .section(_text(copy, "结果", "标题"), icon=_text(copy, "图标", "结果"))
        .line(_text(copy, "错误", _ERROR_KEYS.get(code, "同行变化")))
        .build()
    )


def format_error(copy: HostingCopy):
    return error(copy, "format")


def _time(value: datetime) -> str:
    return value.astimezone().strftime("%m-%d %H:%M")


def _text(copy: HostingCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "format_error", "result"]
