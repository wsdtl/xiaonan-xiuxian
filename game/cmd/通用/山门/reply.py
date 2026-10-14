"""山门命令回复构造。"""

from __future__ import annotations

from ...presentation import error_document

from game.features.zongmen_shanmen import GateAction, GateCopy, GateResult
from message import Action, DocumentMessage, M

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


def result(
    copy: GateCopy,
    value: GateResult,
    actions: tuple[GateAction, ...] = (),
) -> DocumentMessage:
    """进出结果卡。洞天里的建筑菜单随卡发（位置面板那一类底部按钮）。"""

    key = "进入" if value.action == "进入" else "离开"
    builder = (
        M.document()

        .inline_section(
            _text(copy, "结果", "空间"),
            M.status(_text(copy, "结果", key), tone="positive"),
            icon=_text(copy, "图标", "结果"),
        )
        .section(_text(copy, "结果", "空间"), icon=_text(copy, "图标", "空间"))
        .field(_text(copy, "结果", "人数"), value.participant_count)
    )
    for item in actions:
        builder = builder.action(
            Action(
                action_id=item.action_id,
                label=item.label,
                data=item.command,
                behavior=item.behavior,
                style=item.style,
            )
        )
    return builder.build()


def error(copy: GateCopy, code: str) -> DocumentMessage:
    # 统一走 error_document：无 ` / ` 的文案渲染结果与原来相同。
    return error_document(
        _text(copy, "结果", "标题"), _text(copy, "图标", "结果"), "通行受阻",
        _text(copy, "错误", _ERROR_KEYS.get(code, "同行变化")), tone="danger"
    )


def _text(copy: GateCopy, section: str, key: str) -> str:
    return copy.text[section][key]


__all__ = ["error", "result"]
