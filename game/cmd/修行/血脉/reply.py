"""血脉命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from game.features.xuemai import GenealogyCopy, GenealogyView, SuccessionResult
from message import DocumentMessage, M

from ...presentation import error_document


def text(
    copy: GenealogyCopy, section: str, key: str, values: Mapping[str, object] | None = None
) -> str:
    return copy.text[section][key].format_map(values or {})


def error(copy: GenealogyCopy, message: str) -> DocumentMessage:
    """失败回执：形状走 error_document，失败消息必须带信。"""

    return error_document(
        text(copy, "错误", "标题"),
        copy.icons["错误"],
        "交互失败",
        message,
        tone="danger",
        hint=text(copy, "命令", "格式"),
    )


def genealogy(copy: GenealogyCopy, view: GenealogyView) -> DocumentMessage:
    """族谱：一个人名下的一串记录。只增不改。"""

    builder = M.document().section(
        text(copy, "族谱", "标题", {"名称": view.self_code}),
        icon=copy.icons["族谱"],
    )
    builder = builder.line(text(copy, "族谱", "代次", {"代次": view.generation}))
    if not view.entries:
        return builder.line(text(copy, "族谱", "无记录")).build()
    for entry in view.entries:
        mark = text(copy, "族谱", "已传位") if entry.retired else text(copy, "族谱", "在位")
        builder = builder.row(
            (text(copy, "族谱", "族谱名"), entry.blood_name),
            (text(copy, "族谱", "玩家名"), entry.player_name or entry.blood_name),
        ).row(
            (text(copy, "族谱", "性别"), entry.sex),
            (text(copy, "族谱", "血脉"), entry.dna),
        ).line(mark)
    return builder.build()


def succession(copy: GenealogyCopy, result: SuccessionResult) -> DocumentMessage:
    """传位回执：旧壳进族谱、你现在是谁、进入第几代、新血脉。"""

    builder = M.document().section(
        text(copy, "传位", "标题", {"名称": result.new_name}),
        icon=copy.icons["族谱"],
    )
    builder = builder.line(
        text(
            copy,
            "传位",
            "成功",
            {"旧壳": result.retired_name, "新壳": result.new_name, "代次": result.generation},
        )
    )
    if result.bloodlines:
        builder = builder.line(
            text(copy, "传位", "新血脉", {"血脉": "、".join(result.bloodlines)})
        )
    return builder.build()


def succession_usage(copy: GenealogyCopy) -> DocumentMessage:
    """没给新生儿时，发选用法。"""

    return M.document().section(
        text(copy, "传位", "标题", {"名称": ""}), icon=copy.icons["族谱"]
    ).line(text(copy, "传位", "用法")).build()
