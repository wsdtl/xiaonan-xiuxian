"""命令主标题的图标：按命令的帮助分类查图标。

主标题＝触发这条回复的命令原文（施工单见 tools/基准/说明.md）。图标沿用现有卡面的观感：
帮助分类 → message 侧已登记的图标 key（全部取自 38 个合法 key，不会撞「未登记图标」判据）。
分类的唯一权威是 game/cmd/help_registry.py 的 HelpSpec.category。
"""

from __future__ import annotations

from .help_registry import help_registry

#: 帮助分类 → 图标 key。
CATEGORY_ICONS: dict[str, str] = {
    "系统": "system",
    "角色": "player",
    "道侣": "companion",
    "宗门": "world",
    "修行": "cultivation",
    "行动": "explore",
    "世界": "map",
    "战斗": "combat",
    "炼制": "skill",
    "资源": "material",
}

#: 拿不到命令或分类时的兜底图标。
DEFAULT_ICON = "status"


def icon_for_command(command: object) -> str:
    """按命令的帮助分类取图标；查不到命令或分类时给默认图标。"""

    entry = help_registry.find(command)
    if entry is None:
        return DEFAULT_ICON
    return CATEGORY_ICONS.get(entry.spec.category, DEFAULT_ICON)


__all__ = ["CATEGORY_ICONS", "DEFAULT_ICON", "icon_for_command"]
