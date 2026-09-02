"""应用生命周期总编排。

启动顺序固定为：获取单实例锁、挂载资源与驱动器、启动驱动器、启动调度器、
执行业务回调；关闭时先停止调度器，再释放业务服务和驱动器。这里负责顺序，
不包含任何业务规则。
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator, Callable, Iterable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

from .log import C, logger
from .mount import AdapterMount, FastAPIMount
from .on_event import OnEvent
from .runtime_guard import runtime_guard
from .schedulers import Scheduler


class LifecycleCleanupError(RuntimeError):
    """关闭阶段多项资源清理失败。"""

    def __init__(self, message: str, errors: Iterable[Exception]) -> None:
        self.errors = tuple(errors)
        super().__init__(f"{message}（{len(self.errors)} 项）")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """FastAPI 生命周期。

    启动：挂载适配器、启动调度器、按优先级运行启动回调。
    关闭：关闭调度器、按优先级运行关闭回调、关闭适配器。
    """

    cleanup_errors: list[Exception] = []
    runtime_guard.acquire()
    try:
        async with AsyncExitStack() as cleanup:
            cleanup.callback(
                _capture_sync_cleanup,
                "运行时单实例锁",
                runtime_guard.release,
                cleanup_errors,
            )

            adapters = _mount_app(app)
            for adapter in adapters:
                cleanup.push_async_callback(
                    _capture_cleanup,
                    f"适配器 {adapter.__name__}",
                    adapter.shutdown,
                    cleanup_errors,
                )
                await adapter.run()

            disconnect_callbacks = OnEvent.ordered_callbacks(OnEvent.disconnect_list)
            cleanup.push_async_callback(
                _capture_callbacks,
                disconnect_callbacks,
                cleanup_errors,
            )

            # AsyncExitStack 逆序清理：调度器必须先停，后台作业才不会在
            # 数据库等业务服务释放后继续访问它们。
            # 调度器的三个动作都是同步 API，不需要再包一层协程。
            cleanup.callback(
                _capture_sync_cleanup,
                "调度器",
                _shutdown_schedulers,
                cleanup_errors,
            )
            _start_schedulers()
            _add_scheduler_jobs()

            await _run_callbacks(OnEvent.ordered_callbacks(OnEvent.connect_list))

            logger.opt(colors=True).success(f"{C.ok('FastAPI 服务启动成功')}")
            yield
    except Exception:
        if cleanup_errors:
            logger.opt(colors=True).error(
                C.join(
                    C.fail("服务异常退出时另有清理失败"),
                    C.kv("count", len(cleanup_errors)),
                )
            )
        raise

    if cleanup_errors:
        raise LifecycleCleanupError("服务关闭阶段存在清理失败", cleanup_errors)


def _mount_app(app: FastAPI) -> list[type]:
    """挂载静态资源和适配器，返回需要参与生命周期的处理器。"""

    FastAPIMount(app)
    return AdapterMount(app)


def _start_schedulers() -> None:
    """启动唯一的定时任务调度器。

    Uvicorn reload 会创建新的事件循环；绑定动作必须放在生命周期里，不能
    在模块导入时保存旧循环。
    """

    Scheduler.bind_to_current_loop()
    if not Scheduler.instance.running:
        Scheduler.instance.start()


def _add_scheduler_jobs() -> None:
    """把模块导入阶段登记的任务安装到已启动的调度器。

    任务 id 是唯一键。重复创建应用时，已经安装的任务直接跳过，避免同一
    个后台任务被重复执行。
    """

    for task in Scheduler.jobs:
        kwargs = task.get("kwargs", {})
        job_id = kwargs.get("id")
        if Scheduler.instance.get_job(job_id):
            continue

        Scheduler.instance.add_job(
            task.get("func"),
            *task.get("args", ()),
            **kwargs,
        )
        logger.opt(colors=True).success(
            C.join(
                C.ok("成功添加定时任务"),
                C.kv("id", job_id),
            )
        )


async def _run_callbacks(callbacks: Iterable[Callable]) -> None:
    """按已排序的顺序执行回调，兼容同步函数和协程函数。"""

    for callback in callbacks:
        result = callback()
        if inspect.isawaitable(result):
            await result


async def _capture_callbacks(
    callbacks: Iterable[Callable], cleanup_errors: list[Exception]
) -> None:
    """逐个关闭业务服务；单项失败不能阻断后续清理。"""

    for callback in callbacks:
        await _capture_cleanup(
            f"业务关闭回调 {callback.__module__}.{callback.__name__}",
            callback,
            cleanup_errors,
        )


async def _capture_cleanup(
    label: str,
    callback: Callable,
    cleanup_errors: list[Exception],
) -> None:
    """执行一项同步或异步清理并保存异常。"""

    try:
        result = callback()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001 - 必须继续执行后续清理
        cleanup_errors.append(exc)
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("服务清理失败"), C.kv("target", label))
        )


def _capture_sync_cleanup(
    label: str,
    callback: Callable[[], None],
    cleanup_errors: list[Exception],
) -> None:
    """执行必须保持同步的清理动作并保存异常。"""

    try:
        callback()
    except Exception as exc:  # noqa: BLE001 - 必须继续执行后续清理
        cleanup_errors.append(exc)
        logger.opt(colors=True, exception=exc).error(
            C.join(C.fail("服务清理失败"), C.kv("target", label))
        )


def _shutdown_schedulers() -> None:
    """停止调度器，避免关闭数据库后仍有后台任务访问业务服务。"""

    scheduler = Scheduler.instance
    if scheduler.running:
        scheduler.shutdown(wait=False)
