"""玩法微服务共享的展示数据加载骨架。

每个玩法在自己的 `data/<组件>/展示` 数据集里声明文本与按钮，并由自己的
`presentation.py`（或 `service.py`）解释。各玩法的**校验规则原本就不同**：
文本转换有「裸 `str`」与「`str(value or "")`」两种语义，按钮唯一性有
「全局编号唯一」「同一页面内编号唯一」两种口径，必填页面集合也各自声明。
因此本模块只提供各玩法逐字节相同的那部分骨架：

- 对象与列表的形状校验；
- 按固定字段投影按钮行；
- 按页面与条件筛选按钮。

域特有的必填字段、条件白名单和唯一性口径仍留在各玩法模块，由调用方在
投影之后自行校验。展示格式化属于 `game/cmd`，本模块不承担回复构造。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from game.core.data import JsonDataError

# 按钮 JSON 的固定字段；顺序即投影顺序。
BUTTON_KEYS = ("页面", "条件", "编号", "名称", "命令", "行为", "样式")
# 宗门系按钮不带条件列，页面字段语义也不同：宗门主体用「页面」，
# 山门用「位置」区分同一按钮在入口与洞天两侧的出现位置。
BUTTON_KEYS_WITHOUT_CONDITION = ("页面", "编号", "名称", "命令", "行为", "样式")
POSITIONED_BUTTON_KEYS = ("位置", "编号", "名称", "命令", "行为", "样式")

Button = Mapping[str, str]


def require_mapping(value: object, label: str) -> Mapping[str, Any]:
    """要求 `value` 是对象；否则指出具体配置路径。"""

    if not isinstance(value, Mapping):
        raise JsonDataError(f"{label}必须是对象")
    return value


def require_sequence(value: object, label: str) -> Sequence[Any]:
    """要求 `value` 是列表；字符串与字节串不算列表。"""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise JsonDataError(f"{label}必须是字典列表")
    return value


def project_buttons(
    rows: object,
    *,
    label: str,
    keys: tuple[str, ...] = BUTTON_KEYS,
) -> tuple[Button, ...]:
    """按固定字段把按钮行投影为只读文本映射。

    只做形状与字段抽取，不做任何语义校验；唯一性、页面和条件白名单由调用方
    按各自口径校验，以保持原有报错信息与判定宽度不变。

    `keys` 决定投影列。缺列的按钮族（例如宗门系不带「条件」、山门用「位置」
    代替「页面」）传入自己的列定义，避免凭空多出下游不认识的键。
    """

    return tuple(
        MappingProxyType(
            {
                key: str(require_mapping(row, f"{label}[]").get(key) or "").strip()
                for key in keys
            }
        )
        for row in require_sequence(rows, label)
    )


def select_buttons(
    buttons: tuple[Button, ...],
    *,
    page: str,
    conditions: set[str] | None = None,
) -> tuple[Button, ...]:
    """取出指定页面内条件已满足的按钮。

    `conditions` 为 `None` 时只按页面筛选，供不区分条件的玩法使用。
    """

    if conditions is None:
        return tuple(button for button in buttons if button["页面"] == page)
    return tuple(
        button
        for button in buttons
        if button["页面"] == page
        and (not button["条件"] or button["条件"] in conditions)
    )


def format_command(button: Button, variables: Mapping[str, object] | None) -> str:
    """按变量表展开按钮命令模板，缺少变量时指明具体名称。"""

    values = {str(key): str(value) for key, value in (variables or {}).items()}
    return button["命令"].format_map(values)


__all__ = [
    "BUTTON_KEYS",
    "BUTTON_KEYS_WITHOUT_CONDITION",
    "Button",
    "POSITIONED_BUTTON_KEYS",
    "format_command",
    "project_buttons",
    "require_mapping",
    "require_sequence",
    "select_buttons",
]
