from __future__ import annotations

import pytest

from game.cmd.查看与工具.帮助.branches import (
    BranchParseError,
    _menu,
    parse_branches,
)
from message import ClosingBlock, CommandLink

KNOWN = frozenset(
    {
        "查看",
        "购买",
        "取消托管",
        "继续托管",
        "人物装配",
        "人药",
        "侣药",
        "去",
        "前往",
    }
)


def parse(text: str) -> tuple[str, ...]:
    return parse_branches(text, known=KNOWN.__contains__)


def test_shared_tail_uses_last_argument() -> None:
    assert parse("去|前往 天衡城") == ("去 天衡城", "前往 天衡城")


def test_shared_tail_without_arguments() -> None:
    assert parse("继续托管|取消托管") == ("继续托管", "取消托管")


def test_shared_tail_rejects_unknown_command() -> None:
    with pytest.raises(BranchParseError, match="不存在"):
        parse("去|不存在 天衡城")


def test_full_mode_keeps_each_segment() -> None:
    assert parse("查看 清心散|取消托管") == ("查看 清心散", "取消托管")


def test_full_mode_handles_heterogeneous_commands() -> None:
    assert parse("查看 清心散|人物装配 功法 黄品清心散 1") == (
        "查看 清心散",
        "人物装配 功法 黄品清心散 1",
    )


def test_full_mode_rejects_a_bare_argument_as_command() -> None:
    # 小还丹 是物品名，不是命令词；同一命令换参数应该走共享头，而不是全量。
    with pytest.raises(BranchParseError, match="小还丹"):
        parse("查看 清心散|小还丹")


def test_shared_head_repeats_the_first_command() -> None:
    assert parse(">查看 清心散|小还丹|养神丹") == (
        "查看 清心散",
        "查看 小还丹",
        "查看 养神丹",
    )


def test_shared_head_with_place_names() -> None:
    assert parse(">去 天衡城|溪隐台") == ("去 天衡城", "去 溪隐台")


def test_shared_head_checks_only_the_first_command_word() -> None:
    assert parse(">查看 清心散|小还丹") == ("查看 清心散", "查看 小还丹")
    with pytest.raises(BranchParseError, match="不存在"):
        parse(">不存在 清心散|小还丹")


def test_duplicate_commands_are_collapsed() -> None:
    assert parse("查看 清心散|查看 清心散|购买 小还丹") == (
        "查看 清心散",
        "购买 小还丹",
    )


@pytest.mark.parametrize(
    "text",
    (
        "查看",
        "查看|",
        "查看||购买",
        "查看|购买 清心散|人物装配 功法 黄品清心散 1",
        "查看 清心散|小还丹",
        "查看|不存在 清心散",
        ">查看|小还丹",
        "> 小还丹|养神丹",
        ">不存在 清心散|小还丹",
        ">查看 清心散 1|小还丹",
        ">查看 清心散|小还丹 1",
    ),
)
def test_invalid_shapes_are_rejected(text: str) -> None:
    with pytest.raises(BranchParseError):
        parse(text)


def test_menu_only_fills_and_carries_one_fixed_closing() -> None:
    document = _menu(("查看 清心散", "取消托管")).document
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
