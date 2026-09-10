"""查看正式编号实体的命令回复构造。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re

from game.features.chakan_wupin import ItemInspectionResult
from message import M

from .items import (
    _build_description_lines,
    _definition_lines,
    _normalize_brackets,
    _player_description,
)


def missing_query():
    return (
        M.document()
        .section("查看", icon="item")
        .line(M.status("缺少目标", tone="warning"), " 请提供编号或完整名称。")
        .small("例如：查看 100005 · 查看 小还丹")
        .build()
    )


def inspection(result: ItemInspectionResult):
    if result.detail is None and result.candidates:
        reply = (
            M.document()
            .header("查看结果")
            .section("名称不唯一", icon="notice")
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
                    submit=False,
                ),
                f" · {candidate.item_id}",
            )
        return reply.build()
    if result.detail is None:
        return (
            M.document()
            .section("查看", icon="notice")
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
    lines = (
        _build_description_lines(detail)
        if detail.section in {"功法", "真意", "气机", "器律"}
        else _definition_lines(detail.section, detail.fields, related)
    )
    reply = M.document().header(detail.name)
    # 构筑正文统一从说明字段进入详情区；其他实体仍使用短引言加结构化详情。
    description = _player_description(detail)
    if detail.section in {"功法", "真意", "气机", "器律"}:
        # 构筑正文已按说明字段逐行放入详情区，避免引言重复出现。
        description = ""
    if description:
        reply.section(title, icon=icon).field("编号", detail.item_id)
        reply.line(description)
    else:
        reply.inline_section(
            title,
            f"编号 {detail.item_id}",
            icon=icon,
        )
    if lines:
        reply.section(_detail_title(detail.category), icon=icon)
        for line in lines:
            reply.line(_normalize_brackets(line))
    elif not detail.description:
        reply.section("详情", icon=icon).line(
            M.status("暂无", tone="muted"), " 暂无更多记载。"
        )
    return reply.build()


def _display_title(category: str) -> tuple[str, str]:
    return {
        "功法": ("功法", "skill"),
        "真意": ("真意", "skill"),
        "气机": ("气机", "status"),
        "器律": ("器律", "weapon"),
        "阵法": ("阵法", "skill"),
        "先天灵宝": ("先天灵宝", "item"),
        "丹药": ("丹药", "recovery"),
        "灵植": ("灵植", "recovery"),
        "灵矿": ("灵矿", "material"),
        "兽宝": ("兽宝", "material"),
        "基础物品": ("基础物品", "item"),
        "丹方": ("丹方", "recovery"),
        "道侣": ("道侣", "player"),
        "伤势": ("伤势", "status"),
    }.get(category, (category, "docs"))


def _detail_title(category: str) -> str:
    return {
        "功法": "法门",
        "真意": "真意",
        "气机": "契合",
        "器律": "器纹",
        "丹药": "丹效",
        "丹方": "炼制",
        "阵法": "阵势",
        "先天灵宝": "权柄",
        "道侣": "人物志",
        "伤势": "影响",
        "境界": "境界",
        "人物状态": "状态流转",
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

__all__ = ["inspection", "missing_query"]
