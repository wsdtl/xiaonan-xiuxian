"""正式游戏回复的统一构造与发送边界。

业务只造正文；人物头与命令标题由这里在发送前前置。
系统推送走另一条入口：不加人物头，也不套命令标题。
"""

from __future__ import annotations

from launch.adapter import (
    MENTION_NONE,
    ReplyTarget,
    SendOptions,
    SendRequest,
    current_message_context,
    manager,
)
from message import (
    ClosingBlock,
    CommandTitleBlock,
    Document,
    DocumentMessage,
    HeaderBlock,
    ImageMessage,
    Message,
    M,
    coerce_message,
)

from .closings import closing_for

async def _identity_text(user_id: str) -> str:
    """人物头：昵称 境界 等级；没建档就写「未建档」。"""

    from game.app import current_game_services

    try:
        return await current_game_services().features.chakan_juese.identity_text(user_id)
    except Exception:  # noqa: BLE001 - 玩法没起也不该挡住回复
        return "未建档"


def compose_player_reply(
    message: Message,
    *,
    identity: str,
    title: str,
    icon: str = "",
) -> Message:
    """在正文前前置人物头与命令标题；业务正文不得自带头部块。"""

    if not isinstance(message, DocumentMessage):
        return message
    document = message.document
    if any(isinstance(block, (HeaderBlock, CommandTitleBlock)) for block in document.blocks):
        raise ValueError("业务正文不能包含人物头或命令标题块")
    blocks = []
    if identity:
        blocks.append(HeaderBlock(M.text(identity)))
    if title:
        bottom_commands = {action.data for action in document.actions}
        blocks.append(
            CommandTitleBlock(
                M.text(title),
                icon=icon,
                button=title not in bottom_commands,
            )
        )
    blocks.extend(document.blocks)
    if not any(isinstance(block, ClosingBlock) for block in document.blocks):
        blocks.append(_default_closing(title))
    return DocumentMessage(Document(tuple(blocks), document.actions))


def _default_closing(title: str) -> ClosingBlock:
    """默认结尾；`查看` 的「帮助 查看」做成无边框命令，其余保持纯文本。"""

    if title.split(maxsplit=1)[:1] == ["查看"]:
        return ClosingBlock(
            M.text("发送「查看 编号」查看目标详情；发送「")
            + (M.command("帮助 查看", "帮助 查看"),)
            + M.text("」看写法。")
        )
    return ClosingBlock(M.text(closing_for(title)))


async def send_game_reply(
    message: Message,
    *,
    is_log: bool = True,
    request_id: object | None = None,
    title: str | None = None,
) -> bool:
    """发送玩家命令的回包：自动前置人物头与命令标题。

    `title` 只在展示名与玩家原文不同的时候传（如 `查看 400001` 显示卡名）；
    不传就沿用当前消息原文。
    """

    context = current_message_context()
    if context is None:
        raise RuntimeError("玩家回包缺少当前消息上下文")
    payload = coerce_message(message)
    if payload is None:
        raise TypeError("玩家回包只接受 message.Message")
    if isinstance(payload, ImageMessage):
        return await manager.send(payload, is_log=is_log, request_id=request_id)
    # 原文不是展示数据：没显式给标题就只写命令词，绝不回显参数/编号。
    display_title = title.strip() if title is not None else context.command.strip()
    decorated = compose_player_reply(
        payload,
        identity=await _identity_text(context.user_id),
        title=display_title,
        icon="game.cmd",
    )
    return await manager.send(decorated, is_log=is_log, request_id=request_id)


async def send_system_message(
    message: Message,
    target: ReplyTarget,
    *,
    options: SendOptions | None = None,
    is_log: bool = True,
    request_id: object | None = None,
) -> bool:
    """发送系统推送：不读当前上下文，不加人物头/命令标题，目标必须显式。"""

    if not isinstance(target, ReplyTarget):
        raise TypeError("系统推送必须提供显式 ReplyTarget")
    payload = coerce_message(message)
    if payload is None:
        raise TypeError("系统推送只接受 message.Message")
    send_options = options or SendOptions(mention=MENTION_NONE, log=is_log)
    request = SendRequest(
        message=payload,
        target=target,
        options=send_options,
        request_id=request_id,
    )
    return await manager.send(request, is_log=is_log, request_id=request_id)


__all__ = [
    "compose_player_reply",
    "send_game_reply",
    "send_system_message",
]
