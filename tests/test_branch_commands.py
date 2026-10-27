from __future__ import annotations

import pytest

from game.cmd.查看与工具.帮助.branches import (
    BranchParseError,
    _menu,
    parse_branches,
)
from message import ClosingBlock, CommandLink


def test_shared_tail_uses_last_argument() -> None:
    assert parse_branches("查看|借阅功法 400001") == (
        "查看 400001",
        "借阅功法 400001",
    )


def test_shared_tail_without_arguments() -> None:
    assert parse_branches("继续托管|取消托管") == ("继续托管", "取消托管")


def test_shared_tail_is_structural_not_registry_bound() -> None:
    # 不查命令注册表：没登记过的词也照样还原，能不能执行由后续命令链判断。
    assert parse_branches("不存在的命令|另一个命令 参数") == (
        "不存在的命令 参数",
        "另一个命令 参数",
    )


def test_full_mode_keeps_each_segment() -> None:
    assert parse_branches("查看 400001|取消托管") == ("查看 400001", "取消托管")


def test_full_mode_handles_heterogeneous_commands() -> None:
    assert parse_branches(
        "查看 400001|人物装配 功法 400001 03"
    ) == ("查看 400001", "人物装配 功法 400001 03")


def test_shared_head_repeats_the_first_command() -> None:
    assert parse_branches(">查看 400001|400002|400003") == (
        "查看 400001",
        "查看 400002",
        "查看 400003",
    )


def test_shared_head_with_place_names() -> None:
    assert parse_branches(">去 天衡城|溪隐台") == ("去 天衡城", "去 溪隐台")


def test_duplicate_commands_are_collapsed() -> None:
    assert parse_branches("查看 400001|查看 400001|取消托管") == (
        "查看 400001",
        "取消托管",
    )


@pytest.mark.parametrize(
    "text",
    (
        "查看",
        "查看|",
        "查看||借阅",
        "查看|借阅 400001|人物装配 功法 400001 03",
        ">查看|400002",
        "> 400002|400003",
        ">查看 400001 03|400002",
        ">查看 400001|400002 03",
    ),
)
def test_invalid_shapes_are_rejected(text: str) -> None:
    with pytest.raises(BranchParseError):
        parse_branches(text)


def test_menu_only_fills_and_carries_one_fixed_closing() -> None:
    document = _menu(("查看 400001", "取消托管")).document
    assert isinstance(document.blocks[-1], ClosingBlock)
    assert "点一条填入" in document.blocks[-1].content[0].value
    links = [
        span
        for block in document.blocks
        for line in getattr(block, "lines", ())
        for span in line.content
        if isinstance(span, CommandLink)
    ]
    assert [link.command for link in links] == ["查看 400001", "取消托管"]
    assert all(link.submit is False for link in links)
