"""项目定时任务注册表。

装饰器只收集任务定义，lifespan 在调度器启动后统一安装。普通函数和协程函数
共用 APScheduler 的 AsyncIO 调度器；每项任务必须有稳定 id，便于去重和日志定位。
"""

import asyncio
from collections.abc import Callable
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config import config


def _get_scheduler_timezone() -> ZoneInfo:
    """读取项目时区，避免 APScheduler 自动探测系统时区。"""

    try:
        return ZoneInfo(config.project.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"PROJECT_TIMEZONE 配置无效，当前值是：{config.project.timezone}") from exc


SCHEDULER_TIMEZONE = _get_scheduler_timezone()


class Scheduler:
    """项目唯一的定时任务注册器。"""

    instance = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
    jobs: ClassVar[list[dict]] = []

    @classmethod
    def bind_to_current_loop(cls) -> None:
        """服务重启时让调度器绑定当前事件循环。"""

        if cls.instance.running:
            return
        loop = asyncio.get_running_loop()
        bound_loop = getattr(cls.instance, "_eventloop", None)
        if bound_loop is not None and bound_loop is not loop:
            cls.instance = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)

    @staticmethod
    def job(*args, **kwargs) -> Callable:
        """注册定时任务；普通函数和协程函数都由同一调度器执行。

        必须传入 id。装载阶段会用这个 id 防止重复安装。

            @Scheduler.job("interval", seconds=10, id="sync_user_cache")
            def sync_user_cache():
                ...
        """

        def wrapper(func: Callable):
            Scheduler._check_job_id(func, kwargs)
            # 这里不启动任务。模块导入可能发生在事件循环创建前，统一由
            # lifespan 在启动阶段安装，才能保证调度器绑定当前循环。
            Scheduler.jobs.append(
                {
                    "func": func,
                    "args": args,
                    "kwargs": kwargs,
                }
            )
            return func

        return wrapper

    @staticmethod
    def _check_job_id(func: Callable, kwargs: dict) -> None:
        """检查定时任务是否传入 id。"""

        if kwargs.get("id"):
            return

        raise ValueError(
            f"定时任务 {func.__module__}.{func.__name__} 必须传入 id，例如："
            f' @Scheduler.job("interval", minutes=3, id="{func.__name__}")'
        )
