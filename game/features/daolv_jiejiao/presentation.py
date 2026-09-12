"""道侣展示 JSON 的严格玩法适配。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from types import MappingProxyType

from game.core.data import JsonDataError, strict_text as _text
from game.features.presentation import require_mapping

from .contracts import CompanionAction, CompanionCopy


@dataclass(frozen=True)
class CompanionButton:
    page: str
    condition: str
    action_id: str
    label: str
    command: str
    behavior: str
    style: str


def load_companion_presentation(
    dataset: Mapping[str, object],
) -> tuple[CompanionCopy, tuple[CompanionButton, ...]]:
    if set(dataset) != {"文本", "图标", "道侣"}:
        raise JsonDataError("道侣展示必须包含文本、图标和道侣按钮")
    text_value = require_mapping(dataset["文本"], "道侣/展示/规则/文本.json")
    expected_sections = {"查看", "交谈", "赠礼", "邀约", "暂别", "命令", "错误"}
    if set(text_value) != expected_sections:
        raise JsonDataError("道侣展示文本分区不完整")
    text = MappingProxyType(
        {
            section: MappingProxyType(
                {
                    str(key): _text(raw, f"道侣文本.{section}.{key}")
                    for key, raw in require_mapping(value, f"道侣文本.{section}").items()
                }
            )
            for section, value in text_value.items()
        }
    )
    icons_value = require_mapping(dataset["图标"], "道侣/展示/规则/图标.json")
    expected_icons = {
        "身份",
        "性情",
        "喜好",
        "关系",
        "交谈",
        "赠礼",
        "邀约",
        "暂别",
        "错误",
    }
    if set(icons_value) != expected_icons:
        raise JsonDataError("道侣展示图标不完整")
    icons = MappingProxyType(
        {
            str(key): _text(value, f"道侣图标.{key}")
            for key, value in icons_value.items()
        }
    )
    buttons = _buttons(dataset["道侣"])
    identities = tuple((button.page, button.action_id) for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("同一道侣页面不能重复使用按钮编号")
    return CompanionCopy(text, icons), buttons


def render_action(button: CompanionButton, companion_id: str) -> CompanionAction:
    variables = {"道侣": companion_id}
    return CompanionAction(
        button.action_id,
        button.label.format_map(variables),
        button.command.format_map(variables),
        button.behavior,
        button.style,
    )


def _buttons(value: object) -> tuple[CompanionButton, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError("道侣/展示/按钮/道侣.json必须是字典列表")
    result: list[CompanionButton] = []
    for index, raw in enumerate(value):
        row = require_mapping(raw, f"道侣按钮[{index}]")
        if unknown := set(row) - {
            "页面",
            "条件",
            "编号",
            "名称",
            "命令",
            "行为",
            "样式",
        }:
            raise JsonDataError(
                f"道侣按钮[{index}]存在未知字段：{'、'.join(sorted(unknown))}"
            )
        page = _text(row.get("页面"), f"道侣按钮[{index}].页面")
        if page not in {"查看", "交谈", "赠礼", "邀约", "暂别"}:
            raise JsonDataError(f"道侣按钮[{index}]页面无效：{page}")
        condition = str(row.get("条件") or "").strip()
        if condition not in {"", "可邀约", "同行中"}:
            raise JsonDataError(f"道侣按钮[{index}]条件无效：{condition}")
        label = _template(row.get("名称"), f"道侣按钮[{index}].名称", set())
        command_fields = set() if page == "暂别" else {"道侣"}
        command = _template(
            row.get("命令"),
            f"道侣按钮[{index}].命令",
            command_fields,
        )
        behavior = _text(row.get("行为"), f"道侣按钮[{index}].行为")
        style = _text(row.get("样式"), f"道侣按钮[{index}].样式")
        if behavior not in {"callback", "send", "fill", "link"}:
            raise JsonDataError(f"道侣按钮[{index}]行为无效：{behavior}")
        if style not in {"primary", "secondary"}:
            raise JsonDataError(f"道侣按钮[{index}]样式无效：{style}")
        result.append(
            CompanionButton(
                page,
                condition,
                _text(row.get("编号"), f"道侣按钮[{index}].编号"),
                label,
                command,
                behavior,
                style,
            )
        )
    return tuple(result)


def _template(value: object, label: str, fields: set[str]) -> str:
    template = _text(value, label)
    found: set[str] = set()
    try:
        for _, field_name, format_spec, conversion in Formatter().parse(template):
            if field_name is None:
                continue
            if not field_name or format_spec or conversion:
                raise ValueError
            found.add(field_name)
    except ValueError as exc:
        raise JsonDataError(f"{label}包含无效模板") from exc
    if found != fields:
        raise JsonDataError(f"{label}占位符必须是：{'、'.join(sorted(fields)) or '无'}")
    return template


__all__ = ["CompanionButton", "load_companion_presentation", "render_action"]
