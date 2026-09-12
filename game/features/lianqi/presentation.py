"""读取炼器展示 JSON 并生成强业务联动动作。"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from game.core.data import JsonDataError, JsonDataService, strict_text as _text
from game.features.presentation import project_buttons, require_mapping

from .contracts import ForgingAction, ForgingCopy

_PAGES = frozenset({"总览", "预览", "完成"})
_REQUIRED_TEXT = {
    "总览": frozenset({"标题", "工匠", "流派", "引言", "器阶"}),
    "列表": frozenset({"标题", "工匠", "可炼", "缺材", "页码"}),
    "预览": frozenset(
        {"标题", "工匠", "器律", "器阶", "铸法", "兽引", "矿材"}
    ),
    "完成": frozenset({"标题", "工匠", "过程", "所得"}),
    "错误": frozenset({"标题", "无工匠", "格式"}),
}


def load_presentation(
    data: JsonDataService,
) -> tuple[ForgingCopy, tuple[Mapping[str, str], ...]]:
    raw_text = data.dataset("炼器展示").get("文本")
    if not isinstance(raw_text, Mapping):
        raise JsonDataError("炼器展示缺少文本.json")
    text = MappingProxyType(
        {
            str(section): MappingProxyType(
                {
                    str(key): _text(value, f"炼器文本.{section}.{key}")
                    for key, value in require_mapping(raw, f"炼器文本.{section}").items()
                }
            )
            for section, raw in raw_text.items()
        }
    )
    if set(text) != set(_REQUIRED_TEXT):
        raise JsonDataError("炼器文本页面必须完整且不能包含未声明页面")
    for section, fields in _REQUIRED_TEXT.items():
        if set(text[section]) != set(fields):
            raise JsonDataError(f"炼器文本字段不完整：{section}")
    buttons = project_buttons(
        data.dataset("炼器按钮").get("按钮"),
        label="炼器按钮",
    )
    _validate_buttons(buttons)
    return ForgingCopy(text), buttons


def actions(
    buttons: tuple[Mapping[str, str], ...],
    page: str,
    conditions: set[str],
    variables: Mapping[str, object] | None = None,
) -> tuple[ForgingAction, ...]:
    values = {str(key): str(value) for key, value in (variables or {}).items()}
    try:
        return tuple(
            ForgingAction(
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
        raise RuntimeError(f"炼器按钮缺少模板变量：{exc.args[0]}") from exc


def _validate_buttons(buttons: tuple[Mapping[str, str], ...]) -> None:
    if any(button["页面"] not in _PAGES for button in buttons):
        raise JsonDataError("炼器按钮使用了未知页面")
    if any(
        not button["编号"] or not button["名称"] or not button["命令"]
        for button in buttons
    ):
        raise JsonDataError("炼器按钮编号、名称和命令不能为空")
    identities = tuple((button["页面"], button["编号"]) for button in buttons)
    if len(identities) != len(set(identities)):
        raise JsonDataError("炼器同一页面的按钮编号不能重复")
    conditions = {button["条件"] for button in buttons if button["条件"]}
    if conditions - {"可以开炉"}:
        raise JsonDataError("炼器按钮使用了未知条件")


__all__ = ["actions", "load_presentation"]
