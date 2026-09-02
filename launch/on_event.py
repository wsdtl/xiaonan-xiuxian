"""业务启动与关闭回调注册表。

模块导入阶段只登记回调，真正执行由 lifespan 负责。优先级解决跨模块资源顺序，
注册顺序保证同优先级结果稳定。
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from itertools import count
from typing import ClassVar


@dataclass(frozen=True)
class EventCallback:
    """一个生命周期回调及其排序信息。"""

    priority: int
    order: int
    func: Callable


class OnEvent:
    """启动和关闭回调注册器。

    装饰器只登记函数，不在导入模块时执行任何工作；真正执行由
    `launch.lifespan` 统一编排。数值越大越先执行，同值按注册顺序执行。
    """

    connect_list: ClassVar[list[EventCallback]] = []
    disconnect_list: ClassVar[list[EventCallback]] = []
    _order_counter = count()

    @staticmethod
    def connect(priority: int = 0) -> Callable:
        """登记服务启动回调。"""

        def wrapper(func: Callable):
            OnEvent.connect_list.append(
                EventCallback(
                    priority=priority,
                    order=next(OnEvent._order_counter),
                    func=func,
                )
            )
            return func

        return wrapper

    @staticmethod
    def disconnect(priority: int = 0) -> Callable:
        """登记服务关闭回调。"""

        def wrapper(func: Callable):
            OnEvent.disconnect_list.append(
                EventCallback(
                    priority=priority,
                    order=next(OnEvent._order_counter),
                    func=func,
                )
            )
            return func

        return wrapper

    @staticmethod
    def ordered_callbacks(callbacks: Iterable[EventCallback]) -> list[Callable]:
        """按优先级取出回调；同优先级保持注册顺序。"""

        return [
            callback.func
            for callback in sorted(
                callbacks,
                key=lambda callback: (-callback.priority, callback.order),
            )
        ]
