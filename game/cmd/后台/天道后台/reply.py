"""天道后台入口回复构造。"""

from __future__ import annotations

from message import Action, M


def entry(url: str):
    return (
        M.document()
        .section("天道后台", icon="system")
        .line(M.status("已就绪", tone="positive"), " ", M.link("打开天道后台", url))
        .action(Action("heavenly_dao_console.open", "打开后台", url, behavior="link"))
        .build()
    )


__all__ = ["entry"]
