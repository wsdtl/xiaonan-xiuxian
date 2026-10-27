"""别名收口后的保留与删除边界。"""

from __future__ import annotations

from game.cmd.help_registry import help_registry
from main import create_app

_KEEP = (
    "创建角色",
    "角色",
    "我的存档",
    "存档",
    "兑换码",
    "组队",
    "前往",
    "人物自动用药",
    "道侣自动用药",
)
_REMOVED = (
    "血脉族谱",
    "提升品级",
    "道侣交谈",
    "邀约道侣",
    "暂别道侣",
    "铜雀台夺元",
    "归元观归元",
    "裂天原补天",
    "太素坊易形",
    "太素坊化形",
    "归元观洗根",
    "坐忘台坐忘",
)


def test_kept_aliases_still_resolve() -> None:
    create_app()
    for alias in _KEEP:
        assert help_registry.find(alias) is not None, alias


def test_long_aliases_are_gone() -> None:
    create_app()
    for alias in _REMOVED:
        assert help_registry.find(alias) is None, alias


def test_web_switch_uses_full_semantic_name() -> None:
    create_app()
    assert help_registry.find("网页资源公开") is not None
    assert help_registry.find("网页资源关闭") is not None
    assert help_registry.find("网页公开") is None
    assert help_registry.find("网页关闭") is None
