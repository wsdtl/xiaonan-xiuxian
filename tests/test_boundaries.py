"""调用边界回归：命令层不按业务动作分支，不读地点资格。"""
from __future__ import annotations

from pathlib import Path


def _python_files(root: str) -> list[Path]:
    return sorted(Path(root).rglob("*.py"))


def test_command_layer_has_no_business_action_branch() -> None:
    forbidden = ("if action ==", "elif action ==", "if action in", "elif action in")
    for path in _python_files("game/cmd"):
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path}: 命令层仍在分支业务动作：{marker}"


def test_command_layer_does_not_read_location_eligibility() -> None:
    forbidden = ("available_functions", "plant_pool", "mineral_pool")
    for path in _python_files("game/cmd"):
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path}: 命令层仍在读地点资格：{marker}"


def test_auto_travel_does_not_read_gameplay_tiers() -> None:
    text = Path("game/core/auto_travel/service.py").read_text(encoding="utf-8")
    assert "cultivator_tiers" not in text
    assert "beast_tiers" not in text


def test_panel_has_no_terrain_or_position_button_path() -> None:
    text = Path("game/features/weizhi/service.py").read_text(encoding="utf-8")
    assert "terrain_actions" not in text
    assert '_actions_for("位置")' not in text
