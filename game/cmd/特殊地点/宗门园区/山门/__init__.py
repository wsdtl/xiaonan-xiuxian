"""宗门园区山门：外圈进入洞天、洞天离开的显式入口。"""

from __future__ import annotations

from typing import Any

from game.app import current_game_services
from game.features.zongmen_shanmen import GateAction, GateFeatureError
from message import M

from ....actions import message_actions
from ....command import GameCommand
from launch.adapter import MessageContext


def _text(copy: dict[str, str], key: str) -> str:
    return str(copy.get(key) or key)


def _page(
    copy: dict[str, str],
    actions: tuple[GateAction, ...],
    page: str,
    notice: str = "",
):
    builder = M.document().section(_text(copy, "标题"), icon="navigation").line(
        M.text(notice or _text(copy, page))
    )
    return builder.actions(message_actions(actions)).build()


@GameCommand.command(
    cmd="山门",
    metadata={
        "scope": "专属",
        "guard_rule": "已创建",
        "help": {
            "category": "宗门",
            "summary": "从宗门园区进入宗门洞天，或从洞天离开",
            "usage": ("山门", "山门 进入", "山门 离开"),
            "side_effect": "只有本宗成员可以进出；同行整体切换空间",
            "order": 37,
        },
    },
)
async def shanmen(
    user_id: str, message: str, message_context: MessageContext, manager: Any
) -> None:
    feature = current_game_services().features.zongmen_shanmen
    action = str(message or "").strip()
    copy = dict(feature.copy().text)
    try:
        if action == "进入":
            await feature.enter(user_id, message_context.request_id)
            await manager.send(
                _page(copy, feature.page_actions("洞天"), "洞天", _text(copy, "进入成功"))
            )
            return
        if action == "离开":
            await feature.leave(user_id, message_context.request_id)
            await manager.send(
                _page(copy, feature.page_actions("外圈"), "外圈", _text(copy, "离开成功"))
            )
            return
        if action:
            await manager.send(
                M.document()
                .section(_text(copy, "标题"), icon="navigation")
                .line(_text(copy, "格式"))
                .build()
            )
            return
        page = await feature.page(user_id)
        if page == "不在山门":
            await manager.send(
                M.document()
                .section(_text(copy, "标题"), icon="navigation")
                .line(_text(copy, "不在山门"))
                .build()
            )
            return
        await manager.send(_page(copy, feature.page_actions(page), page))
    except GateFeatureError:
        page = "洞天" if action == "离开" else "外圈"
        await manager.send(
            _page(
                copy,
                feature.page_actions(page),
                page,
                _text(copy, "进不去" if action == "进入" else "出不去"),
            )
        )


__all__ = []
