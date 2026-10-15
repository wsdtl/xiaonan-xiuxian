"""生育命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping

from game.features.hunpei import BirthResult, BirthView, HunpeiCopy
from message import DocumentMessage, M

from ...presentation import error_document


def text(
    copy: HunpeiCopy, section: str, key: str, values: Mapping[str, object] | None = None
) -> str:
    return copy.text[section][key].format_map(values or {})


def error(copy: HunpeiCopy, message: str) -> DocumentMessage:
    return error_document(
        text(copy, "错误", "标题"),
        copy.icons["错误"],
        "交互失败",
        message,
        tone="danger",
        hint=text(copy, "命令", "格式"),
    )


def birth(copy: HunpeiCopy, value: BirthView) -> DocumentMessage:
    """生育前视图：能不能生、为什么不能。"""

    if not value.companion_code:
        # 没有同行道侣：标题仍走生育页，正文用「无道侣」那一行——
        # 空栏目会被「消息零信息」判据点名。
        return (
            M.document()
            .section(
                text(copy, "生育", "标题", {"道侣": text(copy, "生育", "无道侣")}),
                icon=copy.icons["生育"],
            )
            .line(text(copy, "生育", "无道侣"))
            .build()
        )
    line = (
        text(copy, "生育", "可以生育")
        if value.can_birth
        else text(copy, "生育", "不可生育", {"原因": value.reason})
    )
    return (
        M.document()
        .section(text(copy, "生育", "标题", {"道侣": value.companion_name}), icon=copy.icons["生育"])
        .line(text(copy, "生育", "代次", {"代次": value.generation}))
        .line(
            text(
                copy,
                "生育",
                "胎次",
                {"已生": value.births_this_generation, "上限": value.births_limit},
            )
        )
        .line(line)
        .build()
    )


def born(copy: HunpeiCopy, result: BirthResult) -> DocumentMessage:
    """生育成功回执。"""

    newborn = result.newborn
    builder = M.document().section(
        text(copy, "生育", "标题", {"道侣": result.companion_name}), icon=copy.icons["生育"]
    )
    builder = builder.line(
        text(
            copy,
            "生育",
            "成功",
            {
                "编号": newborn.code,
                "性别": newborn.sex,
                "代次": result.generation,
                "胎次": result.births_this_generation,
            },
        )
    )
    if newborn.bloodlines:
        builder = builder.line(
            text(copy, "生育", "新血脉", {"血脉": "、".join(newborn.bloodlines)})
        )
    return builder.build()