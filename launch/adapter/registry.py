"""通信驱动器注册表与公共回复路由器。

MessageHandler 把同一业务回调注册到所有启用驱动器；AdapterReplyManager 根据
当前 ContextVar 或显式 ReplyTarget 选择真实 manager。业务层无需判断协议。
"""

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from fastapi import APIRouter

from launch.log import C, logger
from message import coerce_message

from .base_handler import BaseMessageHandler
from .context import SendRequest, current_message_context
from .depends import call_with_dependencies

_current_manager: ContextVar[Any | None] = ContextVar(
    "adapter_current_manager",
    default=None,
)


@dataclass(frozen=True)
class AdapterHttpMount:
    """驱动器可选的 HTTP 入口；没有入口的驱动器填 `None`。"""

    path: str
    router: APIRouter


@dataclass(frozen=True)
class AdapterSpec:
    """挂载层需要知道的一份适配器描述。

    `handler` 管理生命周期和命令规则，`manager` 负责回复，`has_context`
    用于没有显式上下文时选择当前驱动器。其余协议细节留在驱动器目录内。
    """

    name: str
    handler: type[BaseMessageHandler]
    manager: Any
    has_context: Callable[[], bool]
    http_mount: AdapterHttpMount | None = None


def available_adapter_specs() -> dict[str, AdapterSpec]:
    """返回项目已接入的适配器清单。

    这里使用函数内导入，避免公共注册器导入时提前启动 QQ 或 Local 模块。
    QQ 的 webhook（qq_wh）与 WebSocket（qq_ws）是两个独立驱动器，但共用
    qq_protocol 里的同一份命令注册表、事件解析和回复管理器。
    """

    from . import local, qq_wh, qq_ws
    from .local.manager import current_event as current_local_event
    from .qq_protocol.manager import current_event, manager as qq_manager

    return {
        "qq": AdapterSpec(
            name="qq",
            handler=qq_wh.QqEventHandler,
            manager=qq_manager,
            has_context=lambda: current_event.get() is not None,
            http_mount=AdapterHttpMount(
                path=qq_wh.QQ_EVENT_ROUTE,
                router=qq_wh.router,
            ),
        ),
        "qq_ws": AdapterSpec(
            name="qq_ws",
            handler=qq_ws.QqWsEventHandler,
            manager=qq_manager,
            has_context=lambda: current_event.get() is not None,
        ),
        "local": AdapterSpec(
            name="local",
            handler=local.LocalEventHandler,
            manager=local.manager,
            has_context=lambda: current_local_event.get() is not None,
        ),
    }


# 入站传输开关的合法取值。
QQ_TRANSPORTS: dict[str, tuple[str, ...]] = {
    "webhook": ("qq", "local"),
    "websocket": ("qq_ws", "local"),
    "both": ("qq", "qq_ws", "local"),
}

# 未配置时的入站方式。开放平台回调是长期在用的路径，保持默认可以让升级
# 驱动器这件事不影响线上；要切网关长连接时在 `.env` 显式写 websocket。
DEFAULT_QQ_TRANSPORT = "webhook"


def qq_transport() -> str:
    """读取 QQ 入站传输开关，未配置时默认沿用 webhook。"""

    from launch.config import config

    value = str(
        config.get("QQ_TRANSPORT", DEFAULT_QQ_TRANSPORT) or DEFAULT_QQ_TRANSPORT
    ).strip().lower()
    if value not in QQ_TRANSPORTS:
        raise ValueError(
            f"QQ_TRANSPORT 只能是 {'/'.join(QQ_TRANSPORTS)}，当前值是：{value}"
        )
    return value


def enabled_adapter_names() -> list[str]:
    """返回当前运行时启用的适配器名称。

    驱动器清单由代码登记，配置只决定 QQ 走哪一种入站传输；`local` 始终
    启用，天道后台和托管依赖它派发命令。
    """

    return list(QQ_TRANSPORTS[qq_transport()])


def enabled_adapter_specs() -> list[AdapterSpec]:
    """返回当前启用的适配器描述。"""

    available = available_adapter_specs()
    return [available[name] for name in enabled_adapter_names()]


class MessageHandler:
    """把一份业务回调复制注册到当前启用的消息适配器。

    业务组件只写一次 `GameCommand` 或 `MessageHandler`，这里负责把同一个
    回调分别交给 QQ 与 Local 的本地注册表。两个驱动器仍各自保存规则和
    运行时状态，公共层不合并它们的匹配实现。
    """

    @staticmethod
    def fullmatch(
        cmd,
        *,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册必须完整匹配整条消息的回调。"""

        return MessageHandler._register(
            "fullmatch", cmd, priority=priority, block=block, metadata=metadata
        )

    @staticmethod
    def command(
        cmd,
        *,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册命令词加参数的回调。"""

        return MessageHandler._register(
            "command", cmd, priority=priority, block=block, metadata=metadata
        )

    @staticmethod
    def regex(
        cmd,
        *,
        priority: int = 0,
        block: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Callable:
        """注册完整消息正则回调。"""

        return MessageHandler._register(
            "regex", cmd, priority=priority, block=block, metadata=metadata
        )

    @staticmethod
    def _register(
        method_name: str,
        cmd,
        *,
        priority: int,
        block: bool,
        metadata: dict[str, Any] | None,
    ) -> Callable:
        """把三种注册器共有的复制逻辑集中到一个地方。"""

        def wrapper(func: Callable) -> Callable:
            for spec in enabled_adapter_specs():
                registrar = getattr(spec.handler, method_name)
                registrar(
                    cmd=cmd,
                    priority=priority,
                    block=block,
                    metadata=metadata,
                )(MessageHandler._bind_manager(func, spec.manager))
            return func

        return wrapper

    @staticmethod
    def _bind_manager(func: Callable, real_manager: Any) -> Callable:
        """给驱动器回调绑定真实 manager，同时向业务暴露公共 manager。

        `real_manager` 只用于没有显式上下文时的兜底选择；业务回调拿到的
        始终是下面的公共 `manager`，这样游戏代码不需要判断当前是 QQ 还是
        Local。真正的驱动器 manager 只在适配器边界内使用。
        """

        @wraps(func)
        async def wrapped(**context: Any) -> Any:
            token = _current_manager.set(context.get("manager") or real_manager)
            try:
                public_context = dict(context)
                public_context["manager"] = manager
                return await call_with_dependencies(func, public_context)
            finally:
                _current_manager.reset(token)

        return wrapped


class AdapterReplyManager:
    """根据当前消息上下文选择真实适配器回复器。"""

    async def send(
        self,
        message: object,
        is_log: bool = True,
        request_id: object | None = None,
    ) -> bool:
        """把公共消息交给当前或显式目标所属的驱动器。

        业务层永远调用这个入口；QQ 的队列、本地的捕获结果和协议载荷都
        在各自 manager 内部处理。
        """

        payload = message.message if isinstance(message, SendRequest) else message
        if coerce_message(payload) is None:
            raise TypeError(
                "公共 manager 只接受 message.Message；"
                "平台原生 payload 只能在对应驱动器内部使用"
            )

        manager = self._current_manager()
        if isinstance(message, SendRequest) and message.target is not None:
            manager = self._manager_for_adapter(message.target.adapter) or manager

        if manager is None:
            if is_log:
                logger.opt(colors=True).warning(
                    C.join(
                        C.warn("回复失败，缺少当前适配器上下文"),
                        C.kv("user", _current_user_id()),
                    )
                )
            return False

        return await manager.send(
            message,
            is_log=is_log,
            request_id=request_id,
        )

    @staticmethod
    def _current_manager() -> Any | None:
        current = _current_manager.get()
        if current is not None:
            return current

        message_context = current_message_context()
        if message_context is not None:
            manager = AdapterReplyManager._manager_for_adapter(message_context.adapter)
            if manager is not None:
                return manager

        for spec in enabled_adapter_specs():
            if spec.has_context():
                return spec.manager

        return None

    @staticmethod
    def _manager_for_adapter(adapter: str) -> Any | None:
        spec = available_adapter_specs().get(str(adapter or "").strip().lower())
        if spec is None:
            return None
        return spec.manager


def _current_user_id() -> str:
    context = current_message_context()
    return context.user_id if context is not None else "-"


manager = AdapterReplyManager()
