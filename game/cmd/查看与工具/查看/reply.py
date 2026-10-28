"""查看正式编号实体的命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import MappingProxyType

from game.features.chakan_wupin import ItemInspectionResult
from game.features.weizhi import CharacterPublicProfile, CompanionView, PositionCopy
from message import Action, DocumentMessage, M

from ...actions import CommandAction, message_actions
from ...character_overview import overview, overview_error

from .items import (
    _build_description_lines,
    _definition_lines,
    SectionInput,
    _normalize_brackets,
    _player_description,
)


def missing_query() -> DocumentMessage:
    return (
        M.document()
        .section("提示", icon="game.box")
        .line(M.status("缺少目标", tone="warning"), " 请提供编号或完整名称。")
        .small("例如：查看 清心散")
        .build()
    )


def inspection(
    result: ItemInspectionResult,
    baike_url: str = "",
    actions: Sequence[Action] = (),
) -> DocumentMessage:
    if result.detail is None and result.candidates:
        reply = (
            M.document()

            .section("名称不唯一", icon="game.pin_doc")
            .line(
                M.status("需要选择", tone="warning"),
                _normalize_brackets(
                    f" “{result.query}”对应多项资料，请选择编号查看。"
                ),
            )
            .section("候选")
        )
        for index, candidate in enumerate(result.candidates, start=1):
            reply.item(
                index,
                M.command(
                    M.text(
                        f"{candidate.section} · {candidate.name}",
                        tone=_category_tone(candidate.section),
                    ),
                    f"查看 {candidate.item_id}",
                ),
                f" · {candidate.item_id}",
            )
        return reply.build()
    if result.detail is None:
        return (
            M.document()
            .section("结果", icon="game.pin_doc")
            .line(
                M.status("未找到", tone="danger"),
                _normalize_brackets(f" “{result.query}”没有对应资料。"),
            )
            .small("请检查编号或完整名称是否正确。")
            .build()
        )
    detail = result.detail
    title, icon = _display_title(detail.category)
    related = {item.item_id: item for item in result.related_details}
    reply = M.document()
    # 构筑正文统一从说明字段进入详情区；其他实体仍使用短引言加结构化详情。
    description = _player_description(detail)
    if detail.section in {"功法", "真意", "气机", "器律"}:
        description = ""
    if description:
        reply.section(title, icon=icon)
        for part in description.splitlines():
            if part.strip():
                reply.line(part)
    previews = result.grade_previews
    if previews and detail.section == "丹药":
        purpose_text = (
            " ".join(result.use_purposes)
            if detail.fields.get("无品级") and result.use_purposes
            else ""
        )
        for preview in previews:
            reply.section("丹效", icon=icon)
            if not detail.fields.get("无品级"):
                label = f"品级：{preview.name}"
                if preview.quantity:
                    label += f" · 持有 {preview.quantity}"
                reply.line(label)
            for line in preview.rendered:
                if purpose_text and line.startswith("用途："):
                    line = f"用途：{purpose_text}"
                reply.line(_normalize_brackets(line))
            effect = preview.fields.get("使用效果")
            if isinstance(effect, Mapping):
                permanent = effect.get("永久属性")
                if isinstance(permanent, Mapping) and permanent:
                    reply.line(
                        "永久属性："
                        + "、".join(
                            f"{key}+{_compact_number(value)}"
                            for key, value in permanent.items()
                        )
                    )
            if result.use_location:
                reply.line(_linked_line(f"使用地点：{result.use_location}", detail))
    elif previews and detail.section in {"功法", "真意", "气机", "器律"}:
        for preview in previews:
            scaled = replace(detail, fields=MappingProxyType(preview.fields))
            lines = _build_description_lines(scaled, preview.rendered)
            groups = _card_groups(lines, detail.section)
            reply.section(f"{detail.section}：{detail.name}", icon=icon)
            reply.line(f"品级：{preview.name} · 能力 ×{preview.multiplier:g}")
            for line in groups[0]:
                reply.line(_normalize_brackets(line))
            for title, body in groups[1]:
                reply.section(title, icon="")
                for line in body:
                    reply.line(_normalize_brackets(line))
    elif previews and detail.section == "阵法":
        for preview in previews:
            reply.section(f"阵势：{preview.name}", icon=icon)
            reply.line(
                "持有：未持有"
                if not preview.quantity
                else f"持有：{preview.quantity} 个"
            )
            monitor = detail.fields.get("宏观监测")
            if isinstance(monitor, Sequence) and not isinstance(monitor, (str, bytes)):
                reply.line("监测：" + "、".join(map(str, monitor)))
            core = detail.fields.get("阵法核心")
            if core:
                reply.line(f"核心：{core}")
            for line in preview.extra_lines:
                reply.line(_normalize_brackets(line))
    else:
        lines = (
            _build_description_lines(detail, result.rendered)
            if detail.section in {"功法", "真意", "气机", "器律"}
            else _definition_lines(
                detail.section,
                SectionInput(detail.fields, related, result.rendered, result.mask_text),
            )
        )
        lines = _with_held_grade(detail.section, result, lines)
        if lines:
            detail_title = _detail_title(detail.category)
            if detail.section in {"功法", "真意", "气机", "器律"}:
                detail_title = f"{detail.section}：{detail.name}"
            reply.section(detail_title, icon=icon)
            for line in lines:
                linked = _linked_line(line, detail)
                reply.line(linked if linked is not None else _normalize_brackets(line))
        elif not detail.description:
            reply.section("详情", icon=icon).line(
                M.status("暂无", tone="muted"), " 暂无更多记载。"
            )
    _append_baike(reply, baike_url, detail.item_id)
    # 联动按钮由实体自己的玩法给（如道侣的交谈/赠予/邀约/暂别），查看这一层不写死任何按钮。
    if actions:
        reply.actions(message_actions(actions))
    return reply.build()


def _append_baike(reply, base_url: str, item_id: str) -> None:
    """百科入口只留底部按钮；正文不再重复一条同名链接。"""

    if not base_url or not item_id:
        return
    url = f"{base_url}?q={item_id}"
    reply.action(Action("baike.open", "打开百科", url, behavior="link"))


def _compact_number(value: object) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return str(int(value)) if float(value).is_integer() else f"{float(value):g}"
    return str(value)


def _card_heading(line: str, section: str) -> str | None:
    """卡面「主动/被动/常驻」升级成栏目标题；普通行返回 None。"""

    for prefix, icon in (("主动：", "⚔️"), ("被动：", "🛡️"), ("常驻：", "♾️"), ("契合：", "♾️")):
        if line.startswith(prefix):
            label = "常驻" if prefix == "契合：" else prefix[:-1]
            return f"{icon} {section}{label}能力："
    return None


def _card_groups(
    lines: tuple[str, ...], section: str
) -> tuple[tuple[str, ...], tuple[tuple[str, tuple[str, ...]], ...]]:
    """把卡面正文按能力栏目拆开：首段是卡头，后面每段一个标题。"""

    first: list[str] = []
    groups: list[tuple[str, list[str]]] = []
    for line in lines:
        title = _card_heading(line, section)
        if title is not None:
            groups.append((title, []))
        elif groups:
            groups[-1][1].append(line)
        else:
            first.append(line)
    return tuple(first), tuple((title, tuple(body)) for title, body in groups)


def _linked_line(line: str, detail) -> tuple | None:
    """把实体引用做成无边框命令；不是引用就返回 None，保持原文。"""

    section = detail.section
    if section == "丹药" and line.startswith("使用地点："):
        value = line.removeprefix("使用地点：").strip()
        if value:
            return M.text("使用地点：") + (M.command(value, f"去 {value}"),)
    if section == "敌人" and line.startswith("种族："):
        value = line.removeprefix("种族：").strip()
        if value:
            return M.text("种族：") + (M.command(value, f"查看 {value}"),)
    if section == "敌人" and line.startswith("构筑："):
        value = line.removeprefix("构筑：").strip()
        if value:
            return M.text("构筑：") + (M.command(value, f"查看 {value}"),)
    if section == "境界" and line.startswith("下一境界："):
        value = line.removeprefix("下一境界：").strip()
        if value:
            return M.text("下一境界：") + (M.command(value, f"查看 {value}"),)
    if section in {"构筑", "敌人"} and line.startswith("建议种族："):
        value = line.removeprefix("建议种族：").strip()
        if value:
            return M.text("建议种族：") + (M.command(value, f"查看 {value}"),)
    if section in {"构筑", "敌人"} and line.startswith(("功法（", "真意（", "气机（")):
        head, _, tail = line.partition("：")
        names = [name for name in tail.split("、") if name]
        if names:
            content = M.text(head + "：")
            for index, name in enumerate(names):
                if index:
                    content += M.text("、")
                content += (M.command(name, f"查看 {name}"),)
            return content
    return None


_GRADE_SECTIONS = frozenset(
    {"丹药", "基础物品", "功法", "真意", "气机", "器律", "阵法"}
)


def _with_held_grade(
    section: str, result: ItemInspectionResult, lines: tuple[str, ...]
) -> tuple[str, ...]:
    """按领域决定要不要印品级行，以及印哪一种写法。

    品级只属于「物品 / 构筑 / 丹药 / 阵法」；种族、血脉、构筑模板、境界、
    伤势、状态、环境、道侣、灵宝都没有品级，不能统一前置一行「未持有」。
    基础物品没有基础值，只报持有/未持有；其余物品未写品级时按黄品预览。
    """

    if section not in _GRADE_SECTIONS:
        return lines
    grades = result.held_grades
    if section == "基础物品":
        if not grades:
            return ("品级：未持有",) + lines
        names = "、".join(item.name.removesuffix("品") for item in grades)
        return (f"品级：持有 {names}",) + lines
    if not grades:
        return ("品级：黄品",) + lines
    head = tuple(f"品级：{item.name}" for item in grades)
    return head + lines


def _display_title(category: str) -> tuple[str, str]:
    return {
        "功法": ("功法", "game.manual"),
        "真意": ("真意", "game.manual"),
        "气机": ("气机", "game.seed"),
        "器律": ("器律", "game.dagger"),
        "阵法": ("阵法", "game.blue_diamond"),
        "先天灵宝": ("先天灵宝", "game.amulet"),
        "丹药": ("丹药", "game.pill"),
        "灵植": ("灵植", "game.herb"),
        "灵矿": ("灵矿", "game.material"),
        "兽宝": ("兽宝", "game.material"),
        "灵石": ("灵石", "game.box"),
        "基础物品": ("基础物品", "game.box"),
        "道侣": ("道侣", "game.heart"),
        "伤势": ("伤势", "game.blood_drop"),
        "敌人": ("介绍", "game.scroll"),
        "种族": ("描述", "game.scroll"),
        "境界": ("描述", "game.scroll"),
        "构筑": ("描述", "game.scroll"),
    }.get(category, (category, "game.scroll"))


def _detail_title(category: str) -> str:
    return {
        "功法": "法门",
        "真意": "真意",
        "气机": "契合",
        "器律": "器纹",
        "丹药": "丹效",
        "阵法": "阵势",
        "先天灵宝": "权柄",
        "道侣": "人物志",
        "伤势": "影响",
        "境界": "等级区间",
        "人物状态": "状态流转",
        "基础物品": "持有",
        "灵植": "持有",
        "兽宝": "持有",
        "灵矿": "持有",
        "灵石": "持有",
        "种族": "锁定技",
        "普通血脉": "效果",
        "天外血脉": "效果",
        "构筑": "详情",
    }.get(category, "记载")


def _category_tone(category: str) -> str:
    return {
        "功法": "mystic",
        "真意": "mystic",
        "气机": "info",
        "器律": "metal",
        "阵法": "mystic",
        "先天灵宝": "cultivation",
        "丹药": "positive",
        "灵植": "wood",
        "灵矿": "metal",
        "道侣": "companion",
        "伤势": "danger",
    }.get(category, "emphasis")

def companion(
    copy: PositionCopy,
    view: CompanionView,
    actions: tuple[CommandAction, ...],
    cultivation: object | None = None,
) -> DocumentMessage:
    """看「我名下」这个道侣现在的样子：属性/资源 + 修为/构筑/本命武器。"""

    builder = M.document()
    section = builder.section(view.name, icon=copy.cultivator_icon)
    section.line(f"{view.realm_name} {view.level} 级 · 经验 {view.experience}")
    for key, value in view.attributes.items():
        section.field(str(key), str(value))
    for key, value in view.resources.items():
        section.field(str(key), str(value))
    if view.weapon_name:
        section.field(view.weapon_name, f"{view.weapon_level} 阶")
    if cultivation is not None:
        builder.section("修为", icon="game.seed")
        builder.row(
            ("境界", str(getattr(cultivation, "realm_name", ""))),
            ("等级", str(getattr(getattr(cultivation, "instance", None), "level", ""))),
        )
        next_experience = int(getattr(cultivation, "next_experience", 0) or 0)
        if next_experience:
            builder.field(
                "经验",
                M.progress(view.experience, next_experience, tone="emphasis"),
            )
        names = getattr(cultivation, "cultivation_names", ()) or ()
        if names:
            builder.section("修行构筑", icon="game.gear")
            for category, values in names:
                builder.field(str(category), "、".join(str(value) for value in values))
        builder.section("本命武器", icon="game.dagger")
        builder.field("名称", view.weapon_name)
        builder.row(
            ("器阶", str(getattr(cultivation, "weapon_stage", ""))),
            ("等级", str(view.weapon_level)),
        )
        builder.field(
            "器律孔",
            f"{len(getattr(cultivation, 'weapon_law_names', ()) or ())}/{int(getattr(cultivation, 'open_law_slots', 0) or 0)}",
        )
        for slot, law_name in getattr(cultivation, "weapon_law_names", ()) or ():
            builder.item(int(slot), str(law_name))
    builder.actions(message_actions(actions))
    return builder.build()

def cultivator(
    copy: PositionCopy,
    profile: CharacterPublicProfile,
    actions: tuple[CommandAction, ...],
) -> DocumentMessage:
    """看一个人：只给公开摘要那几项，名字仍是可点的无边框按钮。"""

    builder = M.document()
    builder.section(copy.cultivator_view, icon=copy.cultivator_icon).line(
        M.command(profile.name, f"查看 {profile.user_id}"),
        " · ",
        copy.cultivator_summary.format_map(
            {
                "境界": profile.realm_name,
                "等级": profile.level,
                "性别": profile.gender,
                "状态": "",
            }
        ),
    )
    builder.actions(message_actions(actions))
    return builder.build()


__all__ = ["inspection", "missing_query", "overview", "overview_error"]
