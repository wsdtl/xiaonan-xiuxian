"""山门命令回复构造。"""

from __future__ import annotations

from game.features.zongmen_shanmen import GateCopy, GateResult
from message import DocumentMessage, M

_ERROR_KEYS = {
    "not_member": "未加入宗门",
    "not_leader": "不是领队",
    "not_at_gate": "不在山门",
    "not_in_cave": "不在洞天",
    "external_member": "外宗成员",
    "space_conflict": "空间冲突",
    "current_busy": "当前忙碌",
    "fellowship_conflict": "同行变化",
    "sect_changed": "同行变化",
}


def result(copy: GateCopy, value: GateResult) -> DocumentMessage:
    key = "进入" if value.action == "进入" else "离开"
    return (
        M.document()
        .header(_text(copy, "结果", "标题"))
        .inline_section(
            _text(copy, "结果", "空间"),
            M.status(_text(copy, "结果", key), tone="positive"),
            icon=_text(copy, "图标", "结果"),
        )
        .section(_text(copy, "结果", "空间"), icon=_text(copy, "图标", "空间"))
        .field(_text(copy, "结果", "人数"), value.participant_count)
        .build()
    )


def error(copy: GateCopy, code: str) -> DocumentMessage:
    return (
        M.document()
        .section(_text(copy, "结果", "标题"), icon=_text(copy, "图标", "结果"))
        .line(
            M.status("通行受阻", tone="danger"),
            " ",
            _text(copy, "错误", _ERROR_KEYS.get(code, "同行变化")),
        )
        .build()
    )


def _text(copy: GateCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "result"]
