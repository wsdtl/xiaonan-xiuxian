"""玩家帮助二级组件。"""

from __future__ import annotations

# 多分支命令与帮助同类（都是命令导航）；显式导入才会注册。
from . import branches as _branches  # noqa: F401

from game.app import current_game_services

from ...command import GameCommand
from . import reply
from ...reply_composer import send_game_reply
from typing import Any


@GameCommand.command(
    cmd="帮助",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        "help": {
            "category": "查看与工具",
            "summary": "查看当前已经开放的命令分类、用法和结果",
            "side_effect": "只读，什么也不改动",
            "usage": ("帮助", "帮助 分类", "帮助 命令"),
            "order": 0,
        },
    },
)
async def help_command(message: str, manager: Any) -> None:
    await send_game_reply(reply.help_message(message))


def _id_converter():
    """「中文名 → 编号」转换器：名称表向玩法要，再逐词替换。

    认不出就原样留着——它只负责把能给编号的地方换成编号，不做校验。
    范围用**全库编号实体**（help 是给机器看的，越全越好；按节白名单会漏掉世界内容，
    例如丹泉苑的炼丹师就不在物品那几节里）。
    """

    # 事实向玩法要（边界：触发层不直接访问数据服务）。
    name_to_id = dict(current_game_services().features.chakan_wupin.id_alias_table())

    def convert(text: str) -> str:
        return " ".join(name_to_id.get(token, token) for token in str(text).split())

    return convert


@GameCommand.command(
    cmd="help",
    metadata={
        "scope": "通用",
        "guard_rule": "始终可用",
        # 刻意不写 help 块：这条命令不参与「帮助」的分类联动，也不出现在帮助页里。
        "hidden": True,
    },
)
async def id_help_command(message: str, manager: Any) -> None:
    """`help [分类或命令]`：与「帮助」同一套内容，多穿一层「中文名/品级 → 编号」。

    这一页是给机器/脚本的纯 id 写法，不是给人读的；给人看的走中文「帮助」。
    """

    query = " ".join(str(message or "").split())
    await send_game_reply(
        reply.help_message(query, id_converter=_id_converter(), nav="help")
    )


__all__ = []
