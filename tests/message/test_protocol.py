from __future__ import annotations

import pytest

from launch.message_events import snapshot_from_message
from message import Action, M, RenderedMessage, render_local_message
from message.renderers.markdown import render_markdown
from message.renderers.plain_text import render_plain_text


def test_standard_reply_has_stable_sections_and_no_italics() -> None:
    message = (
        M.document()
        .header("人物创建完成")
        .inline_section("状态", "已完成")
        .section("人物")
        .row(("姓名", "林远"), ("性别", "男"))
        .field("境界", "灵动")
        .item(1, "小还丹 × 3")
        .note("数据已保存")
        .build()
    )

    markdown = render_markdown(message.document)
    assert markdown == (
        "**人物创建完成**\n"
        "> 状态: 已完成\n"
        "> \n"
        "> 人物\n"
        "> > 姓名: 林远&nbsp;|&nbsp;性别: 男\n"
        "> > 境界: 灵动\n"
        "> > &#91;1&#93; 小还丹 × 3\n"
        "> \n"
        "> 数据已保存"
    )
    assert "_" not in markdown
    assert "*林远*" not in markdown
    assert "*灵动*" not in markdown

    plain = render_plain_text(message.document)
    assert "人物创建完成" in plain
    assert "姓名: 林远 | 性别: 男" in plain
    assert "_" not in plain
    assert ">" not in plain


def test_document_schema_rejects_raw_structure_and_unknown_icons() -> None:
    for value in ("> 手写引用", "---"):
        with pytest.raises(ValueError):
            M.document().section("测试").line(value)
    with pytest.raises(ValueError, match="必须属于 section"):
        M.document().line("无归属正文")
    message = M.document().section("测试", icon="unknown").build()
    with pytest.raises(ValueError, match="未知消息图标分类"):
        render_markdown(message.document)


def test_message_builders_freeze_and_reject_duplicate_actions() -> None:
    action = Action("confirm", "确认", "确认操作")

    with pytest.raises(ValueError, match="action_id 不能重复"):
        M.document().action(action).action(action).build()
    rendered = render_local_message(M.document().section("状态").line("正常"))

    assert isinstance(rendered, RenderedMessage)
    assert rendered.kind == "markdown"
    assert rendered.content == "> 状态\n> > 正常"
    sentinel = object()
    assert render_local_message(sentinel) is sentinel


def test_inline_command_is_a_text_link_and_cannot_duplicate_bottom_button() -> None:
    message = M.document().section("资源").line(
        M.command("小还丹", "查看 100001", submit=False)
    ).build()

    rendered = render_local_message(message)
    assert isinstance(rendered, RenderedMessage)
    assert rendered.content == "> 资源\n> > 小还丹"
    snapshot = snapshot_from_message(message)
    assert tuple(
        (value.kind, value.data, value.behavior, value.style)
        for value in snapshot.interactions
    ) == (("command_link", "查看 100001", "fill", "link"),)

    with pytest.raises(ValueError, match="正文联动不能与底部按钮重复"):
        M.document().section("资源").line(
            M.command("查看", "查看 100001")
        ).action(Action("view", "查看", "查看 100001")).build()


def test_markdown_renderer_escapes_inline_style_characters() -> None:
    message = M.document().section("测试").line("真意_*`\\").build()

    assert render_markdown(message.document) == "> 测试\n> > 真意\\_\\*\\`\\\\"
