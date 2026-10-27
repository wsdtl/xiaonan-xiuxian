"""使用网关的回执：成功渲染、重定向与错误。"""
from __future__ import annotations

from typing import Any

from game.features.shiyong import UseOutcome, UseRedirect
from message import DocumentMessage, M

from ...presentation import error_document
from ...use_reply import RENDERERS


def render(outcome: UseOutcome, feature: Any) -> DocumentMessage:
    renderer = RENDERERS.get(outcome.render_key)
    if renderer is None:
        raise RuntimeError(f"使用回执没有渲染器：{outcome.render_key}")
    return renderer(feature, outcome.result)


def redirect(value: UseRedirect) -> DocumentMessage:
    builder = (
        M.document()
        .section(value.title, icon="game.pin_doc")
        .line(M.status("不能直接使用", tone="warning"), " ", value.message)
    )
    for action in value.actions:
        builder.item(action.label, M.command(action.label, action.command))
    closing = "点一条查看帮助。" if value.actions else "请按提示走对应入口。"
    return builder.closing(closing).build()


def error(feature: Any, message: str) -> DocumentMessage:
    return error_document(
        feature.copy("错误标题"),
        "game.pin_doc",
        feature.copy("错误状态"),
        message,
        hint=feature.copy("错误尾注"),
    )


__all__ = ["error", "redirect", "render"]
