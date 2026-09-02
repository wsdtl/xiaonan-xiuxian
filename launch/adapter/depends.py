"""命令回调的轻量依赖注入器。

解析器按函数签名注入公共上下文和 Depends，单条消息内可缓存依赖结果。组件
依赖不得隐藏驱动器私有 Depends，协议依赖必须直接出现在命令入口签名中。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from .context import current_message_context, current_reply_target

_current_message_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "adapter_current_message_context",
    default=None,
)


@dataclass(frozen=True)
class Depends:
    """声明一个命令参数由依赖函数计算得到。

    它只解决“按函数签名取值”这一件事，不是 FastAPI 的完整依赖系统；
    每条消息都会新建一个解析上下文，缓存也只在这一条消息内有效。
    """

    dependency: Callable
    use_cache: bool = True


class DependencyContext:
    """单条消息内的依赖解析上下文。

    `values` 是驱动器整理好的公共字段，`cache` 防止同一依赖在一条命令
    中被重复执行；消息结束后两者都会随调用栈释放。
    """

    def __init__(self, values: Mapping[str, Any]) -> None:
        self.values = dict(values)
        self.cache: dict[Callable, Any] = {}


async def call_with_dependencies(func: Callable, context: Mapping[str, Any]) -> Any:
    """按函数签名解析参数，支持普通上下文字段和 Depends。

    这是驱动器调用业务回调的唯一入口：先展开公共上下文，再解析参数，
    最后调用函数并等待协程结果。任何异常都交回上层驱动器处理。
    """

    values = _expanded_context(context)
    dependency_context = DependencyContext(values)
    token = _current_message_context.set(values)
    try:
        kwargs = await resolve_kwargs(func, dependency_context)
        result = func(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
    finally:
        _current_message_context.reset(token)


def current_context_value(name: str, default: Any = None) -> Any:
    """读取当前消息上下文中的字段。"""

    context = _current_message_context.get()
    return default if context is None else context.get(name, default)


def _expanded_context(values: Mapping[str, Any]) -> dict[str, Any]:
    """同时提供聚合消息对象和常用公共字段。"""

    context = dict(values)
    message_context = context.get("message_context") or current_message_context()
    if message_context is not None:
        context.setdefault("message_context", message_context)
        context.setdefault("reply_target", message_context.reply_target)
        context.setdefault("request_id", message_context.request_id)
    else:
        reply_target = context.get("reply_target") or current_reply_target()
        if reply_target is not None:
            context.setdefault("reply_target", reply_target)
    return context


async def resolve_kwargs(func: Callable, dependency_context: DependencyContext) -> dict[str, Any]:
    """为命令回调解析可注入参数，缺少必填参数时立即报错。"""

    return await _resolve_parameters(
        func,
        dependency_context,
        missing_label="命令参数",
    )


async def resolve_dependency(
    depends: Depends,
    dependency_context: DependencyContext,
    stack: tuple[Callable, ...] = (),
) -> Any:
    """递归解析一个 Depends，并执行循环与协议边界检查。"""

    dependency = depends.dependency
    if dependency in stack:
        raise RuntimeError(f"循环依赖：{dependency!r}")
    _assert_dependency_boundary(dependency, stack)
    if depends.use_cache and dependency in dependency_context.cache:
        return dependency_context.cache[dependency]

    kwargs = await resolve_dependency_kwargs(
        dependency,
        dependency_context,
        stack + (dependency,),
    )
    result = dependency(**kwargs)
    if inspect.isawaitable(result):
        result = await result

    if depends.use_cache:
        dependency_context.cache[dependency] = result
    return result


async def resolve_dependency_kwargs(
    dependency: Callable,
    dependency_context: DependencyContext,
    stack: tuple[Callable, ...] = (),
) -> dict[str, Any]:
    """为依赖函数解析参数；规则与命令回调保持一致。"""

    return await _resolve_parameters(
        dependency,
        dependency_context,
        stack=stack,
        missing_label="依赖参数",
    )


async def _resolve_parameters(
    func: Callable,
    dependency_context: DependencyContext,
    *,
    stack: tuple[Callable, ...] = (),
    missing_label: str,
) -> dict[str, Any]:
    """按同一套规则解析命令或 Depends 的函数签名。

    命令和依赖函数的区别只有两点：递归时是否携带依赖栈，以及缺少参数时
    的错误前缀。把签名遍历集中在这里，避免两套规则以后出现细微分叉。
    """

    signature = inspect.signature(func)
    kwargs: dict[str, Any] = {}

    for name, parameter in signature.parameters.items():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            kwargs.update(dependency_context.values)
            continue

        if parameter.kind not in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ):
            continue

        default = parameter.default
        if isinstance(default, Depends):
            kwargs[name] = await resolve_dependency(default, dependency_context, stack)
            continue

        if name in dependency_context.values:
            kwargs[name] = dependency_context.values[name]
            continue

        if default is inspect.Parameter.empty:
            label = f"{missing_label}：{name}"
            if missing_label == "依赖参数":
                label = f"{missing_label}：{func.__name__}.{name}"
            raise TypeError(label)

    return kwargs


def _assert_dependency_boundary(dependency: Callable, stack: tuple[Callable, ...]) -> None:
    """禁止组件依赖函数把驱动器私有依赖藏进内部。"""

    if not stack or not _is_adapter_private_dependency(dependency):
        return

    parent = next((item for item in reversed(stack) if _is_component_dependency(item)), None)
    if parent is None:
        return

    raise RuntimeError(
        "组件 Depends 不能嵌套驱动器私有 Depends："
        f"{_callable_label(parent)} -> {_callable_label(dependency)}；"
        "请在命令函数签名里显式声明驱动器 Depends"
    )


def _is_component_dependency(func: Callable) -> bool:
    """判断依赖函数是否属于组件层。"""

    module = _callable_module(func)
    return bool(module) and not module.startswith("launch.")


def _is_adapter_private_dependency(func: Callable) -> bool:
    """判断依赖函数是否属于某个驱动器私有依赖模块。"""

    module = _callable_module(func)
    parts = module.split(".")
    return len(parts) >= 4 and parts[0] == "launch" and parts[1] == "adapter" and parts[-1] == "depends"


def _callable_module(func: Callable) -> str:
    """读取函数真实模块名，兼容被装饰过的函数。"""

    try:
        func = inspect.unwrap(func)
    except ValueError:
        pass
    return str(getattr(func, "__module__", "") or "")


def _callable_label(func: Callable) -> str:
    """生成依赖函数的错误提示名。"""

    module = _callable_module(func)
    name = str(getattr(func, "__qualname__", None) or getattr(func, "__name__", repr(func)))
    return f"{module}.{name}" if module else name
