"""布阵命令回复构造。"""

from __future__ import annotations

from game.features.buzhen import FormationArmCopy, FormationArmResult

from message import DocumentMessage, M


def completed(copy: FormationArmCopy, value: FormationArmResult) -> DocumentMessage:
    text = copy.text["布阵"]
    prepared = value.prepared
    return (
        M.document()
        .header(text["标题"])
        .section(f"{prepared.grade_name}{prepared.name}", icon="combat")
        .line(M.status("布阵完成", tone="positive"))
        .line(text["过程"])
        .field(text["结果"], "下一场正式战斗")
        .field("阵藏条目", prepared.reserve_key)
        .small(text["话语"])
        .build()
    )


def error(copy: FormationArmCopy, message: str) -> DocumentMessage:
    return (
        M.document()
        .section(copy.text["错误"]["标题"], icon="notice")
        .line(M.status("布阵失败", tone="danger"), " ", message)
        .build()
    )


__all__ = ["completed", "error"]
