"""查看页的品级算值与逐品级展示。"""

from __future__ import annotations

import asyncio


def _inspect(services, query: str):
    return asyncio.run(services.features.chakan_wupin.inspect(query))


def test_explicit_grade_scales_ability_values(services) -> None:
    result = _inspect(services, "地品负甲听潮")
    assert result.detail is not None
    assert [preview.name for preview in result.grade_previews] == ["地品"]
    body = "\n".join(result.grade_previews[0].rendered)
    assert "血气上限+58.5" in body
    assert "格挡减伤+32.5" in body


def test_battle_pill_grade_scales_保留血气(services) -> None:
    result = _inspect(services, "圣品一息续命丹")
    assert result.detail is not None
    preview = result.grade_previews[0]
    assert preview.name == "圣品"
    assert preview.multiplier == 2.0
    assert "保留血气60" in "\n".join(preview.rendered)


def test_breakthrough_pill_grade_scales_permanent(services) -> None:
    result = _inspect(services, "圣品聚血丹")
    assert result.detail is not None
    preview = result.grade_previews[0]
    effect = preview.fields["使用效果"]
    assert effect["永久属性"]["血气上限"] == 24


def test_formation_previews_all_five_grades(services) -> None:
    result = _inspect(services, "530001")
    assert result.detail is not None
    assert [preview.name for preview in result.grade_previews] == [
        "黄品",
        "玄品",
        "地品",
        "天品",
        "圣品",
    ]
    assert all(preview.quantity == 0 for preview in result.grade_previews)
    assert any("承载" in line for line in result.grade_previews[0].extra_lines)


def test_yijing_renders_all_nine_tiers(services) -> None:
    from game.cmd.查看与工具.查看.items import SectionInput, _yijing_lines

    result = _inspect(services, "630001")
    body = "\n".join(
        _yijing_lines(SectionInput(result.detail.fields, {}, result.rendered, ""))
    )
    assert "1阶：" in body
    assert "9阶：" in body
    assert "每阶增幅：" in body
    assert " \n7阶效果：" in body
    assert " \n8阶效果：" in body
    assert " \n9阶效果：" in body
    assert "0.5倍威力" in body


def test_bloodline_has_activation_and_effect_label(services) -> None:
    from game.cmd.查看与工具.查看.items import SectionInput, _bloodline_lines

    ordinary = _inspect(services, "古松血")
    ordinary_body = "\n".join(
        _bloodline_lines(
            SectionInput(ordinary.detail.fields, {}, ordinary.rendered, "")
        )
    )
    assert "生效判断：G1：75~100；G2：65~100" in ordinary_body
    assert "效果：血气上限+4" in ordinary_body

    outer = _inspect(services, "九幽冥体血")
    outer_body = "\n".join(
        _bloodline_lines(SectionInput(outer.detail.fields, {}, outer.rendered, ""))
    )
    assert "生效判断：G1+G6=99" in outer_body
    assert "效果：吸血率+15" in outer_body


def test_awakenable_bloodline_renders_tiers(services) -> None:
    result = _inspect(services, "810001")
    body = "\n".join(result.rendered)
    assert "气血 ≥70%：×1" in body
    assert "气血 <5%：×2.5" in body


def test_special_pill_has_no_grade_and_location(services) -> None:
    result = _inspect(services, "160001")
    assert result.detail is not None
    assert result.detail.fields.get("无品级") is True
    assert result.use_location == "妇产科医院"
    assert result.use_purposes == ("生育", "求子")


def test_build_detail_cards_are_commands(services) -> None:
    from game.cmd.查看与工具.查看.reply import inspection

    result = _inspect(services, "玄龟镇海经")
    message = inspection(result, "", ())
    section = next(
        block
        for block in message.document.blocks
        if "".join(getattr(span, "value", "") for span in getattr(block, "title", ()))
        == "详情"
    )
    commands = [
        getattr(span, "command", "")
        for line in section.lines
        for span in line.content
        if getattr(span, "command", "")
    ]
    assert "查看 负甲听潮" in commands
    assert "查看 烟波族" in commands


def test_enemy_build_cards_are_commands(services) -> None:
    from game.cmd.查看与工具.查看.reply import inspection
    from game.features.chakan_wupin import ItemInspectionResult

    feature = services.features.chakan_wupin
    detail = feature.inspect_enemy("敌·陆清野")
    assert detail is not None
    result = ItemInspectionResult(
        "敌·陆清野",
        detail=detail,
        related_details=feature.related_details(detail),
    )
    message = inspection(result, "", ())
    section = next(
        block
        for block in message.document.blocks
        if "".join(getattr(span, "value", "") for span in getattr(block, "title", ()))
        == "记载"
    )
    commands = [
        getattr(span, "command", "")
        for line in section.lines
        for span in line.content
        if getattr(span, "command", "")
    ]
    assert "查看 玄龟镇海经" in commands
    assert "查看 负甲听潮" in commands
    assert "查看 烟波族" in commands


def test_card_capability_labels_are_domain_named() -> None:
    from game.cmd.查看与工具.查看.reply import _card_heading

    assert _card_heading("主动：", "功法") == "⚔️ 功法主动能力："
    assert _card_heading("被动：", "真意") == "🛡️ 真意被动能力："
    assert _card_heading("常驻：", "气机") == "♾️ 气机常驻能力："
    assert _card_heading("契合：", "气机") == "♾️ 气机常驻能力："


def test_enemy_race_line_becomes_command() -> None:
    from types import SimpleNamespace

    from game.cmd.查看与工具.查看.reply import _linked_line

    content = _linked_line("种族：烟波族", SimpleNamespace(section="敌人"))
    assert content is not None
    assert any(getattr(span, "command", "") == "查看 烟波族" for span in content)

    location = _linked_line("使用地点：妇产科医院", SimpleNamespace(section="丹药"))
    assert location is not None
    assert any(
        getattr(span, "command", "") == "去 妇产科医院" for span in location
    )

    cards = _linked_line(
        "功法（2）：负甲听潮、沉江不渡", SimpleNamespace(section="构筑")
    )
    assert cards is not None
    assert [
        getattr(span, "command", "") for span in cards if getattr(span, "command", "")
    ] == ["查看 负甲听潮", "查看 沉江不渡"]
