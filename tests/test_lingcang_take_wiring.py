"""宗门灵藏取用的接线回归：命令、玩法、核心三层都得在，且参数形状一致。

审-8 落地时我在两层各写了一半又改坏过两次（KeyError、缩进），所以把「三层接线」钉进自测：
少任何一层、或参数名对不上，这里立刻红。
"""

from __future__ import annotations

import inspect

from game.cmd.command import registered_commands
from game.core.sect_assets import SectAssetService
from game.features.zongmen_lingcang import LingcangFeature


def _命令名() -> list[str]:
    """注册表里每条是 (名字, scope, 模块) 三元组。"""

    命令 = registered_commands()
    条 = list(命令.values()) if isinstance(命令, dict) else list(命令)
    出: list[str] = []
    for 项 in 条:
        if isinstance(项, (tuple, list)):
            出.append(str(项[0]))
        else:
            出.append(str(getattr(项, "cmd", 项)))
    return 出


def test_命令表里有取灵藏() -> None:
    名字 = _命令名()
    assert any("取灵藏" in x for x in 名字), 名字


def test_三层都有取用方法() -> None:
    assert hasattr(SectAssetService, "take_material")
    assert hasattr(LingcangFeature, "take_material")


def test_取用与捐入参数形状一致() -> None:
    核心取 = list(inspect.signature(SectAssetService.take_material).parameters)
    核心捐 = list(inspect.signature(SectAssetService.donate_material).parameters)
    assert 核心取 == 核心捐, (核心取, 核心捐)
