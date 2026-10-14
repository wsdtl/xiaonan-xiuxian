"""布阵命令回复构造。"""

from __future__ import annotations

from ...presentation import candidate_lines, error_document

from game.features.buzhen import (
    FormationArmCopy,
    FormationArmResult,
    FormationChoiceError,
)

from message import DocumentMessage, M


def completed(
    copy: FormationArmCopy, value: FormationArmResult, treasure: str = ""
) -> DocumentMessage:
    text = copy.text["布阵"]
    prepared = value.prepared
    builder = (
        M.document()
        .header(text["标题"])
        .section(f"{prepared.grade_name}{prepared.name}", icon="combat")
        .line(M.status("布阵完成", tone="positive"))
        .line(text["过程"])
        .field(text["结果"], "下一场正式战斗")
    )
    # 阵藏条目是代码内部的键（品级编号＋阵法编号[灵宝编号]），不给玩家看；
    # 有没有灵宝加成也不写「无灵宝」三个字——没有就不显示这一段。
    if treasure:
        builder = builder.field(text["灵宝"], treasure)
    return (
        builder
        .small(text["话语"])
        .build()
    )


def error(copy: FormationArmCopy, message: str) -> DocumentMessage:
    # 形状统一走 error_document（game/cmd/presentation.py），行为与原来一致。
    return error_document(        copy.text["错误"]["标题"], "notice", "布阵失败", message, tone="danger"
    )


def choose(
    copy: FormationArmCopy, exc: FormationChoiceError, *, command: str = "布阵"
) -> DocumentMessage:
    """阵藏里有多条同名阵法：铺成选择卡，候选可点，点一下精确选中。

    显示名带投入——玩家一眼看出同名同品级同灵宝的那几件差在哪；命令用规定的旧写法
    （品级阵法名 + 三个投入数），点下去就是合法输入。
    """

    text = copy.text["错误"]
    builder = M.document().header(text["标题"])
    candidate_lines(
        builder,
        title=text["选择标题"],
        entries=tuple(
            (name, f"{command} {tail}", detail) for name, tail, detail in exc.candidates
        ),
        footer=text["选择尾注"],
    )
    return builder.build()


__all__ = ["choose", "completed", "error"]
