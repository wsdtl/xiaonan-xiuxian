"""读取阵法展示 JSON 并生成炼阵动作。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService, strict_text as _text
from game.features.presentation import project_buttons, require_mapping

from .contracts import FormationAction, FormationCopy

_PAGES = frozenset({"总览", "预览", "完成"})
_REQUIRED = {
    "总览": frozenset({"标题", "阵师", "传承", "引言", "阵法"}),
    "列表": frozenset({"标题", "阵师", "页码"}),
    "预览": frozenset({"标题", "阵师", "阵法", "品级", "阵基", "阵眼", "节点", "材料"}),
    "完成": frozenset({"标题", "阵师", "过程", "所得"}),
    "布阵": frozenset({"标题", "过程", "结果", "话语"}),
    "错误": frozenset({"标题", "格式"}),
}


def load_presentation(data: JsonDataService) -> tuple[FormationCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("阵法展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("阵法展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {
                    str(key): _text(value, f"阵法文本.{section}.{key}")
                    for key, value in require_mapping(raw, f"阵法文本.{section}").items()
                }
            )
            for section, raw in raw_text.items()
        }
    )
    if set(text) != set(_REQUIRED):
        raise JsonDataError("阵法文本页面必须完整且不能包含未声明页面")
    for section, fields in _REQUIRED.items():
        if set(text[section]) != set(fields):
            raise JsonDataError(f"阵法文本字段不完整：{section}")
    buttons = project_buttons(
        data.dataset("阵法按钮").get("按钮"),
        label="阵法按钮",
    )
    _validate_buttons(buttons)
    return FormationCopy(text), buttons


def actions(buttons: tuple[Mapping[str, str], ...], page: str, conditions: set[str], variables: Mapping[str, object] | None=None) -> tuple[FormationAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    try:
        return tuple(
            FormationAction(
                button["编号"],
                button["名称"],
                button["命令"].format_map(values),
                button["行为"],
                button["样式"],
            )
            for button in buttons
            if button["页面"] == page
            and (not button["条件"] or button["条件"] in conditions)
        )
    except KeyError as exc:
        raise RuntimeError(f"阵法按钮缺少模板变量：{exc.args[0]}") from exc


def _validate_buttons(buttons: tuple[Mapping[str, str], ...]) -> None:
    if any(button["页面"] not in _PAGES | {"布阵"} for button in buttons):
        raise JsonDataError("阵法按钮使用了未知页面")
    identities = tuple((button["页面"], button["编号"]) for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("阵法同一页面的按钮编号不能重复")
    if any(not button["编号"] or not button["名称"] or not button["命令"] for button in buttons):
        raise JsonDataError("阵法按钮编号、名称和命令不能为空")
    conditions = {button["条件"] for button in buttons if button["条件"]}
    if conditions - {"可以炼阵", "有上一页", "有下一页"}:
        raise JsonDataError("阵法按钮使用了未知条件")


__all__ = ["actions", "load_presentation"]
