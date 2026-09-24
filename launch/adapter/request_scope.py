"""单条消息（一次请求）范围内的一次性资源挂载点。

驱动器只知道「一条消息处理完了」，不知道业务要在这段范围里挂什么会占用句柄的资源。
游戏组合根在启动时登记钩子（核心库的连接复用就是这样接上的）：处理一条消息前依次
执行，处理完再按相反顺序收尾。

范围覆盖守卫与业务回调两条路径上的每一条出口——守卫拦下、业务抛错、提前返回都会
收尾，因此钩子拿到的资源不会跨消息存活。钩子自己的异常不影响消息本身：开始钩子失败
只记日志（这条消息退回「没有该资源」的做法），收尾钩子失败同样只记日志。
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ..log import C, logger

#: 开始钩子：返回自己的收尾函数（不需要收尾就返回 None）。
RequestScopeHook = Callable[[], "Callable[[], None] | None"]

_HOOKS: list[RequestScopeHook] = []


def register_request_scope(hook: RequestScopeHook) -> None:
    """登记一个请求范围钩子；同一个钩子只登记一次。"""

    if hook not in _HOOKS:
        _HOOKS.append(hook)


def unregister_request_scope(hook: RequestScopeHook) -> None:
    """移除请求范围钩子。"""

    try:
        _HOOKS.remove(hook)
    except ValueError:
        return


@contextmanager
def request_scope() -> Iterator[None]:
    """一条消息的完整范围；退出时按登记的反序收尾。"""

    closers: list[Callable[[], None]] = []
    for hook in tuple(_HOOKS):
        try:
            closer = hook()
        except Exception as exc:  # noqa: BLE001 - 钩子失败不能顶掉这条消息
            logger.opt(colors=True, exception=exc).warning(C.warn("请求范围钩子开始失败"))
            continue
        if closer is not None:
            closers.append(closer)
    try:
        yield
    finally:
        for closer in reversed(closers):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 - 收尾失败同样只记日志
                logger.opt(colors=True, exception=exc).warning(C.warn("请求范围钩子收尾失败"))


__all__ = [
    "RequestScopeHook",
    "register_request_scope",
    "request_scope",
    "unregister_request_scope",
]
