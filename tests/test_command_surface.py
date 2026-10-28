"""命令面收口后的根命令与文本回归。"""

from __future__ import annotations

import json
from pathlib import Path

from game.cmd.help_registry import help_registry
from main import create_app


def _load(relative: str):
    return json.loads(Path(relative).read_text(encoding="utf-8"))


def test_root_surface_has_no_old_entrypoints() -> None:
    create_app()
    for command in ("探险", "闭关", "出关", "采药", "采矿", "宗门战", "炼丹", "炼丹目录", "炼器", "炼器目录", "炼阵", "炼阵目录"):
        assert help_registry.find(command) is not None, command
    for command in ("开始探险", "探险结束", "开始闭关", "闭关开始", "闭关进度", "闭关结束", "闭关结果", "闭始", "闭终", "开始采药", "开始采矿", "接战", "拒战", "锁阵", "开丹炉", "开炉", "阵法审查"):
        assert help_registry.find(command) is None, command


def test_action_and_craft_buttons_use_new_roots() -> None:
    location = _load("data/世界/展示/按钮/地点功能.json")
    alchemy = _load("data/物品/展示/按钮.json")
    forging = _load("data/物品/展示/炼器-按钮.json")
    formation = _load("data/物品/展示/阵法-按钮.json")
    commands = [
        str(row["命令"])
        for rows in (location, alchemy, forging, formation)
        for row in rows
    ]
    forbidden = ("开始探险", "开始闭关", "开始采药", "开始采矿", "开丹炉", "开炉", "阵法审查")
    assert not any(command.startswith(word) for command in commands for word in forbidden)
    assert any(command.startswith("炼丹目录") for command in commands)
    assert any(command.startswith("炼器目录") for command in commands)
    assert any(command.startswith("炼阵目录") for command in commands)


def test_retreat_buttons_and_hosting_use_only_two_commands() -> None:
    buttons = _load("data/玩法/行动/闭关/展示/按钮.json")
    commands = {str(row["命令"]) for row in buttons}
    assert commands <= {"闭关", "出关", "帮助 闭关"}
    assert "闭关" in commands
    assert "出关" in commands

    hosting = _load("data/玩法/行动/托管/规则/托管.json")
    retreat = hosting["活动"]["闭关"]
    assert retreat["开始命令"] == "闭关"
    assert retreat["结束命令"] == "出关"
