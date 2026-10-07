"""验证 QQ 入站传输开关（`.env` 的 QQ_TRANSPORT）。

驱动器清单由代码登记，配置只决定 QQ 走哪一种入站方式。这个开关决定了
`available_adapter_specs()` 里哪些驱动器会被启用，因此必须逐值核对：
写错一个值不能让服务静默退化，也不能悄悄少启用一个驱动器。

同时核对两个 QQ 驱动器共用同一个回复管理器：业务层只写一次命令，回复
必须由同一个队列处理，不能出现"某个入站收不到回复"。
"""

from __future__ import annotations

import pathlib
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from launch.adapter import registry  # noqa: E402

# 取值 → 期望启用的驱动器名（顺序与实现一致）
EXPECTED_ENABLED: dict[str, list[str]] = {
    "websocket": ["qq_ws", "local"],
    "webhook": ["qq", "local"],
    "both": ["qq", "qq_ws", "local"],
}


class FakeConfig:
    """替换框架 config，只为读取 QQ_TRANSPORT。"""

    def __init__(self, value: str | None) -> None:
        self.value = value

    def get(self, name: str, default: str = "") -> str:
        if name != "QQ_TRANSPORT":
            raise AssertionError(f"开关测试不应读取其他配置项：{name}")
        return default if self.value is None else self.value


def with_transport(value: str | None):
    """在指定开关值下读取启用驱动器清单。

    必须从 `sys.modules` 取配置模块：`launch/__init__.py` 导出了同名的
    `config` 对象，`import launch.config as x` 会拿到那个对象而不是模块。
    """

    config_module = sys.modules["launch.config"]
    original = config_module.config
    config_module.config = FakeConfig(value)
    try:
        return registry.enabled_adapter_names()
    finally:
        config_module.config = original


def main() -> int:
    """运行开关值矩阵与共享管理器核对。"""

    print("QQ 入站传输开关验证")
    failures: list[str] = []

    def check(label: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"  [通过] {label}")
            return
        text = f"{label}：{detail}" if detail else label
        failures.append(text)
        print(f"  [失败] {text}")

    for value, expected in EXPECTED_ENABLED.items():
        actual = with_transport(value)
        check(f"QQ_TRANSPORT={value} → {expected}", actual == expected, f"实际 {actual}")

    # 未配置时默认沿用 webhook：驱动器新增不应改变线上入站方式。
    check(
        "QQ_TRANSPORT 未配置时默认 webhook",
        with_transport(None) == EXPECTED_ENABLED["webhook"],
        f"实际 {with_transport(None)}",
    )
    check(
        "QQ_TRANSPORT 空字符串按未配置处理",
        with_transport("") == EXPECTED_ENABLED["webhook"],
        f"实际 {with_transport('')}",
    )
    check(
        "QQ_TRANSPORT 大小写与空白不敏感",
        with_transport("  WebSocket  ") == EXPECTED_ENABLED["websocket"],
        f"实际 {with_transport('  WebSocket  ')}",
    )

    # 非法值必须显式报错，不能静默退化成某个默认值。
    for bad in ("bogus", "ws", "qq"):
        try:
            with_transport(bad)
        except ValueError as exc:
            check(f"非法值 {bad!r} 被拒绝", "QQ_TRANSPORT" in str(exc), str(exc))
        else:
            check(f"非法值 {bad!r} 被拒绝", False, "未报错")

    # 两个 QQ 驱动器必须共用同一个回复管理器实例。
    original = with_transport("both")
    specs = registry.available_adapter_specs()
    check(
        "qq 与 qq_ws 共用同一个回复管理器",
        specs["qq"].manager is specs["qq_ws"].manager,
        f"{specs['qq'].manager} vs {specs['qq_ws'].manager}",
    )
    check(
        "local 使用自己的回复管理器",
        specs["local"].manager is not specs["qq"].manager,
    )
    check(
        "只有 webhook 驱动器带 HTTP 入口",
        specs["qq"].http_mount is not None
        and specs["qq_ws"].http_mount is None
        and specs["local"].http_mount is None,
    )
    check(
        "both 模式确实同时启用两个 QQ 驱动器",
        original == EXPECTED_ENABLED["both"],
        f"实际 {original}",
    )

    if failures:
        print(f"\n验证不成立 {len(failures)} 处：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\n全部通过：开关取值、非法值拒绝与驱动器共用回复管理器")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
