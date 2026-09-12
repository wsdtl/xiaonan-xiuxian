"""字段取值校验：服务从 `Mapping` 里取出一个字段时，顺手确认它的形状。

字段契约（`schema.py`）管的是「整份文档合不合已声明的形状」；本模块管的是另一件更小的
事：运行期取一个字段，确认它是正整数 / 非负整数 / 对象 / 非空文本 / 严格文本 / 布尔 /
数值 / 数组。

之所以单独立一层：这些判定以前在每个服务里各抄一份。严格口径量下来，前四个是
`positive_int` 41 处、`mapping` 33 处、`nonempty_text` 23 处、`nonnegative_int` 19 处，
后四个是 `strict_text` 11 处、`boolean` 8 处、`number` 6 处、`sequence` 5 处，
彼此只差「抛哪个异常」。判定本身抄上百遍，等于修好一处不会传给另外几十处——
例如 `bool` 是 `int` 的子类、必须先排除，这一条就抄了 57 遍。

**两个文本校验器不是重复，别合并**：`strict_text` 要求本来就是 `str`，
`nonempty_text` 会先 `str(value or "")` 再判空。调用哪个取决于该字段允许不允许代转。

域错误仍由调用方决定：`error=` 传自己服务的异常类型，命令层捕获的就还是各服务的错误。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import JsonDataError


def positive_int(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> int:
    """取正整数。`bool` 是 `int` 的子类，必须显式排除。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise error(f"{label}必须是正整数")
    return value


def nonnegative_int(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> int:
    """取非负整数。同样要排除 `bool`。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise error(f"{label}必须是非负整数")
    return value


def mapping(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> Mapping[str, Any]:
    """取对象。"""

    if not isinstance(value, Mapping):
        raise error(f"{label}必须是对象")
    return value


def nonempty_text(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> str:
    """取非空文本：先转成字符串再去空白，空则报错。"""

    result = str(value or "").strip()
    if not result:
        raise error(f"{label}不能为空")
    return result


def strict_text(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> str:
    """取非空文本，但本来就要求是 `str`：不代做类型转换。"""

    if not isinstance(value, str) or not value.strip():
        raise error(f"{label}必须是非空文本")
    return value.strip()


def boolean(value: object, label: str, error: type[Exception] = JsonDataError) -> bool:
    """取布尔值。`1` / `0` 不是布尔，不代转。"""

    if not isinstance(value, bool):
        raise error(f"{label}必须是布尔值")
    return value


def number(value: object, label: str, error: type[Exception] = JsonDataError) -> float:
    """取数值（`int` 或 `float`），返回 `float`。`bool` 是 `int` 的子类，要排除。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error(f"{label}必须是数值")
    return float(value)


def sequence(
    value: object, label: str, error: type[Exception] = JsonDataError
) -> tuple[Any, ...]:
    """取数组，返回 `tuple`。字符串与字节串不算数组。"""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise error(f"{label}必须是数组")
    return tuple(value)


__all__ = [
    "boolean",
    "mapping",
    "nonempty_text",
    "nonnegative_int",
    "number",
    "positive_int",
    "sequence",
    "strict_text",
]
