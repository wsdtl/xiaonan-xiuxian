"""验证框架启动顺序：业务服务必须先于驱动器就绪。

`game/app.py` 把微服务装配挂在 `OnEvent.connect(priority=1000)` 上，命令回调
统一通过 `current_game_services()` 取服务，服务未装配时该函数直接抛
`RuntimeError`。

驱动器一旦 `run()` 就开始收事件（webhook 路由在 lifespan 之前就挂好了，
WebSocket 建连后立即鉴权收消息）。所以只要驱动器早于业务回调启动，启动窗口内
到达的任何一条玩家消息都会撞上"微服务尚未初始化"。这个顺序不能靠代码注释保证，
必须由测试卡住：本文件用一个探针驱动器记录"驱动器启动那一刻服务是否已经可用"。

探针驱动器不访问网络，只复刻驱动器与生命周期的契约（类对象、静态 run/shutdown）。
"""

from __future__ import annotations

import asyncio
import importlib
import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import game.app  # noqa: E402,F401 - 注册业务关闭/启动回调与微服务装配

# 必须用 import_module：`launch/__init__.py` 导出了同名的 `lifespan`/`Scheduler`
# 对象，`import launch.lifespan as x` 拿到的是那个对象而不是模块。
_lifespan_module = importlib.import_module("launch.lifespan")
lifespan = _lifespan_module.lifespan
_scheduler_module = importlib.import_module("launch.schedulers")
OnEvent = _lifespan_module.OnEvent

# 探针观测点：驱动器启动时刻的服务状态，以及业务回调时刻的调度器状态。
_services_at_adapter: list[tuple[bool, str]] = []
_scheduler_at_callback: list[bool] = []


@OnEvent.connect(priority=1)
def _probe_scheduler_running() -> None:
    """记录业务回调期间调度器是否已经启动。

    托管恢复等启动回调会调用 `Scheduler.instance.add_job`，调度器未运行时
    它们静默返回，重启后托管计划就恢复不了。
    """

    _scheduler_at_callback.append(bool(_scheduler_module.Scheduler.instance.running))


class ProbeAdapter:
    """记录驱动器启动时刻的观测结果，不连任何网络。"""

    observations: list[tuple[str, bool, str]] = []

    @staticmethod
    async def run() -> None:
        services_ready, detail = _services_state()
        _services_at_adapter.append((services_ready, detail))
        ProbeAdapter.observations.append(("run", services_ready, detail))

    @staticmethod
    async def shutdown() -> None:
        services_ready, detail = _services_state()
        ProbeAdapter.observations.append(("shutdown", services_ready, detail))


def _services_state() -> tuple[bool, str]:
    """读取"此刻命令回调能不能拿到游戏服务"。"""

    try:
        game_app = importlib.import_module("game.app")
        game_app.current_game_services()
    except RuntimeError as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001 - 其它异常也算不可用，但要保留原因
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


class _FakeApp:
    """lifespan 只用到 app 的 state 与 routes（挂载静态资源与适配器路由）。"""

    def __init__(self) -> None:
        self.state = type("State", (), {})()
        self.routes: list[object] = []
        self.router = type("Router", (), {"routes": self.routes})()
        self._mount_names: dict[str, object] = {}

    def mount(self, path: str, app: object = None, name: str = "") -> None:
        """记录 mount 调用，供静态资源挂载使用。"""

        self._mount_names[name] = path
        self.routes.append(type("Route", (), {"path": path})())

    def include_router(self, router: object, tags: list[str] | None = None) -> None:
        """记录适配器路由的 include_router 调用。"""

        for route in getattr(router, "routes", []):
            self.routes.append(route)


async def observe_startup_order() -> tuple[list[tuple[str, bool, str]], list[str]]:
    """跑一次真实 lifespan 启动与关闭，返回探针记录与最终应用路由。"""

    ProbeAdapter.observations = []
    original_mount = _lifespan_module._mount_app
    _lifespan_module._mount_app = lambda app: [ProbeAdapter]
    app = _FakeApp()
    try:
        async with lifespan(app):
            # 进入这里说明启动阶段已经全部完成。
            pass
    finally:
        _lifespan_module._mount_app = original_mount
    return list(ProbeAdapter.observations), [
        str(getattr(route, "path", "")) for route in app.routes
    ]


async def observe_real_adapter_mount() -> list[str]:
    """用真实 `_mount_app` 跑一次启动，返回最终应用上挂到的全部路径。

    适配器 HTTP 入口是在 lifespan 启动阶段挂载的，`create_app()` 之后查不到，
    所以只能这样验证：驱动器的挂载步骤不能被顺序调整漏掉。
    """

    app = _FakeApp()
    async with lifespan(app):
        pass
    return [str(getattr(route, "path", "")) for route in app.routes]


def main() -> int:
    """断言驱动器启动时业务服务已经可用。"""

    print("框架启动顺序验证")
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  [通过] {label}")
            return
        text = f"{label}：{detail}" if detail else label
        failures.append(text)
        print(f"  [失败] {text}")

    observations, probe_paths = asyncio.run(observe_startup_order())
    run_records = [item for item in observations if item[0] == "run"]
    shutdown_records = [item for item in observations if item[0] == "shutdown"]

    check("探针驱动器确实被启动", len(run_records) == 1, str(observations))

    if run_records:
        ready, detail = run_records[0][1], run_records[0][2]
        check(
            "驱动器启动时游戏微服务已装配",
            ready,
            f"驱动器 run() 时 current_game_services() 仍在报错：{detail}",
        )

    check(
        "业务启动回调运行时调度器已启动",
        bool(_scheduler_at_callback) and all(_scheduler_at_callback),
        f"回调期间观测到 running={_scheduler_at_callback}",
    )

    # 用真实 _mount_app 再跑一次：必须同时挂到静态资源与 QQ webhook 入口。
    # （探针那一轮替换了 _mount_app，所以不能在那里断言挂载结果。）
    real_paths = asyncio.run(observe_real_adapter_mount())
    check(
        "真实挂载包含 QQ webhook 入口",
        "/qq/events" in real_paths,
        f"paths={real_paths}",
    )
    check(
        "真实挂载包含静态资源",
        "/static" in real_paths,
        f"paths={real_paths}",
    )

    # 关闭阶段必须相反：驱动器先停，业务服务后停。
    check("探针驱动器确实被关闭", len(shutdown_records) == 1, str(observations))

    if failures:
        print(f"\n验证不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n全部通过：驱动器在业务服务就绪之后启动")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
