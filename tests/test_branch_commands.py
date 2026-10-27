from __future__ import annotations

import pytest

from game.cmd.branching import (
    BranchParseError,
    branch_menu,
    parse_branches,
)
from message import ClosingBlock, CommandLink


def test_shared_tail_uses_last_argument() -> None:
    assert parse_branches("去|前往 天衡城") == ("去 天衡城", "前往 天衡城")


def test_shared_tail_without_arguments() -> None:
    assert parse_branches("继续托管|取消托管") == ("继续托管", "取消托管")


def test_shared_tail_does_not_check_command_words() -> None:
    # 纯解析：不查命令表，也不判断这两个词是不是命令。
    assert parse_branches("不存在|也不存在 一份") == (
        "不存在 一份",
        "也不存在 一份",
    )


def test_full_mode_keeps_each_segment() -> None:
    assert parse_branches("查看 清心散|取消托管") == ("查看 清心散", "取消托管")


def test_full_mode_handles_heterogeneous_commands() -> None:
    assert parse_branches("查看 清心散|使用 黄品清心散 1") == (
        "查看 清心散",
        "使用 黄品清心散 1",
    )


def test_full_mode_does_not_judge_a_bare_segment() -> None:
    # 第二段是不是命令，不归分支控件判断；它只按结构原样收下。
    assert parse_branches("查看 清心散|小还丹") == ("查看 清心散", "小还丹")


def test_shared_head_repeats_the_first_command() -> None:
    assert parse_branches(">查看 清心散|小还丹|养神丹") == (
        "查看 清心散",
        "查看 小还丹",
        "查看 养神丹",
    )


def test_shared_head_with_place_names() -> None:
    assert parse_branches(">去 天衡城|溪隐台") == ("去 天衡城", "去 溪隐台")


def test_shared_head_supports_multi_word_prefix() -> None:
    assert parse_branches(">使用 黄品功法 1|2|3") == (
        "使用 黄品功法 1",
        "使用 黄品功法 2",
        "使用 黄品功法 3",
    )


def test_shared_head_does_not_check_the_command_word() -> None:
    assert parse_branches(">不存在 清心散|小还丹") == (
        "不存在 清心散",
        "不存在 小还丹",
    )


def test_duplicate_commands_are_collapsed() -> None:
    assert parse_branches("查看 清心散|查看 清心散|购买 小还丹") == (
        "查看 清心散",
        "购买 小还丹",
    )


@pytest.mark.parametrize(
    "text",
    (
        "查看",
        "查看|",
        "查看||购买",
        "查看|购买 清心散|使用 黄品清心散 1",
        ">查看|小还丹",
        "> 小还丹|养神丹",
        ">查看 清心散|小还丹 1",
    ),
)
def test_invalid_shapes_are_rejected(text: str) -> None:
    with pytest.raises(BranchParseError):
        parse_branches(text)


def test_menu_only_fills_and_carries_one_fixed_closing() -> None:
    document = branch_menu(("查看 清心散", "取消托管")).document
    assert isinstance(document.blocks[-1], ClosingBlock)
    assert "点一条填入" in document.blocks[-1].content[0].value
    links = [
        span
        for block in document.blocks
        for line in getattr(block, "lines", ())
        for span in line.content
        if isinstance(span, CommandLink)
    ]
    assert [link.command for link in links] == ["查看 清心散", "取消托管"]
    assert all(link.submit is False for link in links)
